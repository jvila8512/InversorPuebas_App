"""
felicity_modbus.py — Adaptador Modbus RTU para inversores Felicity
Implementación completa del protocolo Modbus RTU.
Compatible con el proyecto C# Felicity-Inverter-Monitor-master
"""

import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum

try:
    from PyQt5.QtCore import QThread, pyqtSignal
    HAS_QT = True
except ImportError:
    HAS_QT = False
    # Stub para cuando se usa sin Qt
    class QThread:
        pass
    def pyqtSignal(*args):
        return None

import serial
import serial.tools.list_ports

from core.register_maps import (
    CLASSIC_MAP,
    RegisterMap,
    decode_settings_fields,
    decode_status_fields,
    get_map,
)


logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES MODBUS RTU
# ══════════════════════════════════════════════════════════════════════════════

SLAVE_ADDRESS = 0x01
FUNCTION_READ_HOLDING = 0x03
FUNCTION_WRITE_SINGLE = 0x06
FUNCTION_READ_INPUT = 0x04

# Registros de estado (0x1101 - 0x112A)
STATUS_START = 0x1101
STATUS_COUNT = 42  # 0x112A - 0x1101 + 1

# Registros de configuración (0x211F - 0x2159)
SETTINGS_START = 0x211F
SETTINGS_COUNT = 59  # 0x2159 - 0x211F + 1

# Timeout y retries
READ_TIMEOUT_MS = 1000
MAX_RETRIES = 3


# ══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ══════════════════════════════════════════════════════════════════════════════

class WorkingMode(Enum):
    """Modo de trabajo del inversor."""
    POWER = 0       # Encendido
    STANDBY = 1     # Espera
    BYPASS = 2      # Derivación
    BATTERY = 3     # Batería
    FAULT = 4       # Falla
    LINE = 5        # Línea (red)
    CHARGING = 6    # Cargando

    def __str__(self):
        return self.name

    @classmethod
    def from_int(cls, value: int) -> 'WorkingMode':
        try:
            return cls(value)
        except ValueError:
            return cls.FAULT


class ChargeMode(Enum):
    """Modo de carga de la batería."""
    NONE = 0      # Sin carga
    BULK = 1      # Carga rápida
    ABSORB = 2    # Absorción
    FLOAT = 3     # Flotación

    def __str__(self):
        return self.name

    @classmethod
    def from_int(cls, value: int) -> 'ChargeMode':
        try:
            return cls(value)
        except ValueError:
            return cls.NONE


class OutputPriority(Enum):
    """Prioridad de salida."""
    UTILITY_FIRST = 0    # Red primero
    SOLAR_FIRST = 1     # Solar primero
    SBU = 2             # Solar → Batería → Red


class ChargePriority(Enum):
    """Prioridad de carga."""
    UTILITY_ONLY = 0      # Solo red
    SOLAR_FIRST = 1       # Solar primero
    SOLAR_AND_UTILITY = 2 # Solar + Red
    SOLAR_ONLY = 3        # Solo solar


