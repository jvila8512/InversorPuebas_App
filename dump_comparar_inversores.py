
#!/usr/bin/env python3
"""
dump_comparar_inversores.py — Volcado a CSV y comparación multi-marca
======================================================================
Herramienta para:
  1. Volcar registros Modbus de Felicity / MUST a CSV.
  2. Consultar SUMRY vía PI30 (ASCII) y volcar a CSV.
  3. Comparar los parámetros principales de las tres marcas en una tabla unificada.

Reutiliza la lógica de transporte TCP de verificar_rs485.py.

Uso:
    # Volcar Felicity a CSV
    python dump_comparar_inversores.py --brand felicity --host 192.168.1.50 --framer rtu --out felicity.csv

    # Volcar MUST a CSV
    python dump_comparar_inversores.py --brand must --host 192.168.1.50 --framer rtu --slave 4 --out must.csv

    # Volcar SUMRY (PI30) a CSV
    python dump_comparar_inversores.py --brand sumry --host 192.168.1.50 --port 8080 --out sumry.csv

    # Comparar los tres (requiere los CSV generados)
    python dump_comparar_inversores.py --compare felicity.csv must.csv sumry.csv --out comparacion.csv

Autor: InversorApp
Fecha: 2026-11-09
Version: 1.0
"""

from __future__ import annotations

import argparse
import csv
import json
import socket
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ══════════════════════════════════════════════════════════════════════════════
# CRC-16 MODBUS (reutilizado)
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
    if len(frame) < 3:
        return False
    return calculate_crc(frame[:-2]) == frame[-2:]


# ══════════════════════════════════════════════════════════════════════════════
# MAPAS DE REGISTROS UNIFICADOS
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FieldDef:
    address: int
    label: str
    canonical: str  # nombre unificado para comparación
    scale: float = 1.0
    signed: bool = False
    unit: str = ""


# ── FELICITY (IVGM 8K / Series RS485) ────────────────────────────────────────
# Fuente: documento "Inverter Communication Protocol - Series RS485" + wiki zeronest
# Nota: baudrate 9600, slave ID 1, formato 8N1 (confirmado por zeronest).
FELICITY_MAP: Dict[int, FieldDef] = {
    0x1100: FieldDef(0x1100, "WorkMode", "work_mode"),
    0x1109: FieldDef(0x1109, "Warn code", "warn_code"),
    0x110A: FieldDef(0x110A, "Fault code", "fault_code"),
    0x1118: FieldDef(0x1118, "PV1 voltage", "pv_voltage", 0.1, False, "V"),
    0x1119: FieldDef(0x1119, "PV2 voltage", "pv_voltage_2", 0.1, False, "V"),
    0x111C: FieldDef(0x111C, "PV1 current", "pv_current", 0.1, True, "A"),
    0x111D: FieldDef(0x111D, "PV2 current", "pv_current_2", 0.1, True, "A"),
    0x1120: FieldDef(0x1120, "Home load A", "load_power", 1.0, True, "W"),
    0x1121: FieldDef(0x1121, "Home load B", "load_power_2", 1.0, True, "W"),
    0x1128: FieldDef(0x1128, "PV1 power", "pv_power", 1.0, True, "W"),
    0x1129: FieldDef(0x1129, "PV2 power", "pv_power_2", 1.0, True, "W"),
    0x112C: FieldDef(0x112C, "Bat1 voltage", "battery_voltage", 0.1, False, "V"),
    0x1130: FieldDef(0x1130, "Bat1 current", "battery_current", 0.1, True, "A"),
    0x1131: FieldDef(0x1131, "Bat1 power", "battery_power", 1.0, True, "W"),
    0x1138: FieldDef(0x1138, "Bat1 SOC", "battery_soc", 0.1, False, "%"),
}

# ── MUST (PH18/PV18 y familia PH/PV) ────────────────────────────────────────
# Fuente: mapa documentado en el .md adjunto + aggsoft (PV Inverter 3600)
# Se usan las direcciones del Bloque D (telemetría del inversor).
MUST_MAP: Dict[int, FieldDef] = {
    25201: FieldDef(25201, "Inverter Work State", "work_mode"),
    25205: FieldDef(25205, "Battery Voltage", "battery_voltage", 0.1, False, "V"),
    25206: FieldDef(25206, "Inverter Output Voltage", "output_voltage", 0.1, False, "V"),
    25207: FieldDef(25207, "Grid Voltage", "grid_voltage", 0.1, False, "V"),
    25209: FieldDef(25209, "Battery Current", "battery_current", 0.1, True, "A"),
    25210: FieldDef(25210, "Inverter Output Current", "output_current", 0.1, True, "A"),
    25213: FieldDef(25213, "Inverter Power", "output_power", 1.0, True, "W"),
    25214: FieldDef(25214, "Grid Power", "grid_power", 1.0, True, "W"),
    25215: FieldDef(25215, "Load Power", "load_power", 1.0, True, "W"),
    25216: FieldDef(25216, "System Load Percentage", "load_percent", 1.0, False, "%"),
    25219: FieldDef(25219, "Battery Capacity (SOC)", "battery_soc", 1.0, False, "%"),
    25233: FieldDef(25233, "AC Radiator Temperature", "temp_radiator_ac", 1.0, False, "°C"),
    25234: FieldDef(25234, "Transformer Temperature", "temp_transformer", 1.0, False, "°C"),
    25235: FieldDef(25235, "DC Radiator Temperature", "temp_radiator_dc", 1.0, False, "°C"),
}

