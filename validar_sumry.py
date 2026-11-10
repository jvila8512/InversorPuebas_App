#!/usr/bin/env python3
"""
validar_sumry.py — Sonda de validacion PI30 (ASCII) para inversores Sumry
=========================================================================
Valida contra el equipo real:
  1. El cableado (RS232 o RS485)
  2. Los parametros de linea (baud, paridad)
  3. La comunicacion PI30 (comandos QPI, QPIRI, QPIGS, QMOD, QPIWS)
  4. La coherencia de los valores devueltos

Sumry usa el protocolo ASCII PI30 (comandos de texto), NO registros Modbus.
Por eso esta sonda es distinta a validar_must.py.

Soporta dos transportes:
  - RS232 directo:      --port COM3
  - RS485 via gateway:  --host 192.168.1.50 --tcp-port 5020
    (el gateway debe estar en modo TRANSPARENTE / passthrough: PI30 es texto,
     noModbus TCP, asi que no corresponde framing MBAP)
  - RS485 via USB:      --port COM4 --iface rs485

Uso:
    # RS232
    python validar_sumry.py --port COM3 --iface rs232

    # RS485 con gateway transparente
    python validar_sumry.py --host 192.168.1.50 --tcp-port 5020 --iface rs485

    # RS485 con adaptador USB
    python validar_sumry.py --port COM4 --iface rs485

Autor: InversorApp
Fecha: 2026-11-10
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from typing import Dict, List, Optional, Tuple

try:
    import serial
except ImportError:
    serial = None


# ══════════════════════════════════════════════════════════════════════════════
# PROTOCOLO PI30
# ══════════════════════════════════════════════════════════════════════════════

def crc_pi30(data: str) -> bytes:
    """CRC de 16 bits del protocolo PI30."""
    crc = 0
    for char in data:
        crc ^= ord(char)
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    lo, hi = crc & 0xFF, (crc >> 8) & 0xFF
    for reserved in (0x28, 0x0D, 0x0A):
        if lo == reserved:
            lo += 1
        if hi == reserved:
            hi += 1
    return bytes([lo, hi])


def build_command(cmd: str) -> bytes:
    """Trama completa: ( + CMD + CRC + CR"""
    return f"({cmd}".encode() + crc_pi30(cmd) + b'\r'


def validate_response(raw: bytes) -> Optional[str]:
    """Valida la trama y devuelve el payload limpio, o None."""
    if len(raw) < 4 or raw[0:1] != b'(':
        return None
    return raw[1:-3].decode('ascii', errors='replace').strip()


QMOD_MODES = {
    'P': 'Power On', 'S': 'Standby', 'L': 'Line (red)', 'B': 'Bateria',
    'F': 'Falla', 'H': 'Power Saving', 'Y': 'Bypass', 'E': 'ECO',
    'C': 'Charge', 'D': 'Shutdown',
}

QPIWS_BITS = [
    "Fallo del inversor", "Bus over", "Bus under", "Bus soft fail",
    "Line fail", "OPV short", "Voltaje inversor bajo", "Voltaje inversor alto",
    "Sobre temperatura", "Fan bloqueado", "Voltaje bateria alto",
    "Bateria baja", "Reservado", "Battery under shutdown", "Battery derating",
    "Sobrecarga", "Fallo EEPROM", "Sobre corriente inversor",
    "Inversor soft fail", "Self test fail", "OP DC voltaje over", "Bat open",
    "Current sensor fail", "Battery short", "Power limit", "PV voltaje alto",
    "MPPT overload fault", "MPPT overload warning",
    "Bateria muy baja para cargar", "Reservado", "Reservado", "Reservado",
]


# ══════════════════════════════════════════════════════════════════════════════
# PARSEOS
# ══════════════════════════════════════════════════════════════════════════════

def parse_qpigs(payload: str) -> Optional[Dict[str, float]]:
    """QPIGS — estado general en tiempo real."""
    try:
        p = payload.split()
        if len(p) < 17:
            return None
        return {
            "grid_voltage":     float(p[0]),
            "grid_frequency":   float(p[1]),
            "output_voltage":   float(p[2]),
            "output_frequency": float(p[3]),
            "output_va":        float(p[4]),
            "output_watts":     float(p[5]),
            "load_percent":     float(p[6]),
            "bus_voltage":      float(p[7]),
            "battery_voltage":  float(p[8]),
            "battery_charge_a": float(p[9]),
            "battery_capacity": float(p[10]),
            "heatsink_temp":    float(p[11]),
            "pv_current":       float(p[12]),
            "pv_voltage":       float(p[13]),
            "pv_power":         float(p[19]) if len(p) > 19 else None,
        }
    except (ValueError, IndexError):
        return None


def parse_qpiri(payload: str) -> Optional[Dict[str, float]]:
    """QPIRI — parametros nominales y de configuracion."""
    try:
        p = payload.split()
        if len(p) < 16:
            return None
        return {
            "grid_rating_v":        float(p[0]),
            "ac_output_v":          float(p[2]),
            "ac_output_hz":         float(p[3]),
            "ac_output_a":          float(p[4]),
            "ac_output_va":         float(p[5]),
            "ac_output_w":          float(p[6]),
            "battery_rating_v":     float(p[7]),
            "battery_float_v":      float(p[10]),
            "battery_absorb_v":     float(p[9]),
            "max_charge_current":   float(p[11]),
            "output_source_prio":   float(p[14]),
            "charge_source_prio":   float(p[15]),
        }
    except (ValueError, IndexError):
        return None


def parse_qmod(payload: str) -> str:
    code = payload.strip()
    return QMOD_MODES.get(code, f"Desconocido ({code})")


def parse_qpiws(payload: str) -> List[str]:
    activos = []
    for i, bit in enumerate(payload.strip()):
        if bit == '1' and i < len(QPIWS_BITS):
            activos.append(QPIWS_BITS[i])
    return activos


# ══════════════════════════════════════════════════════════════════════════════
# TRANSPORTES
# ══════════════════════════════════════════════════════════════════════════════

class SerialTransport:
    """RS232 directo o RS485 mediante adaptador USB (COM)."""

    def __init__(self, port: str, baudrate: int = 2400, parity: str = "N",
                 stopbits: int = 1, timeout: float = 2.0):
        if serial is None:
            raise RuntimeError("pyserial no esta instalado: pip install pyserial")
        self.port = port
        self.baudrate = baudrate
        self.parity = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN,
                       "O": serial.PARITY_ODD}.get(parity, serial.PARITY_NONE)
        self.stopbits = stopbits
        self.timeout = timeout
        self._ser = None

    def connect(self) -> Tuple[bool, str]:
        try:
            self._ser = serial.Serial(port=self.port, baudrate=self.baudrate,
                                      parity=self.parity, stopbits=self.stopbits,
                                      bytesize=8, timeout=self.timeout)
            return True, f"Conectado a {self.port} @ {self.baudrate} baud"
        except Exception as e:
            return False, f"Error abriendo {self.port}: {e}"

    def disconnect(self):
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def send_command(self, cmd: str) -> Tuple[Optional[str], float]:
        """Envia un comando PI30 y devuelve (payload, latencia_ms)."""
        try:
            self._ser.reset_input_buffer()
            t0 = time.perf_counter()
            self._ser.write(build_command(cmd))
            raw = self._recv_line()
            latency = (time.perf_counter() - t0) * 1000
        except Exception:
            return None, 0.0
        if raw is None:
            return None, latency
        return validate_response(raw), latency

    def _recv_line(self) -> Optional[bytes]:
        buffer = bytearray()
        deadline = time.perf_counter() + self.timeout
        while time.perf_counter() < deadline:
            chunk = self._ser.read(64)
            if chunk:
                buffer.extend(chunk)
                if b'\r' in buffer:
                    break
            elif buffer:
                break
        return bytes(buffer) if buffer else None


class TcpTransport:
    """RS485 (o RS232) via gateway TCP en modo TRANSPARENTE."""

    def __init__(self, host: str, port: int = 5020, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None

    def connect(self) -> Tuple[bool, str]:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.host, self.port))
            return True, f"Conectado a {self.host}:{self.port} (transparente)"
        except Exception as e:
            return False, f"Error conectando a {self.host}:{self.port}: {e}"

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    def send_command(self, cmd: str) -> Tuple[Optional[str], float]:
        try:
            t0 = time.perf_counter()
            self._sock.sendall(build_command(cmd))
            raw = self._recv_line()
            latency = (time.perf_counter() - t0) * 1000
        except Exception:
            return None, 0.0
        if raw is None:
            return None, latency
        return validate_response(raw), latency

    def _recv_line(self) -> Optional[bytes]:
        buffer = bytearray()
        deadline = time.perf_counter() + self.timeout
        while time.perf_counter() < deadline:
            try:
                chunk = self._sock.recv(256)
            except socket.timeout:
                break
            except OSError:
                return None
            if not chunk:
                return None
            buffer.extend(chunk)
            if b'\r' in buffer:
                break
        return bytes(buffer) if buffer else None


# ══════════════════════════════════════════════════════════════════════════════
# REPORTE
# ══════════════════════════════════════════════════════════════════════════════

def print_qpigs(data: Dict[str, float]):
    print()
    print("  QPIGS — Estado en tiempo real")
    print("  " + "-" * 52)
    filas = [
        ("Voltaje de red",        data["grid_voltage"],     "V"),
        ("Frecuencia de red",     data["grid_frequency"],   "Hz"),
        ("Voltaje de salida",     data["output_voltage"],   "V"),
        ("Frecuencia de salida",  data["output_frequency"], "Hz"),
        ("Potencia aparente",     data["output_va"],        "VA"),
        ("Potencia activa",       data["output_watts"],     "W"),
        ("Carga",                 data["load_percent"],     "%"),
        ("Voltaje BUS",           data["bus_voltage"],      "V"),
        ("Voltaje bateria",       data["battery_voltage"],  "V"),
        ("Corriente de carga",    data["battery_charge_a"], "A"),
        ("Capacidad (SOC)",       data["battery_capacity"], "%"),
        ("Temperatura disipador", data["heatsink_temp"],    "°C"),
        ("Corriente PV",          data["pv_current"],       "A"),
        ("Voltaje PV",            data["pv_voltage"],       "V"),
    ]
    if data.get("pv_power") is not None:
        filas.append(("Potencia PV", data["pv_power"], "W"))

    for label, value, unit in filas:
        print(f"    {label:<24}{value:>10.1f} {unit}")


def print_qpiri(data: Dict[str, float]):
    print()
    print("  QPIRI — Parametros nominales y de configuracion")
    print("  " + "-" * 52)
    prio_salida = {0: "Utility First", 1: "Solar First", 2: "SBU"}
    prio_carga = {0: "Utility Only", 1: "Solar First",
                  2: "Solar + Utility", 3: "Solar Only"}
    filas = [
        ("Voltaje nominal red",     data["grid_rating_v"],      "V"),
        ("Voltaje salida",          data["ac_output_v"],        "V"),
        ("Frecuencia salida",       data["ac_output_hz"],       "Hz"),
        ("Corriente salida",        data["ac_output_a"],        "A"),
        ("Potencia aparente",       data["ac_output_va"],       "VA"),
        ("Potencia activa",         data["ac_output_w"],        "W"),
        ("Voltaje nominal bateria", data["battery_rating_v"],   "V"),
        ("Voltaje flotacion",       data["battery_float_v"],    "V"),
        ("Voltaje absorcion",       data["battery_absorb_v"],   "V"),
        ("Corriente max carga",     data["max_charge_current"], "A"),
    ]
    for label, value, unit in filas:
        print(f"    {label:<24}{value:>10.1f} {unit}")

    print(f"    {'Prioridad salida':<24}{prio_salida.get(int(data['output_source_prio']), '?'):>10}")
    print(f"    {'Prioridad carga':<24}{prio_carga.get(int(data['charge_source_prio']), '?'):>10}")


def verdict(data: Dict[str, float]) -> List[str]:
    """Chequeos de coherencia fisica."""
    notas = []

    def check(label, value, lo, hi, unit):
        ok = lo <= value <= hi
        notas.append(f"  [{'OK ' if ok else '?? '}] {label} {value:.1f} {unit} "
                     f"(esperado {lo}-{hi})")

    check("Voltaje de red", data["grid_voltage"], 120, 300, "V")
    check("Frecuencia de red", data["grid_frequency"], 45, 65, "Hz")
    check("Voltaje de salida", data["output_voltage"], 120, 300, "V")
    check("Voltaje bateria", data["battery_voltage"], 20, 70, "V")
    check("Carga", data["load_percent"], 0, 100, "%")
    check("SOC", data["battery_capacity"], 0, 100, "%")
    check("Temperatura", data["heatsink_temp"], 0, 100, "°C")
    if data.get("pv_power") is not None:
        check("Potencia PV", data["pv_power"], 0, 100000, "W")

    return notas


# ══════════════════════════════════════════════════════════════════════════════
# COMANDO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def run(transport, comandos: List[str], timeout: float = 3.0):
    """Ejecuta la lista de comandos PI30 e imprime los resultados."""
    resultados: Dict[str, Optional[str]] = {}

    for cmd in comandos:
        payload, latency = transport.send_command(cmd)
        resultados[cmd] = payload
        estado = "OK" if payload else "SIN RESPUESTA"
        print(f"  {cmd:<8} {estado:<14} [{latency:.0f} ms]  {payload or ''}")

    # Interpretacion
    qpigs = parse_qpigs(resultados.get("QPIGS", "") or "")
    qpiri = parse_qpiri(resultados.get("QPIRI", "") or "")

    if qpigs:
        print_qpigs(qpigs)
        print()
        print("  VEREDICTO QPIGS")
        print("  " + "-" * 52)
        for nota in verdict(qpigs):
            print(nota)
    else:
        print("\n  No se pudo interpretar QPIGS.")

    if qpiri:
        print_qpiri(qpiri)
    else:
        print("\n  No se pudo interpretar QPIRI.")

    qmod = resultados.get("QMOD")
    if qmod:
        print(f"\n  Modo de operacion (QMOD): {parse_qmod(qmod)}")

    qpiws = resultados.get("QPIWS")
    if qpiws:
        activos = parse_qpiws(qpiws)
        print(f"\n  Alertas (QPIWS): {len(activos)} activas")
        for a in activos:
            print(f"    - {a}")
        if not activos:
            print("    (ninguna)")

    qpi = resultados.get("QPI")
    if qpi:
        print(f"\n  Protocolo (QPI): {qpi}")

    print()
    print("  Compare estos valores con la pantalla del inversor.")
    print()


def parse_int(text: str) -> int:
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Sonda de validacion PI30 (ASCII) para inversores Sumry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    grupo_transporte = p.add_argument_group("transporte")
    grupo_transporte.add_argument("--port", help="Puerto serie (RS232 o USB-RS485)")
    grupo_transporte.add_argument("--host", help="IP del gateway TCP (modo transparente)")
    grupo_transporte.add_argument("--tcp-port", type=int, default=5020,
                                  help="Puerto TCP del gateway (defecto 5020)")
    grupo_transporte.add_argument("--iface", choices=("rs232", "rs485"),
                                  default="rs485")

    grupo_linea = p.add_argument_group("linea serie")
    grupo_linea.add_argument("--baud", type=int, default=2400)
    grupo_linea.add_argument("--parity", default="N", choices=("N", "E", "O"))
    grupo_linea.add_argument("--timeout", type=float, default=2.0)

    p.add_argument("--commands", default="QPI,QPIRI,QPIGS,QMOD,QPIWS",
                   help="Comandos a ejecutar, separados por coma")

    args = p.parse_args(argv)

    if args.host:
        transport = TcpTransport(args.host, args.tcp_port, args.timeout)
    elif args.port:
        transport = SerialTransport(args.port, args.baud, args.parity,
                                    timeout=args.timeout)
    else:
        p.error("Especifica --port (serie) o --host (gateway TCP)")

    print(f"  Interfaz: {args.iface.upper()}")
    print("  Protocolo: PI30 (ASCII)")
    if args.iface == "rs485":
        print("  Cableado RS485: A=D+ / B=D- / GND, terminacion 120 ohm.")

    ok, msg = transport.connect()
    print(f"  {msg}")
    if not ok:
        return 1

    try:
        comandos = [c.strip() for c in args.commands.split(",") if c.strip()]
        run(transport, comandos, args.timeout)
    finally:
        transport.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
