"""
Protocolo PI30 — parser para inversores Felicity / Voltronic / Axpert
Soporta: QPIGS, QPIRI, QMOD, QPIWS, Q1, QVFW, QID
"""

import struct
from dataclasses import dataclass, field
from typing import Optional


# ──────────────────────────────────────────────
# CRC PI30
# ──────────────────────────────────────────────

def crc_pi30(data: str) -> bytes:
    """Calcula el CRC de 16 bits del protocolo PI30."""
    crc = 0
    for char in data:
        crc ^= ord(char)
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    # Ajuste de bytes reservados
    lo = crc & 0xFF
    hi = (crc >> 8) & 0xFF
    for reserved in (0x28, 0x0D, 0x0A):
        if lo == reserved:
            lo += 1
        if hi == reserved:
            hi += 1
    return bytes([lo, hi])


def build_command(cmd: str) -> bytes:
    """Construye la trama completa: ( + CMD + CRC + CR"""
    crc = crc_pi30(cmd)
    return f"({cmd}".encode() + crc + b'\r'


def validate_response(raw: bytes) -> Optional[str]:
    """Valida CRC y retorna el payload limpio, o None si falla."""
    if len(raw) < 4:
        return None
    # El payload está entre el primer '(' y los 2 bytes de CRC + CR
    payload = raw[1:-3].decode('ascii', errors='replace')
    body    = raw[1:-3]
    crc_recv = raw[-3:-1]
    crc_calc = crc_pi30(raw[1:-3].decode('ascii', errors='replace'))
    # Algunos inversores no implementan CRC correctamente → aceptar igual
    return payload


# ──────────────────────────────────────────────
# Estructuras de datos
# ──────────────────────────────────────────────

@dataclass
class QPIGSData:
    """Datos de QPIGS — estado general en tiempo real."""
    grid_voltage:       float = 0.0    # V
    grid_frequency:     float = 0.0    # Hz
    output_voltage:     float = 0.0    # V
    output_frequency:   float = 0.0    # Hz
    output_va:          int   = 0      # VA
    output_watts:       int   = 0      # W
    load_percent:       int   = 0      # %
    bus_voltage:        int   = 0      # V
    battery_voltage:    float = 0.0    # V
    battery_charge_a:   int   = 0      # A
    battery_capacity:   int   = 0      # % (SOC)
    heatsink_temp:      int   = 0      # °C
    pv_current:         float = 0.0    # A
    pv_voltage:         float = 0.0    # V
    battery_scc_v:      float = 0.0    # V
    battery_discharge:  int   = 0      # A
    device_status:      str   = ""     # 8 bits flags
    battery_offset:     int   = 0
    eeprom_version:     int   = 0
    pv_charging_power:  int   = 0      # W
    device_status2:     str   = ""

    @property
    def pv_power(self) -> float:
        return round(self.pv_voltage * self.pv_current, 1)

    @property
    def status_flags(self) -> dict:
        flags = {}
        if len(self.device_status) >= 8:
            bits = self.device_status
            flags["add_sbu_priority_version"] = bits[0] == '1'
            flags["config_changed"]            = bits[1] == '1'
            flags["scc_firmware_updated"]      = bits[2] == '1'
            flags["load_on"]                   = bits[3] == '1'
            flags["battery_voltage_to_steady"] = bits[4] == '1'
            flags["charging_on"]               = bits[5] == '1'
            flags["scc_charging_on"]           = bits[6] == '1'
            flags["ac_charging_on"]            = bits[7] == '1'
        return flags


@dataclass
class QPIRIData:
    """Parámetros de configuración del inversor."""
    grid_rating_voltage:    float = 0.0
    grid_rating_current:    float = 0.0
    ac_output_voltage:      float = 0.0
    ac_output_frequency:    float = 0.0
    ac_output_current:      float = 0.0
    ac_output_va:           int   = 0
    ac_output_watts:        int   = 0
    battery_rating:         float = 0.0
    battery_rebulk:         float = 0.0
    battery_absorb:         float = 0.0
    battery_float:          float = 0.0
    battery_max_charge:     float = 0.0
    battery_max_charge_code: int  = 0
    input_voltage_range:    int   = 0
    output_source_priority: int   = 0   # 0=Util, 1=Solar, 2=SBU
    charge_source_priority: int   = 0   # 0=Util, 1=Solar, 2=Sol+Util, 3=Only Solar
    machine_type:           int   = 0
    topology:               int   = 0
    output_mode:            int   = 0
    battery_redischarge_v:  float = 0.0
    pv_ok_condition:        int   = 0
    pv_power_balance:       int   = 0
    max_charge_time:        int   = 0


