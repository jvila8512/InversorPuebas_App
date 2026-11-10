"""
modbus_tcp.py — Transporte Modbus sobre TCP/IP
===============================================================
Para usar con gateways RS485→TCP (USR-TCP232, Moxa NPort, etc).

Dos framings soportados:
  - "mbap" (por defecto): Modbus TCP estándar. Trama MBAP de 7 bytes
    (txid + protocol id + length + unit id) + PDU, SIN CRC.
  - "rtu": trama RTU cruda (unit + PDU + CRC) tunelada por TCP.

La interfaz es compatible con ModbusConnection (felicity_modbus.py).
"""

import logging
import socket
import time
from typing import Optional

from core.felicity_modbus import (
    ModbusStatus,
    ModbusSettings,
    ModbusInfo,
    WriteResult,
    OutputPriority,
    ChargePriority,
    WorkingMode,
    ChargeMode,
    calculate_crc,
    verify_crc,
    FUNCTION_READ_HOLDING,
    FUNCTION_WRITE_SINGLE,
    READ_TIMEOUT_MS,
    MAX_RETRIES,
)
from core.register_maps import (
    CLASSIC_MAP,
    RegisterMap,
    decode_status_fields,
    get_map,
)


logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# CONEXIÓN MODBUS SOBRE TCP
# ══════════════════════════════════════════════════════════════════════════════