# ── SUMRY (PI30) ─────────────────────────────────────────────────────────────
# SUMRY usa protocolo ASCII PI30 (comandos QPIGS, etc.).
# Los campos se extraen de la respuesta a QPIGS, no de registros Modbus.
# La posición exacta de cada campo puede variar ligeramente según firmware.
# Se mapean los campos más comunes a nombres canónicos.
SUMRY_QPIGS_INDEX = {
    0: ("grid_voltage", "V", 1.0),
    1: ("grid_frequency", "Hz", 1.0),
    2: ("output_voltage", "V", 1.0),
    3: ("output_frequency", "Hz", 1.0),
    4: ("battery_voltage", "V", 1.0),
    5: ("battery_current", "A", 1.0),
    6: ("battery_soc", "%", 1.0),
    7: ("load_power", "W", 1.0),
    8: ("pv_voltage", "V", 1.0),
    9: ("pv_current", "A", 1.0),
    10: ("pv_power", "W", 1.0),
    11: ("temp_radiator", "°C", 1.0),
    12: ("battery_soc_2", "%", 1.0),  # a veces duplicado
    13: ("bus_voltage", "V", 1.0),
}

BRAND_MAPS = {
    "felicity": (FELICITY_MAP, "Felicity IVGM/Series RS485"),
    "must": (MUST_MAP, "MUST PH/PV/EP"),
    "sumry": (None, "SUMRY PI30 (ASCII)"),
}


# ══════════════════════════════════════════════════════════════════════════════
# TRANSPORTE TCP (reutilizado de verificar_rs485.py)
# ══════════════════════════════════════════════════════════════════════════════


class ModbusTcpClient:
    INTER_BYTE_TIMEOUT = 0.2

    def __init__(self, host: str, port: int = 502, framing: str = "mbap", timeout: float = 3.0):
        self.host = host
        self.port = port
        self.framing = framing
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None
        self._txid = 0

    def connect(self) -> Tuple[bool, str]:
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout)
            self._socket.connect((self.host, self.port))
            return True, f"Conectado a {self.host}:{self.port} ({self.framing.upper()})"
        except OSError as e:
            self._socket = None
            return False, f"Error: {e}"

    def disconnect(self):
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def _next_txid(self) -> int:
        self._txid = (self._txid + 1) & 0xFFFF
        return self._txid

    def _build_read(self, slave: int, addr: int, count: int) -> bytes:
        pdu = bytes([0x03, (addr >> 8) & 0xFF, addr & 0xFF,
                     (count >> 8) & 0xFF, count & 0xFF])
        if self.framing == "mbap":
            header = bytes([(self._next_txid() >> 8) & 0xFF, self._next_txid() & 0xFF,
                            0x00, 0x00, 0x00, len(pdu) + 1])
            return header + bytes([slave]) + pdu
        payload = bytes([slave]) + pdu
        return payload + calculate_crc(payload)

    def _recv(self, expected: int) -> Optional[bytes]:
        if self._socket is None:
            return None
        orig = self._socket.gettimeout()
        buf = bytearray()
        try:
            self._socket.settimeout(self.timeout)
            try:
                first = self._socket.recv(min(expected, 256))
            except socket.timeout:
                return None
            if not first:
                return None
            buf.extend(first)
            self._socket.settimeout(self.INTER_BYTE_TIMEOUT)
            while len(buf) < expected:
                try:
                    chunk = self._socket.recv(min(expected - len(buf), 256))
                except socket.timeout:
                    break
                if not chunk:
                    break
                buf.extend(chunk)
        finally:
            try:
                self._socket.settimeout(orig)
            except OSError:
                pass
        return bytes(buf) if buf else None

    def read_holding(self, slave: int, addr: int, count: int, retries: int = 2) -> Optional[List[int]]:
        if self._socket is None:
            return None
        frame = self._build_read(slave, addr, count)
        expected = 3 + count * 2 + 2 if self.framing == "rtu" else 7 + 2 + count * 2
        for _ in range(retries + 1):
            try:
                self._socket.sendall(frame)
                resp = self._recv(expected)
            except OSError:
                continue
            if resp is None:
                continue
            # Parseo mínimo (sin comprobar excepción exhaustiva)
            if self.framing == "rtu":
                if len(resp) < 5 or resp[0] != slave or resp[1] != 0x03 or not verify_crc(resp):
                    continue
                bc = resp[2]
                data = resp[3:3 + bc]
            else:
                if len(resp) < 9 or resp[6] != slave or resp[7] != 0x03:
                    continue
                bc = resp[8]
                data = resp[9:9 + bc]
            if len(data) < count * 2:
                continue
            return [(data[i * 2] << 8) | data[i * 2 + 1] for i in range(count)]
        return None


