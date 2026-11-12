"""
register_maps.py — Mapas de registros por modelo de inversor
============================================================
Define el layout de registros para cada familia de inversor Felicity.
La tabla CLASICO es la que usa hoy la app (Voltronic/Axpert/IVEM 48V).
La tabla IVGM_8K corresponde a la serie "RS485" (IVGM8KLP2G1).

Las tablas replican exactamente las de verificar_rs485.py para que la
app y la sonda interpreten los registros de la misma forma.

IVGM-8K: mapa VALIDADO contra hardware real (ver docs/prueba coenxion).
Telemetría 0x1118-0x116F y configuración de paralelo 0x2140-0x2143.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Dict, Optional


# ══════════════════════════════════════════════════════════════════════════════
# ESTRUCTURAS
# ══════════════════════════════════════════════════════════════════════════════

# El firmware de Felicity usa 0xFFFE (-2) y 0xFFFF (-1) para marcar
# "parámetro no configurado / no disponible". NO son datos: hay que
# ignorarlos en lugar de mostrarlos como -2 o 65534.
NOT_AVAILABLE_VALUES = (0xFFFE, 0xFFFF)


def is_not_available(raw: Optional[int]) -> bool:
    """True si el registro bruto marca 'no disponible'."""
    return raw is not None and raw in NOT_AVAILABLE_VALUES

# ESTRUCTURAS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class FieldDef:
    """Definición de un campo dentro de un mapa de registros."""

    key: str
    address: int
    label: str
    scale: float = 1.0
    signed: bool = False
    unit: str = ""


@dataclass(frozen=True)
class RegisterMap:
    """Mapa de registros completo de un modelo de inversor."""

    name: str
    label: str
    status_start: int
    status_count: int
    settings_start: Optional[int] = None
    settings_count: int = 0
    info_start: Optional[int] = None
    info_count: int = 0
    fields: Dict[str, FieldDef] = field(default_factory=dict)
    derived_keys: frozenset = frozenset()
    # Campos del bloque de ajustes (direcciones relativas a settings_start).
    settings_fields: Dict[str, FieldDef] = field(default_factory=dict)

    def provides(self, key: str) -> bool:
        """Indica si el mapa puede decodificar un campo canónico."""
        return key in self.fields or key in self.derived_keys

    def field_for(self, key: str) -> Optional[FieldDef]:
        """Devuelve la definición de un campo propio del mapa."""
        return self.fields.get(key)

    def settings_field_for(self, key: str) -> Optional[FieldDef]:
        """Devuelve la definición de un campo del bloque de ajustes."""
        return self.settings_fields.get(key)


# ══════════════════════════════════════════════════════════════════════════════
# MAPA CLÁSICO (Voltronic / Axpert / IVEM 48V)
# ══════════════════════════════════════════════════════════════════════════════

CLASSIC_MAP = RegisterMap(
    name="classic",
    label="Clásico Voltronic/Axpert (5K, IVEM 48V)",
    status_start=0x1100,
    status_count=43,
    settings_start=0x211F,
    settings_count=59,
    info_start=0xF800,
    info_count=13,
    fields={
        "setting_data_sn": FieldDef("setting_data_sn", 0x1100, "SettingDataSn"),
        "working_mode": FieldDef("working_mode", 0x1101, "Working mode"),
        "charge_mode": FieldDef("charge_mode", 0x1102, "Charge mode"),
        "fault_code": FieldDef("fault_code", 0x1103, "Fault code"),
        "power_flow": FieldDef("power_flow", 0x1104, "PowerFlowMsg"),
        "battery_voltage": FieldDef("battery_voltage", 0x1108, "Battery voltage", 0.01, False, "V"),
        "battery_current": FieldDef("battery_current", 0x1109, "Battery current", 1.0, True, "A"),
        "battery_power": FieldDef("battery_power", 0x110A, "Battery power", 1.0, True, "W"),
        "output_voltage": FieldDef("output_voltage", 0x1111, "AC output voltage", 0.1, False, "V"),
        "grid_voltage": FieldDef("grid_voltage", 0x1117, "Grid voltage", 0.1, False, "V"),
        "grid_frequency": FieldDef("grid_frequency", 0x1119, "Grid frequency", 0.01, False, "Hz"),
        "output_active_power": FieldDef("output_active_power", 0x111E, "Output active power", 1.0, True, "W"),
        "output_apparent_power": FieldDef("output_apparent_power", 0x111F, "Output apparent power", 1.0, False, "VA"),
        "load_percent": FieldDef("load_percent", 0x1120, "Load percent", 1.0, False, "%"),
        "pv_voltage": FieldDef("pv_voltage", 0x1126, "PV voltage", 0.1, False, "V"),
        "pv_power": FieldDef("pv_power", 0x112A, "PV power", 1.0, True, "W"),
    },
)


# ══════════════════════════════════════════════════════════════════════════════
# MAPA IVGM-8K (Felicity "Series RS485")
# ══════════════════════════════════════════════════════════════════════════════

IVGM_8K_MAP = RegisterMap(
    name="ivgm_8k",
    label="IVGM-8K (Felicity Series RS485)",
    status_start=0x1100,
    status_count=130,        # 0x1100 - 0x1181
    settings_start=0x2140,   # bloque de configuración de paralelo
    settings_count=4,
    info_start=0xF800,
    info_count=14,
    fields={
        # ── Identificación / estado general ─────────────────────────────
        "work_mode": FieldDef("work_mode", 0x1100, "WorkMode"),
        "state1": FieldDef("state1", 0x1101, "State1"),
        "state2": FieldDef("state2", 0x1102, "State2"),
        "state3": FieldDef("state3", 0x1103, "State3"),
        "state4": FieldDef("state4", 0x1104, "State4"),
        "warn_code": FieldDef("warn_code", 0x1109, "Warn code"),
        "fault_code": FieldDef("fault_code", 0x110A, "Fault code"),

        # ── Fotovoltaica ─────────────────────────────────────────────────
        "pv1_voltage": FieldDef("pv1_voltage", 0x1118, "PV1 voltage", 0.1, False, "V"),
        "pv2_voltage": FieldDef("pv2_voltage", 0x1119, "PV2 voltage", 0.1, False, "V"),
        "pv1_current": FieldDef("pv1_current", 0x111C, "PV1 current", 0.1, True, "A"),
        "pv2_current": FieldDef("pv2_current", 0x111D, "PV2 current", 0.1, True, "A"),
        "pv1_power": FieldDef("pv1_power", 0x1128, "PV1 power", 1.0, True, "W"),
        "pv2_power": FieldDef("pv2_power", 0x1129, "PV2 power", 1.0, True, "W"),
        "pv3_power": FieldDef("pv3_power", 0x112A, "PV3 power", 1.0, True, "W"),
        "pv4_power": FieldDef("pv4_power", 0x112B, "PV4 power", 1.0, True, "W"),

        # ── Batería 1 ───────────────────────────────────────────────────
        "battery_voltage": FieldDef("battery_voltage", 0x112C, "Bat1 voltage", 0.1, False, "V"),
        "battery_current": FieldDef("battery_current", 0x1130, "Bat1 current", 0.1, True, "A"),
        "battery_power": FieldDef("battery_power", 0x1131, "Bat1 power", 1.0, True, "W"),
        "battery_soc": FieldDef("battery_soc", 0x1138, "Bat1 SOC", 0.1, False, "%"),

        # ── Salida AC (salida del inversor) ─────────────────────────────
        "output_frequency": FieldDef("output_frequency", 0x113E, "Output frequency", 0.01, False, "Hz"),
        "output_voltage_a": FieldDef("output_voltage_a", 0x113F, "AC output voltage fase A", 0.1, False, "V"),
        "output_voltage_b": FieldDef("output_voltage_b", 0x1140, "AC output voltage fase B", 0.1, False, "V"),

        # ── Temperaturas ────────────────────────────────────────────────
        "boost_temp": FieldDef("boost_temp", 0x1144, "Temperatura boost", 1.0, False, "°C"),
        "inverter_temp": FieldDef("inverter_temp", 0x1145, "Temperatura inversor", 1.0, False, "°C"),
        "ambient_temp": FieldDef("ambient_temp", 0x1146, "Temperatura ambiente", 1.0, False, "°C"),
        "battery_temp": FieldDef("battery_temp", 0x1147, "Temperatura batería", 0.1, False, "°C"),

        # ── Red / inversor / carga (entradas A y B) ─────────────────────
        "grid_a_voltage": FieldDef("grid_a_voltage", 0x1150, "Tensión red fase A", 0.1, False, "V"),
        "grid_b_voltage": FieldDef("grid_b_voltage", 0x1151, "Tensión red fase B", 0.1, False, "V"),
        "inverter_a_voltage": FieldDef("inverter_a_voltage", 0x1153, "Tensión inversor fase A", 0.1, False, "V"),
        "inverter_b_voltage": FieldDef("inverter_b_voltage", 0x1154, "Tensión inversor fase B", 0.1, False, "V"),
        "load_a_voltage": FieldDef("load_a_voltage", 0x1156, "Tensión carga fase A", 0.1, False, "V"),
        "load_b_voltage": FieldDef("load_b_voltage", 0x1157, "Tensión carga fase B", 0.1, False, "V"),
        "load_a_current": FieldDef("load_a_current", 0x1162, "Corriente carga fase A", 0.1, True, "A"),
        "load_b_current": FieldDef("load_b_current", 0x1163, "Corriente carga fase B", 0.1, True, "A"),

        # ── Frecuencias ─────────────────────────────────────────────────
        "inverter_frequency": FieldDef("inverter_frequency", 0x116E, "Frecuencia inversor", 0.01, False, "Hz"),
        "load_frequency": FieldDef("load_frequency", 0x116F, "Frecuencia carga", 0.01, False, "Hz"),

        # ── Porcentaje de carga ────────────────────────────────────────
        "load_a_percent": FieldDef("load_a_percent", 0x117F, "Carga fase A", 1.0, False, "%"),
        "load_b_percent": FieldDef("load_b_percent", 0x1180, "Carga fase B", 1.0, False, "%"),

        # ── Potencias de salida ────────────────────────────────────────
        "load_a": FieldDef("load_a", 0x1120, "Home load A", 1.0, True, "W"),
        "load_b": FieldDef("load_b", 0x1121, "Home load B", 1.0, True, "W"),
    },
    # Bloque de configuración de paralelo (0x2140-0x2143).
    settings_fields={
        "parallel_count": FieldDef("parallel_count", 0x2140, "Cantidad de inversores en paralelo"),
        "parallel_address": FieldDef("parallel_address", 0x2141, "Dirección de paralelo (1=maestro)"),
        "modbus_id": FieldDef("modbus_id", 0x2142, "Modbus ID (slave id)"),
        "rated_power": FieldDef("rated_power", 0x2143, "Potencia nominal", 1.0, False, "W"),
    },
    derived_keys=frozenset({
        "working_mode", "output_active_power", "pv_voltage", "pv_power",
        "output_voltage", "grid_voltage", "grid_frequency", "load_percent",
        "output_frequency",
    }),
)


# ══════════════════════════════════════════════════════════════════════════════
# MAPA MUST (PH/PV/EP — "Bloque D")
# ══════════════════════════════════════════════════════════════════════════════
#
# ATENCIÓN: este mapa proviene de una herramienta de terceros (aggsoft,
# "PV Inverter 3600") y NO está validado contra hardware real.
# Validalo con verificar_rs485.py antes de confiar en los valores.

MUST_MAP = RegisterMap(
    name="must",
    label="MUST PH/PV/EP (Bloque D) — SIN VALIDAR",
    status_start=0x6271,
    status_count=35,
    fields={
        "working_mode":        FieldDef("working_mode", 0x6271, "Inverter Work State"),
        "battery_voltage":     FieldDef("battery_voltage", 0x6275, "Battery Voltage", 0.1, False, "V"),
        "output_voltage":      FieldDef("output_voltage", 0x6276, "Inverter Output Voltage", 0.1, False, "V"),
        "grid_voltage":        FieldDef("grid_voltage", 0x6277, "Grid Voltage", 0.1, False, "V"),
        "battery_current":     FieldDef("battery_current", 0x6279, "Battery Current", 0.1, True, "A"),
        "output_current":      FieldDef("output_current", 0x627A, "Inverter Output Current", 0.1, True, "A"),
        "inverter_power":      FieldDef("inverter_power", 0x627D, "Inverter Power", 1.0, True, "W"),
        "grid_power":          FieldDef("grid_power", 0x627E, "Grid Power", 1.0, True, "W"),
        "output_active_power": FieldDef("output_active_power", 0x627F, "Load Power", 1.0, True, "W"),
        "load_percent":        FieldDef("load_percent", 0x6280, "System Load Percentage", 1.0, False, "%"),
        "battery_soc":         FieldDef("battery_soc", 0x6283, "Battery Capacity (SOC)", 1.0, False, "%"),
    },
)


# ══════════════════════════════════════════════════════════════════════════════
# REGISTRO DE MAPAS
# ══════════════════════════════════════════════════════════════════════════════

MAPS: Dict[str, RegisterMap] = {m.name: m for m in (CLASSIC_MAP, IVGM_8K_MAP, MUST_MAP)}

# Claves canónicas que la app consume en la UI. Todo mapa debe poder
# decodificarlas; si un mapa no las provee, valen 0.0.
CANONICAL_STATUS_KEYS = (
    "working_mode",
    "charge_mode",
    "fault_code",
    "battery_voltage",
    "battery_current",
    "battery_power",
    "output_voltage",
    "output_frequency",
    "grid_voltage",
    "grid_frequency",
    "output_active_power",
    "output_apparent_power",
    "load_percent",
    "pv_voltage",
    "pv_power",
)


def get_map(name) -> RegisterMap:
    """
    Resuelve un mapa por nombre. Acepta un RegisterMap directamente.
    Si el nombre es desconocido, devuelve el mapa clásico con una advertencia.
    """
    if isinstance(name, RegisterMap):
        return name
    key = (name or "classic").lower()
    if key not in MAPS:
        warnings.warn(
            f"Mapa de registros desconocido '{name}'; usando 'classic'",
            stacklevel=2,
        )
        return CLASSIC_MAP
    return MAPS[key]


# ══════════════════════════════════════════════════════════════════════════════
# DECODIFICACIÓN
# ══════════════════════════════════════════════════════════════════════════════

def to_signed(value: int) -> int:
    """Convierte un valor de 16 bits sin signo a con signo."""
    return value - 0x10000 if value >= 0x8000 else value


def decode_status_fields(
    registers: list,
    start_address: int,
    map: RegisterMap,
) -> Dict[str, float]:
    """
    Decodifica un bloque de registros de estado aplicando el mapa dado.

    Devuelve un diccionario con las claves canónicas del mapa clásico
    (working_mode, battery_voltage, pv_power, ...) más las claves
    propias del mapa (battery_soc, pv1_voltage, ...). Los campos que el
    mapa no provee quedan en 0.0.
    """
    if map is None:
        map = CLASSIC_MAP
    if isinstance(map, str):
        map = get_map(map)

    by_address = {start_address + i: v for i, v in enumerate(registers or [])}

    decoded: Dict[str, float] = {}
    for key, field_def in map.fields.items():
        raw = by_address.get(field_def.address)
        if raw is None:
            continue
        # 0xFFFE / 0xFFFF = "no configurado / no disponible". No son datos.
        if is_not_available(raw):
            continue
        value = to_signed(raw) if field_def.signed else raw
        decoded[key] = value * field_def.scale

    # Alias canónicos para mapas con nombres de campo distintos.
    if map.name == "ivgm_8k":
        decoded["working_mode"] = decoded.get("work_mode", 0.0)
        decoded["pv_voltage"] = decoded.get("pv1_voltage", 0.0)
        decoded["pv_power"] = (
            decoded.get("pv1_power", 0.0)
            + decoded.get("pv2_power", 0.0)
            + decoded.get("pv3_power", 0.0)
            + decoded.get("pv4_power", 0.0)
        )
        decoded["output_active_power"] = (
            decoded.get("load_a", 0.0) + decoded.get("load_b", 0.0)
        )
        # Salida AC: fase A como tensión de salida; la red se lee de la
        # entrada de red (0x1150/0x1151) y la frecuencia del inversor.
        decoded["output_voltage"] = decoded.get("output_voltage_a", 0.0)
        decoded["grid_voltage"] = decoded.get("grid_a_voltage", 0.0)
        decoded["grid_frequency"] = decoded.get("inverter_frequency", 0.0)
        decoded["output_frequency"] = decoded.get("output_frequency", 0.0)
        decoded["load_percent"] = decoded.get("load_a_percent", 0.0)

    for key in CANONICAL_STATUS_KEYS:
        decoded.setdefault(key, 0.0)

    return decoded


def decode_settings_fields(
    registers: list,
    start_address: int,
    map: RegisterMap,
) -> Dict[str, float]:
    """
    Decodifica el bloque de ajustes (configuración) de un mapa.

    Devuelve las claves definidas en ``map.settings_fields``. Los registros
    marcados como "no disponible" (0xFFFE / 0xFFFF) se omiten.
    """
    if map is None:
        return {}
    if isinstance(map, str):
        map = get_map(map)

    by_address = {start_address + i: v for i, v in enumerate(registers or [])}

    decoded: Dict[str, float] = {}
    for key, field_def in map.settings_fields.items():
        raw = by_address.get(field_def.address)
        if raw is None or is_not_available(raw):
            continue
        value = to_signed(raw) if field_def.signed else raw
        decoded[key] = value * field_def.scale
    return decoded
