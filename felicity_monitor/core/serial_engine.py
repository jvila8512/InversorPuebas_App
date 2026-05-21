"""
Motor de comunicación RS232 para inversor Felicity.
Usa QThread de PyQt5 para no bloquear la UI.
"""

import time
import serial
import serial.tools.list_ports
from typing import Optional, Callable
from PyQt5.QtCore import QThread, pyqtSignal, QMutex

from core.protocol import (
    build_command, validate_response,
    parse_qpigs, parse_qpiri, parse_qmod, parse_qpiws,
    InverterStatus, QPIGSData
)


# ──────────────────────────────────────────────
# Configuraciones de puerto disponibles
# ──────────────────────────────────────────────

BAUD_RATES    = [2400, 4800, 9600, 19200, 38400]
DATA_BITS     = [serial.EIGHTBITS, serial.SEVENBITS]
STOP_BITS_OPT = [serial.STOPBITS_ONE, serial.STOPBITS_TWO]
PARITIES      = {
    'None': serial.PARITY_NONE,
    'Even': serial.PARITY_EVEN,
    'Odd':  serial.PARITY_ODD,
}

DEFAULT_CONFIG = {
    'baudrate':  2400,
    'bytesize':  serial.EIGHTBITS,
    'parity':    serial.PARITY_NONE,
    'stopbits':  serial.STOPBITS_ONE,
    'timeout':   2.0,
}


def list_serial_ports() -> list[str]:
    """Devuelve lista de puertos COM disponibles."""
    return [p.device for p in serial.tools.list_ports.comports()]


# ──────────────────────────────────────────────
# Clase de conexión serial base
# ──────────────────────────────────────────────

class SerialConnection:
    """Wrapper sobre pyserial con retry y logging."""

    def __init__(self, port: str, config: dict):
        self.port   = port
        self.config = {**DEFAULT_CONFIG, **config}
        self._ser: Optional[serial.Serial] = None
        self._mutex = QMutex()

    def connect(self) -> tuple[bool, str]:
        """Abre el puerto. Retorna (éxito, mensaje)."""
        try:
            self._ser = serial.Serial(
                port     = self.port,
                baudrate = self.config['baudrate'],
                bytesize = self.config['bytesize'],
                parity   = self.config['parity'],
                stopbits = self.config['stopbits'],
                timeout  = self.config['timeout'],
            )
            return True, f"Conectado a {self.port} @ {self.config['baudrate']} baud"
        except serial.SerialException as e:
            return False, str(e)

    def disconnect(self):
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def send_command(self, cmd: str) -> tuple[Optional[str], float]:
        """
        Envía un comando y espera respuesta.
        Retorna (payload, latencia_ms). payload=None si falla.
        """
        if not self.is_open:
            return None, 0.0

        self._mutex.lock()
        try:
            frame = build_command(cmd)
            self._ser.reset_input_buffer()
            t0 = time.perf_counter()
            self._ser.write(frame)

            # Leer hasta CR o timeout
            response = b''
            while True:
                chunk = self._ser.read(64)
                if not chunk:
                    break
                response += chunk
                if b'\r' in response:
                    break

            latency_ms = (time.perf_counter() - t0) * 1000

            if not response:
                return None, latency_ms

            payload = validate_response(response)
            return payload, latency_ms

        except serial.SerialException:
            return None, 0.0
        finally:
            self._mutex.unlock()


# ──────────────────────────────────────────────
# Hilo de monitoreo en tiempo real
# ──────────────────────────────────────────────

class MonitorThread(QThread):
    """
    Hilo que envía QPIGS cada `interval` segundos
    y emite señales con los datos nuevos.
    """
    data_received  = pyqtSignal(object)   # QPIGSData
    error_occurred = pyqtSignal(str)
    latency_update = pyqtSignal(float)    # ms
    status_changed = pyqtSignal(str)      # modo QMOD

    def __init__(self, conn: SerialConnection, interval: float = 3.0):
        super().__init__()
        self.conn     = conn
        self.interval = interval
        self._running = False
        self._full_poll_counter = 0

    def run(self):
        self._running = True
        while self._running:
            self._poll()
            time.sleep(self.interval)

    def stop(self):
        self._running = False
        self.wait(3000)

    def _poll(self):
        # QPIGS cada ciclo
        payload, lat = self.conn.send_command("QPIGS")
        self.latency_update.emit(round(lat, 1))

        if payload is None:
            self.error_occurred.emit("Sin respuesta del inversor (timeout)")
            return

        data = parse_qpigs(payload)
        if data:
            self.data_received.emit(data)
        else:
            self.error_occurred.emit(f"Respuesta inválida: {payload[:40]}")

        # QMOD cada 5 ciclos
        self._full_poll_counter += 1
        if self._full_poll_counter % 5 == 0:
            mod_payload, _ = self.conn.send_command("QMOD")
            if mod_payload:
                self.status_changed.emit(parse_qmod(mod_payload))


# ──────────────────────────────────────────────
# Hilo de auto-detección de parámetros
# ──────────────────────────────────────────────

class AutoDetectThread(QThread):
    """
    Prueba combinaciones de baud rate y configuración
    hasta encontrar una que responda correctamente.
    """
    progress   = pyqtSignal(str)
    found      = pyqtSignal(str, dict)   # (puerto, config)
    not_found  = pyqtSignal()

    def __init__(self, port: str):
        super().__init__()
        self.port = port

    def run(self):
        configs_to_try = [
            {'baudrate': 2400,  'parity': serial.PARITY_NONE},
            {'baudrate': 9600,  'parity': serial.PARITY_NONE},
            {'baudrate': 19200, 'parity': serial.PARITY_NONE},
            {'baudrate': 2400,  'parity': serial.PARITY_EVEN},
            {'baudrate': 9600,  'parity': serial.PARITY_EVEN},
        ]

        for cfg in configs_to_try:
            full_cfg = {**DEFAULT_CONFIG, **cfg}
            self.progress.emit(
                f"Probando {self.port} @ {cfg['baudrate']} baud "
                f"parity={cfg['parity']} ..."
            )
            conn = SerialConnection(self.port, full_cfg)
            ok, msg = conn.connect()
            if not ok:
                self.progress.emit(f"  Error: {msg}")
                continue

            payload, lat = conn.send_command("QPI")
            conn.disconnect()

            if payload and "PI30" in payload:
                self.progress.emit(
                    f"  ENCONTRADO: PI30 @ {cfg['baudrate']} baud  [{lat:.0f} ms]"
                )
                self.found.emit(self.port, full_cfg)
                return

            time.sleep(0.3)

        self.not_found.emit()