# ══════════════════════════════════════════════════════════════════════════════
# LECTURA Y VOLCADO A CSV
# ══════════════════════════════════════════════════════════════════════════════


def to_signed(value: int) -> int:
    return value - 0x10000 if value >= 0x8000 else value


def volcar_modbus(
    client: ModbusTcpClient,
    slave: int,
    brand: str,
    out_path: str,
    block_size: int = 60,
) -> None:
    """Vuelca todos los registros del mapa de la marca a CSV."""
    reg_map, brand_label = BRAND_MAPS[brand]
    if reg_map is None:
        print(f"  La marca {brand} no usa Modbus; use --brand sumry con PI30.")
        return

    addresses = sorted(reg_map.keys())
    if not addresses:
        print(f"  Mapa vacío para {brand}.")
        return

    start = addresses[0]
    end = addresses[-1]
    total = end - start + 1
    print(f"  Volcando {total} registros de {brand_label} (0x{start:04X}..0x{end:04X})...")

    all_raw: Dict[int, int] = {}
    base = start
    remaining = total
    while remaining > 0:
        chunk = min(block_size, remaining)
        values = client.read_holding(slave, base, chunk)
        if values is None:
            print(f"    Fallo en 0x{base:04X} ({chunk} regs)")
            for i in range(chunk):
                all_raw[base + i] = -1  # marcador de error
        else:
            for i, v in enumerate(values):
                all_raw[base + i] = v
        base += chunk
        remaining -= chunk

    timestamp = datetime.now().isoformat(timespec="seconds")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "brand", "brand_label", "slave_id",
            "address_dec", "address_hex", "field_label",
            "raw_value", "scaled_value", "unit", "canonical_name"
        ])
        for addr in addresses:
            if addr not in all_raw:
                continue
            raw = all_raw[addr]
            field = reg_map[addr]
            if raw == -1:
                scaled = "ERROR"
            elif field.signed:
                scaled = to_signed(raw) * field.scale
            else:
                scaled = raw * field.scale
            writer.writerow([
                timestamp, brand, brand_label, slave,
                addr, f"0x{addr:04X}", field.label,
                raw, scaled, field.unit, field.canonical
            ])
    print(f"  CSV guardado: {out_path} ({len(addresses)} filas)")


def volcar_sumry_pi30(
    host: str,
    port: int,
    out_path: str,
    timeout: float = 3.0,
) -> None:
    """
    Conecta al ESP32 (bridge TCP→RS232) y envía comandos PI30.
    Guarda la respuesta de QPIGS parseada a CSV.
    """
    print(f"  Conectando a SUMRY vía PI30 en {host}:{port}...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
    except OSError as e:
        print(f"  Error de conexión: {e}")
        return

    def send_cmd(cmd: str) -> Optional[str]:
        """Envía un comando PI30 y devuelve la respuesta como string."""
        full = cmd + "\r"
        sock.sendall(full.encode("ascii"))
        time.sleep(0.3)  # PI30 necesita pausa entre comandos
        try:
            data = sock.recv(4096)
        except socket.timeout:
            return None
        if not data:
            return None
        return data.decode("ascii", errors="ignore").strip()

    try:
        # Comando de identificación
        qpi = send_cmd("QPI")
        print(f"  QPI → {qpi}")

        # Comando principal de estado
        qpigs = send_cmd("QPIGS")
        if qpigs is None:
            print("  No se recibió respuesta a QPIGS.")
            return

        print(f"  QPIGS → {qpigs[:120]}...")
        # La respuesta suele empezar con '(' y terminar con ';' o similar.
        # Limpiamos y separamos por espacios.
        clean = qpigs.strip("()\r\n;")
        parts = clean.split()
        timestamp = datetime.now().isoformat(timespec="seconds")

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp", "brand", "brand_label", "field_index",
                "field_label", "raw_value", "scaled_value", "unit", "canonical_name"
            ])
            for idx, token in enumerate(parts):
                if idx in SUMRY_QPIGS_INDEX:
                    canonical, unit, scale = SUMRY_QPIGS_INDEX[idx]
                    try:
                        raw_val = float(token)
                        scaled = raw_val * scale
                    except ValueError:
                        raw_val = token
                        scaled = "PARSE_ERROR"
                    writer.writerow([
                        timestamp, "sumry", "SUMRY PI30",
                        idx, canonical, raw_val, scaled, unit, canonical
                    ])
                else:
                    writer.writerow([
                        timestamp, "sumry", "SUMRY PI30",
                        idx, f"unknown_{idx}", token, "", "", ""
                    ])
        print(f"  CSV guardado: {out_path} ({len(parts)} campos)")
    finally:
        sock.close()