# ══════════════════════════════════════════════════════════════════════════════
# ESTRUCTURAS DE DATOS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ModbusStatus:
    """Estado del inversor leído via Modbus RTU — Registros 0x1100-0x112A."""
    # Raw registers
    raw_registers: list = field(default_factory=list)
    map_name: str = "classic"

    # ── Modos (0x1100-0x1104) ──
    setting_data_sn: int = 0           # 0x1100 — Contador de cambios en settings
    working_mode: WorkingMode = WorkingMode.STANDBY  # 0x1101
    charge_mode: ChargeMode = ChargeMode.NONE        # 0x1102
    fault_code: int = 0                # 0x1103 — Código de falla
    power_flow_raw: int = 0            # 0x1104 — PowerFlowMsg (bits)

    # ── Batería (0x1108-0x110A) ──
    battery_voltage: float = 0.0       # 0x1108 — V (override -2 → /100)
    battery_current: float = 0.0       # 0x1109 — A (signed, +carga/-descarga)
    battery_power: int = 0             # 0x110A — W (signed, +carga/-descarga)
    battery_charge_a: float = 0.0      # A (cargando, derivado de battery_current)
    battery_discharge_a: float = 0.0   # A (descargando, derivado de battery_current)
    battery_charge_w: int = 0          # W (cargando, derivado de battery_power)
    battery_discharge_w: int = 0       # W (descargando, derivado de battery_power)
    battery_soc: int = 0              # % (SOC - calculado)

    # ── Salida AC (0x1111, 0x111E-0x1120) ──
    output_voltage: float = 0.0        # 0x1111 — V (override -1 → /10)
    output_active_power: int = 0       # 0x111E — W (signed)
    output_apparent_power: int = 0     # 0x111F — VA
    load_watts: int = 0                # 0x111E — W (alias de output_active_power)
    load_percent: int = 0              # 0x1120 — %

    # ── Red / AC entrada (0x1117, 0x1119) ──
    grid_voltage: float = 0.0          # 0x1117 — V (override -1 → /10)
    grid_frequency: float = 0.0        # 0x1119 — Hz (override -2 → /100)

    # ── PV / Panel solar (0x1126, 0x112A) ──
    pv_voltage: float = 0.0            # 0x1126 — V (override -1 → /10)
    pv_power: int = 0                  # 0x112A — W (signed)

    # ── Temperatura ──
    heatsink_temp: int = 0             # °C

    # ── Campos específicos de la serie IVGM-8K (Series RS485) ──
    pv1_voltage: float = 0.0           # 0x1118 — V
    pv2_voltage: float = 0.0           # 0x1119 — V
    pv1_current: float = 0.0           # 0x111C — A
    pv2_current: float = 0.0           # 0x111D — A
    pv1_power: int = 0                 # 0x1128 — W
    pv2_power: int = 0                 # 0x1129 — W
    output_frequency: float = 0.0      # 0x113E — Hz
    output_voltage_a: float = 0.0      # 0x113F — V (fase A)
    output_voltage_b: float = 0.0      # 0x1140 — V (fase B)
    boost_temp: int = 0                # 0x1144 — °C
    inverter_temp: int = 0             # 0x1145 — °C
    ambient_temp: int = 0              # 0x1146 — °C
    battery_temp: float = 0.0          # 0x1147 — °C
    grid_a_voltage: float = 0.0        # 0x1150 — V
    grid_b_voltage: float = 0.0        # 0x1151 — V
    inverter_a_voltage: float = 0.0    # 0x1153 — V
    inverter_b_voltage: float = 0.0    # 0x1154 — V
    load_a_voltage: float = 0.0        # 0x1156 — V
    load_b_voltage: float = 0.0        # 0x1157 — V
    load_a_current: float = 0.0        # 0x1162 — A
    load_b_current: float = 0.0        # 0x1163 — A
    inverter_frequency: float = 0.0    # 0x116E — Hz
    load_frequency: float = 0.0        # 0x116F — Hz

    @property
    def has_ivgm_telemetry(self) -> bool:
        """True si el mapa cargado es de la serie IVGM-8K."""
        return self.map_name == "ivgm_8k"

    # ── Propiedades derivadas de PowerFlowMsg (0x1104) ──

    @property
    def battery_connected(self) -> bool:
        """b15: 0=Batería desconectada, 1=Batería conectada."""
        return bool(self.power_flow_raw & (1 << 15))

    @property
    def line_normal(self) -> bool:
        """b14: 0=Red anormal, 1=Red normal."""
        return bool(self.power_flow_raw & (1 << 14))

    @property
    def pv_input_normal(self) -> bool:
        """b13: 0=PV anormal, 1=PV normal."""
        return bool(self.power_flow_raw & (1 << 13))

    @property
    def load_connect_allowed(self) -> bool:
        """b12: 0=Carga no permitida, 1=Carga permitida."""
        return bool(self.power_flow_raw & (1 << 12))

    @property
    def battery_flow(self) -> str:
        """b11-b10: 00=Sin flujo, 01=Batería cargando, 10=Batería descargando."""
        val = (self.power_flow_raw >> 10) & 0x03
        return {0: "Sin flujo", 1: "Cargando", 2: "Descargando"}.get(val, "Desconocido")

    @property
    def line_flow(self) -> str:
        """b9-b8: 00=Sin flujo, 01=Consumiendo de red, 10=Inyectando a red."""
        val = (self.power_flow_raw >> 8) & 0x03
        return {0: "Sin flujo", 1: "Consumiendo", 2: "Inyectando"}.get(val, "Desconocido")

    @property
    def pv_mppt_working(self) -> bool:
        """b7: 0=Sin flujo PV, 1=PV MPPT trabajando."""
        return bool(self.power_flow_raw & (1 << 7))

    @property
    def load_connected(self) -> bool:
        """b6: 0=Sin flujo carga, 1=Carga conectada."""
        return bool(self.power_flow_raw & (1 << 6))

    @property
    def power_flow_supported(self) -> bool:
        """b0: 0=Versión no soportada, 1=Versión soportada."""
        return bool(self.power_flow_raw & 0x01)

    # ── Propiedades heredadas ──

    @property
    def battery_power_w(self) -> float:
        """Potencia neta de batería (+ = carga, - = descarga)."""
        return self.battery_charge_w - self.battery_discharge_w

    @property
    def is_charging(self) -> bool:
        return self.battery_charge_a > 0

    @property
    def is_discharging(self) -> bool:
        return self.battery_discharge_a > 0

    def to_dict(self) -> dict:
        """Convierte a diccionario para JSON/API."""
        return {
            "working_mode": str(self.working_mode),
            "charge_mode": str(self.charge_mode),
            "fault_code": self.fault_code,
            "power_flow": {
                "battery_connected": self.battery_connected,
                "line_normal": self.line_normal,
                "pv_input_normal": self.pv_input_normal,
                "battery_flow": self.battery_flow,
                "line_flow": self.line_flow,
                "pv_mppt_working": self.pv_mppt_working,
                "load_connected": self.load_connected,
            },
            "battery_voltage": self.battery_voltage,
            "battery_current": self.battery_current,
            "battery_power": self.battery_power,
            "battery_charge_a": self.battery_charge_a,
            "battery_discharge_a": self.battery_discharge_a,
            "battery_charge_w": self.battery_charge_w,
            "battery_discharge_w": self.battery_discharge_w,
            "battery_soc": self.battery_soc,
            "output_voltage": self.output_voltage,
            "output_active_power": self.output_active_power,
            "output_apparent_power": self.output_apparent_power,
            "load_watts": self.load_watts,
            "load_percent": self.load_percent,
            "grid_voltage": self.grid_voltage,
            "grid_frequency": self.grid_frequency,
            "pv_voltage": self.pv_voltage,
            "pv_power": self.pv_power,
            "heatsink_temp": self.heatsink_temp,
        }


