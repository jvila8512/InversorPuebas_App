"""
write_commands.py — Comandos de escritura PI30 con validación y seguridad completa.
Todos los comandos pasan por validación antes de enviarse al inversor.
"""

from dataclasses import dataclass
from typing import Optional
from core.profiles import InverterProfile, OUTPUT_PRIORITIES, CHARGE_PRIORITIES


# ──────────────────────────────────────────────
# Resultado de un comando de escritura
# ──────────────────────────────────────────────

@dataclass
class WriteResult:
    success:   bool
    command:   str
    response:  str
    message:   str
    latency_ms: float = 0.0

    @property
    def is_ack(self) -> bool:
        return "ACK" in self.response if self.response else False


# ──────────────────────────────────────────────
# Modos en los que NO se permite escritura
# ──────────────────────────────────────────────

BLOCKED_MODES = {"Fault", "F"}


# ──────────────────────────────────────────────
# Validador central
# ──────────────────────────────────────────────

class WriteValidator:
    """
    Valida que un comando sea seguro de enviar
    dado el estado actual del inversor y el perfil activo.
    """

    def __init__(self, profile: InverterProfile):
        self.profile = profile

    def check_mode(self, current_mode: str) -> Optional[str]:
        """Retorna mensaje de error si el modo bloquea escritura, None si OK."""
        for blocked in BLOCKED_MODES:
            if blocked.lower() in current_mode.lower():
                return f"No se puede escribir en modo: {current_mode}. Resuelve el fallo primero."
        return None

    def validate_float_v(self, value: float) -> list[str]:
        errors = []
        r = self.profile.get_ranges()
        lo, hi, _ = r["float_v"]
        if not (lo <= value <= hi):
            errors.append(f"Flotación {value}V fuera de rango [{lo}–{hi}V]")
        if value >= self.profile.absorb_v:
            errors.append(f"Flotación ({value}V) debe ser menor que Absorción ({self.profile.absorb_v}V)")
        if value <= self.profile.recharge_v:
            errors.append(f"Flotación ({value}V) debe ser mayor que Recarga ({self.profile.recharge_v}V)")
        return errors

    def validate_absorb_v(self, value: float) -> list[str]:
        errors = []
        r = self.profile.get_ranges()
        lo, hi, _ = r["absorb_v"]
        if not (lo <= value <= hi):
            errors.append(f"Absorción {value}V fuera de rango [{lo}–{hi}V]")
        if value <= self.profile.float_v:
            errors.append(f"Absorción ({value}V) debe ser mayor que Flotación ({self.profile.float_v}V)")
        return errors

    def validate_recharge_v(self, value: float) -> list[str]:
        errors = []
        r = self.profile.get_ranges()
        lo, hi, _ = r["recharge_v"]
        if not (lo <= value <= hi):
            errors.append(f"Recarga {value}V fuera de rango [{lo}–{hi}V]")
        if value >= self.profile.float_v:
            errors.append(f"Recarga ({value}V) debe ser menor que Flotación ({self.profile.float_v}V)")
        if value <= self.profile.shutdown_v:
            errors.append(f"Recarga ({value}V) debe ser mayor que Shutdown ({self.profile.shutdown_v}V)")
        return errors

    def validate_shutdown_v(self, value: float) -> list[str]:
        errors = []
        r = self.profile.get_ranges()
        lo, hi, _ = r["shutdown_v"]
        if not (lo <= value <= hi):
            errors.append(f"Shutdown {value}V fuera de rango [{lo}–{hi}V]")
        if value >= self.profile.recharge_v:
            errors.append(f"Shutdown ({value}V) debe ser menor que Recarga ({self.profile.recharge_v}V)")
        return errors


# ──────────────────────────────────────────────
# Comandos de escritura
# ──────────────────────────────────────────────

