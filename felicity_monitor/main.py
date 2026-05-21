"""
Felicity Inverter Monitor — App PyQt5
Versión con soporte Modbus RTU (protocolo del proyecto C#)
Implementación completa de los 9 parámetros de ESCRITURA con validación
Incluye TAB SCANNER para descubrir registros ocultos
Pestañas: Conexión | Monitor | Settings | Control | Perfiles | Scanner | API
"""

import sys
import json
import time
import threading
from datetime import datetime
from collections import deque

import serial
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
    QTextEdit, QProgressBar, QSlider, QCheckBox, QLineEdit,
    QSplitter, QFrame, QScrollArea, QSizePolicy, QStatusBar,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QMutex
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False

from core.felicity_modbus import (
    ModbusConnection, ModbusStatus, ModbusSettings, ModbusInfo,
    OutputPriority, ChargePriority, WorkingMode, ChargeMode,
    list_serial_ports as list_ports_modbus,
    BAUD_RATES_MODBUS, PARITIES_MODBUS, DEFAULT_MODBUS_CONFIG
)
from core.modbus_tcp import ModbusTCPConnection
from core.profiles import ProfileManager
from core.tab_profiles import TabProfiles


# ══════════════════════════════════════════════════════════════════════════════
# COLORES Y ESTILOS
# ══════════════════════════════════════════════════════════════════════════════

STYLE = """
QMainWindow, QWidget { background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', Arial; }
QTabWidget::pane { border: 1px solid #333; background: #1a1a2e; }
QTabBar::tab { background: #16213e; padding: 10px 20px; color: #aaa; border-radius: 4px; margin: 2px; }
QTabBar::tab:selected { background: #0f3460; color: #e94560; font-weight: bold; }
QGroupBox { border: 1px solid #333; border-radius: 8px; margin-top: 12px; padding-top: 8px; font-weight: bold; color: #aaa; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QPushButton { background: #0f3460; color: #e0e0e0; border: none; padding: 8px 18px; border-radius: 6px; font-weight: bold; }
QPushButton:hover { background: #e94560; }
QPushButton:disabled { background: #333; color: #666; }
QPushButton#btn_connect { background: #1b7f4f; }
QPushButton#btn_connect:hover { background: #27ae60; }
QPushButton#btn_disconnect { background: #7f1b1b; }
QPushButton#btn_disconnect:hover { background: #c0392b; }
QPushButton#btn_write { background: #1b5e20; }
QPushButton#btn_write:hover { background: #2e7d32; }
QPushButton#btn_scan { background: #4a148c; }
QPushButton#btn_scan:hover { background: #7b1fa2; }
QComboBox, QSpinBox, QDoubleSpinBox { background: #16213e; border: 1px solid #444; border-radius: 4px; padding: 5px; color: #e0e0e0; }
QTextEdit { background: #0d0d1a; color: #00ff88; font-family: 'Courier New', monospace; font-size: 11px; border: 1px solid #333; border-radius: 4px; }
QLabel.metric-val { font-size: 26px; font-weight: bold; color: #00d2ff; }
QLabel.metric-lbl { font-size: 11px; color: #888; }
QProgressBar { border: 1px solid #444; border-radius: 4px; background: #16213e; height: 18px; text-align: center; }
QProgressBar::chunk { background: #e94560; border-radius: 3px; }
QStatusBar { background: #0d0d1a; color: #888; border-top: 1px solid #333; }
QLineEdit { background: #16213e; border: 1px solid #444; border-radius: 4px; padding: 5px; color: #e0e0e0; }
QTableWidget { background: #0d0d1a; color: #00d2ff; border: 1px solid #333; gridline-color: #333; }
QTableWidget::item:selected { background: #0f3460; }
QHeaderView::section { background: #16213e; color: #e0e0e0; padding: 5px; border: 1px solid #333; }
"""


# ══════════════════════════════════════════════════════════════════════════════
# VALIDACIÓN DE PARÁMETROS DE ESCRITURA
# ══════════════════════════════════════════════════════════════════════════════

class WriteValidator:
    """Validador completo para los 9 parámetros de escritura del inversor."""

    RANGES_48V = {
        'cutoff':       (40.0, 48.0, 44.0),
        'absorb':       (55.0, 58.4, 56.8),
        'float':        (52.0, 54.4, 54.0),
        'recharge':     (44.0, 51.0, 48.0),
        'back_to_bat':  (44.0, 51.0, 46.0),
    }

    RANGES_CURRENT = {
        'max_charge':   (0, 100, 60),
        'max_ac_charge': (0, 30, 30),
    }

    @classmethod
    def validate_voltage(cls, param: str, value: float) -> tuple[bool, str]:
        if param not in cls.RANGES_48V:
            return False, f"Parámetro desconocido: {param}"
        min_v, max_v, default = cls.RANGES_48V[param]
        if not (min_v <= value <= max_v):
            return False, f"{param.upper()} = {value}V fuera de rango [{min_v} - {max_v}V]"
        return True, "OK"

    @classmethod
    def validate_current(cls, param: str, value: int) -> tuple[bool, str]:
        if param not in cls.RANGES_CURRENT:
            return False, f"Parámetro desconocido: {param}"
        min_v, max_v, default = cls.RANGES_CURRENT[param]
        if not (min_v <= value <= max_v):
            return False, f"{param.upper()} = {value}A fuera de rango [{min_v} - {max_v}A]"
        return True, "OK"

    @classmethod
    def validate_coherence(cls, cutoff: float, absorb: float, float_v: float,
                           recharge: float, back_to_bat: float) -> list[str]:
        errors = []
        if absorb <= float_v:
            errors.append(f"Absorción ({absorb}V) debe ser > Flotación ({float_v}V)")
        if float_v <= recharge:
            errors.append(f"Flotación ({float_v}V) debe ser > Recarga ({recharge}V)")
        if recharge <= cutoff:
            errors.append(f"Recarga ({recharge}V) debe ser > Corte ({cutoff}V)")
        if back_to_bat <= cutoff:
            errors.append(f"Regreso a batería ({back_to_bat}V) debe ser > Corte ({cutoff}V)")
        return errors


# ══════════════════════════════════════════════════════════════════════════════
# WIDGET: TARJETA MÉTRICA
# ══════════════════════════════════════════════════════════════════════════════

class MetricCard(QFrame):
    def __init__(self, title: str, unit: str = '', warn_high: float = None, parent=None):
        super().__init__(parent)
        self.warn_high = warn_high
        self.setStyleSheet("QFrame { background: #16213e; border: 1px solid #333; border-radius: 10px; }")
        self.setMinimumWidth(130)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("font-size:11px; color:#888;")
        self.lbl_title.setAlignment(Qt.AlignCenter)

        self.lbl_value = QLabel("—")
        self.lbl_value.setStyleSheet("font-size:24px; font-weight:bold; color:#00d2ff;")
        self.lbl_value.setAlignment(Qt.AlignCenter)

        self.lbl_unit = QLabel(unit)
        self.lbl_unit.setStyleSheet("font-size:11px; color:#555;")
        self.lbl_unit.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_value)
        layout.addWidget(self.lbl_unit)

    def update(self, value, decimals: int = 1):
        if value is None:
            self.lbl_value.setText("—")
            return
        text = f"{value:.{decimals}f}" if isinstance(value, float) else str(value)
        self.lbl_value.setText(text)
        if self.warn_high and float(value) > self.warn_high:
            self.lbl_value.setStyleSheet("font-size:24px; font-weight:bold; color:#e74c3c;")
        else:
            self.lbl_value.setStyleSheet("font-size:24px; font-weight:bold; color:#00d2ff;")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — CONEXIÓN MODBUS
# ══════════════════════════════════════════════════════════════════════════════

