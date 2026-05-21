"""
profiles.py — Perfiles de inversor configurables
Cada perfil define: protocolo, batería, rangos de voltaje y comandos válidos.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional


# ──────────────────────────────────────────────
# Tipos de batería
# ──────────────────────────────────────────────

# Velocidades de puerto serie estándar
BAUD_RATES = [2400, 4800, 9600, 14400, 19200, 38400, 57600, 115200]

BATTERY_TYPES = ["LiFePO4", "AGM", "GEL", "Flooded", "Litio (otro)"]

BATTERY_VOLTAGE_BANKS = [12, 24, 36, 48, 60, 72]

OUTPUT_PRIORITIES = {
    "Utility First (red primero)": "POP00",
    "Solar First (solar primero)": "POP01",
    "SBU (Solar→Batería→Red)":     "POP02",
}

CHARGE_PRIORITIES = {
    "Utility Only (solo red)":        "PCP00",
    "Solar First (solar primero)":    "PCP01",
    "Solar + Utility (ambos)":        "PCP02",
    "Solar Only (solo solar)":        "PCP03",
}

# Rangos por tipo de batería y voltaje de banco
# Estructura: { tipo: { banco_v: { param: (min, max, default) } } }
BATTERY_VOLTAGE_RANGES = {
    "LiFePO4": {
        24: {
            "float_v":    (26.0, 27.2, 27.0),
            "absorb_v":   (27.5, 29.2, 28.8),
            "recharge_v": (22.0, 25.5, 24.0),
            "shutdown_v": (20.0, 24.0, 22.0),
        },
        48: {
            "float_v":    (52.0, 54.4, 54.0),
            "absorb_v":   (55.0, 58.4, 56.8),
            "recharge_v": (44.0, 51.0, 48.0),
            "shutdown_v": (42.0, 48.0, 44.0),
        },
    },
    "AGM": {
        24: {
            "float_v":    (27.0, 27.4, 27.2),
            "absorb_v":   (28.0, 29.2, 28.8),
            "recharge_v": (22.0, 25.5, 24.0),
            "shutdown_v": (20.0, 24.0, 21.0),
        },
        48: {
            "float_v":    (54.0, 54.8, 54.4),
            "absorb_v":   (56.0, 58.4, 56.4),
            "recharge_v": (44.0, 51.0, 46.5),
            "shutdown_v": (40.0, 46.0, 42.0),
        },
    },
    "GEL": {
        24: {
            "float_v":    (27.0, 27.4, 27.2),
            "absorb_v":   (27.8, 29.0, 28.6),
            "recharge_v": (22.0, 25.5, 24.0),
            "shutdown_v": (20.0, 24.0, 21.0),
        },
        48: {
            "float_v":    (54.0, 54.8, 54.4),
            "absorb_v":   (55.6, 58.0, 57.2),
            "recharge_v": (44.0, 51.0, 46.5),
            "shutdown_v": (40.0, 46.0, 42.0),
        },
    },
    "Flooded": {
        24: {
            "float_v":    (26.4, 27.2, 26.8),
            "absorb_v":   (28.0, 29.4, 29.0),
            "recharge_v": (22.0, 25.5, 24.0),
            "shutdown_v": (20.0, 24.0, 21.0),
        },
        48: {
            "float_v":    (52.8, 54.4, 53.6),
            "absorb_v":   (56.0, 58.8, 58.0),
            "recharge_v": (44.0, 51.0, 46.5),
            "shutdown_v": (40.0, 46.0, 42.0),
        },
    },
    "Litio (otro)": {
        24: {
            "float_v":    (25.0, 28.0, 27.0),
            "absorb_v":   (27.0, 29.5, 28.8),
            "recharge_v": (20.0, 25.5, 23.0),
            "shutdown_v": (19.0, 24.0, 21.0),
        },
        48: {
            "float_v":    (50.0, 56.0, 54.0),
            "absorb_v":   (54.0, 59.0, 57.6),
            "recharge_v": (40.0, 51.0, 46.0),
            "shutdown_v": (38.0, 48.0, 42.0),
        },
    },
}


# ──────────────────────────────────────────────
# Dataclass del perfil
# ──────────────────────────────────────────────

@dataclass
class InverterProfile:
    name:             str   = "Nuevo perfil"
    brand:            str   = "Genérico"
    model:            str   = ""
    protocol:         str   = "PI30"
    battery_type:     str   = "LiFePO4"
    battery_bank_v:   int   = 48

    # Parámetros de comunicación
    baudrate:         int   = 2400
    parity:           str   = "None"
    stopbits:         int   = 1
    timeout:          float = 2.0

    # Voltajes configurados (se cargan desde los rangos o se personalizan)
    float_v:          float = 54.0
    absorb_v:         float = 56.8
    recharge_v:       float = 48.0
    shutdown_v:       float = 44.0

    # Prioridades actuales
    output_priority:  str   = "Solar First (solar primero)"
    charge_priority:  str   = "Solar + Utility (ambos)"

    # Notas del usuario
    notes:            str   = ""

    def get_ranges(self) -> dict:
        """Retorna los rangos válidos para este perfil."""
        btype = self.battery_type
        bank  = self.battery_bank_v
        if btype in BATTERY_VOLTAGE_RANGES and bank in BATTERY_VOLTAGE_RANGES[btype]:
            return BATTERY_VOLTAGE_RANGES[btype][bank]
        # Fallback genérico para 48V
        return {
            "float_v":    (50.0, 60.0, self.float_v),
            "absorb_v":   (50.0, 62.0, self.absorb_v),
            "recharge_v": (40.0, 55.0, self.recharge_v),
            "shutdown_v": (38.0, 52.0, self.shutdown_v),
        }

    def apply_defaults_from_ranges(self):
        """Carga los valores por defecto según tipo y banco de batería."""
        ranges = self.get_ranges()
        self.float_v    = ranges["float_v"][2]
        self.absorb_v   = ranges["absorb_v"][2]
        self.recharge_v = ranges["recharge_v"][2]
        self.shutdown_v = ranges["shutdown_v"][2]

    def validate_voltages(self) -> list[str]:
        """
        Valida que los voltajes sean coherentes entre sí.
        Retorna lista de errores (vacía = OK).
        """
        errors = []
        ranges = self.get_ranges()

        checks = [
            ("float_v",    "Flotación",  self.float_v),
            ("absorb_v",   "Absorción",  self.absorb_v),
            ("recharge_v", "Recarga",    self.recharge_v),
            ("shutdown_v", "Shutdown",   self.shutdown_v),
        ]

        for key, label, val in checks:
            lo, hi, _ = ranges[key]
            if not (lo <= val <= hi):
                errors.append(f"{label}: {val}V fuera de rango [{lo}V – {hi}V]")

        # Coherencia entre sí
        if self.absorb_v <= self.float_v:
            errors.append(f"Absorción ({self.absorb_v}V) debe ser > Flotación ({self.float_v}V)")
        if self.float_v <= self.recharge_v:
            errors.append(f"Flotación ({self.float_v}V) debe ser > Recarga ({self.recharge_v}V)")
        if self.recharge_v <= self.shutdown_v:
            errors.append(f"Recarga ({self.recharge_v}V) debe ser > Shutdown ({self.shutdown_v}V)")

        return errors

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "InverterProfile":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ──────────────────────────────────────────────
# Perfiles predefinidos
# ──────────────────────────────────────────────

DEFAULT_PROFILES = [
    InverterProfile(
        name="Felicity 5K — LiFePO4 48V",
        brand="Felicity",
        model="5000W Hybrid",
        protocol="PI30",
        battery_type="LiFePO4",
        battery_bank_v=48,
        baudrate=2400,
        float_v=54.0,
        absorb_v=56.8,
        recharge_v=48.0,
        shutdown_v=44.0,
        output_priority="Solar First (solar primero)",
        charge_priority="Solar + Utility (ambos)",
    ),
    InverterProfile(
        name="Axpert 3K — AGM 24V",
        brand="Voltronic / Axpert",
        model="3000W",
        protocol="PI30",
        battery_type="AGM",
        battery_bank_v=24,
        baudrate=2400,
        float_v=27.2,
        absorb_v=28.8,
        recharge_v=24.0,
        shutdown_v=21.0,
        output_priority="Utility First (red primero)",
        charge_priority="Solar + Utility (ambos)",
    ),
    InverterProfile(
        name="Genérico PI30 — 48V",
        brand="Genérico",
        model="",
        protocol="PI30",
        battery_type="AGM",
        battery_bank_v=48,
        baudrate=2400,
        float_v=54.4,
        absorb_v=56.4,
        recharge_v=46.5,
        shutdown_v=42.0,
    ),
]


# ──────────────────────────────────────────────
# Gestor de perfiles (carga/guarda en JSON)
# ──────────────────────────────────────────────

PROFILES_FILE = os.path.join(os.path.dirname(__file__), "..", "profiles.json")


class ProfileManager:
    def __init__(self):
        self.profiles: list[InverterProfile] = []
        self.active_index: int = 0
        self.load()

    def load(self):
        if os.path.exists(PROFILES_FILE):
            try:
                with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.profiles     = [InverterProfile.from_dict(d) for d in data.get("profiles", [])]
                self.active_index = data.get("active_index", 0)
                if not self.profiles:
                    self._load_defaults()
                return
            except Exception:
                pass
        self._load_defaults()

    def _load_defaults(self):
        self.profiles     = list(DEFAULT_PROFILES)
        self.active_index = 0

    def save(self):
        data = {
            "profiles":     [p.to_dict() for p in self.profiles],
            "active_index": self.active_index,
        }
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @property
    def active(self) -> InverterProfile:
        if 0 <= self.active_index < len(self.profiles):
            return self.profiles[self.active_index]
        return self.profiles[0]

    def add(self, profile: InverterProfile):
        self.profiles.append(profile)
        self.save()

    def update(self, index: int, profile: InverterProfile):
        self.profiles[index] = profile
        self.save()

    def delete(self, index: int):
        if len(self.profiles) <= 1:
            return False
        self.profiles.pop(index)
        self.active_index = min(self.active_index, len(self.profiles) - 1)
        self.save()
        return True

    def names(self) -> list[str]:
        return [p.name for p in self.profiles]
