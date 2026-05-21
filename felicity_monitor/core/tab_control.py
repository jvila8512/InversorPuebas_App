"""
tab_control.py — Pestaña de Control y Escritura
Implementa los 3 controles: prioridad de salida, voltajes de batería, buzzer.
"""

from datetime import datetime
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QComboBox,
    QDoubleSpinBox, QTextEdit, QFrame, QMessageBox,
    QProgressBar, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor

from core.profiles import InverterProfile, OUTPUT_PRIORITIES, CHARGE_PRIORITIES
from core.write_commands import WriteCommands, WriteResult


# ──────────────────────────────────────────────
# Widget: resultado de comando
# ──────────────────────────────────────────────

class ResultBadge(QLabel):
    def __init__(self, parent=None):
        super().__init__("—", parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(180)
        self.setStyleSheet("""
            padding: 6px 14px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: bold;
            background: #1a1a2e;
            color: #555;
            border: 1px solid #333;
        """)

    def set_result(self, result: WriteResult):
        if result.success:
            self.setText(f"ACK · {result.latency_ms:.0f}ms")
            self.setStyleSheet("""
                padding:6px 14px; border-radius:6px; font-size:12px; font-weight:bold;
                background:#1b4d2e; color:#27ae60; border:1px solid #27ae60;
            """)
        else:
            self.setText("NAK / Error")
            self.setStyleSheet("""
                padding:6px 14px; border-radius:6px; font-size:12px; font-weight:bold;
                background:#4d1b1b; color:#e74c3c; border:1px solid #e74c3c;
            """)

    def reset(self):
        self.setText("—")
        self.setStyleSheet("""
            padding:6px 14px; border-radius:6px; font-size:12px; font-weight:bold;
            background:#1a1a2e; color:#555; border:1px solid #333;
        """)


# ──────────────────────────────────────────────
# Tab principal de control
# ──────────────────────────────────────────────

class TabControl(QWidget):
    log_message = pyqtSignal(str, str)  # mensaje, color

    def __init__(self):
        super().__init__()
        self._writer: WriteCommands = None
        self._current_mode: str = ""
        self._profile: InverterProfile = None
        self._build_ui()
        self._set_enabled(False)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Banner de estado ──────────────────────
        self.lbl_status_banner = QLabel("Sin conexión — Conecta el inversor primero")
        self.lbl_status_banner.setAlignment(Qt.AlignCenter)
        self.lbl_status_banner.setStyleSheet("""
            background:#2a1a0a; color:#f39c12; font-size:13px;
            padding:10px; border-radius:8px; border:1px solid #f39c12;
        """)
        layout.addWidget(self.lbl_status_banner)

        # ── Test de capacidad de escritura ────────
        grp_test = QGroupBox("Paso 1 — Verificar que el inversor acepta escritura")
        gt = QHBoxLayout(grp_test)

        self.btn_test_write = QPushButton("Probar escritura (test buzzer)")
        self.btn_test_write.clicked.connect(self._on_test_write)
        self.btn_test_write.setStyleSheet("padding:10px; font-weight:bold;")

        self.badge_test = ResultBadge()

        self.lbl_test_info = QLabel(
            "Envía PEa (buzzer ON) y PDa (buzzer OFF) inmediatamente.\n"
            "Si responde ACK → el inversor acepta escritura."
        )
        self.lbl_test_info.setStyleSheet("color:#888; font-size:11px;")
        self.lbl_test_info.setWordWrap(True)

        gt.addWidget(self.btn_test_write)
        gt.addWidget(self.badge_test)
        gt.addWidget(self.lbl_test_info, 1)
        layout.addWidget(grp_test)

        # ── Control 1: Prioridad de salida ────────
        grp_prio = QGroupBox("Control 1 — Prioridad de salida")
        gp = QVBoxLayout(grp_prio)

        lbl_info1 = QLabel(
            "Define qué fuente alimenta la carga primero: Red eléctrica, Solar o SBU (Solar→Bat→Red)"
        )
        lbl_info1.setStyleSheet("color:#888; font-size:11px;")
        lbl_info1.setWordWrap(True)
        gp.addWidget(lbl_info1)

        row1 = QHBoxLayout()
        self.cb_out_priority = QComboBox()
        for label in OUTPUT_PRIORITIES:
            self.cb_out_priority.addItem(label)
        self.cb_out_priority.setMinimumWidth(260)

        self.btn_set_priority = QPushButton("Aplicar prioridad")
        self.btn_set_priority.clicked.connect(self._on_set_priority)
        self.badge_priority = ResultBadge()

        row1.addWidget(QLabel("Prioridad:"))
        row1.addWidget(self.cb_out_priority)
        row1.addWidget(self.btn_set_priority)
        row1.addWidget(self.badge_priority)
        row1.addStretch()
        gp.addLayout(row1)

        self.lbl_priority_current = QLabel("Actual: desconocida")
        self.lbl_priority_current.setStyleSheet("color:#555; font-size:11px;")
        gp.addWidget(self.lbl_priority_current)
        layout.addWidget(grp_prio)

        # ── Control 2: Voltajes de batería ────────
        grp_volts = QGroupBox("Control 2 — Voltajes de batería")
        gv = QVBoxLayout(grp_volts)

        lbl_info2 = QLabel(
            "Los rangos válidos se toman del perfil activo. "
            "El inversor guarda estos valores en EEPROM — no cambiar con frecuencia."
        )
        lbl_info2.setStyleSheet("color:#888; font-size:11px;")
        lbl_info2.setWordWrap(True)
        gv.addWidget(lbl_info2)

        # Grid de voltajes
        vgrid = QGridLayout()
        vgrid.setSpacing(8)

        self.voltage_controls = {}
        volt_defs = [
            ("absorb_v",   "Absorción (CV)",    "PCVV", 0),
            ("float_v",    "Flotación",          "PBFT", 1),
            ("recharge_v", "Recarga (retorno)",  "PBCV", 2),
            ("shutdown_v", "Shutdown",           "PSDV", 3),
        ]

        for key, label, cmd_prefix, row in volt_defs:
            # Label
            lbl = QLabel(f"{label}:")
            lbl.setMinimumWidth(150)
            vgrid.addWidget(lbl, row, 0)

            # SpinBox
            sp = QDoubleSpinBox()
            sp.setRange(10.0, 80.0)
            sp.setSingleStep(0.1)
            sp.setDecimals(1)
            sp.setSuffix(" V")
            sp.setMinimumWidth(90)
            vgrid.addWidget(sp, row, 1)

            # Rango hint
            lbl_range = QLabel("rango: —")
            lbl_range.setStyleSheet("color:#555; font-size:11px;")
            vgrid.addWidget(lbl_range, row, 2)

            # Botón aplicar
            btn = QPushButton(f"Aplicar")
            btn.setMinimumWidth(80)
            btn.clicked.connect(lambda checked, k=key: self._on_set_voltage(k))
            vgrid.addWidget(btn, row, 3)

            # Badge resultado
            badge = ResultBadge()
            badge.setMinimumWidth(130)
            vgrid.addWidget(badge, row, 4)

            self.voltage_controls[key] = {
                "spinbox":    sp,
                "btn":        btn,
                "badge":      badge,
                "lbl_range":  lbl_range,
                "cmd_prefix": cmd_prefix,
            }

        gv.addLayout(vgrid)

        # Botón aplicar todos
        row_all = QHBoxLayout()
        self.btn_apply_all = QPushButton("Aplicar todos los voltajes")
        self.btn_apply_all.setStyleSheet("background:#0f3460; font-weight:bold; padding:8px;")
        self.btn_apply_all.clicked.connect(self._on_apply_all_voltages)
        self.lbl_apply_all_result = QLabel("")
        self.lbl_apply_all_result.setStyleSheet("font-size:12px; color:#888;")
        row_all.addWidget(self.btn_apply_all)
        row_all.addWidget(self.lbl_apply_all_result)
        row_all.addStretch()
        gv.addLayout(row_all)

        layout.addWidget(grp_volts)

        # ── Control 3: Buzzer ─────────────────────
        grp_buzzer = QGroupBox("Control 3 — Buzzer")
        gb = QHBoxLayout(grp_buzzer)

        lbl_bz = QLabel("El buzzer suena en alarmas y eventos del inversor.")
        lbl_bz.setStyleSheet("color:#888; font-size:11px;")

        self.btn_buzzer_on  = QPushButton("Activar buzzer")
        self.btn_buzzer_off = QPushButton("Desactivar buzzer")
        self.btn_buzzer_on.clicked.connect(lambda: self._on_set_buzzer(True))
        self.btn_buzzer_off.clicked.connect(lambda: self._on_set_buzzer(False))
        self.badge_buzzer = ResultBadge()

        gb.addWidget(lbl_bz, 1)
        gb.addWidget(self.btn_buzzer_on)
        gb.addWidget(self.btn_buzzer_off)
        gb.addWidget(self.badge_buzzer)
        layout.addWidget(grp_buzzer)

        # ── Log de escritura ──────────────────────
        grp_log = QGroupBox("Log de comandos enviados")
        gl = QVBoxLayout(grp_log)

        row_log_btns = QHBoxLayout()
        btn_clear = QPushButton("Limpiar log")
        btn_clear.clicked.connect(lambda: self.txt_log.clear())
        btn_clear.setStyleSheet("font-size:11px; padding:4px 10px;")
        row_log_btns.addWidget(btn_clear)
        row_log_btns.addStretch()
        gl.addLayout(row_log_btns)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMinimumHeight(140)
        self.txt_log.setMaximumHeight(200)
        gl.addWidget(self.txt_log)
        layout.addWidget(grp_log)

    # ── API pública ───────────────────────────────

    def set_connection(self, connection, profile: InverterProfile):
        """Llamado cuando hay conexión activa."""
        self._profile = profile
        if connection and connection.is_open:
            self._writer = WriteCommands(connection, profile)
            self._set_enabled(True)
            self._update_profile_hints()
            self.lbl_status_banner.setText(
                f"Conectado · Perfil: {profile.name} · "
                f"Batería: {profile.battery_type} {profile.battery_bank_v}V"
            )
            self.lbl_status_banner.setStyleSheet("""
                background:#0a2a1a; color:#27ae60; font-size:13px;
                padding:10px; border-radius:8px; border:1px solid #27ae60;
            """)
        else:
            self._writer = None
            self._set_enabled(False)

    def clear_connection(self):
        """Llamado al desconectar."""
        self._writer = None
        self._set_enabled(False)
        self.lbl_status_banner.setText("Sin conexión — Conecta el inversor primero")
        self.lbl_status_banner.setStyleSheet("""
            background:#2a1a0a; color:#f39c12; font-size:13px;
            padding:10px; border-radius:8px; border:1px solid #f39c12;
        """)

    def update_mode(self, mode: str):
        """Recibe el modo actual del inversor."""
        self._current_mode = mode
        if "Fault" in mode or mode == "F":
            self.lbl_status_banner.setText(
                f"MODO FAULT — Escritura bloqueada hasta resolver el fallo"
            )
            self.lbl_status_banner.setStyleSheet("""
                background:#2a0a0a; color:#e74c3c; font-size:13px;
                padding:10px; border-radius:8px; border:1px solid #e74c3c;
            """)

    def update_from_qpiri(self, profile_hints: dict):
        """
        Recibe valores actuales leídos del inversor (QPIRI)
        para mostrarlos como referencia en los spinboxes.
        """
        mapping = {
            "float_v":    "battery_float",
            "absorb_v":   "battery_absorb",
            "recharge_v": "battery_rebulk",
            "shutdown_v": "battery_redischarge_v",
        }
        for key, src_key in mapping.items():
            if src_key in profile_hints and key in self.voltage_controls:
                val = profile_hints[src_key]
                if val and val > 0:
                    self.voltage_controls[key]["spinbox"].setValue(val)
                    self._log(f"Valor actual del inversor — {key}: {val}V", "#888")

    # ── Slots privados ────────────────────────────

    def _set_enabled(self, enabled: bool):
        widgets = [
            self.btn_test_write,
            self.btn_set_priority,
            self.btn_buzzer_on,
            self.btn_buzzer_off,
            self.btn_apply_all,
        ]
        for w in widgets:
            w.setEnabled(enabled)
        for ctrl in self.voltage_controls.values():
            ctrl["btn"].setEnabled(enabled)

    def _update_profile_hints(self):
        """Actualiza rangos y valores por defecto desde el perfil activo."""
        if not self._profile:
            return
        ranges = self._profile.get_ranges()
        labels = {
            "absorb_v":   "absorb_v",
            "float_v":    "float_v",
            "recharge_v": "recharge_v",
            "shutdown_v": "shutdown_v",
        }
        defaults = {
            "absorb_v":   self._profile.absorb_v,
            "float_v":    self._profile.float_v,
            "recharge_v": self._profile.recharge_v,
            "shutdown_v": self._profile.shutdown_v,
        }
        for key, ctrl in self.voltage_controls.items():
            if key in ranges:
                lo, hi, _ = ranges[key]
                ctrl["spinbox"].setRange(lo, hi)
                ctrl["spinbox"].setValue(defaults.get(key, (lo + hi) / 2))
                ctrl["lbl_range"].setText(f"rango: {lo}–{hi}V")

        # Prioridad desde perfil
        idx = self.cb_out_priority.findText(self._profile.output_priority)
        if idx >= 0:
            self.cb_out_priority.setCurrentIndex(idx)

    def _on_test_write(self):
        if not self._writer:
            return
        self.badge_test.reset()
        result = self._writer.test_write_capability()
        self.badge_test.set_result(result)
        color = "#27ae60" if result.success else "#e74c3c"
        self._log(f"Test escritura: {result.message}  ({result.latency_ms:.0f}ms)", color)

    def _on_set_priority(self):
        if not self._writer:
            return
        label = self.cb_out_priority.currentText()
        self.badge_priority.reset()

        reply = QMessageBox.question(
            self, "Confirmar cambio",
            f"¿Cambiar prioridad de salida a:\n\n  {label}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        result = self._writer.set_output_priority(label, self._current_mode)
        self.badge_priority.set_result(result)

        if result.success:
            self.lbl_priority_current.setText(f"Actual: {label}")
            self._log(f"Prioridad de salida → {label}  ACK ({result.latency_ms:.0f}ms)", "#27ae60")
        else:
            self._log(f"Error prioridad: {result.message}", "#e74c3c")

    def _on_set_voltage(self, key: str):
        if not self._writer:
            return
        ctrl = self.voltage_controls[key]
        value = ctrl["spinbox"].value()
        ctrl["badge"].reset()

        labels = {
            "absorb_v":   "Absorción",
            "float_v":    "Flotación",
            "recharge_v": "Recarga",
            "shutdown_v": "Shutdown",
        }
        label = labels.get(key, key)

        reply = QMessageBox.question(
            self, "Confirmar cambio",
            f"¿Establecer voltaje de {label} a {value:.1f}V?\n\n"
            f"Este valor se guarda en la EEPROM del inversor.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        methods = {
            "absorb_v":   self._writer.set_absorb_voltage,
            "float_v":    self._writer.set_float_voltage,
            "recharge_v": self._writer.set_recharge_voltage,
            "shutdown_v": self._writer.set_shutdown_voltage,
        }
        result = methods[key](value, self._current_mode)
        ctrl["badge"].set_result(result)

        if result.success:
            self._log(f"{label} → {value:.1f}V  ACK ({result.latency_ms:.0f}ms)", "#27ae60")
        else:
            self._log(f"Error {label}: {result.message}", "#e74c3c")

    def _on_apply_all_voltages(self):
        if not self._writer:
            return

        # Recoger valores
        vals = {k: ctrl["spinbox"].value() for k, ctrl in self.voltage_controls.items()}

        # Construir resumen
        summary = (
            f"Absorción:  {vals['absorb_v']:.1f}V\n"
            f"Flotación:  {vals['float_v']:.1f}V\n"
            f"Recarga:    {vals['recharge_v']:.1f}V\n"
            f"Shutdown:   {vals['shutdown_v']:.1f}V"
        )

        reply = QMessageBox.question(
            self, "Confirmar — aplicar TODOS los voltajes",
            f"Se enviarán 4 comandos al inversor (escritura en EEPROM):\n\n{summary}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        order = ["absorb_v", "float_v", "recharge_v", "shutdown_v"]
        methods = {
            "absorb_v":   self._writer.set_absorb_voltage,
            "float_v":    self._writer.set_float_voltage,
            "recharge_v": self._writer.set_recharge_voltage,
            "shutdown_v": self._writer.set_shutdown_voltage,
        }
        all_ok = True
        for key in order:
            result = methods[key](vals[key], self._current_mode)
            self.voltage_controls[key]["badge"].set_result(result)
            if not result.success:
                all_ok = False
                self._log(f"Error {key}: {result.message}", "#e74c3c")
            else:
                self._log(f"{key} → {vals[key]:.1f}V  ACK", "#27ae60")

        msg = "Todos los voltajes aplicados correctamente" if all_ok else \
              "Algunos voltajes fallaron — revisa el log"
        self.lbl_apply_all_result.setText(msg)
        self.lbl_apply_all_result.setStyleSheet(
            f"font-size:12px; color:{'#27ae60' if all_ok else '#e74c3c'};"
        )

    def _on_set_buzzer(self, enable: bool):
        if not self._writer:
            return
        self.badge_buzzer.reset()
        result = self._writer.set_buzzer(enable, self._current_mode)
        self.badge_buzzer.set_result(result)
        state = "activado" if enable else "desactivado"
        if result.success:
            self._log(f"Buzzer {state}  ACK ({result.latency_ms:.0f}ms)", "#27ae60")
        else:
            self._log(f"Error buzzer: {result.message}", "#e74c3c")

    def _log(self, text: str, color: str = "#888"):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt_log.append(f'<span style="color:{color}">[{ts}] {text}</span>')
        self.txt_log.verticalScrollBar().setValue(
            self.txt_log.verticalScrollBar().maximum()
        )
