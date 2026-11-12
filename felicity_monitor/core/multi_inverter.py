"""
multi_inverter.py — Motor de polling multi-inversor en paralelo
================================================================
Lee N inversores conectados en paralelo por la misma conexión TCP/serial,
cambiando el slave_id en cada petición Modbus.

Cada inversor puede tener su PROPIO mapa de registros, lo que permite
mezclar modelos en el mismo bus (por ejemplo, un 5K con mapa clásico y un
IVGM-8K con el mapa "Series RS485").
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict
from enum import Enum

from PyQt5.QtCore import QThread, pyqtSignal

from core.felicity_modbus import ModbusStatus, WorkingMode
from core.register_maps import MAPS, get_map
from core.app_paths import data_file


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN MULTI-INVERSOR
# ══════════════════════════════════════════════════════════════════════════════

CONFIG_FILE = data_file("multi_inverter.json")


@dataclass
class InverterEntry:
    """Un inversor dentro del bus: su ID, etiqueta y mapa de registros."""

    slave_id: int = 1
    label: str = ""
    map_name: str = "classic"

    @property
    def map_label(self) -> str:
        """Etiqueta legible del mapa asignado."""
        mapa = MAPS.get(self.map_name)
        return mapa.label if mapa else self.map_name


@dataclass
class MultiInverterConfig:
    """Configuración del sistema multi-inversor."""
    enabled: bool = False
    total_inverters: int = 1        # 1..15 (esquema antiguo, secuencial)
    start_id: int = 1               # ID Modbus del primer inversor (esquema antiguo)
    poll_interval_sec: float = 5.0  # Intervalo entre ciclos completos
    timeout_ms: int = 800           # Timeout por petición individual
    retry_on_timeout: int = 1       # Reintentos por ID antes de marcar Offline
    inverters: List[InverterEntry] = field(default_factory=list)

    def validate(self) -> List[str]:
        """Valida la config y devuelve lista de errores."""
        errors = []
        if self.total_inverters < 1 or self.total_inverters > 15:
            errors.append("total_inverters debe ser 1..15")
        if self.start_id < 1 or self.start_id > 247:
            errors.append("start_id debe ser 1..247")
        if self.poll_interval_sec < 1.0:
            errors.append("poll_interval_sec debe ser >= 1.0")
        if self.timeout_ms < 100 or self.timeout_ms > 5000:
            errors.append("timeout_ms debe ser 100..5000")
        for entry in self.entries:
            if entry.slave_id < 1 or entry.slave_id > 247:
                errors.append(f"slave_id invalido: {entry.slave_id}")
            if entry.map_name not in MAPS:
                errors.append(
                    f"mapa desconocido '{entry.map_name}' en slave {entry.slave_id}"
                )
        return errors

    @property
    def entries(self) -> List[InverterEntry]:
        """
        Entradas efectivas. Si no hay lista explícita, deriva una entrada por
        cada ID secuencial (compatibilidad con el esquema antiguo).
        """
        if self.inverters:
            return list(self.inverters)
        return [
            InverterEntry(
                slave_id=slave_id,
                label=f"Inversor {slave_id}",
                map_name="classic",
            )
            for slave_id in self.inverter_ids
        ]

    @property
    def inverter_ids(self) -> List[int]:
        """Lista de IDs a consultar."""
        if self.inverters:
            return [entry.slave_id for entry in self.inverters]
        return list(range(self.start_id, self.start_id + self.total_inverters))


def load_multi_config() -> MultiInverterConfig:
    """
    Carga la config desde JSON, o devuelve defaults.
    Acepta tanto el esquema nuevo (con "inverters") como el antiguo.
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            entries_data = data.pop('inverters', None)
            config = MultiInverterConfig(**data)
            if entries_data:
                config.inverters = [
                    InverterEntry(
                        slave_id=int(e.get('slave_id', 1)),
                        label=str(e.get('label', '')),
                        map_name=str(e.get('map_name', 'classic')),
                    )
                    for e in entries_data
                ]
            return config
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return MultiInverterConfig()