@dataclass
class ModbusSettings:
    """Configuración del inversor leída via Modbus RTU — Registros 0x211F-0x2159."""
    raw_registers: list = field(default_factory=list)

    # ── Voltajes de batería ──
    battery_cutoff_voltage: float = 0.0       # 0x211F — V (corte por descarga)
    battery_cv_voltage: float = 0.0           # 0x2122 — V (absorción/CV)
    battery_float_voltage: float = 0.0        # 0x2123 — V (flotación)
    battery_back_to_grid_voltage: float = 0.0 # 0x2156 — V (regreso a red / recarga)
    battery_back_to_battery_voltage: float = 0.0  # 0x2159 — V (regreso a batería)

    # ── Prioridades ──
    output_priority: OutputPriority = OutputPriority.SOLAR_FIRST   # 0x212A
    charge_priority: ChargePriority = ChargePriority.SOLAR_AND_UTILITY  # 0x212C

    # ── Corrientes ──
    max_charge_current: int = 0         # 0x212E — A
    max_ac_charge_current: int = 0      # 0x2130 — A

    # ── Nuevos campos del protocolo ──
    ac_output_frequency: int = 0        # 0x2129 — 0=50Hz, 1=60Hz
    application_mode: int = 0           # 0x212B — 0=APL, 1=UPS
    battery_type: int = 0               # 0x212D — 0=AGM, 1=Flooded, 2=User, 3=LiFePo4
    buzzer_enabled: bool = False        # 0x2131 — 0=Desactivado, 1=Activado
    overload_restart: bool = False      # 0x2133 — Sobrecarga reinicio
    over_temp_restart: bool = False     # 0x2134 — Sobretemperatura reinicio
    lcd_backlight: bool = False         # 0x2135 — Backlight LCD
    overload_to_bypass: bool = False    # 0x2137 — Sobrecarga → bypass

    # ── Configuración de paralelo (IVGM-8K, 0x2140-0x2143) ──
    parallel_count: int = 0          # 0x2140 — cuántos inversores hay en paralelo
    parallel_address: int = 0        # 0x2141 — rol: 1=maestro, 2..N=esclavos
    modbus_id: int = 0               # 0x2142 — ID Modbus (slave id) del inversor
    rated_power: int = 0             # 0x2143 — potencia nominal en W

    @property
    def parallel_role_str(self) -> str:
        """Describe el rol en paralelo a partir del número de dirección."""
        if self.parallel_address <= 0:
            return "—"
        if self.parallel_address == 1:
            return "Maestro"
        return f"Esclavo {self.parallel_address - 1}"

    @property
    def ac_output_frequency_str(self) -> str:
        return "50 Hz" if self.ac_output_frequency == 0 else "60 Hz"

    @property
    def application_mode_str(self) -> str:
        return {0: "APL", 1: "UPS"}.get(self.application_mode, "Desconocido")

    @property
    def battery_type_str(self) -> str:
        return {
            0: "AGM / Gel", 1: "Flooded (Abierta)",
            2: "Definida por usuario", 3: "LiFePo4 (Litio)"
        }.get(self.battery_type, "Desconocido")

    def to_dict(self) -> dict:
        return {
            "battery_cutoff_voltage": self.battery_cutoff_voltage,
            "battery_cv_voltage": self.battery_cv_voltage,
            "battery_float_voltage": self.battery_float_voltage,
            "battery_back_to_grid_voltage": self.battery_back_to_grid_voltage,
            "battery_back_to_battery_voltage": self.battery_back_to_battery_voltage,
            "output_priority": str(self.output_priority),
            "charge_priority": str(self.charge_priority),
            "max_charge_current": self.max_charge_current,
            "max_ac_charge_current": self.max_ac_charge_current,
            "ac_output_frequency": self.ac_output_frequency_str,
            "application_mode": self.application_mode_str,
            "battery_type": self.battery_type_str,
            "buzzer_enabled": self.buzzer_enabled,
            "overload_restart": self.overload_restart,
            "over_temp_restart": self.over_temp_restart,
            "lcd_backlight": self.lcd_backlight,
            "overload_to_bypass": self.overload_to_bypass,
        }


