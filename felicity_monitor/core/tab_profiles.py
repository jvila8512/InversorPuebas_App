"""
tab_profiles.py — Pestaña de gestión de perfiles de inversor
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QComboBox,
    QLineEdit, QDoubleSpinBox, QSpinBox, QTextEdit,
    QMessageBox, QFrame, QScrollArea
)
from PyQt5.QtCore import pyqtSignal, Qt
from core.profiles import (
    ProfileManager, InverterProfile,
    BATTERY_TYPES, BATTERY_VOLTAGE_BANKS,
    OUTPUT_PRIORITIES, CHARGE_PRIORITIES, BAUD_RATES
)

try:
    import serial
    PARITIES = {"None": serial.PARITY_NONE, "Even": serial.PARITY_EVEN, "Odd": serial.PARITY_ODD}
except ImportError:
    PARITIES = {"None": "N", "Even": "E", "Odd": "O"}

BAUD_RATES = [2400, 4800, 9600, 19200, 38400]


class TabProfiles(QWidget):
    profile_changed = pyqtSignal(object)   # InverterProfile

    def __init__(self, manager: ProfileManager):
        super().__init__()
        self.manager = manager
        self._editing_index = -1
        self._build_ui()
        self._load_profile_list()
        self._load_profile(self.manager.active_index)

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(12)

        # ── Panel izquierdo: lista de perfiles ──
        left = QVBoxLayout()

        grp_list = QGroupBox("Perfiles guardados")
        gl = QVBoxLayout(grp_list)

        self.cb_profiles = QComboBox()
        self.cb_profiles.currentIndexChanged.connect(self._on_profile_selected)
        gl.addWidget(self.cb_profiles)

        row_btns = QHBoxLayout()
        self.btn_new    = QPushButton("Nuevo")
        self.btn_clone  = QPushButton("Clonar")
        self.btn_delete = QPushButton("Borrar")
        self.btn_new.clicked.connect(self._on_new)
        self.btn_clone.clicked.connect(self._on_clone)
        self.btn_delete.clicked.connect(self._on_delete)
        row_btns.addWidget(self.btn_new)
        row_btns.addWidget(self.btn_clone)
        row_btns.addWidget(self.btn_delete)
        gl.addLayout(row_btns)

        self.btn_activate = QPushButton("Usar este perfil")
        self.btn_activate.setStyleSheet("background:#1b7f4f; font-weight:bold; padding:10px;")
        self.btn_activate.clicked.connect(self._on_activate)
        gl.addWidget(self.btn_activate)

        self.lbl_active = QLabel("Activo: —")
        self.lbl_active.setStyleSheet("color:#27ae60; font-size:12px; font-weight:bold;")
        self.lbl_active.setAlignment(Qt.AlignCenter)
        gl.addWidget(self.lbl_active)

        left.addWidget(grp_list)
        left.addStretch()

        # ── Panel derecho: editor de perfil ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        editor_widget = QWidget()
        right = QVBoxLayout(editor_widget)
        right.setSpacing(10)
        scroll.setWidget(editor_widget)

        # Info general
        grp_info = QGroupBox("Información del perfil")
        gi = QGridLayout(grp_info)

        gi.addWidget(QLabel("Nombre:"), 0, 0)
        self.le_name = QLineEdit()
        gi.addWidget(self.le_name, 0, 1, 1, 2)

        gi.addWidget(QLabel("Marca:"), 1, 0)
        self.le_brand = QLineEdit()
        gi.addWidget(self.le_brand, 1, 1)

        gi.addWidget(QLabel("Modelo:"), 1, 2)
        self.le_model = QLineEdit()
        gi.addWidget(self.le_model, 1, 3)

        gi.addWidget(QLabel("Protocolo:"), 2, 0)
        self.le_protocol = QLineEdit("PI30")
        self.le_protocol.setReadOnly(True)
        self.le_protocol.setStyleSheet("color:#888;")
        gi.addWidget(self.le_protocol, 2, 1)

        right.addWidget(grp_info)

        # Comunicación
        grp_comm = QGroupBox("Comunicación RS232")
        gc = QGridLayout(grp_comm)

        gc.addWidget(QLabel("Baud rate:"), 0, 0)
        self.cb_baud = QComboBox()
        for b in BAUD_RATES:
            self.cb_baud.addItem(str(b), b)
        gc.addWidget(self.cb_baud, 0, 1)

        gc.addWidget(QLabel("Paridad:"), 0, 2)
        self.cb_parity = QComboBox()
        for name in PARITIES:
            self.cb_parity.addItem(name)
        gc.addWidget(self.cb_parity, 0, 3)

        gc.addWidget(QLabel("Timeout (s):"), 1, 0)
        self.sp_timeout = QDoubleSpinBox()
        self.sp_timeout.setRange(0.5, 10.0)
        self.sp_timeout.setSingleStep(0.5)
        self.sp_timeout.setValue(2.0)
        gc.addWidget(self.sp_timeout, 1, 1)

        right.addWidget(grp_comm)

        # Batería
        grp_bat = QGroupBox("Configuración de batería")
        gb = QGridLayout(grp_bat)

        gb.addWidget(QLabel("Tipo:"), 0, 0)
        self.cb_bat_type = QComboBox()
        for t in BATTERY_TYPES:
            self.cb_bat_type.addItem(t)
        self.cb_bat_type.currentTextChanged.connect(self._on_battery_changed)
        gb.addWidget(self.cb_bat_type, 0, 1)

        gb.addWidget(QLabel("Banco (V):"), 0, 2)
        self.cb_bank_v = QComboBox()
        for v in BATTERY_VOLTAGE_BANKS:
            self.cb_bank_v.addItem(f"{v}V", v)
        self.cb_bank_v.currentIndexChanged.connect(self._on_battery_changed)
        gb.addWidget(self.cb_bank_v, 0, 3)

        btn_defaults = QPushButton("Cargar valores por defecto")
        btn_defaults.clicked.connect(self._apply_defaults)
        btn_defaults.setStyleSheet("font-size:11px; padding:4px 8px;")
        gb.addWidget(btn_defaults, 1, 0, 1, 4)

        right.addWidget(grp_bat)

        # Voltajes
        grp_v = QGroupBox("Voltajes de carga (según tipo y banco)")
        gv = QGridLayout(grp_v)
        gv.setSpacing(8)

        self.voltage_fields = {}
        voltage_params = [
            ("absorb_v",   "Absorción (CV)",    0, 0),
            ("float_v",    "Flotación",          0, 2),
            ("recharge_v", "Recarga (retorno)",  1, 0),
            ("shutdown_v", "Shutdown (apagado)", 1, 2),
        ]

        for key, label, row, col in voltage_params:
            gv.addWidget(QLabel(f"{label}:"), row, col)
            sp = QDoubleSpinBox()
            sp.setRange(10.0, 80.0)
            sp.setSingleStep(0.1)
            sp.setDecimals(1)
            sp.setSuffix(" V")
            gv.addWidget(sp, row, col + 1)
            self.voltage_fields[key] = sp

        # Indicadores de rango
        self.lbl_ranges = QLabel("")
        self.lbl_ranges.setStyleSheet("color:#888; font-size:11px; font-family:'Courier New';")
        self.lbl_ranges.setWordWrap(True)
        gv.addWidget(self.lbl_ranges, 2, 0, 1, 4)

        right.addWidget(grp_v)

        # Prioridades
        grp_prio = QGroupBox("Prioridades por defecto del perfil")
        gp = QGridLayout(grp_prio)

        gp.addWidget(QLabel("Salida:"), 0, 0)
        self.cb_out_prio = QComboBox()
        for label in OUTPUT_PRIORITIES:
            self.cb_out_prio.addItem(label)
        gp.addWidget(self.cb_out_prio, 0, 1)

        gp.addWidget(QLabel("Carga:"), 1, 0)
        self.cb_chg_prio = QComboBox()
        for label in CHARGE_PRIORITIES:
            self.cb_chg_prio.addItem(label)
        gp.addWidget(self.cb_chg_prio, 1, 1)

        right.addWidget(grp_prio)

        # Notas
        grp_notes = QGroupBox("Notas")
        gn = QVBoxLayout(grp_notes)
        self.txt_notes = QTextEdit()
        self.txt_notes.setMaximumHeight(80)
        self.txt_notes.setPlaceholderText("Notas sobre este inversor / instalación...")
        gn.addWidget(self.txt_notes)
        right.addWidget(grp_notes)

        # Botones guardar
        row_save = QHBoxLayout()
        self.btn_save = QPushButton("Guardar cambios")
        self.btn_save.setStyleSheet("background:#0f3460; font-weight:bold; padding:10px;")
        self.btn_save.clicked.connect(self._on_save)
        self.btn_validate = QPushButton("Validar voltajes")
        self.btn_validate.clicked.connect(self._on_validate)
        row_save.addWidget(self.btn_validate)
        row_save.addWidget(self.btn_save)
        right.addLayout(row_save)

        right.addStretch()

        # Ensamblar layout
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(220)
        layout.addWidget(left_widget)
        layout.addWidget(scroll, 1)

    # ── Helpers ──────────────────────────────────

    def _load_profile_list(self):
        self.cb_profiles.blockSignals(True)
        self.cb_profiles.clear()
        for name in self.manager.names():
            self.cb_profiles.addItem(name)
        self.cb_profiles.setCurrentIndex(self.manager.active_index)
        self.lbl_active.setText(f"Activo: {self.manager.active.name}")
        self.cb_profiles.blockSignals(False)

    def _load_profile(self, index: int):
        if index < 0 or index >= len(self.manager.profiles):
            return
        self._editing_index = index
        p = self.manager.profiles[index]

        self.le_name.setText(p.name)
        self.le_brand.setText(p.brand)
        self.le_model.setText(p.model)
        self.le_protocol.setText(p.protocol)

        # Baud
        for i in range(self.cb_baud.count()):
            if self.cb_baud.itemData(i) == p.baudrate:
                self.cb_baud.setCurrentIndex(i)

        # Paridad
        idx = self.cb_parity.findText(p.parity)
        if idx >= 0:
            self.cb_parity.setCurrentIndex(idx)

        self.sp_timeout.setValue(p.timeout)

        # Batería
        idx = self.cb_bat_type.findText(p.battery_type)
        if idx >= 0:
            self.cb_bat_type.setCurrentIndex(idx)

        for i in range(self.cb_bank_v.count()):
            if self.cb_bank_v.itemData(i) == p.battery_bank_v:
                self.cb_bank_v.setCurrentIndex(i)

        # Voltajes
        self.voltage_fields["absorb_v"].setValue(p.absorb_v)
        self.voltage_fields["float_v"].setValue(p.float_v)
        self.voltage_fields["recharge_v"].setValue(p.recharge_v)
        self.voltage_fields["shutdown_v"].setValue(p.shutdown_v)

        # Prioridades
        idx = self.cb_out_prio.findText(p.output_priority)
        if idx >= 0:
            self.cb_out_prio.setCurrentIndex(idx)
        idx = self.cb_chg_prio.findText(p.charge_priority)
        if idx >= 0:
            self.cb_chg_prio.setCurrentIndex(idx)

        self.txt_notes.setText(p.notes)
        self._update_range_hints()

    def _build_profile_from_ui(self) -> InverterProfile:
        import serial as _serial
        parity_name = self.cb_parity.currentText()
        parity_val  = PARITIES.get(parity_name, "N")
        # Si es objeto serial, convertir a string
        if hasattr(parity_val, '__class__') and parity_val.__class__.__name__ != 'str':
            parity_val = parity_name

        return InverterProfile(
            name             = self.le_name.text().strip() or "Sin nombre",
            brand            = self.le_brand.text().strip(),
            model            = self.le_model.text().strip(),
            protocol         = "PI30",
            battery_type     = self.cb_bat_type.currentText(),
            battery_bank_v   = self.cb_bank_v.currentData(),
            baudrate         = self.cb_baud.currentData(),
            parity           = parity_name,
            timeout          = self.sp_timeout.value(),
            absorb_v         = self.voltage_fields["absorb_v"].value(),
            float_v          = self.voltage_fields["float_v"].value(),
            recharge_v       = self.voltage_fields["recharge_v"].value(),
            shutdown_v       = self.voltage_fields["shutdown_v"].value(),
            output_priority  = self.cb_out_prio.currentText(),
            charge_priority  = self.cb_chg_prio.currentText(),
            notes            = self.txt_notes.toPlainText(),
        )

    def _update_range_hints(self):
        """Muestra los rangos válidos para el tipo y banco seleccionados."""
        bat_type = self.cb_bat_type.currentText()
        bank_v   = self.cb_bank_v.currentData() or 48
        dummy    = InverterProfile(battery_type=bat_type, battery_bank_v=bank_v)
        ranges   = dummy.get_ranges()
        lines = []
        labels = {
            "absorb_v":   "Absorción",
            "float_v":    "Flotación",
            "recharge_v": "Recarga",
            "shutdown_v": "Shutdown",
        }
        for key, label in labels.items():
            lo, hi, default = ranges[key]
            lines.append(f"{label}: [{lo}V – {hi}V]  (defecto: {default}V)")
        self.lbl_ranges.setText("  |  ".join(lines))

    # ── Slots ─────────────────────────────────────

    def _on_profile_selected(self, index: int):
        self._load_profile(index)

    def _on_battery_changed(self):
        self._update_range_hints()

    def _apply_defaults(self):
        bat_type = self.cb_bat_type.currentText()
        bank_v   = self.cb_bank_v.currentData() or 48
        dummy    = InverterProfile(battery_type=bat_type, battery_bank_v=bank_v)
        dummy.apply_defaults_from_ranges()
        self.voltage_fields["absorb_v"].setValue(dummy.absorb_v)
        self.voltage_fields["float_v"].setValue(dummy.float_v)
        self.voltage_fields["recharge_v"].setValue(dummy.recharge_v)
        self.voltage_fields["shutdown_v"].setValue(dummy.shutdown_v)

    def _on_validate(self):
        p = self._build_profile_from_ui()
        errors = p.validate_voltages()
        if errors:
            QMessageBox.warning(self, "Voltajes inválidos",
                                "Se encontraron los siguientes problemas:\n\n" + "\n".join(errors))
        else:
            QMessageBox.information(self, "Voltajes OK",
                                    "Todos los voltajes son coherentes y están dentro de rango.")

    def _on_save(self):
        p = self._build_profile_from_ui()
        errors = p.validate_voltages()
        if errors:
            reply = QMessageBox.question(
                self, "Voltajes con advertencias",
                "Hay advertencias en los voltajes:\n\n" + "\n".join(errors) +
                "\n\n¿Guardar de todas formas?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return

        if self._editing_index >= 0:
            self.manager.update(self._editing_index, p)
        else:
            self.manager.add(p)
            self._editing_index = len(self.manager.profiles) - 1

        self._load_profile_list()
        self.cb_profiles.setCurrentIndex(self._editing_index)

    def _on_activate(self):
        idx = self.cb_profiles.currentIndex()
        self.manager.active_index = idx
        self.manager.save()
        self.lbl_active.setText(f"Activo: {self.manager.active.name}")
        self.profile_changed.emit(self.manager.active)

    def _on_new(self):
        p = InverterProfile(name="Nuevo perfil")
        self.manager.add(p)
        self._load_profile_list()
        self.cb_profiles.setCurrentIndex(len(self.manager.profiles) - 1)

    def _on_clone(self):
        idx = self.cb_profiles.currentIndex()
        if idx < 0:
            return
        import copy
        p = copy.deepcopy(self.manager.profiles[idx])
        p.name = p.name + " (copia)"
        self.manager.add(p)
        self._load_profile_list()
        self.cb_profiles.setCurrentIndex(len(self.manager.profiles) - 1)

    def _on_delete(self):
        idx = self.cb_profiles.currentIndex()
        if len(self.manager.profiles) <= 1:
            QMessageBox.warning(self, "No se puede borrar", "Debe existir al menos un perfil.")
            return
        reply = QMessageBox.question(
            self, "Confirmar",
            f"¿Borrar el perfil '{self.manager.profiles[idx].name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.manager.delete(idx)
            self._load_profile_list()
            self._load_profile(self.manager.active_index)
