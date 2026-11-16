#!/usr/bin/env python3
"""
ver_poll_3inversores.py — Lee y guarda valores principales de 3 inversores Felicity
====================================================================================
Se conecta al bridge RS485→TCP (por defecto 192.168.1.10:502), consulta los
inversores 1, 2 y 3 por separado (Modbus RTU, FC03) y guarda:

  - felicity_latest.json   (última lectura, legible)
  - felicity_history.csv   (histórico, se va añadiendo)

Modos:
  (por defecto)  Bucle infinito, un ciclo cada --interval segundos (def: 10)
  --once         Un solo ciclo y sale

Uso:
  python ver_poll_3inversores.py
  python ver_poll_3inversores.py --host 192.168.1.10 --interval 5
  python ver_poll_3inversores.py --once
  python ver_poll_3inversores.py --slaves 1,2,3 -v

Solo usa la librería estándar de Python 3.7+.

Autor: InversorApp
Fecha: 2026-11-13
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ══════════════════════════════════════════════════════════════════════════════
# CRC-16 / MODBUS
# ══════════════════════════════════════════════════════════════════════════════


def calculate_crc(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def verify_crc(frame: bytes) -> bool:
    return len(frame) >= 3 and calculate_crc(frame[:-2]) == frame[-2:]


def hexs(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE REGISTROS (Felicity IVGM-8K)
# ══════════════════════════════════════════════════════════════════════════════

# Bloques a leer por inversor (dirección, cantidad)
BLOCK_STATUS    = (0x1100, 11)   # WorkMode, warnings, faults
BLOCK_TELEMETRY = (0x1118, 64)   # 0x1118..0x1157: PV, bat, AC volts, temps
BLOCK_FREQ_PWR  = (0x116C, 15)   # 0x116C..0x117A: frecuencias y potencias fase
BLOCK_IDENTITY  = (0x2140, 4)    # 0x2140..0x2143: paralelo, Modbus ID, potencia

# Definición de campos: dirección → (nombre, escala, signed, unidad)
FIELDS: Dict[int, Tuple[str, float, bool, str]] = {
    # --- Status ---
    0x1100: ("work_mode",             1.0,  False, ""),
    0x1109: ("warn_code",             1.0,  False, ""),
    0x110A: ("fault_code",            1.0,  False, ""),

    # --- PV ---
    0x1118: ("pv1_voltage",           0.1,  False, "V"),
    0x1119: ("pv2_voltage",           0.1,  False, "V"),
    0x111C: ("pv1_current",           0.1,  True,  "A"),
    0x111D: ("pv2_current",           0.1,  True,  "A"),
    0x1128: ("pv1_power",             1.0,  True,  "W"),
    0x1129: ("pv2_power",             1.0,  True,  "W"),

    # --- Batería ---
    0x112C: ("battery_voltage",       0.1,  False, "V"),
    0x1130: ("battery_current",       0.1,  True,  "A"),
    0x1131: ("battery_power",         1.0,  True,  "W"),
    0x1138: ("battery_soc",           0.1,  False, "%"),

    # --- Salida AC ---
    0x113E: ("output_frequency",      0.01, False, "Hz"),
    0x113F: ("ac_voltage_a",          0.1,  False, "V"),
    0x1140: ("ac_voltage_b",          0.1,  False, "V"),

    # --- Temperaturas ---
    0x1144: ("temp_boost",            1.0,  True,  "°C"),
    0x1145: ("temp_inverter",         1.0,  True,  "°C"),
    0x1146: ("temp_environment",      1.0,  True,  "°C"),

    # --- Grid / Inverter / Load (voltajes) ---
    0x1150: ("grid_a_voltage",        0.1,  False, "V"),
    0x1151: ("grid_b_voltage",        0.1,  False, "V"),
    0x1153: ("inverter_a_voltage",    0.1,  False, "V"),
    0x1154: ("inverter_b_voltage",    0.1,  False, "V"),
    0x1156: ("load_a_voltage",        0.1,  False, "V"),
    0x1157: ("load_b_voltage",        0.1,  False, "V"),

    # --- Cargas ---
    0x1120: ("load_a_power",          1.0,  True,  "W"),
    0x1121: ("load_b_power",          1.0,  True,  "W"),

    # --- Frecuencias extra ---
    0x116E: ("inverter_frequency",    0.01, False, "Hz"),
    0x116F: ("load_frequency",        0.01, False, "Hz"),

    # --- Potencias por fase (kW, ×0.01) ---
    0x1173: ("grid_a_phase_power",    0.01, True,  "kW"),
    0x1174: ("grid_b_phase_power",    0.01, True,  "kW"),
    0x1176: ("inverter_a_phase_power",0.01, True,  "kW"),
    0x1177: ("inverter_b_phase_power",0.01, True,  "kW"),
    0x1179: ("load_a_phase_power",    0.01, True,  "kW"),
    0x117A: ("load_b_phase_power",    0.01, True,  "kW"),
}

# Identidad / paralelo
IDENTITY_FIELDS: Dict[int, Tuple[str, float, bool, str]] = {
    0x2140: ("parallel_count",        1.0,  False, ""),
    0x2141: ("parallel_address",      1.0,  False, ""),
    0x2142: ("modbus_id_register",    1.0,  False, ""),
    0x2143: ("rated_power",           1.0,  False, "W"),
}

NA_VALUE = 0xFFFE  # "No configurado / no disponible"


# ══════════════════════════════════════════════════════════════════════════════
# TRANSPORTE MODBUS RTU over TCP
# ══════════════════════════════════════════════════════════════════════════════


class ModbusRtuTcp:
    """Cliente Modbus RTU sobre TCP (bridge transparente)."""

    INTER_BYTE_TIMEOUT = 0.2

    def __init__(self, host: str, port: int = 502, timeout: float = 2.0,
                 verbose: bool = False):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.verbose = verbose
        self.sock: Optional[socket.socket] = None

    def connect(self) -> Tuple[bool, str]:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.host, self.port))
            try:
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            return True, f"Conectado a {self.host}:{self.port}"
        except OSError as e:
            self.sock = None
            return False, f"Error de conexión: {e}"

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    @property
    def is_open(self) -> bool:
        return self.sock is not None

    def drain(self):
        """Vacía bytes residuales (evita basura del touchscreen)."""
        if self.sock is None:
            return
        try:
            self.sock.setblocking(False)
            while True:
                try:
                    if not self.sock.recv(256):
                        break
                except (socket.timeout, BlockingIOError):
                    break
        except OSError:
            pass
        finally:
            try:
                self.sock.setblocking(True)
            except OSError:
                pass

    def _recv(self, expected: int) -> Optional[bytes]:
        if self.sock is None:
            return None
        orig = self.sock.gettimeout()
        buf = bytearray()
        try:
            self.sock.settimeout(self.timeout)
            try:
                first = self.sock.recv(min(expected, 256))
            except socket.timeout:
                return None
            if not first:
                return None
            buf.extend(first)
            self.sock.settimeout(self.INTER_BYTE_TIMEOUT)
            while len(buf) < expected:
                try:
                    chunk = self.sock.recv(min(expected - len(buf), 256))
                except socket.timeout:
                    break
                if not chunk:
                    break
                buf.extend(chunk)
        finally:
            try:
                self.sock.settimeout(orig)
            except OSError:
                pass
        return bytes(buf) if buf else None

    def read_registers(self, slave_id: int, address: int,
                       count: int, retries: int = 1) -> Optional[List[int]]:
        """Lee un bloque de holding registers. Devuelve lista de ints o None."""
        if self.sock is None:
            return None

        payload = bytes([slave_id, 0x03,
                         (address >> 8) & 0xFF, address & 0xFF,
                         (count >> 8) & 0xFF, count & 0xFF])
        frame = payload + calculate_crc(payload)
        expected = 3 + count * 2 + 2

        for _ in range(retries + 1):
            self.drain()
            try:
                self.sock.sendall(frame)
                rx = self._recv(expected)
            except OSError:
                continue
            if self.verbose:
                print(f"      TX {hexs(frame)}")
                print(f"      RX {hexs(rx) if rx else '(nada)'}")
            if not rx or len(rx) < 5:
                continue
            if rx[0] != slave_id or not verify_crc(rx):
                continue
            if rx[1] & 0x80:
                # Excepción Modbus
                if self.verbose:
                    print(f"      Excepción Modbus 0x{rx[2]:02X}")
                return None
            if rx[1] != 0x03:
                continue
            byte_count = rx[2]
            data = rx[3:3 + byte_count]
            if len(data) < count * 2:
                continue
            return [(data[i * 2] << 8) | data[i * 2 + 1] for i in range(count)]
        return None


# ══════════════════════════════════════════════════════════════════════════════
# DECODIFICACIÓN
# ══════════════════════════════════════════════════════════════════════════════


def to_signed(v: int) -> int:
    return v - 0x10000 if v >= 0x8000 else v


def decode_block(raw: List[Optional[int]], base: int,
                 fields: Dict[int, Tuple[str, float, bool, str]]) -> Dict[str, Optional[float]]:
    """Decodifica un bloque crudo a un dict {nombre: valor_real|null}."""
    out: Dict[str, Optional[float]] = {}
    for addr, (name, scale, signed, _unit) in fields.items():
        idx = addr - base
        if idx < 0 or idx >= len(raw):
            continue
        v = raw[idx]
        if v is None or v == NA_VALUE:
            out[name] = None
            continue
        iv = to_signed(v) if signed else v
        val = iv * scale
        # Redondeo según escala
        if scale == 1.0:
            out[name] = int(val)
        elif scale == 0.1:
            out[name] = round(val, 1)
        else:
            out[name] = round(val, 2)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# POLLING DE UN INVERSOR
# ══════════════════════════════════════════════════════════════════════════════


def poll_inverter(probe: ModbusRtuTcp, slave_id: int) -> Dict:
    """Lee todos los bloques de un inversor. Devuelve dict con todo."""
    result: Dict = {
        "modbus_id": slave_id,
        "status": "OFFLINE",
        "error": None,
        "data": {},
        "identity": {},
        "derived": {},
    }

    # 1) Identidad (rápido, detecta si responde)
    ident_raw = probe.read_registers(slave_id, BLOCK_IDENTITY[0], BLOCK_IDENTITY[1])
    if ident_raw is None:
        result["error"] = f"sin respuesta a ID {slave_id}"
        return result

    result["identity"] = decode_block(ident_raw, BLOCK_IDENTITY[0], IDENTITY_FIELDS)

    # 2) Status
    status_raw = probe.read_registers(slave_id, BLOCK_STATUS[0], BLOCK_STATUS[1])
    status_data = decode_block(status_raw, BLOCK_STATUS[0], FIELDS) if status_raw else {}

    # 3) Telemetría principal
    tel_raw = probe.read_registers(slave_id, BLOCK_TELEMETRY[0], BLOCK_TELEMETRY[1])
    if tel_raw is None:
        result["error"] = f"ID {slave_id} responde identidad pero falla telemetría"
        # Aun así devolvemos lo que tengamos
        result["data"] = status_data
        return result

    tel_data = decode_block(tel_raw, BLOCK_TELEMETRY[0], FIELDS)

    # 4) Frecuencias y potencias de fase
    freq_raw = probe.read_registers(slave_id, BLOCK_FREQ_PWR[0], BLOCK_FREQ_PWR[1])
    freq_data = decode_block(freq_raw, BLOCK_FREQ_PWR[0], FIELDS) if freq_raw else {}

    # Merge
    data = {**status_data, **tel_data, **freq_data}
    result["data"] = data
    result["status"] = "ONLINE"

    # 5) Campos derivados
    pv1w = data.get("pv1_power") or 0
    pv2w = data.get("pv2_power") or 0
    batw = data.get("battery_power")
    load_a = data.get("load_a_power") or 0
    load_b = data.get("load_b_power") or 0

    pv_total = pv1w + pv2w
    load_total = load_a + load_b

    charging = None
    source = None
    if batw is not None:
        charging = batw > 0
        if batw > 0:
            if pv_total >= batw:
                source = "PV"
            else:
                source = "MIXED"
        elif batw < 0:
            source = "DISCHARGING"
        else:
            source = "IDLE"

    result["derived"] = {
        "pv_total_power": pv_total,
        "load_total_power": load_total,
        "battery_charging": charging,
        "charge_source": source,
    }
    return result


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENCIA
# ══════════════════════════════════════════════════════════════════════════════

CSV_COLUMNS = [
    "timestamp", "inverter_id", "modbus_id",
    "parallel_count", "parallel_address", "modbus_id_register", "rated_power",
    "status", "error",
    # PV
    "pv1_voltage", "pv1_current", "pv1_power",
    "pv2_voltage", "pv2_current", "pv2_power",
    "pv_total_power",
    # Batería
    "battery_voltage", "battery_current", "battery_power",
    "battery_soc", "battery_charging", "charge_source",
    # AC
    "output_frequency", "ac_voltage_a", "ac_voltage_b",
    "grid_a_voltage", "grid_b_voltage",
    "inverter_a_voltage", "inverter_b_voltage",
    "load_a_voltage", "load_b_voltage",
    # Cargas
    "load_a_power", "load_b_power", "load_total_power",
    # Temperaturas
    "temp_boost", "temp_inverter", "temp_environment",
    # Status
    "work_mode", "warn_code", "fault_code",
]


def ensure_csv_header(csv_path: str):
    """Crea el CSV con cabecera si no existe."""
    if not os.path.exists(csv_path):
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerow(CSV_COLUMNS)


def save_csv_append(csv_path: str, timestamp: str, results: List[Dict]):
    """Añade una fila por inversor al CSV histórico."""
    ensure_csv_header(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for r in results:
            ident = r.get("identity", {}) or {}
            data = r.get("data", {}) or {}
            derived = r.get("derived", {}) or {}
            row = [
                timestamp,
                r["modbus_id"],
                r["modbus_id"],
                ident.get("parallel_count"),
                ident.get("parallel_address"),
                ident.get("modbus_id_register"),
                ident.get("rated_power"),
                r["status"],
                r.get("error") or "",
                data.get("pv1_voltage"),
                data.get("pv1_current"),
                data.get("pv1_power"),
                data.get("pv2_voltage"),
                data.get("pv2_current"),
                data.get("pv2_power"),
                derived.get("pv_total_power"),
                data.get("battery_voltage"),
                data.get("battery_current"),
                data.get("battery_power"),
                data.get("battery_soc"),
                derived.get("battery_charging"),
                derived.get("charge_source"),
                data.get("output_frequency"),
                data.get("ac_voltage_a"),
                data.get("ac_voltage_b"),
                data.get("grid_a_voltage"),
                data.get("grid_b_voltage"),
                data.get("inverter_a_voltage"),
                data.get("inverter_b_voltage"),
                data.get("load_a_voltage"),
                data.get("load_b_voltage"),
                data.get("load_a_power"),
                data.get("load_b_power"),
                derived.get("load_total_power"),
                data.get("temp_boost"),
                data.get("temp_inverter"),
                data.get("temp_environment"),
                data.get("work_mode"),
                data.get("warn_code"),
                data.get("fault_code"),
            ]
            w.writerow(row)


def save_json_latest(json_path: str, timestamp: str, host: str,
                     results: List[Dict]):
    """Sobrescribe el JSON con la última lectura."""
    doc = {
        "timestamp": timestamp,
        "host": host,
        "inverters": results,
    }
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False, default=str)


# ══════════════════════════════════════════════════════════════════════════════
# PRESENTACIÓN EN PANTALLA
# ══════════════════════════════════════════════════════════════════════════════


def fmt(val, width: int = 8, decimals: int = 1) -> str:
    if val is None:
        return "—".rjust(width)
    if isinstance(val, bool):
        return ("sí" if val else "no").rjust(width)
    if isinstance(val, (int, float)):
        return f"{val:>{width}.{decimals}f}"
    return str(val).rjust(width)


def print_cycle(timestamp: str, results: List[Dict]):
    """Imprime una tabla comparativa de los 3 inversores."""
    print()
    print("═" * 78)
    print(f"  CICLO {timestamp}")
    print("═" * 78)

    # Tabla resumen lado a lado
    print(f"  {'Campo':<22}", end="")
    for r in results:
        print(f"{'ID ' + str(r['modbus_id']):>16}", end="")
    print()
    print("  " + "-" * 74)

    def row(label: str, key: str, unit: str = "", decimals: int = 1):
        print(f"  {label:<22}", end="")
        for r in results:
            if r["status"] != "ONLINE":
                print(f"{'—':>16}", end="")
                continue
            v = r["data"].get(key)
            txt = fmt(v, 12, decimals)
            print(f"{txt + ' ' + unit:>16}", end="")
        print()

    def row_derived(label: str, key: str):
        print(f"  {label:<22}", end="")
        for r in results:
            if r["status"] != "ONLINE":
                print(f"{'—':>16}", end="")
                continue
            v = r["derived"].get(key)
            print(f"{fmt(v, 12, 1):>16}", end="")
        print()

    # Estado
    print(f"  {'Estado':<22}", end="")
    for r in results:
        st = "ONLINE" if r["status"] == "ONLINE" else "OFFLINE"
        print(f"{st:>16}", end="")
    print()

    # Identidad
    print(f"  {'Rol paralelo':<22}", end="")
    for r in results:
        v = r["identity"].get("parallel_address")
        txt = {1: "Master", 2: "Slave 2", 3: "Slave 3"}.get(v, str(v))
        print(f"{txt:>16}", end="")
    print()

    # PV
    row("PV1 Voltage", "pv1_voltage", "V")
    row("PV1 Current", "pv1_current", "A")
    row("PV1 Power", "pv1_power", "W", 0)
    row("PV2 Voltage", "pv2_voltage", "V")
    row("PV2 Power", "pv2_power", "W", 0)
    row_derived("PV Total", "pv_total_power")

    # Batería
    row("Battery Voltage", "battery_voltage", "V")
    row("Battery Current", "battery_current", "A")
    row("Battery Power", "battery_power", "W", 0)
    row("Battery SOC", "battery_soc", "%")
    row_derived("Cargando", "battery_charging")
    row_derived("Fuente", "charge_source")

    # AC
    row("Output Frequency", "output_frequency", "Hz", 2)
    row("AC Voltage Phase A", "ac_voltage_a", "V")
    row("AC Voltage Phase B", "ac_voltage_b", "V")

    # Cargas
    row("Load A", "load_a_power", "W", 0)
    row("Load B", "load_b_power", "W", 0)
    row_derived("Load Total", "load_total_power")

    # Temperaturas
    row("Temp Boost", "temp_boost", "°C", 0)
    row("Temp Inverter", "temp_inverter", "°C", 0)
    row("Temp Environment", "temp_environment", "°C", 0)

    # Status
    row("Work Mode", "work_mode", "", 0)
    row("Warn Code", "warn_code", "", 0)
    row("Fault Code", "fault_code", "", 0)

    print("═" * 78)

    # Avisos
    for r in results:
        if r["status"] != "ONLINE" and r.get("error"):
            print(f"  ⚠️  ID {r['modbus_id']}: {r['error']}")
    # Detectar IDs duplicados
    modbus_ids = [r["identity"].get("modbus_id_register")
                  for r in results
                  if r["status"] == "ONLINE"
                  and r["identity"].get("modbus_id_register") is not None]
    if len(modbus_ids) > 1 and len(set(modbus_ids)) < len(modbus_ids):
        print("  ⚠️  AVISO: varios inversores reportan el MISMO Modbus ID.")
        print("      Esto confirma el desajuste 0x2142. Corrige el Modbus ID")
        print("      en el menú de cada inversor (o escribe 0x2142) para que")
        print("      coincida con su 'Parallel Address' (1, 2, 3).")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# BUCLE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════


def run_cycle(probe: ModbusRtuTcp, slaves: List[int]) -> Tuple[str, List[Dict]]:
    """Ejecuta un ciclo completo de polling."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    results: List[Dict] = []
    for slave_id in slaves:
        r = poll_inverter(probe, slave_id)
        results.append(r)
        time.sleep(0.1)  # pequeña pausa entre inversores
    return timestamp, results