@dataclass
class ModbusInfo:
    """Información del equipo — Registros 0xF800-0xF80C."""
    raw_registers: list = field(default_factory=list)

    equipment_type: int = 0             # 0xF800 — 0x50 = Inversor alta frecuencia
    sub_type: int = 0                   # 0xF801 — 0x0204=3024, 0x0408=5048
    serial_number: str = ""             # 0xF804-0xF808 — SN 14 dígitos
    cpu1_fw_version: int = 0            # 0xF80B — versión firmware CPU1
    cpu2_fw_version: int = 0            # 0xF80C — versión firmware CPU2

    @property
    def equipment_type_str(self) -> str:
        if self.equipment_type == 0x50:
            return "Inversor Alta Frecuencia"
        return f"Tipo 0x{self.equipment_type:04X}"

    @property
    def sub_type_str(self) -> str:
        return {
            0x0204: "3024 (3000VA/24V)",
            0x0408: "5048 (5000VA/48V)",
        }.get(self.sub_type, f"Subtipo 0x{self.sub_type:04X}")

    @property
    def cpu1_fw_str(self) -> str:
        if self.cpu1_fw_version == 0xFFFF:
            return "N/A"
        return f"V{self.cpu1_fw_version}"

    @property
    def cpu2_fw_str(self) -> str:
        if self.cpu2_fw_version == 0xFFFF:
            return "N/A"
        return f"V{self.cpu2_fw_version}"

    def to_dict(self) -> dict:
        return {
            "equipment_type": self.equipment_type_str,
            "sub_type": self.sub_type_str,
            "serial_number": self.serial_number,
            "cpu1_fw_version": self.cpu1_fw_str,
            "cpu2_fw_version": self.cpu2_fw_str,
        }


# Registros de información del equipo
INFO_START = 0xF800
INFO_COUNT = 13  # 0xF800-0xF80C


@dataclass
class WriteResult:
    """Resultado de una operación de escritura."""
    success: bool
    register_address: int
    value: int
    latency_ms: float = 0.0
    error_message: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE CRC MODBUS
# ══════════════════════════════════════════════════════════════════════════════

