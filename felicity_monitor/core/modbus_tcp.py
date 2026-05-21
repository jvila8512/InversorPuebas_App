"""
modbus_tcp.py — Transporte Modbus RTU sobre TCP/IP
================================================================
Para usar con gateways RS232→TCP (USR-TCP232, Moxa NPort, etc.)
El frame Modbus es IDÉNTICO al RTU serial, solo cambia el transporte.
El gateway encapsula los bytes transparentemente por TCP.
"""

import socket
import time
from typing import Optional

from core.felicity_modbus import (
    ModbusStatus,
    ModbusSettings,
    ModbusInfo,
    WriteResult,
    ModbusConnection as _ModbusRTUConnection,
    calculate_crc,
    verify_crc,
    SLAVE_ADDRESS,
    FUNCTION_READ_HOLDING,
    FUNCTION_WRITE_SINGLE,
    STATUS_START,
    STATUS_COUNT,
    SETTINGS_START,
    SETTINGS_COUNT,
    INFO_START,
    INFO_COUNT,
    READ_TIMEOUT_MS,
    MAX_RETRIES,
)


# ══════════════════════════════════════════════════════════════════════════════
# CONEXIÓN MODBUS RTU OVER TCP
# ══════════════════════════════════════════════════════════════════════════════

class ModbusTCPConnection:
    """
    Conexión Modbus RTU sobre TCP/IP.

    Usa un gateway RS232→TCP que encapsula los frames Modbus RTU
    de forma transparente. El frame es idéntico al serial, pero
    en vez de pyserial mandamos los bytes por socket TCP.

    Interfaz compatible con ModbusConnection (felicity_modbus.py):
      - connect() -> (bool, str)
      - disconnect()
      - is_open -> bool
      - read_holding_registers(start, count) -> list|None
      - write_single_register(address, value) -> WriteResult
      - read_status() -> ModbusStatus|None
      - read_settings() -> ModbusSettings|None
      - set_float_voltage, set_absorb_voltage, etc.
    """

    DEFAULT_TCP_PORT = 502
    DEFAULT_TIMEOUT = 5.0  # segundos (TCP es más lento que serial directo)
    RECV_BUFFER_SIZE = 256

    def __init__(self, host: str, port: int = None, timeout: float = None):
        self.host = host
        self.port = port or self.DEFAULT_TCP_PORT
        self.timeout = timeout or self.DEFAULT_TIMEOUT
        self._socket: Optional[socket.socket] = None

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
                f"(Modbus RTU over TCP)"
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
        # Probe silencioso: verificar que el socket no esté roto
        try:
            # getpeername() falla si el socket se cerró
            self._socket.getpeername()
            return True
        except OSError:
            self._socket = None
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Lectura de registros
    # ─────────────────────────────────────────────────────────────────────────

    def read_holding_registers(self, start_address: int, count: int) -> Optional[list]:
        """
        Lee registros holding via TCP.
        Función 0x03 del protocolo Modbus — idéntico al RTU serial.

        Args:
            start_address: Dirección inicial (ej: 0x1101)
            count: Cantidad de registros a leer

        Returns:
            Lista de valores (int), o None si falla
        """
        if not self.is_open:
            return None

        for attempt in range(MAX_RETRIES):
            try:
                # Construir trama — IDÉNTICA al Modbus RTU serial
                frame = bytearray([
                    SLAVE_ADDRESS,
                    FUNCTION_READ_HOLDING,
                    (start_address >> 8) & 0xFF,
                    start_address & 0xFF,
                    (count >> 8) & 0xFF,
                    count & 0xFF,
                ])
                crc = calculate_crc(bytes(frame))
                frame.extend(crc)

                # Enviar por TCP
                self._socket.sendall(bytes(frame))

                # Leer respuesta
                response = self._read_response(count)

                if response is None:
                    continue

                # Verificar slave ID y function code
                if response[0] != SLAVE_ADDRESS:
                    continue

                # Verificar Modbus exception
                if response[1] & 0x80:
                    return None

                # Verificar que tenemos suficientes bytes
                byte_count = response[2]
                expected = 3 + byte_count + 2  # header + data + crc

                if len(response) < expected:
                    continue

                # Parsear registros (big-endian: MSB first)
                registers = []
                for i in range(count):
                    offset = 3 + (i * 2)
                    if offset + 1 < len(response):
                        value = (response[offset] << 8) | response[offset + 1]
                        registers.append(value)

                if len(registers) == count:
                    return registers

            except (socket.timeout, OSError):
                # Reintentar — TCP puede tener latencia variable
                continue

        return None

    def _read_response(self, expected_count: int) -> Optional[bytes]:
        """
        Lee la respuesta del gateway via TCP.
        A diferencia del serial, TCP garantiza entrega o error.
        """
        if not self._socket:
            return None

        expected_bytes = 3 + (expected_count * 2) + 2  # header + data + crc
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
                    # Conexión cerrada por el gateway
                    return None
            except socket.timeout:
                if len(buffer) >= 5:
                    break
                return None
            except OSError:
                return None

        return bytes(buffer) if buffer else None

    # ─────────────────────────────────────────────────────────────────────────
    # Escritura de registro
    # ─────────────────────────────────────────────────────────────────────────

    def write_single_register(self, register_address: int, value: int) -> WriteResult:
        """
        Escribe un solo registro via TCP.
        Función 0x06 del protocolo Modbus — idéntico al RTU serial.

        Returns: WriteResult con éxito o error
        """
        if not self.is_open:
            return WriteResult(False, register_address, value, 0.0, "No conectado")

        start_time = time.perf_counter()

        try:
            # Construir trama — IDÉNTICA al Modbus RTU serial
            frame = bytearray([
                SLAVE_ADDRESS,
                FUNCTION_WRITE_SINGLE,
                (register_address >> 8) & 0xFF,
                register_address & 0xFF,
                (value >> 8) & 0xFF,
                value & 0xFF,
            ])
            crc = calculate_crc(bytes(frame))
            frame.extend(crc)

            # Enviar por TCP
            self._socket.sendall(bytes(frame))

            # Leer respuesta (8 bytes esperados)
            response = self._recv_exact(8)

            latency = (time.perf_counter() - start_time) * 1000

            if response is None or len(response) < 5:
                return WriteResult(
                    False, register_address, value, latency,
                    "Sin respuesta del gateway"
                )

            # Verificar que sea echo del request
            if (response[0] == SLAVE_ADDRESS
                    and response[1] == FUNCTION_WRITE_SINGLE):
                return WriteResult(True, register_address, value, latency)

            # Verificar exception
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

    def read_status(self) -> Optional[ModbusStatus]:
        """
        Lee el estado actual del inversor via TCP.
        Lee los registros 0x1100 - 0x112A (43 registros).
        Parsing idéntico a ModbusConnection RTU (felicity_modbus.py).
        """
        # Leemos desde 0x1100 para incluir SettingDataSn
        regs = self.read_holding_registers(STATUS_START - 1, STATUS_COUNT + 1)

        if regs is None or len(regs) < STATUS_COUNT + 1:
            # Fallback: intentar sin 0x1100
            regs = self.read_holding_registers(STATUS_START, STATUS_COUNT)
            if regs is None or len(regs) < STATUS_COUNT:
                return None
            regs = [0] + regs  # prepend dummy para 0x1100

        status = ModbusStatus()
        status.raw_registers = list(regs)

        # Offset 0 (0x1100): SettingDataSn
        status.setting_data_sn = regs[0]

        # Offset 1 (0x1101): Working mode
        status.working_mode = _parse_working_mode(regs[1])

        # Offset 2 (0x1102): Charge mode
        status.charge_mode = _parse_charge_mode(regs[2])

        # Offset 3 (0x1103): Fault code
        status.fault_code = regs[3]

        # Offset 4 (0x1104): PowerFlowMsg
        status.power_flow_raw = regs[4]

        # Offset 8 (0x1108): Battery voltage / 100
        status.battery_voltage = round(regs[8] / 100.0, 1)

        # Offset 9 (0x1109): Battery current (signed)
        current = _signed_value(regs[9])
        status.battery_current = current
        if current < 0:
            status.battery_discharge_a = abs(current)
        else:
            status.battery_charge_a = current

        # Offset 10 (0x110A): Battery power (signed)
        power = _signed_value(regs[10])
        status.battery_power = power
        if power < 0:
            status.battery_discharge_w = abs(power)
        else:
            status.battery_charge_w = power

        # Offset 17 (0x1111): AC Output voltage / 10
        status.output_voltage = round(regs[17] / 10.0, 1)

        # Offset 23 (0x1117): Grid voltage / 10
        status.grid_voltage = round(regs[23] / 10.0, 1)

        # Offset 25 (0x1119): AC input frequency / 100
        status.grid_frequency = round(regs[25] / 100.0, 2)

        # Offset 30 (0x111E): Output active power (signed)
        status.output_active_power = _signed_value(regs[30])
        status.load_watts = status.output_active_power

        # Offset 31 (0x111F): Output apparent power
        status.output_apparent_power = regs[31]

        # Offset 32 (0x1120): Load percent
        status.load_percent = regs[32]

        # Offset 38 (0x1126): PV voltage / 10
        status.pv_voltage = round(regs[38] / 10.0, 1)

        # Offset 42 (0x112A): PV power (signed)
        status.pv_power = _signed_value(regs[42])

        return status

    def read_settings(self) -> Optional[ModbusSettings]:
        """
        Lee la configuración del inversor via TCP.
        Lee los registros 0x211F - 0x2159 (59 registros).
        Parsing idéntico a ModbusConnection RTU (felicity_modbus.py).
        """
        regs = self.read_holding_registers(SETTINGS_START, SETTINGS_COUNT)

        if regs is None or len(regs) < SETTINGS_COUNT:
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
        from core.felicity_modbus import OutputPriority, ChargePriority
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

    def read_info(self) -> Optional['ModbusInfo']:
        """
        Lee la información del equipo via TCP.
        Registros 0xF800 - 0xF80C (13 registros).
        Parsing idéntico a ModbusConnection RTU (felicity_modbus.py).
        """
        regs = self.read_holding_registers(INFO_START, INFO_COUNT)

        if regs is None or len(regs) < INFO_COUNT:
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
        from core.felicity_modbus import OutputPriority
        return self.write_single_register(0x212A, priority.value)

    def set_charge_priority(self, priority) -> WriteResult:
        from core.felicity_modbus import ChargePriority
        return self.write_single_register(0x212C, priority.value)

    def set_max_charge_current(self, current: int) -> WriteResult:
        return self.write_single_register(0x212E, current)

    def set_max_ac_charge_current(self, current: int) -> WriteResult:
        return self.write_single_register(0x2130, current)


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIONES AUXILIARES (duplicadas de felicity_modbus para evitar
# dependencia circular en los imports)
# ══════════════════════════════════════════════════════════════════════════════

def _signed_value(value: int) -> int:
    """Convierte un valor unsigned de 16 bits a signed."""
    if value >= 0x8000:
        return value - 0x10000
    return value


def _parse_working_mode(value: int):
    """Parsea modo de trabajo desde registro raw."""
    from core.felicity_modbus import WorkingMode
    return WorkingMode.from_int(value)


def _parse_charge_mode(value: int):
    """Parsea modo de carga desde registro raw."""
    from core.felicity_modbus import ChargeMode
    return ChargeMode.from_int(value)