class TabConnection(QWidget):
    # Señal unificada: (tipo_conexion, params_dict)
    # tipo_conexion: "serial" o "tcp"
    # serial: {"port": "COM3", "baudrate": 2400, ...}
    # tcp: {"host": "192.168.1.100", "port": 502, "timeout": 5.0}
    connect_requested = pyqtSignal(str, dict)
    disconnect_requested = pyqtSignal()
    autodetect_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        grp_info = QGroupBox("Protocolo Modbus RTU")
        info_layout = QVBoxLayout(grp_info)
        lbl_info = QLabel(
            "Protocolo basado en Felicity-Inverter-Monitor (C#)\n"
            "• Dirección esclavo: 0x01\n"
            "• Registros estado: 0x1101-0x112A (42 regs)\n"
            "• Registros config: 0x211F-0x2159 (59 regs)\n"
            "• Funciones: Read Holding (0x03), Write Single (0x06)"
        )
        lbl_info.setStyleSheet("color:#888; font-size:11px; font-family: 'Courier New';")
        info_layout.addWidget(lbl_info)
        layout.addWidget(grp_info)

        # ── Selector de tipo de conexión ──
        grp_type = QGroupBox("Tipo de conexión")
        gt = QHBoxLayout(grp_type)
        self.cb_conn_type = QComboBox()
        self.cb_conn_type.addItem("RS232 — Puerto serie (COM)", "serial")
        self.cb_conn_type.addItem("TCP/IP — Gateway RS232→TCP", "tcp")
        self.cb_conn_type.currentIndexChanged.connect(self._on_type_changed)
        gt.addWidget(self.cb_conn_type)
        layout.addWidget(grp_type)

        # ── Stack de configuración: RS232 o TCP ──
        self.config_stack = QWidget()
        stack_layout = QVBoxLayout(self.config_stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)

        # --- Panel RS232 ---
        self.grp_serial = QGroupBox("Configuración RS232")
        g = QGridLayout(self.grp_serial)

        g.addWidget(QLabel("Puerto:"), 0, 0)
        self.cb_port = QComboBox()
        self.cb_port.setMinimumWidth(160)
        g.addWidget(self.cb_port, 0, 1)

        btn_refresh = QPushButton("Actualizar")
        btn_refresh.clicked.connect(self.refresh_ports)
        g.addWidget(btn_refresh, 0, 2)

        g.addWidget(QLabel("Baud rate:"), 1, 0)
        self.cb_baud = QComboBox()
        for b in BAUD_RATES_MODBUS:
            self.cb_baud.addItem(str(b), b)
        self.cb_baud.setCurrentIndex(0)
        g.addWidget(self.cb_baud, 1, 1)

        g.addWidget(QLabel("Paridad:"), 2, 0)
        self.cb_parity = QComboBox()
        for name, val in PARITIES_MODBUS.items():
            self.cb_parity.addItem(name, val)
        g.addWidget(self.cb_parity, 2, 1)

        g.addWidget(QLabel("Timeout (s):"), 3, 0)
        self.sp_timeout = QDoubleSpinBox()
        self.sp_timeout.setRange(0.5, 10.0)
        self.sp_timeout.setValue(2.0)
        self.sp_timeout.setSingleStep(0.5)
        g.addWidget(self.sp_timeout, 3, 1)

        stack_layout.addWidget(self.grp_serial)

        # --- Panel TCP/IP ---
        self.grp_tcp = QGroupBox("Configuración TCP/IP (Gateway RS232→TCP)")
        gtcp = QGridLayout(self.grp_tcp)

        gtcp.addWidget(QLabel("Host / IP:"), 0, 0)
        self.le_tcp_host = QLineEdit("192.168.1.100")
        self.le_tcp_host.setPlaceholderText("Ej: 192.168.1.100")
        gtcp.addWidget(self.le_tcp_host, 0, 1)

        gtcp.addWidget(QLabel("Puerto TCP:"), 1, 0)
        self.sp_tcp_port = QSpinBox()
        self.sp_tcp_port.setRange(1, 65535)
        self.sp_tcp_port.setValue(502)
        self.sp_tcp_port.setToolTip("Puerto por defecto Modbus TCP: 502")
        gtcp.addWidget(self.sp_tcp_port, 1, 1)

        gtcp.addWidget(QLabel("Timeout (s):"), 2, 0)
        self.sp_tcp_timeout = QDoubleSpinBox()
        self.sp_tcp_timeout.setRange(1.0, 30.0)
        self.sp_tcp_timeout.setValue(5.0)
        self.sp_tcp_timeout.setSingleStep(0.5)
        gtcp.addWidget(self.sp_tcp_timeout, 2, 1)

        lbl_tcp_note = QLabel(
            "Usá un gateway RS232→TCP (USR-TCP232, Moxa NPort, etc.)\n"
            "El gateway encapsula los frames Modbus RTU por TCP de forma transparente."
        )
        lbl_tcp_note.setStyleSheet("color:#888; font-size:10px;")
        gtcp.addWidget(lbl_tcp_note, 3, 0, 1, 2)

        stack_layout.addWidget(self.grp_tcp)

        layout.addWidget(self.config_stack)

        row_btns = QHBoxLayout()
        self.btn_connect = QPushButton("Conectar Modbus")
        self.btn_connect.setObjectName("btn_connect")
        self.btn_connect.clicked.connect(self._on_connect)

        self.btn_disconnect = QPushButton("Desconectar")
        self.btn_disconnect.setObjectName("btn_disconnect")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.disconnect_requested.emit)

        self.btn_autodetect = QPushButton("Auto-detectar")
        self.btn_autodetect.clicked.connect(self._on_autodetect)

        row_btns.addWidget(self.btn_connect)
        row_btns.addWidget(self.btn_disconnect)
        row_btns.addWidget(self.btn_autodetect)
        layout.addLayout(row_btns)

        grp_log = QGroupBox("Comunicación Modbus")
        gl = QVBoxLayout(grp_log)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(200)
        self.txt_log.setPlaceholderText("Log de comunicación Modbus RTU...")
        gl.addWidget(self.txt_log)
        layout.addWidget(grp_log)

        self.lbl_status = QLabel("Sin conexión Modbus")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet("color: #555; font-size: 13px; padding: 8px;")
        layout.addWidget(self.lbl_status)

        self.refresh_ports()
        # Inicializar visibilidad de paneles según tipo de conexión
        self._on_type_changed(0)

    def _on_type_changed(self, index: int):
        """Muestra/oculta el panel de config según tipo de conexión."""
        conn_type = self.cb_conn_type.currentData()
        is_serial = (conn_type == "serial")
        self.grp_serial.setVisible(is_serial)
        self.grp_tcp.setVisible(not is_serial)
        # Auto-detectar solo tiene sentido en serial
        self.btn_autodetect.setEnabled(is_serial)

    def get_connection_type(self) -> str:
        """Retorna 'serial' o 'tcp'."""
        return self.cb_conn_type.currentData() or "serial"

    def refresh_ports(self):
        self.cb_port.clear()
        ports = list_ports_modbus()
        if ports:
            for p in ports:
                self.cb_port.addItem(p)
        else:
            self.cb_port.addItem("(sin puertos)")

    def _get_serial_config(self) -> dict:
        return {
            'port': self.cb_port.currentText(),
            'baudrate': self.cb_baud.currentData(),
            'parity': self.cb_parity.currentData(),
            'stopbits': serial.STOPBITS_ONE,
            'timeout': self.sp_timeout.value(),
        }

    def _get_tcp_config(self) -> dict:
        return {
            'host': self.le_tcp_host.text().strip(),
            'port': self.sp_tcp_port.value(),
            'timeout': self.sp_tcp_timeout.value(),
        }

    def _on_connect(self):
        conn_type = self.get_connection_type()
        if conn_type == "serial":
            port = self.cb_port.currentText()
            if not port or port == "(sin puertos)":
                return
            self.connect_requested.emit("serial", self._get_serial_config())
        else:
            host = self.le_tcp_host.text().strip()
            if not host:
                return
            self.connect_requested.emit("tcp", self._get_tcp_config())

    def _on_autodetect(self):
        port = self.cb_port.currentText()
        if not port or port == "(sin puertos)":
            return
        self.autodetect_requested.emit(port)

    def set_connected(self, ok: bool, msg: str = ""):
        self.btn_connect.setEnabled(not ok)
        self.btn_disconnect.setEnabled(ok)
        if ok:
            self.lbl_status.setText(f"CONECTADO MODBUS · {msg}")
            self.lbl_status.setStyleSheet("color: #27ae60; font-size: 13px; padding: 8px; font-weight: bold;")
        else:
            self.lbl_status.setText("Sin conexión")
            self.lbl_status.setStyleSheet("color: #555; font-size: 13px; padding: 8px;")

    def log(self, text: str, color: str = None):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if color:
            self.txt_log.append(f'<span style="color:{color}">[{ts}] {text}</span>')
        else:
            self.txt_log.append(f'[{ts}] {text}')
        self.txt_log.verticalScrollBar().setValue(
            self.txt_log.verticalScrollBar().maximum()
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — MONITOR EN TIEMPO REAL
# ══════════════════════════════════════════════════════════════════════════════

class TabMonitor(QWidget):
    """Monitor en tiempo real con todos los parámetros del protocolo.

    TODO: Conectar settings_received del monitor thread a update_settings_display:
        self._monitor.settings_received.connect(self.tab_monitor.update_settings_display)
    El signal info_received ya está conectado a update_info en MainWindow._start_monitor().
    """
    poll_interval_changed = pyqtSignal(float)

    def __init__(self):
        super().__init__()
        self._history = {k: deque(maxlen=120) for k in [
            'grid_v', 'batt_v', 'batt_charge_a', 'load', 'pv_w',
            'output_w', 'grid_freq', 'output_va',
        ]}
        self._build_ui()

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _make_bool_label(text: str = "—") -> QLabel:
        """Crea un QLabel para un flag booleano con estilo verde/gris."""
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#555; font-size:12px;")
        return lbl

    @staticmethod
    def _style_bool(lbl: QLabel, value: bool):
        if value:
            lbl.setStyleSheet("color:#27ae60; font-size:12px; font-weight:bold;")
        else:
            lbl.setStyleSheet("color:#555; font-size:12px;")

    @staticmethod
    def _make_enum_label(text: str = "—") -> QLabel:
        """Crea un QLabel para un valor de enum con estilo cyan."""
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#00d2ff; font-size:12px; font-weight:bold;")
        return lbl

    @staticmethod
    def _info_row(grid: QGridLayout, row: int, label: str, widget: QWidget):
        """Agrega una fila (QLabel + widget) a un QGridLayout."""
        lbl = QLabel(label)
        lbl.setStyleSheet("color:#888; font-size:12px;")
        grid.addWidget(lbl, row, 0)
        grid.addWidget(widget, row, 1)

    # ── construcción de UI ───────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        # ── Sección 1: Información del Dispositivo ────────────────────────────
        grp_info = QGroupBox("Información del Dispositivo")
        gi = QGridLayout(grp_info)
        gi.setColumnStretch(1, 1)

        self.info_type = self._make_enum_label()
        self.info_subtype = self._make_enum_label()
        self.info_serial = self._make_enum_label()
        self.info_cpu1 = self._make_enum_label()
        self.info_cpu2 = self._make_enum_label()

        self._info_row(gi, 0, "Tipo de Equipo:", self.info_type)
        self._info_row(gi, 1, "Subtipo:", self.info_subtype)
        self._info_row(gi, 2, "Número de Serie:", self.info_serial)
        self._info_row(gi, 3, "Firmware CPU1:", self.info_cpu1)
        self._info_row(gi, 4, "Firmware CPU2:", self.info_cpu2)
        layout.addWidget(grp_info)

        # ── Sección 2: Datos en Tiempo Real ──────────────────────────────────
        grp_rt = QGroupBox("Datos en Tiempo Real")
        rt_layout = QVBoxLayout(grp_rt)
        rt_layout.setSpacing(8)

        # — Batería —
        grp_bat = QGroupBox("Batería")
        gb = QGridLayout(grp_bat)
        gb.setSpacing(8)
        self.cards = {}
        bat_cards = [
            ('batt_v', "Voltaje", "V", None, 0, 0),
            ('batt_charge_a', "Cargando", "A", None, 0, 1),
            ('batt_discharge_a', "Descargando", "A", None, 0, 2),
            ('batt_charge_w', "Pot. Carga", "W", None, 1, 0),
            ('batt_discharge_w', "Pot. Desc.", "W", None, 1, 1),
        ]
        for key, title, unit, warn, r, c in bat_cards:
            card = MetricCard(title, unit, warn_high=warn)
            self.cards[key] = card
            gb.addWidget(card, r, c)

        # Flujo batería (enum)
        self.lbl_batt_flow = self._make_enum_label()
        self._info_row(gb, 2, "Flujo:", self.lbl_batt_flow)
        # Conectada (bool)
        self.lbl_batt_conn = self._make_bool_label()
        self._info_row(gb, 3, "Conectada:", self.lbl_batt_conn)
        rt_layout.addWidget(grp_bat)

        # — Red / AC Entrada —
        grp_grid = QGroupBox("Red / AC Entrada")
        gg = QGridLayout(grp_grid)
        gg.setSpacing(8)
        grid_cards = [
            ('grid_v', "Voltaje", "V", 250, 0, 0),
            ('grid_freq', "Frecuencia", "Hz", None, 0, 1),
        ]
        for key, title, unit, warn, r, c in grid_cards:
            card = MetricCard(title, unit, warn_high=warn)
            self.cards[key] = card
            gg.addWidget(card, r, c)
        self.lbl_line_status = self._make_bool_label()
        self._info_row(gg, 1, "Estado:", self.lbl_line_status)
        self.lbl_line_flow = self._make_enum_label()
        self._info_row(gg, 2, "Flujo:", self.lbl_line_flow)
        rt_layout.addWidget(grp_grid)

        # — PV / Panel Solar —
        grp_pv = QGroupBox("PV / Panel Solar")
        gpv = QGridLayout(grp_pv)
        gpv.setSpacing(8)
        pv_cards = [
            ('pv_v', "Voltaje", "V", None, 0, 0),
            ('pv_w', "Potencia", "W", None, 0, 1),
        ]
        for key, title, unit, warn, r, c in pv_cards:
            card = MetricCard(title, unit, warn_high=warn)
            self.cards[key] = card
            gpv.addWidget(card, r, c)
        self.lbl_mppt = self._make_bool_label()
        self._info_row(gpv, 1, "MPPT:", self.lbl_mppt)
        rt_layout.addWidget(grp_pv)

        # — Salida AC —
        grp_out = QGroupBox("Salida AC")
        go = QGridLayout(grp_out)
        go.setSpacing(8)
        out_cards = [
            ('out_v', "Voltaje", "V", None, 0, 0),
            ('out_w', "Potencia Activa", "W", None, 0, 1),
            ('out_va', "Potencia Aparente", "VA", None, 0, 2),
            ('load_pct', "Carga", "%", None, 1, 0),
        ]
        for key, title, unit, warn, r, c in out_cards:
            card = MetricCard(title, unit, warn_high=warn)
            self.cards[key] = card
            go.addWidget(card, r, c)
        self.lbl_load_conn = self._make_bool_label()
        self._info_row(go, 1, "Conectada:", self.lbl_load_conn)
        rt_layout.addWidget(grp_out)

        # — Estado / Flags —
        grp_flags = QGroupBox("Estado / Flags")
        gf = QGridLayout(grp_flags)
        gf.setColumnStretch(1, 1)
        self.lbl_work_mode = self._make_enum_label()
        self._info_row(gf, 0, "Modo de Trabajo:", self.lbl_work_mode)
        self.lbl_charge_mode = self._make_enum_label()
        self._info_row(gf, 1, "Modo de Carga:", self.lbl_charge_mode)
        self.lbl_fault = QLabel("0")
        self.lbl_fault.setStyleSheet("color:#e74c3c; font-size:12px; font-weight:bold;")
        self._info_row(gf, 2, "Código de Falla:", self.lbl_fault)
        self.lbl_load_allowed = self._make_bool_label()
        self._info_row(gf, 3, "Carga Permitida:", self.lbl_load_allowed)
        self.lbl_pf_supported = self._make_bool_label()
        self._info_row(gf, 4, "PowerFlow Soportado:", self.lbl_pf_supported)
        self.lbl_setting_sn = QLabel("0")
        self.lbl_setting_sn.setStyleSheet("color:#888; font-size:12px;")
        self._info_row(gf, 5, "SettingDataSN:", self.lbl_setting_sn)
        rt_layout.addWidget(grp_flags)

        layout.addWidget(grp_rt)

        # ── Sección 3: Parámetros de Configuración (solo lectura) ─────────────
        grp_cfg = QGroupBox("Parámetros de Configuración (solo lectura)")
        gc = QVBoxLayout(grp_cfg)
        gc.setSpacing(6)

        # Voltajes
        grp_cv = QGroupBox("Voltajes de Batería")
        gcv = QGridLayout(grp_cv)
        gcv.setColumnStretch(1, 1)
        self.cfg_cutoff = QLabel("— V")
        self.cfg_cutoff.setStyleSheet("color:#00d2ff; font-weight:bold;")
        self._info_row(gcv, 0, "Voltaje Corte:", self.cfg_cutoff)
        self.cfg_absorb = QLabel("— V")
        self.cfg_absorb.setStyleSheet("color:#00d2ff; font-weight:bold;")
        self._info_row(gcv, 1, "Voltaje Absorción:", self.cfg_absorb)
        self.cfg_float = QLabel("— V")
        self.cfg_float.setStyleSheet("color:#00d2ff; font-weight:bold;")
        self._info_row(gcv, 2, "Voltaje Flotación:", self.cfg_float)
        self.cfg_recharge = QLabel("— V")
        self.cfg_recharge.setStyleSheet("color:#00d2ff; font-weight:bold;")
        self._info_row(gcv, 3, "Voltaje Regreso a Red:", self.cfg_recharge)
        self.cfg_back_bat = QLabel("— V")
        self.cfg_back_bat.setStyleSheet("color:#00d2ff; font-weight:bold;")
        self._info_row(gcv, 4, "Voltaje Regreso a Batería:", self.cfg_back_bat)
        gc.addWidget(grp_cv)

        # Otros parámetros
        grp_cp = QGridLayout()
        grp_cp.setColumnStretch(1, 1)
        row = 0
        self.cfg_freq = self._make_enum_label()
        self._info_row(grp_cp, row, "Frecuencia Salida:", self.cfg_freq); row += 1
        self.cfg_app_mode = self._make_enum_label()
        self._info_row(grp_cp, row, "Modo Aplicación:", self.cfg_app_mode); row += 1
        self.cfg_bat_type = self._make_enum_label()
        self._info_row(grp_cp, row, "Tipo Batería:", self.cfg_bat_type); row += 1
        self.cfg_out_prio = self._make_enum_label()
        self._info_row(grp_cp, row, "Prioridad Salida:", self.cfg_out_prio); row += 1
        self.cfg_chg_prio = self._make_enum_label()
        self._info_row(grp_cp, row, "Prioridad Carga:", self.cfg_chg_prio); row += 1
        self.cfg_max_charge = QLabel("— A")
        self.cfg_max_charge.setStyleSheet("color:#00d2ff; font-weight:bold;")
        self._info_row(grp_cp, row, "Corriente Máx Carga:", self.cfg_max_charge); row += 1
        self.cfg_max_ac = QLabel("— A")
        self.cfg_max_ac.setStyleSheet("color:#00d2ff; font-weight:bold;")
        self._info_row(grp_cp, row, "Corriente Máx Carga AC:", self.cfg_max_ac); row += 1
        gc.addLayout(grp_cp)

        # Flags
        grp_cf = QGridLayout()
        grp_cf.setColumnStretch(1, 1)
        row = 0
        self.cfg_buzzer = self._make_bool_label()
        self._info_row(grp_cf, row, "Buzzer:", self.cfg_buzzer); row += 1
        self.cfg_overload_rst = self._make_bool_label()
        self._info_row(grp_cf, row, "Reinicio Sobrecarga:", self.cfg_overload_rst); row += 1
        self.cfg_overtemp_rst = self._make_bool_label()
        self._info_row(grp_cf, row, "Reinicio Sobretemp:", self.cfg_overtemp_rst); row += 1
        self.cfg_backlight = self._make_bool_label()
        self._info_row(grp_cf, row, "Backlight LCD:", self.cfg_backlight); row += 1
        self.cfg_overload_bypass = self._make_bool_label()
        self._info_row(grp_cf, row, "Sobrecarga→Bypass:", self.cfg_overload_bypass); row += 1
        gc.addLayout(grp_cf)

        layout.addWidget(grp_cfg)

        # ── Controles: intervalo + latencia ──────────────────────────────────
        row_interval = QHBoxLayout()
        row_interval.addWidget(QLabel("Intervalo polling:"))
        self.sl_interval = QSlider(Qt.Horizontal)
        self.sl_interval.setRange(1, 30)
        self.sl_interval.setValue(3)
        self.sl_interval.setTickInterval(1)
        self.sl_interval.valueChanged.connect(
            lambda v: (self.lbl_interval.setText(f"{v}s"),
                       self.poll_interval_changed.emit(float(v)))
        )
        self.lbl_interval = QLabel("3s")
        self.lbl_interval.setMinimumWidth(30)
        self.lbl_latency = QLabel("Latencia: — ms")
        self.lbl_latency.setStyleSheet("color:#888; font-size:12px;")
        row_interval.addWidget(self.sl_interval)
        row_interval.addWidget(self.lbl_interval)
        row_interval.addStretch()
        row_interval.addWidget(self.lbl_latency)
        layout.addLayout(row_interval)

        # ── Gráfico histórico ────────────────────────────────────────────────
        if HAS_PYQTGRAPH:
            grp_graph = QGroupBox("Histórico (últimos 120 puntos)")
            gv = QVBoxLayout(grp_graph)

            self.graph_select = QComboBox()
            for label in [
                'Tensión batería (V)', 'Potencia PV (W)',
                'Potencia salida (W)', 'Carga (%)', 'Tensión red (V)',
                'Frecuencia red (Hz)', 'Potencia aparente (VA)',
            ]:
                self.graph_select.addItem(label)
            self.graph_select.currentIndexChanged.connect(self._update_graph)
            gv.addWidget(self.graph_select)

            pg.setConfigOptions(antialias=True, background='#0d0d1a', foreground='#888')
            self.plot_widget = pg.PlotWidget()
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self.plot_widget.setMinimumHeight(200)
            self.plot_curve = self.plot_widget.plot(pen=pg.mkPen('#00d2ff', width=2))
            gv.addWidget(self.plot_widget)
            layout.addWidget(grp_graph)

        layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ── actualización de datos ───────────────────────────────────────────────

    def update_data(self, status: ModbusStatus):
        """Actualiza TODOS los campos de datos en tiempo real."""
        # Batería
        self.cards['batt_v'].update(status.battery_voltage)
        self.cards['batt_charge_a'].update(status.battery_charge_a)
        self.cards['batt_discharge_a'].update(status.battery_discharge_a)
        self.cards['batt_charge_w'].update(status.battery_charge_w, 0)
        self.cards['batt_discharge_w'].update(status.battery_discharge_w, 0)
        self.lbl_batt_flow.setText(status.battery_flow)
        self._style_bool(self.lbl_batt_conn, status.battery_connected)

        # Red / AC Entrada
        self.cards['grid_v'].update(status.grid_voltage)
        self.cards['grid_freq'].update(status.grid_frequency, 2)
        self._style_bool(self.lbl_line_status, status.line_normal)
        self.lbl_line_flow.setText(status.line_flow)

        # PV / Panel Solar
        self.cards['pv_v'].update(status.pv_voltage)
        self.cards['pv_w'].update(status.pv_power, 0)
        self._style_bool(self.lbl_mppt, status.pv_mppt_working)

        # Salida AC
        self.cards['out_v'].update(status.output_voltage)
        self.cards['out_w'].update(status.load_watts, 0)
        self.cards['out_va'].update(status.output_apparent_power, 0)
        self.cards['load_pct'].update(status.load_percent, 0)
        self._style_bool(self.lbl_load_conn, status.load_connected)

        # Estado / Flags
        self.lbl_work_mode.setText(str(status.working_mode).replace('_', ' '))
        self.lbl_charge_mode.setText(str(status.charge_mode).replace('_', ' '))
        fault = status.fault_code
        if fault == 0:
            self.lbl_fault.setText("Sin falla")
            self.lbl_fault.setStyleSheet("color:#27ae60; font-size:12px; font-weight:bold;")
        else:
            self.lbl_fault.setText(str(fault))
            self.lbl_fault.setStyleSheet("color:#e74c3c; font-size:12px; font-weight:bold;")
        self._style_bool(self.lbl_load_allowed, status.load_connect_allowed)
        self._style_bool(self.lbl_pf_supported, status.power_flow_supported)
        self.lbl_setting_sn.setText(str(status.setting_data_sn))

        # Historial para gráfico
        self._history['batt_v'].append(status.battery_voltage)
        self._history['pv_w'].append(status.pv_power)
        self._history['output_w'].append(status.load_watts)
        self._history['load'].append(status.load_percent)
        self._history['grid_v'].append(status.grid_voltage)
        self._history['grid_freq'].append(status.grid_frequency)
        self._history['output_va'].append(status.output_apparent_power)

        if HAS_PYQTGRAPH:
            self._update_graph()

    def update_info(self, info: ModbusInfo):
        """Actualiza la sección de información del dispositivo."""
        self.info_type.setText(info.equipment_type_str)
        self.info_subtype.setText(info.sub_type_str)
        self.info_serial.setText(info.serial_number or "—")
        self.info_cpu1.setText(info.cpu1_fw_str)
        self.info_cpu2.setText(info.cpu2_fw_str)

    def update_settings_display(self, settings: ModbusSettings):
        """Actualiza la sección de parámetros de configuración (solo lectura)."""
        # Voltajes
        self.cfg_cutoff.setText(f"{settings.battery_cutoff_voltage:.1f} V")
        self.cfg_absorb.setText(f"{settings.battery_cv_voltage:.1f} V")
        self.cfg_float.setText(f"{settings.battery_float_voltage:.1f} V")
        self.cfg_recharge.setText(f"{settings.battery_back_to_grid_voltage:.1f} V")
        self.cfg_back_bat.setText(f"{settings.battery_back_to_battery_voltage:.1f} V")
        # Otros parámetros
        self.cfg_freq.setText(settings.ac_output_frequency_str)
        self.cfg_app_mode.setText(settings.application_mode_str)
        self.cfg_bat_type.setText(settings.battery_type_str)
        self.cfg_out_prio.setText(str(settings.output_priority).replace('_', ' '))
        self.cfg_chg_prio.setText(str(settings.charge_priority).replace('_', ' '))
        self.cfg_max_charge.setText(f"{settings.max_charge_current} A")
        self.cfg_max_ac.setText(f"{settings.max_ac_charge_current} A")
        # Flags
        self._style_bool(self.cfg_buzzer, settings.buzzer_enabled)
        self.cfg_buzzer.setText("Activado" if settings.buzzer_enabled else "Desactivado")
        self._style_bool(self.cfg_overload_rst, settings.overload_restart)
        self.cfg_overload_rst.setText("Activado" if settings.overload_restart else "Desactivado")
        self._style_bool(self.cfg_overtemp_rst, settings.over_temp_restart)
        self.cfg_overtemp_rst.setText("Activado" if settings.over_temp_restart else "Desactivado")
        self._style_bool(self.cfg_backlight, settings.lcd_backlight)
        self.cfg_backlight.setText("Activado" if settings.lcd_backlight else "Desactivado")
        self._style_bool(self.cfg_overload_bypass, settings.overload_to_bypass)
        self.cfg_overload_bypass.setText("Activado" if settings.overload_to_bypass else "Desactivado")

    def _update_graph(self):
        if not HAS_PYQTGRAPH:
            return
        idx = self.graph_select.currentIndex()
        keys = ['batt_v', 'pv_w', 'output_w', 'load', 'grid_v', 'grid_freq', 'output_va']
        key = keys[idx]
        data = list(self._history[key])
        if data:
            self.plot_curve.setData(data)

    def update_latency(self, ms: float):
        color = "#27ae60" if ms < 500 else "#f39c12" if ms < 1500 else "#e74c3c"
        self.lbl_latency.setText(f"Latencia: {ms:.0f} ms")
        self.lbl_latency.setStyleSheet(f"color:{color}; font-size:12px;")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — SETTINGS (LECTURA)
# ══════════════════════════════════════════════════════════════════════════════

class TabSettings(QWidget):
    refresh_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._settings: ModbusSettings = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        row_btns = QHBoxLayout()
        self.btn_read = QPushButton("Leer configuración del inversor")
        self.btn_read.clicked.connect(self.refresh_requested.emit)
        row_btns.addWidget(self.btn_read)
        layout.addLayout(row_btns)

        # ── Voltajes de batería ──
        grp_bat = QGroupBox("Configuración de Batería (Registros 0x211F - 0x2159)")
        grid = QGridLayout(grp_bat)

        self.lbl_float_v = QLabel("— V")
        self.lbl_absorb_v = QLabel("— V")
        self.lbl_cutoff_v = QLabel("— V")
        self.lbl_recharge_v = QLabel("— V")
        self.lbl_back_to_bat = QLabel("— V")

        bat_items = [
            ("Voltaje flotación (0x2123):", self.lbl_float_v),
            ("Voltaje absorción (0x2122):", self.lbl_absorb_v),
            ("Voltaje corte (0x211F):", self.lbl_cutoff_v),
            ("Voltaje recarga (0x2156):", self.lbl_recharge_v),
            ("Regreso a batería (0x2159):", self.lbl_back_to_bat),
        ]
        for i, (label, value_lbl) in enumerate(bat_items):
            grid.addWidget(QLabel(label), i, 0)
            value_lbl.setStyleSheet("color:#00d2ff; font-weight:bold;")
            grid.addWidget(value_lbl, i, 1)

        layout.addWidget(grp_bat)

        # ── Prioridades y corrientes ──
        grp_prio = QGroupBox("Prioridades y Corrientes")
        grid2 = QGridLayout(grp_prio)

        self.lbl_out_prio = QLabel("—")
        self.lbl_charge_prio = QLabel("—")
        self.lbl_max_charge = QLabel("— A")
        self.lbl_max_ac = QLabel("— A")

        prio_items = [
            ("Prioridad salida (0x212A):", self.lbl_out_prio),
            ("Prioridad carga (0x212C):", self.lbl_charge_prio),
            ("Corriente máx carga (0x212E):", self.lbl_max_charge),
            ("Corriente máx AC (0x2130):", self.lbl_max_ac),
        ]
        for i, (label, value_lbl) in enumerate(prio_items):
            grid2.addWidget(QLabel(label), i, 0)
            value_lbl.setStyleSheet("color:#f39c12; font-weight:bold;")
            grid2.addWidget(value_lbl, i, 1)

        layout.addWidget(grp_prio)

        # ── Configuración adicional ──
        grp_extra = QGroupBox("Configuración Adicional")
        grid3 = QGridLayout(grp_extra)

        self.lbl_ac_freq = QLabel("—")
        self.lbl_app_mode = QLabel("—")
        self.lbl_bat_type = QLabel("—")
        self.lbl_buzzer = QLabel("—")
        self.lbl_overload_restart = QLabel("—")
        self.lbl_overtemp_restart = QLabel("—")
        self.lbl_backlight = QLabel("—")
        self.lbl_overload_bypass = QLabel("—")

        extra_items = [
            ("Frecuencia salida AC (0x2129):", self.lbl_ac_freq),
            ("Modo aplicación (0x212B):", self.lbl_app_mode),
            ("Tipo batería (0x212D):", self.lbl_bat_type),
            ("Buzzer (0x2131):", self.lbl_buzzer),
            ("Reinicio sobrecarga (0x2133):", self.lbl_overload_restart),
            ("Reinicio sobretemp (0x2134):", self.lbl_overtemp_restart),
            ("Backlight LCD (0x2135):", self.lbl_backlight),
            ("Sobrecarga → Bypass (0x2137):", self.lbl_overload_bypass),
        ]
        for i, (label, value_lbl) in enumerate(extra_items):
            grid3.addWidget(QLabel(label), i, 0)
            value_lbl.setStyleSheet("color:#00d2ff; font-weight:bold;")
            grid3.addWidget(value_lbl, i, 1)

        layout.addWidget(grp_extra)

        grp_raw = QGroupBox("Registros crudos (hexdump)")
        gl = QVBoxLayout(grp_raw)
        self.txt_raw = QTextEdit()
        self.txt_raw.setReadOnly(True)
        self.txt_raw.setMaximumHeight(120)
        self.txt_raw.setPlaceholderText("Registros hexdump...")
        gl.addWidget(self.txt_raw)
        layout.addWidget(grp_raw)

        layout.addStretch()

    def update_settings(self, settings: ModbusSettings):
        self._settings = settings

        self.lbl_float_v.setText(f"{settings.battery_float_voltage:.1f} V")
        self.lbl_absorb_v.setText(f"{settings.battery_cv_voltage:.1f} V")
        self.lbl_cutoff_v.setText(f"{settings.battery_cutoff_voltage:.1f} V")
        self.lbl_recharge_v.setText(f"{settings.battery_back_to_grid_voltage:.1f} V")
        self.lbl_back_to_bat.setText(f"{settings.battery_back_to_battery_voltage:.1f} V")

        self.lbl_out_prio.setText(str(settings.output_priority))
        self.lbl_charge_prio.setText(str(settings.charge_priority))
        self.lbl_max_charge.setText(f"{settings.max_charge_current} A")
        self.lbl_max_ac.setText(f"{settings.max_ac_charge_current} A")

        # Nuevos campos
        self.lbl_ac_freq.setText(settings.ac_output_frequency_str)
        self.lbl_app_mode.setText(settings.application_mode_str)
        self.lbl_bat_type.setText(settings.battery_type_str)

        def bool_str(val: bool) -> str:
            return "Activado" if val else "Desactivado"

        def bool_style(val: bool) -> str:
            return "color:#27ae60; font-weight:bold;" if val else "color:#555; font-weight:bold;"

        self.lbl_buzzer.setText(bool_str(settings.buzzer_enabled))
        self.lbl_buzzer.setStyleSheet(bool_style(settings.buzzer_enabled))

        self.lbl_overload_restart.setText(bool_str(settings.overload_restart))
        self.lbl_overload_restart.setStyleSheet(bool_style(settings.overload_restart))

        self.lbl_overtemp_restart.setText(bool_str(settings.over_temp_restart))
        self.lbl_overtemp_restart.setStyleSheet(bool_style(settings.over_temp_restart))

        self.lbl_backlight.setText(bool_str(settings.lcd_backlight))
        self.lbl_backlight.setStyleSheet(bool_style(settings.lcd_backlight))

        self.lbl_overload_bypass.setText(bool_str(settings.overload_to_bypass))
        self.lbl_overload_bypass.setStyleSheet(bool_style(settings.overload_to_bypass))

        if settings.raw_registers:
            hex_str = ' '.join(f"{x:04X}" for x in settings.raw_registers[:30])
            self.txt_raw.setText(f"Primeros 30 registros: {hex_str}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — CONTROL MODBUS (ESCRITURA) — LOS 9 PARÁMETROS
# ══════════════════════════════════════════════════════════════════════════════

class TabControl(QWidget):
    def __init__(self):
        super().__init__()
        self._conn: ModbusConnection = None
        self._current_settings = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.lbl_status = QLabel("Sin conexión — Conecta el inversor primero")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setStyleSheet(
            "background:#2a1a0a; color:#f39c12; font-size:13px; padding:10px; border-radius:8px;"
        )
        layout.addWidget(self.lbl_status)

        grp_warn = QGroupBox("⚠️ Importante — Escritura en EEPROM")
        gw = QVBoxLayout(grp_warn)
        lbl_warn = QLabel(
            "• Los valores se guardan PERMANENTEMENTE en el inversor\n"
            "• Máximo 1 cambio al día (recomendado)\n"
            "• Los valores deben ser coherentes: Absorción > Flotación > Recarga > Corte"
        )
        lbl_warn.setStyleSheet("color:#f39c12; font-size:11px;")
        gw.addWidget(lbl_warn)
        layout.addWidget(grp_warn)

        grp_v = QGroupBox("📋 VOLTAJES DE BATERÍA (5 parámetros)")
        grid = QGridLayout(grp_v)
        self.lbl_results = {}

        # Cutoff
        self.sp_cutoff = QDoubleSpinBox()
        self.sp_cutoff.setRange(40.0, 48.0)
        self.sp_cutoff.setSuffix(" V")
        self.sp_cutoff.setDecimals(1)
        self.sp_cutoff.setValue(44.0)
        self.sp_cutoff.setMinimumWidth(100)
        btn_cutoff = QPushButton("Aplicar Corte (0x211F)")
        btn_cutoff.setObjectName("btn_write")
        btn_cutoff.clicked.connect(lambda: self._write("cutoff", self.sp_cutoff.value()))
        lbl_cutoff_range = QLabel("Rango: 40-48V")
        lbl_cutoff_range.setStyleSheet("color:#555; font-size:10px;")
        self.lbl_results['cutoff'] = QLabel("")
        self.lbl_results['cutoff'].setStyleSheet("font-size:11px;")
        grid.addWidget(QLabel("Corte (0x211F):"), 0, 0)
        grid.addWidget(self.sp_cutoff, 0, 1)
        grid.addWidget(btn_cutoff, 0, 2)
        grid.addWidget(lbl_cutoff_range, 0, 3)
        grid.addWidget(self.lbl_results['cutoff'], 0, 4)

        # Absorb
        self.sp_absorb = QDoubleSpinBox()
        self.sp_absorb.setRange(55.0, 58.4)
        self.sp_absorb.setSuffix(" V")
        self.sp_absorb.setDecimals(1)
        self.sp_absorb.setValue(56.8)
        self.sp_absorb.setMinimumWidth(100)
        btn_absorb = QPushButton("Aplicar Absorción (0x2122)")
        btn_absorb.setObjectName("btn_write")
        btn_absorb.clicked.connect(lambda: self._write("absorb", self.sp_absorb.value()))
        lbl_absorb_range = QLabel("Rango: 55-58.4V")
        lbl_absorb_range.setStyleSheet("color:#555; font-size:10px;")
        self.lbl_results['absorb'] = QLabel("")
        self.lbl_results['absorb'].setStyleSheet("font-size:11px;")
        grid.addWidget(QLabel("Absorción (0x2122):"), 1, 0)
        grid.addWidget(self.sp_absorb, 1, 1)
        grid.addWidget(btn_absorb, 1, 2)
        grid.addWidget(lbl_absorb_range, 1, 3)
        grid.addWidget(self.lbl_results['absorb'], 1, 4)

        # Float
        self.sp_float = QDoubleSpinBox()
        self.sp_float.setRange(52.0, 54.4)
        self.sp_float.setSuffix(" V")
        self.sp_float.setDecimals(1)
        self.sp_float.setValue(54.0)
        self.sp_float.setMinimumWidth(100)
        btn_float = QPushButton("Aplicar Flotación (0x2123)")
        btn_float.setObjectName("btn_write")
        btn_float.clicked.connect(lambda: self._write("float", self.sp_float.value()))
        lbl_float_range = QLabel("Rango: 52-54.4V")
        lbl_float_range.setStyleSheet("color:#555; font-size:10px;")
        self.lbl_results['float'] = QLabel("")
        self.lbl_results['float'].setStyleSheet("font-size:11px;")
        grid.addWidget(QLabel("Flotación (0x2123):"), 2, 0)
        grid.addWidget(self.sp_float, 2, 1)
        grid.addWidget(btn_float, 2, 2)
        grid.addWidget(lbl_float_range, 2, 3)
        grid.addWidget(self.lbl_results['float'], 2, 4)

        # Recharge
        self.sp_recharge = QDoubleSpinBox()
        self.sp_recharge.setRange(44.0, 51.0)
        self.sp_recharge.setSuffix(" V")
        self.sp_recharge.setDecimals(1)
        self.sp_recharge.setValue(48.0)
        self.sp_recharge.setMinimumWidth(100)
        btn_recharge = QPushButton("Aplicar Recarga (0x2156)")
        btn_recharge.setObjectName("btn_write")
        btn_recharge.clicked.connect(lambda: self._write("recharge", self.sp_recharge.value()))
        lbl_recharge_range = QLabel("Rango: 44-51V")
        lbl_recharge_range.setStyleSheet("color:#555; font-size:10px;")
        self.lbl_results['recharge'] = QLabel("")
        self.lbl_results['recharge'].setStyleSheet("font-size:11px;")
        grid.addWidget(QLabel("Recarga (0x2156):"), 3, 0)
        grid.addWidget(self.sp_recharge, 3, 1)
        grid.addWidget(btn_recharge, 3, 2)
        grid.addWidget(lbl_recharge_range, 3, 3)
        grid.addWidget(self.lbl_results['recharge'], 3, 4)

        # Back to battery
        self.sp_back_to_bat = QDoubleSpinBox()
        self.sp_back_to_bat.setRange(44.0, 51.0)
        self.sp_back_to_bat.setSuffix(" V")
        self.sp_back_to_bat.setDecimals(1)
        self.sp_back_to_bat.setValue(46.0)
        self.sp_back_to_bat.setMinimumWidth(100)
        btn_back_to_bat = QPushButton("Aplicar Regreso Bat (0x2159)")
        btn_back_to_bat.setObjectName("btn_write")
        btn_back_to_bat.clicked.connect(lambda: self._write("back_to_bat", self.sp_back_to_bat.value()))
        lbl_back_range = QLabel("Rango: 44-51V")
        lbl_back_range.setStyleSheet("color:#555; font-size:10px;")
        self.lbl_results['back_to_bat'] = QLabel("")
        self.lbl_results['back_to_bat'].setStyleSheet("font-size:11px;")
        grid.addWidget(QLabel("Regreso Bat (0x2159):"), 4, 0)
        grid.addWidget(self.sp_back_to_bat, 4, 1)
        grid.addWidget(btn_back_to_bat, 4, 2)
        grid.addWidget(lbl_back_range, 4, 3)
        grid.addWidget(self.lbl_results['back_to_bat'], 4, 4)

        layout.addWidget(grp_v)

        grp_p = QGroupBox("⚡ PRIORIDADES (2 parámetros)")
        gp = QVBoxLayout(grp_p)

        row_prio = QHBoxLayout()
        row_prio.addWidget(QLabel("Prioridad salida (0x212A):"))
        self.cb_out_prio = QComboBox()
        self.cb_out_prio.addItem("0 = Red primero", 0)
        self.cb_out_prio.addItem("1 = Solar primero", 1)
        self.cb_out_prio.addItem("2 = SBU (Solar→Bat→Red)", 2)
        row_prio.addWidget(self.cb_out_prio)
        btn_out_prio = QPushButton("Aplicar")
        btn_out_prio.setObjectName("btn_write")
        btn_out_prio.clicked.connect(self._write_output_priority)
        row_prio.addWidget(btn_out_prio)
        self.lbl_results['out_prio'] = QLabel("")
        self.lbl_results['out_prio'].setStyleSheet("font-size:11px;")
        row_prio.addWidget(self.lbl_results['out_prio'])
        row_prio.addStretch()
        gp.addLayout(row_prio)

        row_charge = QHBoxLayout()
        row_charge.addWidget(QLabel("Prioridad carga (0x212C):"))
        self.cb_charge_prio = QComboBox()
        self.cb_charge_prio.addItem("0 = Solo red", 0)
        self.cb_charge_prio.addItem("1 = Solar primero", 1)
        self.cb_charge_prio.addItem("2 = Solar + Red", 2)
        self.cb_charge_prio.addItem("3 = Solo solar", 3)
        row_charge.addWidget(self.cb_charge_prio)
        btn_charge_prio = QPushButton("Aplicar")
        btn_charge_prio.setObjectName("btn_write")
        btn_charge_prio.clicked.connect(self._write_charge_priority)
        row_charge.addWidget(btn_charge_prio)
        self.lbl_results['charge_prio'] = QLabel("")
        self.lbl_results['charge_prio'].setStyleSheet("font-size:11px;")
        row_charge.addWidget(self.lbl_results['charge_prio'])
        row_charge.addStretch()
        gp.addLayout(row_charge)

        layout.addWidget(grp_p)

        grp_c = QGroupBox("🔌 CORRIENTES (2 parámetros)")
        gc = QVBoxLayout(grp_c)

        row_max_charge = QHBoxLayout()
        row_max_charge.addWidget(QLabel("Corriente máx carga (0x212E):"))
        self.sp_max_charge = QSpinBox()
        self.sp_max_charge.setRange(0, 100)
        self.sp_max_charge.setSuffix(" A")
        self.sp_max_charge.setValue(60)
        self.sp_max_charge.setMinimumWidth(100)
        row_max_charge.addWidget(self.sp_max_charge)
        lbl_max_range = QLabel("Rango: 0-100A")
        lbl_max_range.setStyleSheet("color:#555; font-size:10px;")
        row_max_charge.addWidget(lbl_max_range)
        btn_max_charge = QPushButton("Aplicar")
        btn_max_charge.setObjectName("btn_write")
        btn_max_charge.clicked.connect(self._write_max_charge)
        row_max_charge.addWidget(btn_max_charge)
        self.lbl_results['max_charge'] = QLabel("")
        self.lbl_results['max_charge'].setStyleSheet("font-size:11px;")
        row_max_charge.addWidget(self.lbl_results['max_charge'])
        row_max_charge.addStretch()
        gc.addLayout(row_max_charge)

        row_max_ac = QHBoxLayout()
        row_max_ac.addWidget(QLabel("Corriente máx carga AC (0x2130):"))
        self.sp_max_ac = QSpinBox()
        self.sp_max_ac.setRange(0, 30)
        self.sp_max_ac.setSuffix(" A")
        self.sp_max_ac.setValue(30)
        self.sp_max_ac.setMinimumWidth(100)
        row_max_ac.addWidget(self.sp_max_ac)
        lbl_max_ac_range = QLabel("Rango: 0-30A")
        lbl_max_ac_range.setStyleSheet("color:#555; font-size:10px;")
        row_max_ac.addWidget(lbl_max_ac_range)
        btn_max_ac = QPushButton("Aplicar")
        btn_max_ac.setObjectName("btn_write")
        btn_max_ac.clicked.connect(self._write_max_ac)
        row_max_ac.addWidget(btn_max_ac)
        self.lbl_results['max_ac'] = QLabel("")
        self.lbl_results['max_ac'].setStyleSheet("font-size:11px;")
        row_max_ac.addWidget(self.lbl_results['max_ac'])
        row_max_ac.addStretch()
        gc.addLayout(row_max_ac)

        layout.addWidget(grp_c)

        grp_log = QGroupBox("📝 Log de escritura")
        gl = QVBoxLayout(grp_log)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(100)
        gl.addWidget(self.txt_log)
        layout.addWidget(grp_log)

    def set_connection(self, conn: ModbusConnection):
        self._conn = conn
        if conn and conn.is_open:
            self.lbl_status.setText("Conectado — Listo para escribir")
            self.lbl_status.setStyleSheet(
                "background:#0a2a1a; color:#27ae60; font-size:13px; padding:10px; border-radius:8px;"
            )
        else:
            self.lbl_status.setText("Sin conexión — Conecta el inversor primero")
            self.lbl_status.setStyleSheet(
                "background:#2a1a0a; color:#f39c12; font-size:13px; padding:10px; border-radius:8px;"
            )

    def update_from_settings(self, settings: ModbusSettings):
        self._current_settings = settings

        self.sp_absorb.setValue(settings.battery_cv_voltage)
        self.sp_float.setValue(settings.battery_float_voltage)
        self.sp_cutoff.setValue(settings.battery_cutoff_voltage)
        self.sp_recharge.setValue(settings.battery_back_to_grid_voltage)
        self.sp_back_to_bat.setValue(settings.battery_back_to_battery_voltage)
        self.sp_max_charge.setValue(settings.max_charge_current)
        self.sp_max_ac.setValue(settings.max_ac_charge_current)

        for i in range(self.cb_out_prio.count()):
            if self.cb_out_prio.itemData(i) == settings.output_priority.value:
                self.cb_out_prio.setCurrentIndex(i)
                break

        for i in range(self.cb_charge_prio.count()):
            if self.cb_charge_prio.itemData(i) == settings.charge_priority.value:
                self.cb_charge_prio.setCurrentIndex(i)
                break

    def _write(self, param: str, value: float):
        if not self._conn or not self._conn.is_open:
            self._log(f"Error: No hay conexión", '#e74c3c')
            return

        valid, msg = WriteValidator.validate_voltage(param, value)
        if not valid:
            self._show_result(param, False, msg)
            self._log(f"✗ Validación falló: {msg}", '#e74c3c')
            return

        cutoff = self.sp_cutoff.value()
        absorb = self.sp_absorb.value()
        float_v = self.sp_float.value()
        recharge = self.sp_recharge.value()
        back_to_bat = self.sp_back_to_bat.value()

        if param == 'cutoff':
            cutoff = value
        elif param == 'absorb':
            absorb = value
        elif param == 'float':
            float_v = value
        elif param == 'recharge':
            recharge = value
        elif param == 'back_to_bat':
            back_to_bat = value

        errors = WriteValidator.validate_coherence(cutoff, absorb, float_v, recharge, back_to_bat)
        if errors:
            self._log(f"⚠️ Coherencia: {'; '.join(errors)}", '#f39c12')

        param_labels = {
            'cutoff': 'voltaje de CORTE',
            'absorb': 'voltaje de ABSORCIÓN',
            'float': 'voltaje de FLOTACIÓN',
            'recharge': 'voltaje de RECARGA',
            'back_to_bat': 'voltaje de REGRESO A BATERÍA'
        }

        reply = QMessageBox.question(
            self, "Confirmar escritura",
            f"¿Escribir {param_labels.get(param, param)} = {value}V?\n\n"
            f"⚠️ Este valor se guarda PERMANENTEMENTE en la EEPROM del inversor.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        methods = {
            'cutoff': self._conn.set_cutoff_voltage,
            'absorb': self._conn.set_absorb_voltage,
            'float': self._conn.set_float_voltage,
            'recharge': self._conn.set_recharge_voltage,
            'back_to_bat': self._conn.set_back_to_battery_voltage,
        }

        result = methods[param](value)

        if result.success:
            self._show_result(param, True, f"✓ {value}V → ACK ({result.latency_ms:.0f}ms)")
            self._log(f"✓ {param_labels.get(param, param).upper()} = {value}V → ACK ({result.latency_ms:.0f}ms)", '#27ae60')
        else:
            self._show_result(param, False, f"✗ {result.error_message}")
            self._log(f"✗ Error {param_labels.get(param, param)}: {result.error_message}", '#e74c3c')

    def _write_output_priority(self):
        if not self._conn or not self._conn.is_open:
            return
        priority = self.cb_out_prio.currentData()
        priority_names = {0: "Red primero", 1: "Solar primero", 2: "SBU"}

        reply = QMessageBox.question(
            self, "Confirmar",
            f"¿Cambiar prioridad de salida a: {priority_names.get(priority, priority)}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        result = self._conn.set_output_priority(OutputPriority(priority))
        if result.success:
            self.lbl_results['out_prio'].setText(f"✓ {priority_names.get(priority)}")
            self.lbl_results['out_prio'].setStyleSheet("color:#27ae60; font-size:11px;")
            self._log(f"✓ Prioridad salida = {priority_names.get(priority)} → ACK", '#27ae60')
        else:
            self.lbl_results['out_prio'].setText(f"✗ Error")
            self.lbl_results['out_prio'].setStyleSheet("color:#e74c3c; font-size:11px;")
            self._log(f"✗ Error prioridad salida: {result.error_message}", '#e74c3c')

    def _write_charge_priority(self):
        if not self._conn or not self._conn.is_open:
            return
        priority = self.cb_charge_prio.currentData()
        priority_names = {0: "Solo red", 1: "Solar primero", 2: "Solar + Red", 3: "Solo solar"}

        reply = QMessageBox.question(
            self, "Confirmar",
            f"¿Cambiar prioridad de carga a: {priority_names.get(priority, priority)}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        result = self._conn.set_charge_priority(ChargePriority(priority))
        if result.success:
            self.lbl_results['charge_prio'].setText(f"✓ {priority_names.get(priority)}")
            self.lbl_results['charge_prio'].setStyleSheet("color:#27ae60; font-size:11px;")
            self._log(f"✓ Prioridad carga = {priority_names.get(priority)} → ACK", '#27ae60')
        else:
            self.lbl_results['charge_prio'].setText(f"✗ Error")
            self.lbl_results['charge_prio'].setStyleSheet("color:#e74c3c; font-size:11px;")
            self._log(f"✗ Error prioridad carga: {result.error_message}", '#e74c3c')

    def _write_max_charge(self):
        if not self._conn or not self._conn.is_open:
            return
        value = self.sp_max_charge.value()

        valid, msg = WriteValidator.validate_current('max_charge', value)
        if not valid:
            self.lbl_results['max_charge'].setText(f"✗ {msg}")
            self.lbl_results['max_charge'].setStyleSheet("color:#e74c3c; font-size:11px;")
            return

        reply = QMessageBox.question(
            self, "Confirmar",
            f"¿Cambiar corriente máx de carga a {value}A?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        result = self._conn.set_max_charge_current(value)
        if result.success:
            self.lbl_results['max_charge'].setText(f"✓ {value}A → ACK")
            self.lbl_results['max_charge'].setStyleSheet("color:#27ae60; font-size:11px;")
            self._log(f"✓ Corriente máx carga = {value}A → ACK", '#27ae60')
        else:
            self.lbl_results['max_charge'].setText(f"✗ Error")
            self.lbl_results['max_charge'].setStyleSheet("color:#e74c3c; font-size:11px;")
            self._log(f"✗ Error corriente máx carga: {result.error_message}", '#e74c3c')

    def _write_max_ac(self):
        if not self._conn or not self._conn.is_open:
            return
        value = self.sp_max_ac.value()

        valid, msg = WriteValidator.validate_current('max_ac_charge', value)
        if not valid:
            self.lbl_results['max_ac'].setText(f"✗ {msg}")
            self.lbl_results['max_ac'].setStyleSheet("color:#e74c3c; font-size:11px;")
            return

        reply = QMessageBox.question(
            self, "Confirmar",
            f"¿Cambiar corriente máx de carga AC a {value}A?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        result = self._conn.set_max_ac_charge_current(value)
        if result.success:
            self.lbl_results['max_ac'].setText(f"✓ {value}A → ACK")
            self.lbl_results['max_ac'].setStyleSheet("color:#27ae60; font-size:11px;")
            self._log(f"✓ Corriente máx carga AC = {value}A → ACK", '#27ae60')
        else:
            self.lbl_results['max_ac'].setText(f"✗ Error")
            self.lbl_results['max_ac'].setStyleSheet("color:#e74c3c; font-size:11px;")
            self._log(f"✗ Error corriente máx carga AC: {result.error_message}", '#e74c3c')

    def _show_result(self, param: str, success: bool, msg: str):
        if param in self.lbl_results:
            if success:
                self.lbl_results[param].setText(f"✓ {msg}")
                self.lbl_results[param].setStyleSheet("color:#27ae60; font-size:11px;")
            else:
                self.lbl_results[param].setText(f"✗ {msg}")
                self.lbl_results[param].setStyleSheet("color:#e74c3c; font-size:11px;")

    def _log(self, text: str, color: str = "#888"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt_log.append(f'<span style="color:{color}">[{ts}] {text}</span>')
        self.txt_log.verticalScrollBar().setValue(
            self.txt_log.verticalScrollBar().maximum()
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — SCANNER DE REGISTROS MODBUS
# ══════════════════════════════════════════════════════════════════════════════

class TabScanner(QWidget):
    """Escáner de registros Modbus para descubrir parámetros ocultos."""

    def __init__(self):
        super().__init__()
        self._conn = None
        self._scanning = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Info ──
        grp_info = QGroupBox("🔍 Scanner de Registros Modbus")
        gi = QVBoxLayout(grp_info)
        lbl_info = QLabel(
            "Escanea el espacio de direcciones Modbus para descubrir\n"
            "parámetros ocultos o no documentados.\n\n"
            "Zonas a escanear:\n"
            "• Status conocida: 0x1101-0x112A\n"
            "• Settings conocida: 0x211F-0x2159\n"
            "• Status extendida: 0x1000-0x1150\n"
            "• Settings extendida: 0x2000-0x2200\n"
            "• Rango bajo: 0x0000-0x0100\n"
            "• Rango alto: 0x3000-0x3100"
        )
        lbl_info.setStyleSheet("color:#888; font-size:11px;")
        gi.addWidget(lbl_info)
        layout.addWidget(grp_info)

        # ── Opciones ──
        grp_opts = QGroupBox("Opciones de escaneo")
        go = QGridLayout(grp_opts)

        go.addWidget(QLabel("Bloques a leer:"), 0, 0)
        self.cb_zones = QComboBox()
        self.cb_zones.addItem("Todas las zonas", "all")
        self.cb_zones.addItem("Solo zona status (0x1000-0x1200)", "status")
        self.cb_zones.addItem("Solo zona settings (0x2000-0x2200)", "settings")
        self.cb_zones.addItem("Zona baja (0x0000-0x0100)", "low")
        go.addWidget(self.cb_zones, 0, 1)

        self.cb_test_write = QCheckBox("Solo lectura (sin escritura)")
        self.cb_test_write.setChecked(True)
        self.cb_test_write.setEnabled(False)  # Desactivado - solo lectura
        go.addWidget(self.cb_test_write, 1, 0, 1, 2)

        layout.addWidget(grp_opts)

        # ── Botón ──
        row_btn = QHBoxLayout()
        self.btn_scan = QPushButton("🔍 INICIAR ESCANEO")
        self.btn_scan.setObjectName("btn_scan")
        self.btn_scan.clicked.connect(self._start_scan)
        self.btn_stop = QPushButton("⏹ DETENER")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_scan)
        row_btn.addWidget(self.btn_scan)
        row_btn.addWidget(self.btn_stop)
        row_btn.addStretch()
        layout.addLayout(row_btn)

        # ── Progreso ──
        self.lbl_progress = QLabel("Esperando iniciar escaneo...")
        self.lbl_progress.setStyleSheet("color:#888; font-size:12px;")
        layout.addWidget(self.lbl_progress)

        self.pb_progress = QProgressBar()
        self.pb_progress.setRange(0, 100)
        self.pb_progress.setValue(0)
        layout.addWidget(self.pb_progress)

        # ── Tabla de resultados ──
        grp_results = QGroupBox("📊 Resultados del Escaneo")
        gr = QVBoxLayout(grp_results)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Dirección", "Valor Decimal", "Valor Hex", "Clasificación",
            "Posible Valor Real", "Notas", "Zona"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(250)
        gr.addWidget(self.table)

        # Botones de exportar
        row_export = QHBoxLayout()
        btn_copy = QPushButton("📋 Copiar tabla")
        btn_copy.clicked.connect(self._copy_table)
        btn_save = QPushButton("💾 Guardar resultados")
        btn_save.clicked.connect(self._save_results)
        btn_clear = QPushButton("🗑 Limpiar")
        btn_clear.clicked.connect(self._clear_results)
        row_export.addWidget(btn_copy)
        row_export.addWidget(btn_save)
        row_export.addWidget(btn_clear)
        row_export.addStretch()
        gr.addLayout(row_export)

        layout.addWidget(grp_results)

        # ── Log ──
        grp_log = QGroupBox("📝 Log del Scanner")
        gl = QVBoxLayout(grp_log)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(100)
        gl.addWidget(self.txt_log)
        layout.addWidget(grp_log)

    def set_connection(self, conn: ModbusConnection):
        self._conn = conn

    def _log(self, text: str, color: str = "#888"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt_log.append(f'<span style="color:{color}">[{ts}] {text}</span>')
        self.txt_log.verticalScrollBar().setValue(
            self.txt_log.verticalScrollBar().maximum()
        )

    def _classify_value(self, value: int, address: int) -> tuple:
        """Clasifica un valor según su rango y dirección."""
        notes = []

        if 2000 <= value <= 7000:
            return ('voltage_x10', f"{value / 10.0:.1f}V", "Voltaje (/10)")

        if 180 <= value <= 650:
            return ('voltage_x100', f"{value / 100.0:.2f}V", "Voltaje batería (/100)")

        if 0 <= value <= 100:
            return ('percentage', f"{value}%", "Porcentaje o enum")

        if 101 <= value <= 200:
            return ('current', f"{value}A", "Corriente")

        if 0 <= value <= 150:
            return ('temperature', f"{value}°C", "Temperatura")

        if address == 0x1101:
            modes = {0: "Power", 1: "Standby", 2: "Bypass", 3: "Battery", 4: "Fault", 5: "Line", 6: "Charging"}
            return ('mode', modes.get(value, f"Unknown({value})"), "Modo trabajo")

        if address == 0x1102:
            stages = {0: "None", 1: "Bulk", 2: "Absorb", 3: "Float"}
            return ('charge_stage', stages.get(value, f"Unknown({value})"), "Estado carga")

        return ('unknown', f"0x{value:04X}", f"Raw: {value}")

    def _start_scan(self):
        if not self._conn or not self._conn.is_open:
            self._log("❌ No hay conexión. Conecta el inversor primero.", '#e74c3c')
            return

        self._scanning = True
        self.btn_scan.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.table.setRowCount(0)

        # Hilo de escaneo
        self._scan_thread = threading.Thread(target=self._do_scan, daemon=True)
        self._scan_thread.start()

    def _stop_scan(self):
        self._scanning = False
        self.btn_scan.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._log("⏹ Escaneo detenido por usuario", '#f39c12')

    def _do_scan(self):
        """Ejecuta el escaneo en un hilo separado."""
        zone = self.cb_zones.currentData()

        zones_to_scan = []
        if zone == "all" or zone == "status":
            zones_to_scan.extend([
                ('STATUS_KNOWN', 0x1101, 0x112A),
                ('STATUS_EXTENDED', 0x1000, 0x1150),
            ])
        if zone == "all" or zone == "settings":
            zones_to_scan.extend([
                ('SETTINGS_KNOWN', 0x211F, 0x2159),
                ('SETTINGS_EXTENDED', 0x2000, 0x2200),
            ])
        if zone == "all" or zone == "low":
            zones_to_scan.append(('LOW_RANGE', 0x0000, 0x0100))
        if zone == "all":
            zones_to_scan.append(('HIGH_RANGE', 0x3000, 0x3100))

        total_zones = len(zones_to_scan)
        current_zone = 0

        for zone_name, start, end in zones_to_scan:
            if not self._scanning:
                break

            current_zone += 1
            progress = int((current_zone / total_zones) * 100)

            # Actualizar UI
            QTimer.singleShot(0, lambda p=progress, z=zone_name: [
                self.pb_progress.setValue(p),
                self.lbl_progress.setText(f"Escaneando: {z}..."),
                self._log(f"📍 Escaneando {z}: 0x{start:04X} - 0x{end:04X}", '#00d2ff')
            ])

            # Escanear bloque
            for addr in range(start, end + 1, 10):
                if not self._scanning:
                    break

                regs = self._conn.read_holding_registers(addr, min(10, end - addr + 1))

                if regs is None:
                    continue

                for i, value in enumerate(regs):
                    reg_addr = addr + i

                    classification, real_value, notes = self._classify_value(value, reg_addr)

                    # Solo agregar si tiene valor o es zona conocida
                    if value != 0 or zone_name in ['STATUS_KNOWN', 'SETTINGS_KNOWN']:
                        QTimer.singleShot(0, lambda a=reg_addr, v=value, c=classification,
                                          rv=real_value, n=notes, z=zone_name: self._add_row(
                            f"0x{a:04X}", str(v), f"0x{v:04X}", c, rv, n, z
                        ))

        # Terminar
        self._scanning = False
        QTimer.singleShot(0, lambda: [
            self.pb_progress.setValue(100),
            self.lbl_progress.setText(f"Escaneo completado — {self.table.rowCount()} registros encontrados"),
            self.btn_scan.setEnabled(True),
            self.btn_stop.setEnabled(False),
            self._log(f"\n✅ Escaneo completado. Total: {self.table.rowCount()} registros", '#27ae60')
        ])

    def _add_row(self, address, value, hex_value, classification, real_value, notes, zone):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(address))
        self.table.setItem(row, 1, QTableWidgetItem(value))
        self.table.setItem(row, 2, QTableWidgetItem(hex_value))
        self.table.setItem(row, 3, QTableWidgetItem(classification))
        self.table.setItem(row, 4, QTableWidgetItem(real_value))
        self.table.setItem(row, 5, QTableWidgetItem(notes))
        self.table.setItem(row, 6, QTableWidgetItem(zone))

    def _copy_table(self):
        """Copia la tabla al portapapeles."""
        if self.table.rowCount() == 0:
            return

        text = "Dirección\tValor Decimal\tValor Hex\tClasificación\tPosible Valor Real\tNotas\tZona\n"
        for row in range(self.table.rowCount()):
            row_data = []
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                row_data.append(item.text() if item else "")
            text += "\t".join(row_data) + "\n"

        QApplication.clipboard().setText(text)
        self._log("📋 Tabla copiada al portapapeles", '#27ae60')

    def _save_results(self):
        """Guarda los resultados en un archivo."""
        if self.table.rowCount() == 0:
            self._log("No hay resultados para guardar", '#f39c12')
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"scanner_results_{timestamp}.txt"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("RESULTADOS DEL ESCANEO MODBUS - INVERSOR FELICITY\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Fecha/Hora: {datetime.now().isoformat()}\n")
            f.write(f"Total registros: {self.table.rowCount()}\n\n")

            f.write("Dirección\tValor Decimal\tValor Hex\tClasificación\tPosible Valor Real\tNotas\tZona\n")
            f.write("-" * 80 + "\n")

            for row in range(self.table.rowCount()):
                row_data = []
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    row_data.append(item.text() if item else "")
                f.write("\t".join(row_data) + "\n")

            f.write("\n" + "=" * 80 + "\n")
            f.write("FIN DEL REPORTE\n")
            f.write("=" * 80 + "\n")

        self._log(f"💾 Resultados guardados en: {filename}", '#27ae60')

    def _clear_results(self):
        self.table.setRowCount(0)
        self.pb_progress.setValue(0)
        self.lbl_progress.setText("Esperando iniciar escaneo...")
        self._log("🗑 Resultados limpiados", '#888')


# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — API REST Y EXPORTAR
# ══════════════════════════════════════════════════════════════════════════════

class TabAPI(QWidget):
    def __init__(self):
        super().__init__()
        self._last_status: ModbusStatus = None
        self._server_thread = None
        self._server_running = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        grp_api = QGroupBox("Servidor REST local (FastAPI)")
        ga = QVBoxLayout(grp_api)

        row_host = QHBoxLayout()
        row_host.addWidget(QLabel("Host:"))
        self.le_host = QLineEdit("127.0.0.1")
        self.le_host.setMaximumWidth(140)
        row_host.addWidget(self.le_host)
        row_host.addWidget(QLabel("Puerto:"))
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1024, 65535)
        self.sp_port.setValue(8000)
        row_host.addWidget(self.sp_port)
        row_host.addStretch()
        ga.addLayout(row_host)

        row_btns_api = QHBoxLayout()
        self.btn_start_api = QPushButton("Iniciar servidor")
        self.btn_start_api.clicked.connect(self._start_api)
        self.btn_stop_api = QPushButton("Detener")
        self.btn_stop_api.setEnabled(False)
        self.btn_stop_api.clicked.connect(self._stop_api)
        row_btns_api.addWidget(self.btn_start_api)
        row_btns_api.addWidget(self.btn_stop_api)
        row_btns_api.addStretch()
        ga.addLayout(row_btns_api)

        self.lbl_api_status = QLabel("Servidor inactivo")
        self.lbl_api_status.setStyleSheet("color:#555; font-size:12px;")
        ga.addWidget(self.lbl_api_status)

        lbl_endpoints = QLabel(
            "Endpoints Modbus:\n"
            "  GET /status     → Estado actual del inversor\n"
            "  GET /settings   → Configuración actual\n"
            "  GET /health     → Estado del servidor"
        )
        lbl_endpoints.setStyleSheet("color:#888; font-size:12px; font-family: 'Courier New'; background:#0d0d1a; padding:10px; border-radius:6px;")
        ga.addWidget(lbl_endpoints)
        layout.addWidget(grp_api)

        grp_json = QGroupBox("Último snapshot JSON")
        gj = QVBoxLayout(grp_json)

        row_j = QHBoxLayout()
        btn_copy = QPushButton("Copiar JSON")
        btn_copy.clicked.connect(self._copy_json)
        btn_save = QPushButton("Guardar .json")
        btn_save.clicked.connect(self._save_json)
        row_j.addWidget(btn_copy)
        row_j.addWidget(btn_save)
        row_j.addStretch()
        gj.addLayout(row_j)

        self.txt_json = QTextEdit()
        self.txt_json.setReadOnly(True)
        self.txt_json.setMinimumHeight(200)
        self.txt_json.setText("{\n  // Esperando datos del inversor...\n}")
        gj.addWidget(self.txt_json)
        layout.addWidget(grp_json)

    def update_data(self, status: ModbusStatus):
        self._last_status = status
        d = status.to_dict()
        d["timestamp"] = datetime.now().isoformat()
        self.txt_json.setText(json.dumps(d, indent=2, ensure_ascii=False))

    def _copy_json(self):
        QApplication.clipboard().setText(self.txt_json.toPlainText())

    def _save_json(self):
        fname = f"inverter_modbus_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(fname, 'w') as f:
            f.write(self.txt_json.toPlainText())
        self.lbl_api_status.setText(f"Guardado: {fname}")

    def _start_api(self):
        try:
            import uvicorn
            from fastapi import FastAPI
            from fastapi.middleware.cors import CORSMiddleware

            app = FastAPI(title="Felicity Inverter Modbus API", version="1.0")
            app.add_middleware(CORSMiddleware, allow_origins=["*"],
                               allow_methods=["GET"], allow_headers=["*"])

            tab_ref = self

            @app.get("/status")
            def get_status():
                if tab_ref._last_status is None:
                    return {"error": "Sin datos del inversor"}
                return tab_ref._last_status.to_dict()

            @app.get("/health")
            def health():
                return {"status": "ok", "has_data": tab_ref._last_status is not None}

            host = self.le_host.text()
            port = self.sp_port.value()

            self._server_running = True
            self._server_thread = threading.Thread(
                target=uvicorn.run,
                kwargs={"app": app, "host": host, "port": port, "log_level": "warning"},
                daemon=True
            )
            self._server_thread.start()

            self.lbl_api_status.setText(f"Servidor activo → http://{host}:{port}/status")
            self.lbl_api_status.setStyleSheet("color:#27ae60; font-size:12px; font-weight:bold;")
            self.btn_start_api.setEnabled(False)
            self.btn_stop_api.setEnabled(True)

        except ImportError:
            self.lbl_api_status.setText("Instala fastapi y uvicorn: pip install fastapi uvicorn")
            self.lbl_api_status.setStyleSheet("color:#e74c3c; font-size:12px;")

    def _stop_api(self):
        self._server_running = False
        self.lbl_api_status.setText("Servidor detenido")
        self.lbl_api_status.setStyleSheet("color:#555; font-size:12px;")
        self.btn_start_api.setEnabled(True)
        self.btn_stop_api.setEnabled(False)


# ══════════════════════════════════════════════════════════════════════════════
# HILO DE MONITOREO MODBUS
# ══════════════════════════════════════════════════════════════════════════════

class ModbusMonitorThread(QThread):
    data_received = pyqtSignal(object)       # ModbusStatus
    error_occurred = pyqtSignal(str)
    latency_update = pyqtSignal(float)
    settings_received = pyqtSignal(object)   # ModbusSettings
    info_received = pyqtSignal(object)       # ModbusInfo

    def __init__(self, conn, interval: float = 3.0):
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
        status = self.conn.read_status()
        latency_ms = (time.perf_counter() - start_time) * 1000
        self.latency_update.emit(round(latency_ms, 1))

        if status is None:
            self.error_occurred.emit("Sin respuesta del inversor (timeout)")
            return

        self.data_received.emit(status)

        self._poll_counter += 1
        # Cada 10 polls: leer settings
        if self._poll_counter % 10 == 0:
            settings = self.conn.read_settings()
            if settings:
                self.settings_received.emit(settings)

        # Cada 30 polls: leer info del dispositivo
        if self._poll_counter % 30 == 0:
            if hasattr(self.conn, 'read_info'):
                info = self.conn.read_info()
                if info:
                    self.info_received.emit(info)


# ══════════════════════════════════════════════════════════════════════════════
# VENTANA PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Felicity Inverter Monitor — Modbus RTU (RS232 / TCP) + Scanner")
        self.setMinimumSize(1200, 900)
        self.setStyleSheet(STYLE)

        self._conn: ModbusConnection = None
        self._monitor: ModbusMonitorThread = None
        self._profile_manager = ProfileManager()

        self._build_ui()
        self._build_status_bar()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)

        header_row = QHBoxLayout()
        header = QLabel("Felicity Inverter Monitor")
        header.setStyleSheet("font-size:16px; font-weight:bold; color:#e94560;")
        header_row.addWidget(header)
        header_row.addStretch()
        main_layout.addLayout(header_row)

        self.tabs = QTabWidget()
        self.tab_conn = TabConnection()
        self.tab_monitor = TabMonitor()
        self.tab_settings = TabSettings()
        self.tab_control = TabControl()
        self.tab_scanner = TabScanner()
        self.tab_profiles = TabProfiles(self._profile_manager)
        self.tab_api = TabAPI()

        self.tabs.addTab(self.tab_conn, "Conexión")
        self.tabs.addTab(self.tab_monitor, "Monitor")
        self.tabs.addTab(self.tab_settings, "Settings")
        self.tabs.addTab(self.tab_control, "Control (9 params)")
        self.tabs.addTab(self.tab_scanner, "🔍 Scanner")
        self.tabs.addTab(self.tab_profiles, "Perfiles")
        self.tabs.addTab(self.tab_api, "API")
        main_layout.addWidget(self.tabs)

        self.tab_conn.connect_requested.connect(self._on_connect)
        self.tab_conn.disconnect_requested.connect(self._on_disconnect)
        self.tab_settings.refresh_requested.connect(self._read_settings)
        self.tab_monitor.poll_interval_changed.connect(self._on_interval_changed)

    def _build_status_bar(self):
        self.statusBar().showMessage("Listo · Protocolo: Modbus RTU · RS232 / TCP + Scanner")

    def _on_connect(self, conn_type: str, config: dict):
        """Conecta al inversor via RS232 o TCP/IP según corresponda."""
        if conn_type == "tcp":
            host = config.get('host', '')
            port = config.get('port', 502)
            timeout = config.get('timeout', 5.0)
            if not host:
                return
            self._conn = ModbusTCPConnection(host, port, timeout)
        else:
            port = config.get('port', '')
            if not port or port == "(sin puertos)":
                return
            # ModbusConnection necesita port como primer arg y el resto como config
            serial_config = {k: v for k, v in config.items() if k != 'port'}
            self._conn = ModbusConnection(port, serial_config)

        ok, msg = self._conn.connect()
        self.tab_conn.set_connected(ok, msg)
        self.tab_conn.log(msg, '#27ae60' if ok else '#e74c3c')
        self.statusBar().showMessage(f"{'Conectado' if ok else 'Error'}: {msg}")

        if ok:
            self.tab_control.set_connection(self._conn)
            self.tab_scanner.set_connection(self._conn)
            self._start_monitor()
            self._read_settings()

    def _on_disconnect(self):
        self._stop_monitor()
        if self._conn:
            self._conn.disconnect()
            self._conn = None
        self.tab_conn.set_connected(False)
        self.tab_conn.log("Desconectado", '#f39c12')
        self.tab_control.set_connection(None)
        self.tab_scanner.set_connection(None)
        self.statusBar().showMessage("Desconectado")

    def _start_monitor(self):
        if self._monitor:
            self._monitor.stop()
        interval = self.tab_monitor.sl_interval.value()
        self._monitor = ModbusMonitorThread(self._conn, float(interval))
        self._monitor.data_received.connect(self._on_data)
        self._monitor.error_occurred.connect(
            lambda e: self.tab_conn.log(f"Error: {e}", '#e74c3c')
        )
        self._monitor.latency_update.connect(self.tab_monitor.update_latency)
        self._monitor.settings_received.connect(self.tab_settings.update_settings)
        self._monitor.settings_received.connect(self.tab_control.update_from_settings)
        self._monitor.settings_received.connect(self.tab_monitor.update_settings_display)
        self._monitor.info_received.connect(self.tab_monitor.update_info)
        self._monitor.start()

    def _stop_monitor(self):
        if self._monitor:
            self._monitor.stop()
            self._monitor = None

    def _on_data(self, status: ModbusStatus):
        self.tab_monitor.update_data(status)
        self.tab_api.update_data(status)
        self.statusBar().showMessage(
            f"OK · Bat {status.battery_voltage}V · "
            f"PV {status.pv_power}W · Carga {status.load_percent}% · "
            f"Modo: {status.working_mode}"
        )

    def _read_settings(self):
        if not self._conn or not self._conn.is_open:
            return
        settings = self._conn.read_settings()
        if settings:
            self.tab_settings.update_settings(settings)
            self.tab_control.update_from_settings(settings)
            self.tab_conn.log("Settings leídos correctamente", '#27ae60')
        else:
            self.tab_conn.log("Error al leer settings", '#e74c3c')

    def _on_interval_changed(self, seconds: float):
        if self._monitor:
            self._monitor.interval = seconds

    def closeEvent(self, event):
        self._stop_monitor()
        if self._conn:
            self._conn.disconnect()
        event.accept()


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    import os
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))

    icon_path = os.path.join(base_path, 'imagen', 'panel-solar.png')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())