def calculate_crc(data: bytes) -> bytes:
    """
    Calcula CRC-16 Modbus.
    Polynomial: 0xA001
    Initial: 0xFFFF
    Returns: 2 bytes (low, high)
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def verify_crc(data: bytes) -> bool:
    """
    Verifica el CRC de una trama Modbus.
    Los últimos 2 bytes deben ser el CRC.
    """
    if len(data) < 4:
        return False
    payload = data[:-2]
    expected_crc = data[-2:]
    calculated_crc = calculate_crc(payload)
    return expected_crc == calculated_crc


# ══════════════════════════════════════════════════════════════════════════════
# CONEXIÓN MODBUS RTU
# ══════════════════════════════════════════════════════════════════════════════

BAUD_RATES_MODBUS = [2400, 4800, 9600, 19200, 38400]
PARITIES_MODBUS = {
    'None': serial.PARITY_NONE,
    'Even': serial.PARITY_EVEN,
    'Odd': serial.PARITY_ODD,
}

DEFAULT_MODBUS_CONFIG = {
    'baudrate': 2400,
    'bytesize': serial.EIGHTBITS,
    'parity': serial.PARITY_NONE,
    'stopbits': serial.STOPBITS_ONE,
    'timeout': 2.0,
}


def list_serial_ports() -> list:
    """Lista los puertos seriales disponibles."""
    return [p.device for p in serial.tools.list_ports.comports()]


class ModbusConnection:
    """
    Conexión Modbus RTU con inversor Felicity.
    Implementación basada en FelicityInverter.cs (proyecto C#).
    """

    MAX_READ_BLOCK = 60    # máximo de registros por petición

    def __init__(self, port: str, config: dict = None, slave_id: int = 1):
        self.port = port
        self.config = {**DEFAULT_MODBUS_CONFIG, **(config or {})}
        self.slave_id = slave_id
        self.map: RegisterMap = CLASSIC_MAP
        self._serial: Optional[serial.Serial] = None
        self._lock = None

        # Cache del frame de status (optimización)
        self._cached_status_frame: Optional[bytes] = None

    def set_map(self, map) -> None:
        """Establece el mapa de registros activo para lecturas/escrituras."""
        self.map = get_map(map)

    def connect(self) -> tuple[bool, str]:
        """
        Abre la conexión serial.
        Returns: (success, message)
        """
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.config['baudrate'],
                bytesize=self.config['bytesize'],
                parity=self.config['parity'],
                stopbits=self.config['stopbits'],
                timeout=self.config['timeout'],
                write_timeout=1.0,
            )
            return True, f"Conectado a {self.port} @ {self.config['baudrate']} baud (Modbus RTU)"
        except serial.SerialException as e:
            return False, f"Error al abrir puerto: {e}"

    def disconnect(self):
        """Cierra la conexión serial."""
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    # ─────────────────────────────────────────────────────────────────────────
    # Lectura de registros
    # ─────────────────────────────────────────────────────────────────────────

    def read_holding_registers(self, start_address: int, count: int) -> Optional[list]:
        """
        Lee registros holding del inversor.
        Función 0x03 del protocolo Modbus.
        
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
                # Construir trama de request:
                # [Slave ID][Function][Address Hi][Address Lo][Count Hi][Count Lo][CRC]
                frame = bytearray([
                    self.slave_id,
                    FUNCTION_READ_HOLDING,
                    (start_address >> 8) & 0xFF,
                    start_address & 0xFF,
                    (count >> 8) & 0xFF,
                    count & 0xFF,
                ])
                crc = calculate_crc(bytes(frame))
                frame.extend(crc)

                # Enviar request
                self._serial.reset_input_buffer()
                self._serial.reset_output_buffer()
                self._serial.write(frame)

                # Leer respuesta
                response = self._read_response(count)

                if response is None:
                    continue

                # Verificar slave ID y function code
                if response[0] != self.slave_id:
                    continue

                # Verificar Modbus exception
                if response[1] & 0x80:
                    # Exception code está en response[2]
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

            except serial.SerialException:
                continue

        return None

    def _read_response(self, expected_count: int) -> Optional[bytes]:
        """Lee la respuesta del inversor."""
        if not self._serial:
            return None

        buffer = bytearray()
        start_time = time.perf_counter()
        
        # Calcular bytes esperados
        expected_bytes = 3 + (expected_count * 2) + 2  # header + data + crc

        while len(buffer) < expected_bytes:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            if elapsed_ms > READ_TIMEOUT_MS:
                # Intentar con lo que tenemos
                if len(buffer) >= 5:  # Mínimo para una respuesta válida
                    break
                return None

            try:
                if self._serial.in_waiting > 0:
                    chunk = self._serial.read(min(self._serial.in_waiting, 64))
                    if chunk:
                        buffer.extend(chunk)
                else:
                    time.sleep(0.01)
            except serial.SerialException:
                return None

        return bytes(buffer) if buffer else None

    # ─────────────────────────────────────────────────────────────────────────
    # Escritura de registro
    # ─────────────────────────────────────────────────────────────────────────

    def write_single_register(self, register_address: int, value: int) -> WriteResult:
        """
        Escribe un solo registro en el inversor.
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
            # Construir trama:
            # [Slave][Func][Address Hi][Address Lo][Value Hi][Value Lo][CRC]
            frame = bytearray([
                self.slave_id,
                FUNCTION_WRITE_SINGLE,
                (register_address >> 8) & 0xFF,
                register_address & 0xFF,
                (value >> 8) & 0xFF,
                value & 0xFF,
            ])
            crc = calculate_crc(bytes(frame))
            frame.extend(crc)

            # Enviar
            self._serial.reset_input_buffer()
            self._serial.write(frame)

            # Leer respuesta (8 bytes)
            response = self._read_response(1)

            latency = (time.perf_counter() - start_time) * 1000

            if response is None or len(response) < 5:
                return WriteResult(False, register_address, value, latency, 
                                 "Sin respuesta del inversor")

            # Verificar que sea echo del request
            if response[0] == self.slave_id and response[1] == FUNCTION_WRITE_SINGLE:
                return WriteResult(True, register_address, value, latency)

            # Verificar exception
            if response[1] & 0x80:
                return WriteResult(False, register_address, value, latency,
                                 f"Excepción Modbus: código {response[2]}")

            return WriteResult(False, register_address, value, latency, 
                             "Respuesta inesperada")

        except serial.SerialException as e:
            return WriteResult(False, register_address, value, 0.0, str(e))

    # ─────────────────────────────────────────────────────────────────────────
    # Operaciones de alto nivel - Estado
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
        Lee el estado actual del inversor.
        Decodifica según el mapa indicado (por defecto, el mapa activo).
        Soporta ambos mapas: 'classic' (5K/IVEM) e 'ivgm_8k' (IVGM-8K).
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

        # ── Campos propios del mapa (IVGM-8K y compañía) ───────────────
        status.pv1_voltage = round(float(decoded.get("pv1_voltage", 0.0)), 1)
        status.pv2_voltage = round(float(decoded.get("pv2_voltage", 0.0)), 1)
        status.pv1_current = round(float(decoded.get("pv1_current", 0.0)), 2)
        status.pv2_current = round(float(decoded.get("pv2_current", 0.0)), 2)
        status.pv1_power = int(decoded.get("pv1_power", 0))
        status.pv2_power = int(decoded.get("pv2_power", 0))
        status.output_frequency = round(float(decoded.get("output_frequency", 0.0)), 2)
        status.output_voltage_a = round(float(decoded.get("output_voltage_a", 0.0)), 1)
        status.output_voltage_b = round(float(decoded.get("output_voltage_b", 0.0)), 1)
        status.boost_temp = int(round(decoded.get("boost_temp", 0.0)))
        status.inverter_temp = int(round(decoded.get("inverter_temp", 0.0)))
        status.ambient_temp = int(round(decoded.get("ambient_temp", 0.0)))
        status.battery_temp = round(float(decoded.get("battery_temp", 0.0)), 1)
        status.grid_a_voltage = round(float(decoded.get("grid_a_voltage", 0.0)), 1)
        status.grid_b_voltage = round(float(decoded.get("grid_b_voltage", 0.0)), 1)
        status.inverter_a_voltage = round(float(decoded.get("inverter_a_voltage", 0.0)), 1)
        status.inverter_b_voltage = round(float(decoded.get("inverter_b_voltage", 0.0)), 1)
        status.load_a_voltage = round(float(decoded.get("load_a_voltage", 0.0)), 1)
        status.load_b_voltage = round(float(decoded.get("load_b_voltage", 0.0)), 1)
        status.load_a_current = round(float(decoded.get("load_a_current", 0.0)), 2)
        status.load_b_current = round(float(decoded.get("load_b_current", 0.0)), 2)
        status.inverter_frequency = round(float(decoded.get("inverter_frequency", 0.0)), 2)
        status.load_frequency = round(float(decoded.get("load_frequency", 0.0)), 2)

        return status

    def read_settings(self, map=None) -> Optional[ModbusSettings]:
        """
        Lee la configuración actual del inversor.
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

        # ── Mapas con bloque de ajustes propio (ej. IVGM-8K) ──────────
        # El layout se describe en map.settings_fields, así que no se
        # aplican los offsets fijos del mapa clásico.
        if map_obj.settings_fields:
            decoded = decode_settings_fields(
                regs, map_obj.settings_start, map_obj
            )
            settings.parallel_count = int(decoded.get("parallel_count", 0))
            settings.parallel_address = int(decoded.get("parallel_address", 0))
            settings.modbus_id = int(decoded.get("modbus_id", 0))
            settings.rated_power = int(decoded.get("rated_power", 0))
            return settings

        # Los offsets son relativos al inicio del bloque de ajustes (0x211F
        # en el mapa clásico).
        # Offset 0: Battery cut-off voltage / 10
        settings.battery_cutoff_voltage = regs[0] / 10.0

        # Offset 3: Battery CV voltage / 10
        settings.battery_cv_voltage = regs[3] / 10.0

        # Offset 4: Battery float voltage / 10
        settings.battery_float_voltage = regs[4] / 10.0

        # Offset 10: AC output frequency (0=50Hz, 1=60Hz)
        settings.ac_output_frequency = regs[10]

        # Offset 11: Output priority
        try:
            settings.output_priority = OutputPriority(regs[11])
        except ValueError:
            settings.output_priority = OutputPriority.SOLAR_FIRST

        # Offset 12: Application mode
        settings.application_mode = regs[12]

        # Offset 13: Charge priority
        try:
            settings.charge_priority = ChargePriority(regs[13])
        except ValueError:
            settings.charge_priority = ChargePriority.SOLAR_AND_UTILITY

        # Offset 14: Battery type
        settings.battery_type = regs[14]

        # Offset 15: Max charging current
        settings.max_charge_current = regs[15]

        # Offset 17: Max AC charging current
        settings.max_ac_charge_current = regs[17]

        # Offset 18: Buzzer enable
        settings.buzzer_enabled = bool(regs[18])

        # Offset 20: Overload restart enable
        settings.overload_restart = bool(regs[20])

        # Offset 21: Over temperature restart enable
        settings.over_temp_restart = bool(regs[21])

        # Offset 22: LCD backlight enable
        settings.lcd_backlight = bool(regs[22])

        # Offset 24: Overload to bypass
        settings.overload_to_bypass = bool(regs[24])

        # Offset 55: Battery back to grid voltage / 10
        settings.battery_back_to_grid_voltage = regs[55] / 10.0

        # Offset 58: Battery back to battery voltage / 10
        settings.battery_back_to_battery_voltage = regs[58] / 10.0

        return settings

    def read_info(self, map=None) -> Optional['ModbusInfo']:
        """
        Lee la información del equipo.
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

        # Offset 0: Equipment type
        info.equipment_type = regs[0]

        # Offset 1: Sub type
        info.sub_type = regs[1]

        # Offset 4-8: Serial number (5 registros)
        sn_parts = []
        for i in range(4, 9):
            if i < len(regs) and regs[i] != 0:
                sn_parts.append(f"{regs[i]:04d}")
        info.serial_number = ''.join(sn_parts)

        # Offset 11: CPU1 FW version
        info.cpu1_fw_version = regs[11]

        # Offset 12: CPU2 FW version
        info.cpu2_fw_version = regs[12]

        return info

    # ─────────────────────────────────────────────────────────────────────────
    # Escritura de configuraciones
    # ─────────────────────────────────────────────────────────────────────────

    def set_float_voltage(self, voltage: float) -> WriteResult:
        """Establece voltaje de flotación (registro 0x2123)."""
        value = int(voltage * 10)
        return self.write_single_register(0x2123, value)

    def set_absorb_voltage(self, voltage: float) -> WriteResult:
        """Establece voltaje de absorción (registro 0x2122)."""
        value = int(voltage * 10)
        return self.write_single_register(0x2122, value)

    def set_cutoff_voltage(self, voltage: float) -> WriteResult:
        """Establece voltaje de corte (registro 0x211F)."""
        value = int(voltage * 10)
        return self.write_single_register(0x211F, value)

    def set_recharge_voltage(self, voltage: float) -> WriteResult:
        """Establece voltaje de recarga (registro 0x2156)."""
        value = int(voltage * 10)
        return self.write_single_register(0x2156, value)

    def set_back_to_battery_voltage(self, voltage: float) -> WriteResult:
        """Establece voltaje de regreso a batería (registro 0x2159)."""
        value = int(voltage * 10)
        return self.write_single_register(0x2159, value)

    def set_output_priority(self, priority: OutputPriority) -> WriteResult:
        """Establece prioridad de salida (registro 0x212A)."""
        return self.write_single_register(0x212A, priority.value)

    def set_charge_priority(self, priority: ChargePriority) -> WriteResult:
        """Establece prioridad de carga (registro 0x212C)."""
        return self.write_single_register(0x212C, priority.value)

    def set_max_charge_current(self, current: int) -> WriteResult:
        """Establece corriente máxima de carga (registro 0x212E)."""
        return self.write_single_register(0x212E, current)

    def set_max_ac_charge_current(self, current: int) -> WriteResult:
        """Establece corriente máxima de carga AC (registro 0x2130)."""
        return self.write_single_register(0x2130, current)

    # ─────────────────────────────────────────────────────────────────────────
    # Utilidades
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _signed_value(value: int) -> int:
        """Convierte un valor unsigned de 16 bits a signed."""
        if value >= 0x8000:
            return value - 0x10000
        return value


# ══════════════════════════════════════════════════════════════════════════════
# HILO DE MONITOREO MODBUS
# ══════════════════════════════════════════════════════════════════════════════

if HAS_QT:
    class ModbusMonitorThread(QThread):
        """
        Hilo que hace polling del estado del inversor via Modbus RTU.
        Implementación similar a StatusRetriever.cs del proyecto C#.
        """
        data_received = pyqtSignal(object)  # ModbusStatus
        error_occurred = pyqtSignal(str)
        latency_update = pyqtSignal(float)  # ms
        status_changed = pyqtSignal(str)  # modo como string

        def __init__(self, conn: ModbusConnection, interval: float = 3.0):
            super().__init__()
            self.conn = conn
            self.interval = interval
            self._running = False
            self._poll_counter = 0

        def run(self):
            self._running = True
            while self._running:
                self._poll()
                time.sleep(self.interval)

        def stop(self):
            self._running = False
            self.wait(3000)

        def _poll(self):
            start_time = time.perf_counter()

            # Leer estado
            status = self.conn.read_status()

            latency_ms = (time.perf_counter() - start_time) * 1000
            self.latency_update.emit(round(latency_ms, 1))

            if status is None:
                self.error_occurred.emit("Sin respuesta del inversor (timeout)")
                return

            # Emitir datos
            self.data_received.emit(status)

            # Cada 5 polls, también leer settings para actualizar modo
            self._poll_counter += 1
            if self._poll_counter % 5 == 0:
                self.status_changed.emit(str(status.working_mode))


# ══════════════════════════════════════════════════════════════════════════════
# AUTO-DETECCIÓN DE PARÁMETROS MODBUS
# ══════════════════════════════════════════════════════════════════════════════

if HAS_QT:
    class ModbusAutoDetectThread(QThread):
        """
        Prueba combinaciones de baud rate y configuración para encontrar
        la configuración correcta del inversor.
        """
        progress = pyqtSignal(str)
        found = pyqtSignal(str, dict)  # (puerto, config)
        not_found = pyqtSignal()

        def __init__(self, port: str):
            super().__init__()
            self.port = port

        def run(self):
            configs_to_try = [
                {'baudrate': 2400, 'parity': serial.PARITY_NONE},
                {'baudrate': 9600, 'parity': serial.PARITY_NONE},
                {'baudrate': 19200, 'parity': serial.PARITY_NONE},
                {'baudrate': 2400, 'parity': serial.PARITY_EVEN},
                {'baudrate': 9600, 'parity': serial.PARITY_EVEN},
            ]

            for cfg in configs_to_try:
                full_cfg = {**DEFAULT_MODBUS_CONFIG, **cfg}
                self.progress.emit(
                    f"Probando {self.port} @ {cfg['baudrate']} baud "
                    f"parity={cfg['parity']} ..."
                )

                conn = ModbusConnection(self.port, full_cfg)
                ok, msg = conn.connect()

                if not ok:
                    self.progress.emit(f"  Error: {msg}")
                    continue

                # Intentar leer registros de estado
                regs = conn.read_holding_registers(STATUS_START, 5)
                conn.disconnect()

                if regs is not None and len(regs) >= 5:
                    # Verificar que los valores sean razonables
                    # Battery voltage en offset 7 debería ser ~48-60V (4800-6000 como raw)
                    if 4000 < regs[7] < 6500:  # Rango típico para 48V battery
                        self.progress.emit(
                            f"  ENCONTRADO: Modbus @ {cfg['baudrate']} baud  "
                            f"[bat_v={regs[7]/100}V]"
                        )
                        self.found.emit(self.port, full_cfg)
                        return

                time.sleep(0.3)

            self.not_found.emit()


# ══════════════════════════════════════════════════════════════════════════════
# TEST / DEBUG
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python felicity_modbus.py COM3 [baudrate]")
        print()
        print("Ejemplos:")
        print("  python felicity_modbus.py COM3")
        print("  python felicity_modbus.py /dev/ttyUSB0")
        print("  python felicity_modbus.py COM3 2400")
        sys.exit(1)

    port = sys.argv[1]
    baudrate = int(sys.argv[2]) if len(sys.argv) > 2 else 2400

    print(f"╔══════════════════════════════════════════════════════╗")
    print(f"║         FELICITY INVERTER - MODBUS RTU TEST         ║")
    print(f"╠══════════════════════════════════════════════════════╣")
    print(f"║  Puerto: {port:<42}║")
    print(f"║  Baudrate: {baudrate}                                      ║")
    print(f"║  Protocolo: Modbus RTU                              ║")
    print(f"╚══════════════════════════════════════════════════════╝")
    print()

    conn = ModbusConnection(port, {'baudrate': baudrate})
    ok, msg = conn.connect()

    print(f"Conexión: {msg}")
    print()

    if ok:
        # Leer estado
        print("─" * 50)
        print("LECTURA DE ESTADO (0x1101 - 0x112A)")
        print("─" * 50)

        start = time.perf_counter()
        status = conn.read_status()
        latency = (time.perf_counter() - start) * 1000

        if status:
            print(f"Latencia: {latency:.0f}ms")
            print()
            print(f"  Modo trabajo:      {status.working_mode}")
            print(f"  Modo carga:        {status.charge_mode}")
            print(f"  ────────────────────────────────")
            print(f"  BATERÍA:")
            print(f"    Voltaje:         {status.battery_voltage:.1f}V")
            print(f"    Corriente:      {status.battery_charge_a:.1f}A carga / {status.battery_discharge_a:.1f}A descarga")
            print(f"    Potencia:        {status.battery_charge_w}W carga / {status.battery_discharge_w}W descarga")
            print(f"  ────────────────────────────────")
            print(f"  SALIDA AC:")
            print(f"    Voltaje:         {status.output_voltage:.1f}V")
            print(f"    Potencia carga:  {status.load_watts}W")
            print(f"    Carga:           {status.load_percent}%")
            print(f"  ────────────────────────────────")
            print(f"  RED:")
            print(f"    Voltaje:         {status.grid_voltage:.1f}V")
            print(f"  ────────────────────────────────")
            print(f"  PANEL SOLAR:")
            print(f"    Voltaje PV:      {status.pv_voltage:.1f}V")
            print(f"    Potencia PV:     {status.pv_power}W")
        else:
            print("ERROR: No se pudo leer el estado del inversor")
            print("Verifica:")
            print("  - Cable USB/RS232 conectado")
            print("  - Puerto correcto")
            print("  - Baudrate 2400")
            print("  - El inversor está encendido")

        print()
        print("─" * 50)
        print("LECTURA DE CONFIGURACIÓN (0x211F - 0x2159)")
        print("─" * 50)

        settings = conn.read_settings()
        if settings:
            print()
            print(f"  BATERÍA:")
            print(f"    Voltaje flotación:    {settings.battery_float_voltage:.1f}V")
            print(f"    Voltaje absorción:    {settings.battery_cv_voltage:.1f}V")
            print(f"    Voltaje corte:        {settings.battery_cutoff_voltage:.1f}V")
            print(f"    Voltaje recarga:       {settings.battery_back_to_grid_voltage:.1f}V")
            print(f"  ────────────────────────────────")
            print(f"  PRIORIDADES:")
            print(f"    Salida:               {settings.output_priority}")
            print(f"    Carga:                {settings.charge_priority}")
            print(f"  ────────────────────────────────")
            print(f"  CORRIENTES:")
            print(f"    Máx carga:           {settings.max_charge_current}A")
            print(f"    Máx carga AC:         {settings.max_ac_charge_current}A")
        else:
            print("ERROR: No se pudo leer la configuración")

        conn.disconnect()
    else:
        print("No se pudo conectar al inversor")
        print()
        print("Puertos disponibles:")
        for p in list_serial_ports():
            print(f"  - {p}")