# ══════════════════════════════════════════════════════════════════════════════
# COMPARACIÓN DE CSV
# ══════════════════════════════════════════════════════════════════════════════


def leer_csv(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def comparar_csvs(paths: List[str], out_path: str) -> None:
    """
    Toma varios CSV (uno por marca) y genera un CSV de comparación
    con columnas: canonical_name, felicity, must, sumry, unidad.
    """
    print(f"  Comparando {len(paths)} archivos...")
    data_by_brand: Dict[str, Dict[str, str]] = {}

    for path in paths:
        rows = leer_csv(path)
        if not rows:
            print(f"    {path}: vacío")
            continue
        brand = rows[0].get("brand", "desconocida")
        brand_data: Dict[str, str] = {}
        for row in rows:
            canonical = row.get("canonical_name", "").strip()
            if not canonical:
                continue
            scaled = row.get("scaled_value", "").strip()
            unit = row.get("unit", "").strip()
            if scaled and scaled != "ERROR" and scaled != "PARSE_ERROR":
                brand_data[canonical] = f"{scaled} {unit}".strip()
        data_by_brand[brand] = brand_data
        print(f"    {path} → marca '{brand}', {len(brand_data)} campos canónicos")

    all_canonical = set()
    for brand_data in data_by_brand.values():
        all_canonical.update(brand_data.keys())
    all_canonical = sorted(all_canonical)

    brands = sorted(data_by_brand.keys())
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        header = ["canonical_name"] + brands + ["unit"]
        writer.writerow(header)
        for canon in all_canonical:
            row = [canon]
            unit = ""
            for brand in brands:
                val = data_by_brand[brand].get(canon, "—")
                row.append(val)
                if not unit and val != "—":
                    # extraer unidad de la primera marca que tenga valor
                    parts = val.split()
                    if len(parts) > 1:
                        unit = parts[-1]
            row.append(unit)
            writer.writerow(row)
    print(f"  CSV de comparación guardado: {out_path} ({len(all_canonical)} campos)")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Volcado a CSV y comparación multi-marca (Felicity/MUST/SUMRY)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--brand", choices=("felicity", "must", "sumry"),
                        help="Marca a volcar (requiere --host)")
    parser.add_argument("--host", help="IP del ESP32/conversor")
    parser.add_argument("--port", type=int, default=502,
                        help="Puerto TCP (502 para Modbus, otro para PI30)")
    parser.add_argument("--framer", choices=("mbap", "rtu"), default="rtu",
                        help="Framing Modbus (rtu para bridge transparente)")
    parser.add_argument("--slave", type=int, default=1,
                        help="Slave ID Modbus (Felicity:1, MUST:4)")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--out", help="Ruta del CSV de salida")
    parser.add_argument("--compare", nargs="+", metavar="CSV",
                        help="Compara varios CSV y genera tabla unificada")
    args = parser.parse_args(argv)

    # ── Modo comparación ─────────────────────────────────────────────────
    if args.compare:
        if not args.out:
            print("  Error: --compare requiere --out")
            return 1
        comparar_csvs(args.compare, args.out)
        return 0

    # ── Modo volcado ─────────────────────────────────────────────────────
    if not args.brand or not args.host:
        print("  Error: se requiere --brand y --host (o use --compare)")
        parser.print_help()
        return 1

    if not args.out:
        args.out = f"{args.brand}_dump.csv"

    if args.brand == "sumry":
        volcar_sumry_pi30(args.host, args.port, args.out, args.timeout)
        return 0

    # Felicity / MUST → Modbus
    client = ModbusTcpClient(args.host, args.port, args.framer, args.timeout)
    ok, msg = client.connect()
    print(f"  {msg}")
    if not ok:
        return 1
    try:
        slave = args.slave
        if args.brand == "felicity" and slave == 1:
            slave = 1
        elif args.brand == "must" and slave == 1:
            slave = 4  # default MUST
        volcar_modbus(client, slave, args.brand, args.out)
    finally:
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