def save_multi_config(config: MultiInverterConfig):
    """Guarda la config en JSON."""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(asdict(config), f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
# DATOS POR INVERSOR
# ══════════════════════════════════════════════════════════════════════════════

class InverterStatus(Enum):
    """Estado de conexión de un inversor individual."""
    ONLINE = "online"          # Respondió OK
    WARNING = "warning"        # Online con fallo ≠ 0
    FAULT = "fault"            # FaultMode detectado
    OFFLINE = "offline"        # No respondió (timeout)
    UNKNOWN = "unknown"        # Aún no consultado


@dataclass
class InverterData:
    """Datos leídos de un inversor individual."""
    slave_id: int = 1
    label: str = "—"
    map_name: str = "classic"
    status: InverterStatus = InverterStatus.UNKNOWN
    working_mode: str = "—"          # Decodificado en español
    fault_code: int = 0
    fault_description: str = "—"
    battery_voltage: float = 0.0     # V
    battery_current: float = 0.0     # A (signed: + carga, - descarga)
    battery_power: float = 0.0       # W (signed)
    battery_soc: float = 0.0         # %
    output_active_power: float = 0.0 # W
    output_voltage: float = 0.0      # V AC
    pv_voltage: float = 0.0          # V
    pv_power: float = 0.0            # W
    grid_voltage: float = 0.0        # V AC
    grid_frequency: float = 0.0      # Hz
    load_percent: float = 0.0        # %
    # Campos extra de la serie IVGM-8K (mapa "ivgm_8k")
    pv1_voltage: float = 0.0         # 0x1118 — V
    pv2_voltage: float = 0.0         # 0x1119 — V
    inverter_temp: float = 0.0       # 0x1145 — °C
    ambient_temp: float = 0.0        # 0x1146 — °C
    battery_temp: float = 0.0        # 0x1147 — °C
    latency_ms: float = 0.0          # Latencia de esta lectura
    consecutive_timeouts: int = 0    # Timeouts seguidos
    last_seen: float = 0.0           # timestamp del último OK

    @property
    def is_online(self) -> bool:
        return self.status in (InverterStatus.ONLINE, InverterStatus.WARNING)


# ══════════════════════════════════════════════════════════════════════════════
# TABLA DE CÓDIGOS DE FALLO
# ══════════════════════════════════════════════════════════════════════════════

FAULT_CODES_ES = {
    0x01: "Batería baja",
    0x02: "Sobretensión de batería",
    0x04: "Batería desconectada",
    0x08: "Sobrecarga",
    0x10: "Temperatura alta",
    0x20: "Cortocircuito en salida",
    0x40: "Sobretensión en salida",
    0x80: "Sobretensión de red",
    0x100: "Baja tensión de red",
    0x200: "Frecuencia de red fuera de rango",
    0x400: "Sobrecorriente PV",
    0x800: "PV sobretensión",
    0x1000: "Error de comunicación interno",
    0x2000: "Relé de bypass atascado",
    0x4000: "Inversor en estado de fallo",
}


def decode_fault_code(code: int) -> str:
    """Decodifica el código de fallo en descripciones en español."""
    if code == 0:
        return "—"
    faults = []
    for bit, desc in FAULT_CODES_ES.items():
        if code & bit:
            faults.append(desc)
    if not faults:
        return f"Código desconocido ({code:#06x})"
    return "; ".join(faults)


# ══════════════════════════════════════════════════════════════════════════════
# DECODIFICACIÓN DE MODO DE TRABAJO
# ══════════════════════════════════════════════════════════════════════════════

WORKING_MODE_ES = {
    0: "Encendido",
    1: "En espera",
    2: "Bypass (AC directo)",
    3: "Modo batería",
    4: "Falla",
    5: "Modo línea (AC inversor)",
    6: "Carga PV",
}


def decode_working_mode(mode_value: int) -> str:
    """Decodifica el modo de trabajo a español."""
    return WORKING_MODE_ES.get(mode_value, f"Desconocido ({mode_value})")


# ══════════════════════════════════════════════════════════════════════════════
# RESUMEN DEL SISTEMA
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SystemSummary:
    """Resumen agregado de todos los inversores."""
    total_ac_power: float = 0.0          # W (suma)
    total_pv_power: float = 0.0          # W (suma)
    total_battery_power: float = 0.0     # W (suma, negativo = descargando)
    avg_battery_voltage: float = 0.0     # V (promedio de los online)
    avg_battery_soc: float = 0.0         # % (promedio de los online)
    online_count: int = 0                # Inversores online
    total_count: int = 0                 # Total configurado
    alerts: List[str] = field(default_factory=list)  # Lista de alertas

    @classmethod
    def from_inverters(cls, inverters: List[InverterData]) -> 'SystemSummary':
        """Calcula el resumen a partir de la lista de datos individuales."""
        online = [inv for inv in inverters if inv.is_online]

        summary = cls()
        summary.total_count = len(inverters)
        summary.online_count = len(online)

        if online:
            summary.total_ac_power = round(sum(inv.output_active_power for inv in online), 0)
            summary.total_pv_power = round(sum(inv.pv_power for inv in online), 0)
            summary.total_battery_power = round(sum(inv.battery_power for inv in online), 0)
            summary.avg_battery_voltage = round(
                sum(inv.battery_voltage for inv in online) / len(online), 1
            )
            soc_values = [inv.battery_soc for inv in online if inv.battery_soc > 0]
            if soc_values:
                summary.avg_battery_soc = round(sum(soc_values) / len(soc_values), 1)

        # Alertas
        for inv in inverters:
            nombre = inv.label if inv.label != "—" else f"ID {inv.slave_id}"
            if inv.status == InverterStatus.WARNING:
                summary.alerts.append(f"{nombre}: {inv.fault_description}")
            elif inv.status == InverterStatus.FAULT:
                summary.alerts.append(f"{nombre}: FALLA — {inv.fault_description}")
            elif inv.status == InverterStatus.OFFLINE:
                summary.alerts.append(f"{nombre}: Sin comunicación")

        return summary


# ══════════════════════════════════════════════════════════════════════════════
# THREAD DE POLLING MULTI-INVERSOR
# ══════════════════════════════════════════════════════════════════════════════

class MultiInverterThread(QThread):
    """
    Thread que consulta todos los inversores configurados secuencialmente.
    Cada inversor usa su propio slave_id y su propio mapa de registros.
    """
    # Signals
    data_updated = pyqtSignal(object)    # List[InverterData]
    summary_updated = pyqtSignal(object) # SystemSummary
    error_occurred = pyqtSignal(str)
    poll_progress = pyqtSignal(int, int) # (current, total)
    connection_lost = pyqtSignal()

    # Timeout seguidos antes de declarar Offline definitivo
    OFFLINE_THRESHOLD = 3

    def __init__(self, conn, config: MultiInverterConfig, parent=None):
        """
        Args:
            conn: ModbusTCPConnection o ModbusConnection (ya conectado)
            config: Configuración multi-inversor
        """
        super().__init__(parent)
        self.conn = conn
        self.config = config
        self._running = False
        self._inverters: Dict[int, InverterData] = {}
        self._entries: List[InverterEntry] = list(config.entries)
        for entry in self._entries:
            self._inverters[entry.slave_id] = InverterData(
                slave_id=entry.slave_id,
                label=entry.label or f"Inversor {entry.slave_id}",
                map_name=entry.map_name,
            )

    def run(self):
        self._running = True
        while self._running:
            self._poll_cycle()
            if self._running:
                time.sleep(self.config.poll_interval_sec)

    def stop(self):
        self._running = False
        self.wait(5000)

    def _poll_cycle(self):
        """Consulta todos los inversores configurados secuencialmente."""
        entries = list(self.config.entries)
        all_offline = True

        for idx, entry in enumerate(entries):
            if not self._running:
                return

            self.poll_progress.emit(idx + 1, len(entries))
            inv_data = self._poll_single(entry)

            if inv_data.is_online:
                all_offline = False

        # Emitir resultados
        inverter_list = [
            self._inverters[e.slave_id] for e in entries if e.slave_id in self._inverters
        ]
        self.data_updated.emit(inverter_list)
        summary = SystemSummary.from_inverters(inverter_list)
        self.summary_updated.emit(summary)

        # Si TODOS están offline, emitir connection_lost
        if all_offline and len(entries) > 0:
            online_any = any(inv.consecutive_timeouts < self.OFFLINE_THRESHOLD
                           for inv in self._inverters.values())
            if not online_any:
                self.connection_lost.emit()

    def _poll_single(self, entry: InverterEntry) -> InverterData:
        """
        Lee datos de un inversor individual cambiando el slave_id.
        Usa el mapa de registros propio de ese inversor.
        """
        inv_data = self._inverters.get(entry.slave_id)
        if inv_data is None:
            inv_data = InverterData(
                slave_id=entry.slave_id,
                label=entry.label or f"Inversor {entry.slave_id}",
                map_name=entry.map_name,
            )
            self._inverters[entry.slave_id] = inv_data

        inv_data.label = entry.label or f"Inversor {entry.slave_id}"
        inv_data.map_name = entry.map_name

        start_time = time.perf_counter()

        # Guardar slave_id original y setear el temporal
        original_slave_id = self.conn.slave_id
        self.conn.slave_id = entry.slave_id

        try:
            status = self.conn.read_status(map=entry.map_name)
            latency = (time.perf_counter() - start_time) * 1000

            if status is None:
                inv_data.consecutive_timeouts += 1
                inv_data.latency_ms = latency
                if inv_data.consecutive_timeouts >= self.OFFLINE_THRESHOLD:
                    inv_data.status = InverterStatus.OFFLINE
                else:
                    inv_data.status = InverterStatus.UNKNOWN
                return inv_data

            # Éxito — resetear timeouts
            inv_data.consecutive_timeouts = 0
            inv_data.last_seen = time.time()
            inv_data.latency_ms = round(latency, 1)

            # Llenar datos desde ModbusStatus
            inv_data.battery_voltage = status.battery_voltage
            inv_data.battery_current = status.battery_current
            inv_data.battery_power = status.battery_power
            inv_data.battery_soc = float(getattr(status, 'battery_soc', 0) or 0)
            inv_data.output_active_power = status.output_active_power
            inv_data.output_voltage = status.output_voltage
            inv_data.pv_voltage = status.pv_voltage
            inv_data.pv_power = status.pv_power
            inv_data.grid_voltage = status.grid_voltage
            inv_data.grid_frequency = status.grid_frequency
            inv_data.load_percent = status.load_percent
            inv_data.fault_code = status.fault_code
            inv_data.fault_description = decode_fault_code(status.fault_code)

            # Campos extra de la serie IVGM-8K (0 si el mapa no los provee)
            inv_data.pv1_voltage = getattr(status, "pv1_voltage", 0.0)
            inv_data.pv2_voltage = getattr(status, "pv2_voltage", 0.0)
            inv_data.inverter_temp = getattr(status, "inverter_temp", 0)
            inv_data.ambient_temp = getattr(status, "ambient_temp", 0)
            inv_data.battery_temp = getattr(status, "battery_temp", 0.0)

            inv_data.working_mode = decode_working_mode(
                _get_working_mode_value(status)
            )

            # Determinar estado
            if status.fault_code != 0:
                # Verificar si está en FaultMode
                try:
                    if status.working_mode == WorkingMode.FAULT_MODE:
                        inv_data.status = InverterStatus.FAULT
                    else:
                        inv_data.status = InverterStatus.WARNING
                except (ValueError, AttributeError):
                    inv_data.status = InverterStatus.WARNING
            else:
                inv_data.status = InverterStatus.ONLINE

        except Exception as e:
            inv_data.consecutive_timeouts += 1
            if inv_data.consecutive_timeouts >= self.OFFLINE_THRESHOLD:
                inv_data.status = InverterStatus.OFFLINE
            self.error_occurred.emit(f"ID {entry.slave_id}: {e}")
        finally:
            # Restaurar slave_id original
            self.conn.slave_id = original_slave_id

        return inv_data

    def update_config(self, config: MultiInverterConfig):
        """Actualiza la config en caliente (sin reiniciar el thread)."""
        self.config = config
        self._entries = list(config.entries)
        # Reajustar diccionario de inversores
        new_ids = {e.slave_id for e in config.entries}
        old_ids = set(self._inverters.keys())
        # Agregar nuevos
        for entry in config.entries:
            if entry.slave_id not in old_ids:
                self._inverters[entry.slave_id] = InverterData(
                    slave_id=entry.slave_id,
                    label=entry.label or f"Inversor {entry.slave_id}",
                    map_name=entry.map_name,
                )
        # Eliminar los que ya no están
        for inv_id in old_ids - new_ids:
            del self._inverters[inv_id]


def _get_working_mode_value(status: ModbusStatus) -> int:
    """Extrae el valor numérico del working mode de forma mapa-independiente."""
    try:
        if isinstance(status.working_mode, WorkingMode):
            return status.working_mode.value
    except (ValueError, AttributeError):
        pass
    return -1