class ModbusTCPConnection:
    """
    Conexión Modbus sobre TCP/IP con framing conmutable (MBAP o RTU).

    Interfaz compatible con ModbusConnection (felicity_modbus.py):
      - connect() -> (bool, str)
      - disconnect()
      - is_open -> bool
      - read_holding_registers(start, count) -> list|None
      - write_single_register(address, value) -> WriteResult
      - read_status(map=None) -> ModbusStatus|None
      - read_settings(map=None) -> ModbusSettings|None
      - read_info(map=None) -> ModbusInfo|None
      - set_float_voltage, set_absorb_voltage, etc.
    """

    DEFAULT_TCP_PORT = 502
    DEFAULT_TIMEOUT = 5.0  # segundos (TCP es más lento que serial directo)
    RECV_BUFFER_SIZE = 256
    MAX_READ_BLOCK = 60    # máximo de registros por petición

    def __init__(
        self,
        host: str,
        port: int = None,
        timeout: float = None,
        slave_id: int = 1,
        framing: str = "mbap",
    ):
        self.host = host
        self.port = port or self.DEFAULT_TCP_PORT
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self.slave_id = slave_id
        self.framing = self._validate_framing(framing)
        self.map: RegisterMap = CLASSIC_MAP
        self._socket: Optional[socket.socket] = None
        self._txid: int = 0

    @staticmethod
    def _validate_framing(framing: str) -> str:
        framing = (framing or "mbap").lower()
        if framing not in ("mbap", "rtu"):
            raise ValueError(f"Framing no soportado: {framing}")
        return framing

    def set_map(self, map) -> None:
        """Establece el mapa de registros activo para lecturas/escrituras."""
        self.map = get_map(map)

    def connect(self) -> tuple[bool, str]:
        """
        Abre la conexión TCP al gateway.
        Returns: (success, message)
        """
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout)
            self._socket.connect((self.host, self.port))
            return True, (
                f"Conectado a {self.host}:{self.port} "
                f"(Modbus {self.framing.upper()})"
            )
        except socket.timeout:
            self._socket = None
            return False, f"Timeout conectando a {self.host}:{self.port}"
        except ConnectionRefusedError:
            self._socket = None
            return False, f"Conexión rechazada: {self.host}:{self.port}"
        except OSError as e:
            self._socket = None
            return False, f"Error de conexión: {e}"

    def disconnect(self):
        """Cierra la conexión TCP."""
        if self._socket:
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    @property
    def is_open(self) -> bool:
        """Verifica si el socket está conectado."""
        if self._socket is None:
            return False
        try:
            self._socket.getpeername()
            return True
        except OSError:
            self._socket = None
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Construcción de tramas
    # ─────────────────────────────────────────────────────────────────────────

    def _next_txid(self) -> int:
        self._txid = (self._txid + 1) & 0xFFFF
        return self._txid

    def _frame(self, pdu: bytes) -> bytes:
        """Envuelve un PDU según el framing activo (MBAP o RTU)."""
        if self.framing == "mbap":
            txid = self._next_txid()
            header = bytes([
                (txid >> 8) & 0xFF,
                txid & 0xFF,
                0x00,
                0x00,
                0x00,
                len(pdu) + 1,
            ])
            return header + bytes([self.slave_id]) + pdu

        payload = bytes([self.slave_id]) + pdu
        return payload + calculate_crc(payload)

    def _build_read_frame(self, start_address: int, count: int) -> bytes:
        """Construye la trama de lectura de holding (función 0x03)."""
        pdu = bytes([
            FUNCTION_READ_HOLDING,
            (start_address >> 8) & 0xFF,
            start_address & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        ])
        return self._frame(pdu)

    def _build_write_frame(self, register_address: int, value: int) -> bytes:
        """Construye la trama de escritura de un registro (función 0x06)."""
        pdu = bytes([
            FUNCTION_WRITE_SINGLE,
            (register_address >> 8) & 0xFF,
            register_address & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ])
        return self._frame(pdu)

    # ─────────────────────────────────────────────────────────────────────────
    # Lectura de registros
    # ─────────────────────────────────────────────────────────────────────────

    def read_holding_registers(self, start_address: int, count: int) -> Optional[list]:
        """
        Lee registros holding via TCP.
        Función 0x03 del protocolo Modbus.

        Returns:
            Lista de valores (int), o None si falla
        """
        if not self.is_open:
            return None

        for attempt in range(MAX_RETRIES):
            try:
                frame = self._build_read_frame(start_address, count)
                self._socket.sendall(bytes(frame))

                response = self._read_response(count)
                if response is None:
                    continue

                registers = self._parse_read_response(response, count)
                if registers is not None:
                    return registers

            except (socket.timeout, OSError):
                continue

        return None

    def _expected_read_bytes(self, count: int) -> int:
        if self.framing == "mbap":
            return 9 + (count * 2)  # MBAP(7) + func(1) + bytecount(1) + data
        return 5 + (count * 2)      # unit(1) + func(1) + bytecount(1) + data + crc(2)

    def _read_response(self, expected_count: int) -> Optional[bytes]:
        """
        Lee la respuesta del gateway via TCP.
        A diferencia del serial, TCP garantiza entrega o error.
        """
        if not self._socket:
            return None

        expected_bytes = self._expected_read_bytes(expected_count)
        buffer = bytearray()
        start_time = time.perf_counter()

        while len(buffer) < expected_bytes:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            if elapsed_ms > READ_TIMEOUT_MS:
                if len(buffer) >= 5:
                    break
                return None

            try:
                remaining = expected_bytes - len(buffer)
                chunk = self._socket.recv(min(remaining, self.RECV_BUFFER_SIZE))
                if chunk:
                    buffer.extend(chunk)
                else:
                    return None
            except socket.timeout:
                if len(buffer) >= 5:
                    break
                return None
            except OSError:
                return None

        return bytes(buffer) if buffer else None

    def _parse_read_response(self, response: bytes, count: int) -> Optional[list]:
        """Interpreta una respuesta de lectura según el framing activo."""
        if not response:
            return None

        if self.framing == "mbap":
            if len(response) < 9:
                return None
            if response[2:4] != b"\x00\x00":
                return None
            if response[6] != self.slave_id:
                return None
            pdu = response[7:]
            if len(pdu) < 2 or pdu[0] != FUNCTION_READ_HOLDING:
                return None
            if pdu[0] & 0x80:
                return None
            byte_count = pdu[1]
            data = pdu[2:2 + byte_count]
        else:
            if len(response) < 5:
                return None
            if response[0] != self.slave_id:
                return None
            if not verify_crc(response):
                logger.warning("Respuesta RTU con CRC inválido")
                return None
            if response[1] != FUNCTION_READ_HOLDING:
                return None
            if response[1] & 0x80:
                return None
            byte_count = response[2]
            data = response[3:3 + byte_count]

        if len(data) < count * 2:
            return None

        registers = []
        for i in range(count):
            offset = i * 2
            registers.append((data[offset] << 8) | data[offset + 1])
        return registers

    # ─────────────────────────────────────────────────────────────────────────
    # Escritura de registro
    # ─────────────────────────────────────────────────────────────────────────

    def write_single_register(self, register_address: int, value: int) -> WriteResult:
        """
        Escribe un solo registro via TCP.
        Función 0x06 del protocolo Modbus.

        Returns: WriteResult con éxito o error
        """
        if not self.is_open:
            return WriteResult(False, register_address, value, 0.0, "No conectado")

        if self.map is not None and self.map.settings_start is None:
            logger.warning(
                "mapa sin bloque de ajustes: no se puede escribir en %s",
                self.map.label,
            )
            return WriteResult(
                False, register_address, value, 0.0,
                "mapa sin bloque de ajustes",
            )

        start_time = time.perf_counter()

        try:
            frame = self._build_write_frame(register_address, value)
            self._socket.sendall(bytes(frame))

            expected = 12 if self.framing == "mbap" else 8
            response = self._recv_exact(expected)

            latency = (time.perf_counter() - start_time) * 1000

            if response is None or len(response) < 5:
                return WriteResult(
                    False, register_address, value, latency,
                    "Sin respuesta del gateway"
                )

            if self.framing == "mbap":
                if response[6] != self.slave_id:
                    return WriteResult(
                        False, register_address, value, latency,
                        "Slave ID no coincide"
                    )
                if response[7] == FUNCTION_WRITE_SINGLE:
                    return WriteResult(True, register_address, value, latency)
                if response[7] & 0x80:
                    return WriteResult(
                        False, register_address, value, latency,
                        f"Excepción Modbus: código {response[9]}"
                    )
                return WriteResult(
                    False, register_address, value, latency,
                    "Respuesta inesperada"
                )

            if not verify_crc(response):
                return WriteResult(
                    False, register_address, value, latency,
                    "CRC inválido"
                )
            if response[0] != self.slave_id:
                return WriteResult(
                    False, register_address, value, latency,
                    "Slave ID no coincide"
                )
            if response[1] == FUNCTION_WRITE_SINGLE:
                return WriteResult(True, register_address, value, latency)
            if response[1] & 0x80:
                return WriteResult(
                    False, register_address, value, latency,
                    f"Excepción Modbus: código {response[2]}"
                )
            return WriteResult(
                False, register_address, value, latency,
                "Respuesta inesperada"
            )

        except (socket.timeout, OSError) as e:
            latency = (time.perf_counter() - start_time) * 1000
            return WriteResult(False, register_address, value, latency, str(e))

    def _recv_exact(self, num_bytes: int) -> Optional[bytes]:
        """Lee exactamente num_bytes del socket o None si falla."""
        if not self._socket:
            return None
        buffer = bytearray()
        start_time = time.perf_counter()

        while len(buffer) < num_bytes:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            if elapsed_ms > READ_TIMEOUT_MS:
                return bytes(buffer) if buffer else None
            try:
                remaining = num_bytes - len(buffer)
                chunk = self._socket.recv(min(remaining, 64))
                if chunk:
                    buffer.extend(chunk)
                else:
                    return None
            except socket.timeout:
                return bytes(buffer) if buffer else None
            except OSError:
                return None

        return bytes(buffer)

    # ─────────────────────────────────────────────────────────────────────────
    # Operaciones de alto nivel — mismas que ModbusConnection RTU
    # ─────────────────────────────────────────────────────────────────────────

    def _read_status_registers(self, map_obj: RegisterMap) -> Optional[list]:
        """Lee el bloque de estado completo, partiéndolo en bloques <= 60."""
        registers: list = []
        addr = map_obj.status_start
        remaining = map_obj.status_count

        while remaining > 0:
            chunk = min(self.MAX_READ_BLOCK, remaining)
            regs = self.read_holding_registers(addr, chunk)
            if regs is None or len(regs) < chunk:
                return None
            registers.extend(regs)
            addr += chunk
            remaining -= chunk

        return registers

    def read_status(self, map=None) -> Optional[ModbusStatus]:
        """
        Lee el estado actual del inversor via TCP.
        Decodifica según el mapa indicado (por defecto, el mapa activo).
        """
        map_obj = get_map(map) if map is not None else (self.map or CLASSIC_MAP)
        if map is not None:
            self.map = map_obj

        regs = self._read_status_registers(map_obj)
        if regs is None:
            return None

        decoded = decode_status_fields(regs, map_obj.status_start, map_obj)

        status = ModbusStatus()
        status.raw_registers = list(regs)
        status.map_name = map_obj.name

        status.setting_data_sn = int(decoded.get("setting_data_sn", 0))
        status.working_mode = WorkingMode.from_int(int(decoded.get("working_mode", 0)))
        status.charge_mode = ChargeMode.from_int(int(decoded.get("charge_mode", 0)))
        status.fault_code = int(decoded.get("fault_code", 0))
        status.power_flow_raw = int(decoded.get("power_flow", 0))

        status.battery_voltage = round(float(decoded.get("battery_voltage", 0.0)), 1)

        current = float(decoded.get("battery_current", 0.0))
        status.battery_current = current
        if current < 0:
            status.battery_discharge_a = abs(current)
        else:
            status.battery_charge_a = current

        power = float(decoded.get("battery_power", 0.0))
        status.battery_power = int(power)
        if power < 0:
            status.battery_discharge_w = abs(int(power))
        else:
            status.battery_charge_w = int(power)

        if "battery_soc" in decoded:
            status.battery_soc = int(round(decoded["battery_soc"]))

        status.output_voltage = round(float(decoded.get("output_voltage", 0.0)), 1)
        status.grid_voltage = round(float(decoded.get("grid_voltage", 0.0)), 1)
        status.grid_frequency = round(float(decoded.get("grid_frequency", 0.0)), 2)
        status.output_active_power = int(decoded.get("output_active_power", 0))
        status.load_watts = status.output_active_power
        status.output_apparent_power = int(decoded.get("output_apparent_power", 0))
        status.load_percent = int(decoded.get("load_percent", 0))
        status.pv_voltage = round(float(decoded.get("pv_voltage", 0.0)), 1)
        status.pv_power = int(decoded.get("pv_power", 0))

        return status

    def read_settings(self, map=None) -> Optional[ModbusSettings]:
        """
        Lee la configuración del inversor via TCP.
        Si el mapa no tiene bloque de ajustes, devuelve None con advertencia.
        """
        map_obj = get_map(map) if map is not None else (self.map or CLASSIC_MAP)
        if map is not None:
            self.map = map_obj

        if map_obj.settings_start is None or map_obj.settings_count <= 0:
            logger.warning("mapa sin bloque de ajustes: %s", map_obj.label)
            return None

        regs = self.read_holding_registers(map_obj.settings_start, map_obj.settings_count)

        if regs is None or len(regs) < map_obj.settings_count:
            return None

        settings = ModbusSettings()
        settings.raw_registers = list(regs)

        # Offset 0 (0x211F): Battery cut-off voltage / 10
        settings.battery_cutoff_voltage = regs[0] / 10.0

        # Offset 3 (0x2122): Battery CV voltage / 10
        settings.battery_cv_voltage = regs[3] / 10.0

        # Offset 4 (0x2123): Battery float voltage / 10
        settings.battery_float_voltage = regs[4] / 10.0

        # Offset 10 (0x2129): AC output frequency (0=50Hz, 1=60Hz)
        settings.ac_output_frequency = regs[10]

        # Offset 11 (0x212A): Output priority
        try:
            settings.output_priority = OutputPriority(regs[11])
        except ValueError:
            settings.output_priority = OutputPriority.SOLAR_FIRST

        # Offset 12 (0x212B): Application mode
        settings.application_mode = regs[12]

        # Offset 13 (0x212C): Charge priority
        try:
            settings.charge_priority = ChargePriority(regs[13])
        except ValueError:
            settings.charge_priority = ChargePriority.SOLAR_AND_UTILITY

        # Offset 14 (0x212D): Battery type
        settings.battery_type = regs[14]

        # Offset 15 (0x212E): Max charging current
        settings.max_charge_current = regs[15]

        # Offset 17 (0x2130): Max AC charging current
        settings.max_ac_charge_current = regs[17]

        # Offset 18 (0x2131): Buzzer enable
        settings.buzzer_enabled = bool(regs[18])

        # Offset 20 (0x2133): Overload restart enable
        settings.overload_restart = bool(regs[20])

        # Offset 21 (0x2134): Over temperature restart enable
        settings.over_temp_restart = bool(regs[21])

        # Offset 22 (0x2135): LCD backlight enable
        settings.lcd_backlight = bool(regs[22])

        # Offset 24 (0x2137): Overload to bypass
        settings.overload_to_bypass = bool(regs[24])

        # Offset 55 (0x2156): Battery back to grid voltage / 10
        settings.battery_back_to_grid_voltage = regs[55] / 10.0

        # Offset 58 (0x2159): Battery back to battery voltage / 10
        settings.battery_back_to_battery_voltage = regs[58] / 10.0

        return settings

    def read_info(self, map=None) -> Optional['ModbusInfo']:
        """
        Lee la información del equipo via TCP.
        Si el mapa no tiene bloque de información, devuelve None.
        """
        map_obj = get_map(map) if map is not None else (self.map or CLASSIC_MAP)
        if map is not None:
            self.map = map_obj

        if map_obj.info_start is None or map_obj.info_count <= 0:
            logger.warning("mapa sin bloque de información: %s", map_obj.label)
            return None

        regs = self.read_holding_registers(map_obj.info_start, map_obj.info_count)

        if regs is None or len(regs) < map_obj.info_count:
            return None

        info = ModbusInfo()
        info.raw_registers = list(regs)

        # Offset 0 (0xF800): Equipment type
        info.equipment_type = regs[0]

        # Offset 1 (0xF801): Sub type
        info.sub_type = regs[1]

        # Offset 4-8 (0xF804-0xF808): Serial number (5 registros)
        sn_parts = []
        for i in range(4, 9):
            if i < len(regs) and regs[i] != 0:
                sn_parts.append(f"{regs[i]:04d}")
        info.serial_number = ''.join(sn_parts)

        # Offset 11 (0xF80B): CPU1 FW version
        info.cpu1_fw_version = regs[11]

        # Offset 12 (0xF80C): CPU2 FW version
        info.cpu2_fw_version = regs[12]

        return info

    # ─────────────────────────────────────────────────────────────────────────
    # Métodos de escritura — misma interfaz que ModbusConnection RTU
    # ─────────────────────────────────────────────────────────────────────────

    def set_float_voltage(self, voltage: float) -> WriteResult:
        value = int(voltage * 10)
        return self.write_single_register(0x2123, value)

    def set_absorb_voltage(self, voltage: float) -> WriteResult:
        value = int(voltage * 10)
        return self.write_single_register(0x2122, value)

    def set_cutoff_voltage(self, voltage: float) -> WriteResult:
        value = int(voltage * 10)
        return self.write_single_register(0x211F, value)

    def set_recharge_voltage(self, voltage: float) -> WriteResult:
        value = int(voltage * 10)
        return self.write_single_register(0x2156, value)

    def set_back_to_battery_voltage(self, voltage: float) -> WriteResult:
        value = int(voltage * 10)
        return self.write_single_register(0x2159, value)

    def set_output_priority(self, priority) -> WriteResult:
        return self.write_single_register(0x212A, priority.value)

    def set_charge_priority(self, priority) -> WriteResult:
        return self.write_single_register(0x212C, priority.value)

    def set_max_charge_current(self, current: int) -> WriteResult:
        return self.write_single_register(0x212E, current)

    def set_max_ac_charge_current(self, current: int) -> WriteResult:
        return self.write_single_register(0x2130, current)