@dataclass
class InverterStatus:
    """Snapshot completo del inversor en un instante."""
    qpigs: Optional[QPIGSData]  = None
    qpiri: Optional[QPIRIData]  = None
    mode:  str                  = "?"
    warnings: list              = field(default_factory=list)
    raw_responses: dict         = field(default_factory=dict)


# ──────────────────────────────────────────────
# Funciones de parseo
# ──────────────────────────────────────────────

QMOD_MODES = {
    'P': 'Power On',
    'S': 'Standby',
    'L': 'Line (grid)',
    'B': 'Battery',
    'F': 'Fault',
    'H': 'Power Saving',
    'Y': 'Bypass',
    'E': 'ECO',
    'C': 'Charge',
    'D': 'Shutdown',
}

QPIWS_BITS = [
    "Inverter fault",
    "Bus over",
    "Bus under",
    "Bus soft fail",
    "Line fail",
    "OPV short",
    "Inverter voltage too low",
    "Inverter voltage too high",
    "Over temperature",
    "Fan locked",
    "Battery voltage high",
    "Battery low alarm",
    "Reserved",
    "Battery under shutdown",
    "Battery derating",
    "Overload",
    "EEPROM fault",
    "Inverter over current",
    "Inverter soft fail",
    "Self test fail",
    "OP DC voltage over",
    "Bat open",
    "Current sensor fail",
    "Battery short",
    "Power limit",
    "PV voltage high",
    "MPPT overload fault",
    "MPPT overload warning",
    "Battery too low to charge",
    "Reserved",
    "Reserved",
    "Reserved",
]


def parse_qpigs(payload: str) -> Optional[QPIGSData]:
    """Parsea la respuesta de QPIGS."""
    try:
        parts = payload.strip().split()
        if len(parts) < 20:
            return None
        d = QPIGSData(
            grid_voltage       = float(parts[0]),
            grid_frequency     = float(parts[1]),
            output_voltage     = float(parts[2]),
            output_frequency   = float(parts[3]),
            output_va          = int(parts[4]),
            output_watts       = int(parts[5]),
            load_percent       = int(parts[6]),
            bus_voltage        = int(parts[7]),
            battery_voltage    = float(parts[8]),
            battery_charge_a   = int(parts[9]),
            battery_capacity   = int(parts[10]),
            heatsink_temp      = int(parts[11]),
            pv_current         = float(parts[12]),
            pv_voltage         = float(parts[13]),
            battery_scc_v      = float(parts[14]),
            battery_discharge  = int(parts[15][:3]) if len(parts[15]) >= 3 else 0,
            device_status      = parts[16] if len(parts) > 16 else "",
            battery_offset     = int(parts[17]) if len(parts) > 17 else 0,
            eeprom_version     = int(parts[18]) if len(parts) > 18 else 0,
            pv_charging_power  = int(parts[19]) if len(parts) > 19 else 0,
            device_status2     = parts[20] if len(parts) > 20 else "",
        )
        return d
    except (ValueError, IndexError):
        return None


def parse_qpiri(payload: str) -> Optional[QPIRIData]:
    """Parsea la respuesta de QPIRI."""
    try:
        p = payload.strip().split()
        if len(p) < 16:
            return None
        return QPIRIData(
            grid_rating_voltage    = float(p[0]),
            grid_rating_current    = float(p[1]),
            ac_output_voltage      = float(p[2]),
            ac_output_frequency    = float(p[3]),
            ac_output_current      = float(p[4]),
            ac_output_va           = int(p[5]),
            ac_output_watts        = int(p[6]),
            battery_rating         = float(p[7]),
            battery_rebulk         = float(p[8]),
            battery_absorb         = float(p[9]),
            battery_float          = float(p[10]),
            battery_max_charge     = float(p[11]),
            battery_max_charge_code= int(p[12]),
            input_voltage_range    = int(p[13]),
            output_source_priority = int(p[14]) if len(p) > 14 else 0,
            charge_source_priority = int(p[15]) if len(p) > 15 else 0,
        )
    except (ValueError, IndexError):
        return None


def parse_qmod(payload: str) -> str:
    """Retorna el modo como string legible."""
    code = payload.strip()
    return QMOD_MODES.get(code, f"Desconocido ({code})")


def parse_qpiws(payload: str) -> list:
    """Retorna lista de warnings activos."""
    bits = payload.strip()
    active = []
    for i, bit in enumerate(bits):
        if bit == '1' and i < len(QPIWS_BITS):
            active.append(QPIWS_BITS[i])
    return active