def parse_slaves(text: str) -> List[int]:
    out: List[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return sorted({x for x in out if 1 <= x <= 247})


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Lee y guarda los valores principales de 3 inversores Felicity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--host", default="192.168.1.10", help="IP del bridge TCP→RS485")
    parser.add_argument("--port", type=int, default=502, help="Puerto TCP (def: 502)")
    parser.add_argument("--slaves", default="1,2,3",
                        help="IDs Modbus a consultar (def: 1,2,3)")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="Segundos entre ciclos (def: 10)")
    parser.add_argument("--timeout", type=float, default=2.0,
                        help="Timeout de lectura en segundos (def: 2.0)")
    parser.add_argument("--once", action="store_true",
                        help="Un solo ciclo y sale")
    parser.add_argument("--json", default="felicity_latest.json",
                        help="Archivo JSON de última lectura (def: felicity_latest.json)")
    parser.add_argument("--csv", default="felicity_history.csv",
                        help="Archivo CSV de histórico (def: felicity_history.csv)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Mostrar tramas hex TX/RX")
    args = parser.parse_args(argv)

    slaves = parse_slaves(args.slaves)
    if not slaves:
        print("  Error: --slaves no contiene IDs válidos.")
        return 1

    print()
    print("  ═══════════════════════════════════════════════════════════")
    print("  POLLING MULTI-INVERSOR FELICITY IVGM-8K")
    print("  ═══════════════════════════════════════════════════════════")
    print(f"  Bridge: {args.host}:{args.port}  (Modbus RTU over TCP)")
    print(f"  Inversores a consultar: {slaves}")
    print(f"  Intervalo: {args.interval}s" + (" (modo --once)" if args.once else ""))
    print(f"  JSON: {args.json}")
    print(f"  CSV:  {args.csv}")

    probe = ModbusRtuTcp(args.host, args.port, args.timeout, args.verbose)
    ok, msg = probe.connect()
    print(f"\n  {msg}")
    if not ok:
        print("  Revise la IP/puerto y que el bridge esté en la misma red.")
        return 1

    try:
        while True:
            ts, results = run_cycle(probe, slaves)
            print_cycle(ts, results)
            save_json_latest(args.json, ts, args.host, results)
            save_csv_append(args.csv, ts, results)

            if args.once:
                print(f"  Guardado: {args.json}  (última lectura)")
                print(f"  Guardado: {args.csv}  (histórico)\n")
                break

            # Pequeña espera con Ctrl+C amable
            try:
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\n  Interrumpido por el usuario.\n")
                break
    finally:
        probe.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())