class WriteCommands:
    """
    Ejecuta comandos de escritura al inversor con validación completa.
    Requiere una SerialConnection activa y un InverterProfile.
    """

    def __init__(self, connection, profile: InverterProfile):
        self.conn      = connection
        self.profile   = profile
        self.validator = WriteValidator(profile)

    def _send(self, cmd: str) -> WriteResult:
        """Envía el comando y retorna WriteResult."""
        if not self.conn or not self.conn.is_open:
            return WriteResult(False, cmd, "", "No hay conexión activa")

        payload, lat = self.conn.send_command(cmd)

        if payload is None:
            return WriteResult(False, cmd, "", "Sin respuesta del inversor (timeout)", lat)

        success = "ACK" in payload
        msg = "Comando aceptado por el inversor" if success else \
              f"Inversor rechazó el comando (NAK) — valor fuera de rango o no permitido ahora"

        return WriteResult(success, cmd, payload, msg, lat)

    # ── Control 1: Prioridad de salida ──────────

    def set_output_priority(self,
                             priority_label: str,
                             current_mode: str = "") -> WriteResult:
        """
        Cambia la prioridad de salida.
        priority_label: clave del dict OUTPUT_PRIORITIES
        """
        # Validar modo
        mode_err = self.validator.check_mode(current_mode)
        if mode_err:
            return WriteResult(False, "", "", mode_err)

        cmd = OUTPUT_PRIORITIES.get(priority_label)
        if not cmd:
            return WriteResult(False, "", "", f"Prioridad desconocida: {priority_label}")

        return self._send(cmd)

    # ── Control 2: Voltajes de batería ──────────

    def set_float_voltage(self, value: float, current_mode: str = "") -> WriteResult:
        mode_err = self.validator.check_mode(current_mode)
        if mode_err:
            return WriteResult(False, "", "", mode_err)

        errors = self.validator.validate_float_v(value)
        if errors:
            return WriteResult(False, "", "", " | ".join(errors))

        cmd = f"PBFT{value:.1f}"
        result = self._send(cmd)
        if result.success:
            self.profile.float_v = value
        return result

    def set_absorb_voltage(self, value: float, current_mode: str = "") -> WriteResult:
        mode_err = self.validator.check_mode(current_mode)
        if mode_err:
            return WriteResult(False, "", "", mode_err)

        errors = self.validator.validate_absorb_v(value)
        if errors:
            return WriteResult(False, "", "", " | ".join(errors))

        cmd = f"PCVV{value:.1f}"
        result = self._send(cmd)
        if result.success:
            self.profile.absorb_v = value
        return result

    def set_recharge_voltage(self, value: float, current_mode: str = "") -> WriteResult:
        mode_err = self.validator.check_mode(current_mode)
        if mode_err:
            return WriteResult(False, "", "", mode_err)

        errors = self.validator.validate_recharge_v(value)
        if errors:
            return WriteResult(False, "", "", " | ".join(errors))

        cmd = f"PBCV{value:.1f}"
        result = self._send(cmd)
        if result.success:
            self.profile.recharge_v = value
        return result

    def set_shutdown_voltage(self, value: float, current_mode: str = "") -> WriteResult:
        mode_err = self.validator.check_mode(current_mode)
        if mode_err:
            return WriteResult(False, "", "", mode_err)

        errors = self.validator.validate_shutdown_v(value)
        if errors:
            return WriteResult(False, "", "", " | ".join(errors))

        cmd = f"PSDV{value:.1f}"
        result = self._send(cmd)
        if result.success:
            self.profile.shutdown_v = value
        return result

    # ── Control 3: Buzzer ───────────────────────

    def set_buzzer(self, enable: bool, current_mode: str = "") -> WriteResult:
        """Activa o desactiva el buzzer del inversor."""
        mode_err = self.validator.check_mode(current_mode)
        if mode_err:
            return WriteResult(False, "", "", mode_err)

        cmd = "PEa" if enable else "PDa"
        return self._send(cmd)

    # ── Test de escritura (inocuo) ──────────────

    def test_write_capability(self) -> WriteResult:
        """
        Prueba si el inversor acepta escritura usando el buzzer.
        Es el test más inocuo posible — activa y desactiva inmediatamente.
        """
        r1 = self._send("PEa")
        if not r1.success:
            return WriteResult(False, "PEa", r1.response,
                               f"El inversor NO aceptó escritura: {r1.message}", r1.latency_ms)
        # Desactivar inmediatamente
        self._send("PDa")
        return WriteResult(True, "PEa/PDa", r1.response,
                           "Inversor ACEPTA escritura (ACK recibido)", r1.latency_ms)
