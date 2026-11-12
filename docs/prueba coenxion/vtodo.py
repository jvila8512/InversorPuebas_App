#!/usr/bin/env python3
"""
verificar_rs485_v2.py - Sonda de verificacion Modbus RTU sobre TCP/IP (v2)
==========================================================================
Herramienta independiente (no depende de la app) para verificar, contra el
inversor real, la cadena completa:

    inversor --(RS485)--> conversor --(TCP)--> esta sonda

Solo usa la libreria estandar de Python 3.7+ (no hay que instalar nada).

MODOS (elija uno):
  --auto      Prueba combinaciones solas (framing x slave x funcion x
              direccion) hasta que algo responda, y diagnostica por que no.
  --todo      Lee TODOS los registros que existan y los guarda en un CSV.
  --scan      Barre slave IDs y dice cuales responden (o contestan excepcion).
  (nada)      Vuelca registros (--start/--count) y compara los dos mapas.
  --raw HEX   Envia una trama a mano y muestra los bytes crudos que vuelven.
  --sniff N   Solo escucha N segundos (detecta otros maestros en el bus).
  --write A V Escribe un registro (peligroso, pide confirmacion).

EJEMPLOS:
  python verificar_rs485_v2.py --host 192.168.1.25 --port 502 --auto
  python verificar_rs485_v2.py --host 192.168.1.25 --framer rtu --slave 1 --todo
  python verificar_rs485_v2.py --host 192.168.1.25 --framer rtu --slave 1 --todo completo
  python verificar_rs485_v2.py --host 192.168.1.50 --framer rtu --scan
  python verificar_rs485_v2.py --host 192.168.1.50 --framer rtu --slave 1 --start 0x1100 --count 80
  python verificar_rs485_v2.py --host 192.168.1.50 --framer rtu --raw "01 03 11 01 00 01"
  python verificar_rs485_v2.py --host 192.168.1.50 --auto -v --out resultado.txt

CAMBIOS RESPECTO A v1:
  - Muestra el resultado de cada intento y CLASIFICA el fallo: silencio,
    basura (baud/paridad), excepcion Modbus (el equipo esta vivo), o error del
    gateway (el conversor responde pero el inversor no).
  - Las lecturas que fallan ya NO se rellenan con ceros (v1 mostraba una tabla
    de ceros como si fueran datos reales).
  - El scan ya no tarda ~37 min: timeout corto, sin reintentos, 1-32 por defecto.
  - Si un bloque falla con excepcion, lo parte en trozos para ver que
    direcciones SI existen.
  - Vacia el socket antes de cada pregunta (evita leer respuestas viejas) y
    avisa si hay trafico ajeno en el bus (otro maestro).
  - Nuevas opciones: --auto, --raw, --sniff, --fc 4, -v, --out.
  - Veredicto de mapa sin falsos positivos por ceros.

Autor: InversorApp
Fecha: 2026-11-09
"""

from __future__ import annotations

import argparse
import csv
import select
import socket
import sys
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ══════════════════════════════════════════════════════════════════════════════
# CRC-16 MODBUS (polinomio 0xA001)
# ══════════════════════════════════════════════════════════════════════════════


def calculate_crc(data: bytes) -> bytes:
    """Calcula el CRC-16/Modbus. Devuelve los dos bytes (LSB primero)."""
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
    """Verifica el CRC de una trama RTU completa."""
    if len(frame) < 3:
        return False
    payload, crc = frame[:-2], frame[-2:]
    return calculate_crc(payload) == crc


def hexs(data: bytes) -> str:
    """Bytes -> 'AA BB CC' (para mostrar tramas crudas)."""
    return " ".join(f"{b:02X}" for b in data)


# ══════════════════════════════════════════════════════════════════════════════
# MAPAS DE REGISTROS
# ══════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class FieldDef:
    """Definicion de un campo dentro de un mapa de registros."""

    address: int
    label: str
    scale: float = 1.0
    signed: bool = False
    unit: str = ""


@dataclass(frozen=True)
class RegisterMap:
    """Mapa de registros completo de un modelo de inversor."""

    name: str
    label: str
    status_start: int
    status_count: int
    fields: Dict[str, FieldDef] = field(default_factory=dict)


# ── Mapa CLASICO (Voltronic / Axpert / IVEM 48V) ──────────────────────────────
# Es el que usa hoy la app y con el que funciona el inversor de 5K.
CLASSIC_MAP = RegisterMap(
    name="classic",
    label="Clasico Voltronic/Axpert (5K, IVEM 48V)",
    status_start=0x1100,
    status_count=43,
    fields={
        "setting_data_sn":  FieldDef(0x1100, "SettingDataSn"),
        "working_mode":     FieldDef(0x1101, "Working mode"),
        "charge_mode":      FieldDef(0x1102, "Charge mode"),
        "fault_code":       FieldDef(0x1103, "Fault code"),
        "power_flow":       FieldDef(0x1104, "PowerFlowMsg"),
        "battery_voltage":  FieldDef(0x1108, "Battery voltage", 0.01, False, "V"),
        "battery_current":  FieldDef(0x1109, "Battery current", 1.0, True, "A"),
        "battery_power":    FieldDef(0x110A, "Battery power", 1.0, True, "W"),
        "output_voltage":   FieldDef(0x1111, "AC output voltage", 0.1, False, "V"),
        "grid_voltage":     FieldDef(0x1117, "Grid voltage", 0.1, False, "V"),
        "grid_frequency":   FieldDef(0x1119, "Grid frequency", 0.01, False, "Hz"),
        "output_power":     FieldDef(0x111E, "Output active power", 1.0, True, "W"),
        "output_apparent":  FieldDef(0x111F, "Output apparent power", 1.0, False, "VA"),
        "load_percent":     FieldDef(0x1120, "Load percent", 1.0, False, "%"),
        "pv_voltage":       FieldDef(0x1126, "PV voltage", 0.1, False, "V"),
        "pv_power":         FieldDef(0x112A, "PV power", 1.0, True, "W"),
    },
)

# ── Mapa IVGM-8K (Felicity "Series RS485", familia IVGM) ─────────────────────
# Levantado del documento "Inverter Communication Protocol - Series RS485".
# OJO: la integracion de referencia lo marca como PROVISIONAL (no validado
# contra hardware). Por eso esta sonda existe: para confirmarlo con el equipo.
IVGM_8K_MAP = RegisterMap(
    name="ivgm_8k",
    label="IVGM-8K (Felicity Series RS485)",
    status_start=0x1100,
    status_count=120,
    fields={
        "work_mode":        FieldDef(0x1100, "WorkMode"),
        "state1":           FieldDef(0x1101, "State1"),
        "state2":           FieldDef(0x1102, "State2"),
        "state3":           FieldDef(0x1103, "State3"),
        "state4":           FieldDef(0x1104, "State4"),
        "warn_code":        FieldDef(0x1109, "Warn code"),
        "fault_code":       FieldDef(0x110A, "Fault code"),
        "pv1_voltage":      FieldDef(0x1118, "PV1 voltage", 0.1, False, "V"),
        "pv2_voltage":      FieldDef(0x1119, "PV2 voltage", 0.1, False, "V"),
        "pv1_current":      FieldDef(0x111C, "PV1 current", 0.1, True, "A"),
        "pv2_current":      FieldDef(0x111D, "PV2 current", 0.1, True, "A"),
        "load_a":           FieldDef(0x1120, "Home load A", 1.0, True, "W"),
        "load_b":           FieldDef(0x1121, "Home load B", 1.0, True, "W"),
        "pv1_power":        FieldDef(0x1128, "PV1 power", 1.0, True, "W"),
        "pv2_power":        FieldDef(0x1129, "PV2 power", 1.0, True, "W"),
        "battery_voltage":  FieldDef(0x112C, "Bat1 voltage", 0.1, False, "V"),
        "battery_current":  FieldDef(0x1130, "Bat1 current", 0.1, True, "A"),
        "battery_power":    FieldDef(0x1131, "Bat1 power", 1.0, True, "W"),
        "battery_soc":      FieldDef(0x1138, "Bat1 SOC", 0.1, False, "%"),
    },
)

MAPS: Dict[str, RegisterMap] = {m.name: m for m in (CLASSIC_MAP, IVGM_8K_MAP)}

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES Y RESULTADOS
# ══════════════════════════════════════════════════════════════════════════════

FUNC_READ_HOLDING = 0x03
FUNC_READ_INPUT = 0x04
FUNC_WRITE_SINGLE = 0x06

EXCEPTION_NAMES = {
    0x01: "funcion ilegal",
    0x02: "direccion ilegal",
    0x03: "valor/cantidad ilegal",
    0x04: "fallo del esclavo",
    0x06: "esclavo ocupado",
    0x0A: "gateway: ruta no disponible",
    0x0B: "gateway: el inversor no respondio",
}

# Silencio (en segundos) tras el ultimo byte para dar la trama por terminada
# cuando no se puede saber su largo (basura). Los conversores baratos parten
# la trama en paquetes TCP, por eso no es menor.
IDLE_GAP = 0.4
# Tope duro desde el primer byte (a 2400 baud 120 registros tardan ~1 s).
HARD_CAP = 5.0

# Direcciones de prueba para --auto (salen de los mapas/documentos conocidos):
#   0x1100 = inicio de ambos mapas, 0xF800 = DeviceType (info Felicity),
#   0x211F = ajuste "battery cut-off" (Felicity IVEM), 0x0000 = generica.
AUTO_ADDRESSES = [0x1100, 0xF800, 0x211F, 0x0000]


@dataclass
class Result:
    """Resultado de UNA pregunta al equipo.

    status:
      ok         respuesta valida con datos
      exception  el equipo contesto con excepcion Modbus  (ESTA VIVO)
      gateway    el CONVERSOR contesto 0x0A/0x0B: el conversor funciona
                 pero el inversor no le responde
      garbage    llegaron bytes pero no forman una trama valida (baud,
                 paridad, framing o ruido)
      silent     no llego nada
      error      fallo de socket / conexion cerrada
    """

    status: str
    values: Optional[List[int]] = None
    exc_code: Optional[int] = None
    tx: bytes = b""
    rx: bytes = b""
    latency_ms: float = 0.0
    note: str = ""

    def describe(self) -> str:
        if self.status == "ok":
            return "OK"
        if self.status in ("exception", "gateway"):
            name = EXCEPTION_NAMES.get(self.exc_code or -1, "desconocida")
            return f"EXCEPCION 0x{(self.exc_code or 0):02X} ({name})"
        if self.status == "garbage":
            return f"BASURA ({self.note})" if self.note else "BASURA"
        if self.status == "silent":
            return "silencio"
        return f"ERROR ({self.note})" if self.note else "ERROR"


# ══════════════════════════════════════════════════════════════════════════════
# CONSTRUCCION E INTERPRETACION DE TRAMAS
# ══════════════════════════════════════════════════════════════════════════════


def build_request(
    slave_id: int,
    func: int,
    address: int,
    value_or_count: int,
    framing: str = "mbap",
    transaction_id: int = 1,
) -> bytes:
    """Trama de lectura (0x03/0x04: cantidad) o escritura simple (0x06: valor)."""
    pdu = bytes(
        [
            func,
            (address >> 8) & 0xFF,
            address & 0xFF,
            (value_or_count >> 8) & 0xFF,
            value_or_count & 0xFF,
        ]
    )
    if framing == "mbap":
        # MBAP: transaction id (2) + protocol id (2) + length (2) + unit id (1)
        # En Modbus TCP NO se envia CRC.
        header = bytes(
            [
                (transaction_id >> 8) & 0xFF,
                transaction_id & 0xFF,
                0x00,
                0x00,
                0x00,
                len(pdu) + 1,
            ]
        )
        return header + bytes([slave_id]) + pdu
    if framing == "rtu":
        payload = bytes([slave_id]) + pdu
        return payload + calculate_crc(payload)
    raise ValueError(f"Framing no soportado: {framing}")


def expected_total(buf: bytes, framing: str) -> Optional[int]:
    """Largo total de la trama si ya se puede deducir de lo recibido."""
    if framing == "mbap":
        if len(buf) >= 6:
            return 6 + ((buf[4] << 8) | buf[5])
        return None
    if len(buf) >= 2:
        func = buf[1]
        if func & 0x80:
            return 5  # excepcion RTU: slave, func, codigo, crc, crc
        if func in (0x03, 0x04):
            return 3 + buf[2] + 2 if len(buf) >= 3 else None
        if func in (0x06, 0x10):
            return 8
    return None


def classify(
    rx: bytes, slave_id: int, func: int, count: int, framing: str
) -> Result:
    """Convierte los bytes recibidos en un Result clasificado."""
    if not rx:
        return Result("silent")

    if framing == "mbap":
        if len(rx) < 9:
            return Result("garbage", note=f"solo {len(rx)} bytes")
        if rx[2:4] != b"\x00\x00":
            return Result("garbage", note="no es MBAP (protocol id != 0)")
        unit = rx[6]
        pdu = rx[7:]
    else:
        if len(rx) < 5:
            return Result("garbage", note=f"solo {len(rx)} bytes")
        if not verify_crc(rx):
            return Result("garbage", note="CRC invalido")
        unit = rx[0]
        pdu = rx[1:-2]

    if unit != slave_id:
        return Result("garbage", note=f"respondio el ID {unit}, no el {slave_id}")

    fcode = pdu[0]
    if fcode & 0x80:
        code = pdu[1] if len(pdu) > 1 else -1
        status = "gateway" if code in (0x0A, 0x0B) else "exception"
        return Result(status, exc_code=code)
    if fcode != func:
        return Result("garbage", note=f"funcion inesperada 0x{fcode:02X}")

    if func in (FUNC_READ_HOLDING, FUNC_READ_INPUT):
        if len(pdu) < 2:
            return Result("garbage", note="trama corta")
        byte_count = pdu[1]
        data = pdu[2 : 2 + byte_count]
        if byte_count != count * 2 or len(data) < count * 2:
            return Result("garbage", note="cantidad de datos distinta a la pedida")
        values = [(data[i * 2] << 8) | data[i * 2 + 1] for i in range(count)]
        return Result("ok", values=values)

    return Result("ok", values=[])  # eco de escritura


# ══════════════════════════════════════════════════════════════════════════════
# TRANSPORTE TCP
# ══════════════════════════════════════════════════════════════════════════════


class ModbusTcpProbe:
    """Sonda Modbus sobre TCP con framing conmutable (mbap / rtu)."""

    def __init__(
        self,
        host: str,
        port: int = 502,
        framing: str = "mbap",
        timeout: float = 3.0,
        verbose: bool = False,
    ):
        self.host = host
        self.port = port
        self.framing = framing
        self.timeout = timeout
        self.verbose = verbose
        self._socket: Optional[socket.socket] = None
        self._txid = 0
        self._closed = False
        # Bytes que llegaron SIN que nadie preguntara (otro maestro en el bus)
        self.unsolicited = 0

    # -- conexion -------------------------------------------------------------

    def connect(self) -> Tuple[bool, str]:
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout)
            self._socket.connect((self.host, self.port))
            try:
                self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            self._closed = False
            return True, f"Conectado a {self.host}:{self.port} ({self.framing.upper()})"
        except socket.timeout:
            self._socket = None
            return False, (
                f"Timeout conectando a {self.host}:{self.port} "
                "(IP incorrecta o el conversor no esta en la red)"
            )
        except ConnectionRefusedError:
            self._socket = None
            return False, (
                f"Conexion rechazada por {self.host}:{self.port} "
                "(la IP responde pero ese puerto esta cerrado: pruebe 502, 8899, 23)"
            )
        except OSError as e:
            self._socket = None
            return False, f"Error de conexion: {e}"

    def disconnect(self):
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    @property
    def is_open(self) -> bool:
        return self._socket is not None

    def _next_txid(self) -> int:
        self._txid = (self._txid + 1) & 0xFFFF
        return self._txid

    # -- bajo nivel -----------------------------------------------------------

    def drain(self) -> int:
        """Vacia lo pendiente en el socket (sin esperar). Devuelve cuantos bytes habia."""
        if self._socket is None:
            return 0
        total = 0
        try:
            while True:
                readable, _, _ = select.select([self._socket], [], [], 0)
                if not readable:
                    break
                chunk = self._socket.recv(512)
                if not chunk:
                    self._closed = True
                    break
                total += len(chunk)
        except (OSError, ValueError):
            pass
        self.unsolicited += total
        return total

    def recv_frame(self, timeout: float) -> bytes:
        """Recibe UNA trama. Termina en cuanto esta completa, no al agotar el timeout."""
        assert self._socket is not None
        buf = bytearray()
        start = time.perf_counter()
        first: Optional[float] = None
        last = start
        while True:
            now = time.perf_counter()
            if first is None:
                remaining = timeout - (now - start)
                if remaining <= 0:
                    break
                self._socket.settimeout(remaining)
            else:
                idle_left = IDLE_GAP - (now - last)
                hard_left = HARD_CAP - (now - first)
                if idle_left <= 0 or hard_left <= 0:
                    break
                self._socket.settimeout(min(idle_left, hard_left))
            try:
                chunk = self._socket.recv(512)
            except socket.timeout:
                break
            except OSError:
                self._closed = True
                break
            if not chunk:
                self._closed = True
                break
            if first is None:
                first = time.perf_counter()
            last = time.perf_counter()
            buf.extend(chunk)
            total = expected_total(bytes(buf), self.framing)
            if total is not None and len(buf) >= total:
                return bytes(buf[:total])
        return bytes(buf)

    def transact(
        self,
        frame: bytes,
        slave_id: int,
        func: int,
        count: int,
        timeout: Optional[float] = None,
    ) -> Result:
        """Envia una trama y devuelve el resultado clasificado."""
        if self._socket is None:
            return Result("error", note="sin conexion")
        self.drain()
        started = time.perf_counter()
        try:
            self._socket.sendall(frame)
        except OSError as e:
            return Result("error", tx=frame, note=str(e))
        rx = self.recv_frame(timeout if timeout is not None else self.timeout)
        latency = (time.perf_counter() - started) * 1000
        result = classify(rx, slave_id, func, count, self.framing)
        if self._closed and not rx:
            result = Result("error", note="el conversor cerro la conexion")
        result.tx, result.rx, result.latency_ms = frame, rx, latency
        if self.verbose:
            print(f"      TX {hexs(frame)}")
            print(f"      RX {hexs(rx) if rx else '(nada)'}  -> {result.describe()}")
        return result

    # -- operaciones ----------------------------------------------------------

    def read(
        self,
        slave_id: int,
        address: int,
        count: int,
        func: int = FUNC_READ_HOLDING,
        retries: int = 0,
        timeout: Optional[float] = None,
    ) -> Result:
        """Lee registros. Reintenta solo si hubo silencio/basura."""
        last = Result("silent")
        for _ in range(retries + 1):
            frame = build_request(
                slave_id, func, address, count, self.framing, self._next_txid()
            )
            last = self.transact(frame, slave_id, func, count, timeout)
            if last.status in ("ok", "exception", "gateway"):
                return last
        return last

    def write_single(self, slave_id: int, address: int, value: int) -> Result:
        frame = build_request(
            slave_id, FUNC_WRITE_SINGLE, address, value, self.framing, self._next_txid()
        )
        return self.transact(frame, slave_id, FUNC_WRITE_SINGLE, 1)

    def send_raw(self, frame: bytes, timeout: Optional[float] = None) -> bytes:
        """Envia bytes tal cual y devuelve lo que vuelva (sin interpretar)."""
        if self._socket is None:
            return b""
        self.drain()
        self._socket.sendall(frame)
        return self.recv_frame(timeout if timeout is not None else self.timeout)

    def listen(self, seconds: float) -> List[Tuple[float, bytes]]:
        """Solo escucha. Devuelve [(segundo, bytes)]."""
        out: List[Tuple[float, bytes]] = []
        if self._socket is None:
            return out
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            self._socket.settimeout(0.2)
            try:
                chunk = self._socket.recv(512)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            out.append((time.perf_counter() - t0, chunk))
        return out



# ══════════════════════════════════════════════════════════════════════════════
# UTILIDADES DE INTERPRETACION
# ══════════════════════════════════════════════════════════════════════════════


def to_signed(value: int) -> int:
    """Convierte un valor de 16 bits sin signo a con signo."""
    return value - 0x10000 if value >= 0x8000 else value


def decode_registers(
    registers: List[Optional[int]], start_address: int
) -> Dict[int, Optional[int]]:
    """Genera un diccionario {address: valor|None} a partir de una lista."""
    return {start_address + i: value for i, value in enumerate(registers)}


def fmt_field(value: Optional[int], fld: FieldDef) -> str:
    """Valor de un registro formateado segun su definicion ('-' si no se leyo)."""
    if value is None:
        return "-"
    shown = to_signed(value) * fld.scale if fld.signed else value * fld.scale
    return f"{shown:.0f}{fld.unit}" if fld.scale == 1.0 else f"{shown:.2f}{fld.unit}"


def print_register_dump(
    registers: List[Optional[int]],
    start_address: int,
    maps: List[RegisterMap],
    full: bool = False,
):
    """Imprime el volcado. '--' = no se pudo leer (NO es lo mismo que 0)."""
    by_address = decode_registers(registers, start_address)
    mapped = {f.address for m in maps for f in m.fields.values()}

    print()
    print("  Direccion   Valor    Hex      " + "".join(f"{m.name:<12}" for m in maps))
    print("  " + "-" * (28 + 12 * len(maps)))

    hidden = 0
    for address in sorted(by_address):
        value = by_address[address]
        if not full and address not in mapped and (value is None or value == 0):
            hidden += 1
            continue
        cells = []
        for m in maps:
            fld = next((f for f in m.fields.values() if f.address == address), None)
            cells.append("-" if fld is None else fmt_field(value, fld))
        vtxt = "--" if value is None else str(value)
        htxt = "----" if value is None else f"0x{value:04X}"
        print(
            f"  0x{address:04X}      {vtxt:<7} {htxt:<8} "
            + "".join(f"{c:<12}" for c in cells)
        )
    if hidden:
        print(f"  ({hidden} registros en 0 o sin lectura y sin mapa omitidos; use --full)")


def print_map_comparison(registers: List[Optional[int]], start_address: int):
    """Compara la interpretacion de los dos mapas para los campos clave."""
    by_address = decode_registers(registers, start_address)

    print()
    print("  COMPARACION DE MAPAS")
    print("  " + "-" * 62)
    print(f"  {'Campo':<20}{'Clasico':<22}{'IVGM-8K':<22}")
    print("  " + "-" * 62)

    for key in sorted(set(CLASSIC_MAP.fields) | set(IVGM_8K_MAP.fields)):
        cols = []
        for m in (CLASSIC_MAP, IVGM_8K_MAP):
            fld = m.fields.get(key)
            if fld is None:
                cols.append("")
            else:
                cols.append(fmt_field(by_address.get(fld.address), fld))
        print(f"  {key:<20}{cols[0]:<22}{cols[1]:<22}")


def print_verdict(registers: List[Optional[int]], start_address: int):
    """
    Adivina el mapa correcto por coherencia fisica. Un 0 NUNCA cuenta como
    evidencia (un registro inexistente tambien vale 0).
    """
    by_address = decode_registers(registers, start_address)
    read_values = [v for v in by_address.values() if v is not None]

    print()
    print("  VEREDICTO")
    print("  " + "-" * 62)

    if not read_values:
        print("  No se leyo ningun registro: no hay nada que comparar.")
        print()
        return
    if all(v == 0 for v in read_values):
        print("  Todos los registros leidos valen 0: hay comunicacion pero no hay datos.")
        print("  Pruebe otra direccion inicial (--start), --fc 4, o el inversor esta")
        print("  apagado / en reposo.")
        print()
        return

    def scaled(address: int, scale: float) -> Optional[float]:
        raw = by_address.get(address)
        return None if raw is None else raw * scale

    def inside(x: Optional[float], low: float, high: float) -> bool:
        return x is not None and low <= x <= high

    ivgm_bat = scaled(0x112C, 0.1)
    ivgm_soc = scaled(0x1138, 0.1)
    cl_bat = scaled(0x1108, 0.01)
    cl_out = scaled(0x1111, 0.1)

    ivgm_hits = [
        ("Bat1 voltage 0x112C", ivgm_bat, inside(ivgm_bat, 40.0, 63.0)),
        ("Bat1 SOC     0x1138", ivgm_soc, inside(ivgm_soc, 0.1, 100.0)),
    ]
    classic_hits = [
        ("Battery V    0x1108", cl_bat, inside(cl_bat, 40.0, 63.0)),
        ("AC output V  0x1111", cl_out, inside(cl_out, 90.0, 280.0)),
    ]

    def show(title: str, hits):
        score = sum(1 for _, _, ok in hits if ok)
        print(f"  {title}: {score}/2 valores plausibles")
        for label, value, ok in hits:
            txt = "no leido" if value is None else f"{value:.2f}"
            print(f"      {label} = {txt:<10} {'plausible' if ok else '-'}")
        return score

    ivgm_ok = show("IVGM-8K", ivgm_hits)
    cl_ok = show("Clasico", classic_hits)

    if ivgm_ok > cl_ok:
        print("  -> El mapa IVGM-8K parece el correcto para este equipo.")
    elif cl_ok > ivgm_ok:
        print("  -> El mapa CLASICO parece el correcto para este equipo.")
    else:
        print("  -> No se puede determinar. Compare los valores con la pantalla")
        print("     del inversor (tension de bateria, SOC, PV, red, carga).")
    print("  (Ninguno de los dos mapas esta validado: confirme SIEMPRE contra la pantalla.)")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSTICO
# ══════════════════════════════════════════════════════════════════════════════


def print_diagnosis(counts: Dict[str, int], unsolicited: int):
    """Explica en lenguaje llano que significa el patron de resultados."""
    ok = counts.get("ok", 0)
    exc = counts.get("exception", 0)
    gw = counts.get("gateway", 0)
    bad = counts.get("garbage", 0)
    err = counts.get("error", 0)

    print()
    print("  DIAGNOSTICO")
    print("  " + "-" * 62)
    if ok:
        print("  Hay comunicacion valida con el inversor.")
    elif exc:
        print("  El inversor SI esta contestando (excepciones Modbus). Entonces el")
        print("  cableado, el baud y el slave ID estan bien. Lo que falla es la")
        print("  DIRECCION o la FUNCION que se pide. Pruebe:")
        print("    - --fc 4 (registros de entrada en vez de holding)")
        print("    - otra direccion inicial (--start 0x0000, 0xF800, 0x2100...)")
        print("    - --raw con una trama copiada del manual del equipo")
    elif gw:
        print("  El CONVERSOR esta en modo Modbus TCP y contesta, pero avisa que el")
        print("  inversor no le responde (excepcion 0x0A/0x0B). Revise, en orden:")
        print("    1. Baud y paridad del lado SERIE del conversor (pruebe 2400 y 9600, 8N1)")
        print("    2. A y B invertidos (si no hay respuesta, intercambielos: no danan)")
        print("    3. Slave ID (use --scan)")
        print("    4. GND comun y terminacion de 120 ohm en los extremos del bus")
    elif bad:
        print("  Llegan bytes pero no forman una trama valida. Causas tipicas:")
        print("    1. Baud o paridad distintos entre conversor e inversor (la mas comun)")
        print("    2. Framing equivocado: pruebe --framer rtu y --framer mbap")
        print("    3. Ruido: agregue GND comun y terminacion de 120 ohm")
        print("  Use -v para ver los bytes crudos que llegan.")
    elif err:
        print("  Hubo errores de conexion. El conversor cerro la conexion o la red fallo.")
        print("  Algunos conversores solo aceptan UN cliente TCP: cierre la app Java, el")
        print("  programa del conversor y cualquier otra sonda.")
    else:
        print("  SILENCIO TOTAL: no vuelve ningun byte. Revise, en orden:")
        print("    1. Baud y paridad del lado SERIE del conversor (2400 y 9600, 8N1)")
        print("    2. Framing: el conversor puede esperar RTU crudo (--framer rtu)")
        print("    3. A y B invertidos (intercambielos: no danan nada)")
        print("    4. Slave ID (use --scan o --auto)")
        print("    5. Que el puerto TCP sea el del lado serie (502, 8899, 23...)")
        print("    6. Que el cable este en el puerto RS485/COM correcto del inversor")
    if unsolicited:
        print()
        print(f"  AVISO: llegaron {unsolicited} bytes SIN que la sonda preguntara.")
        print("  Hay otro maestro hablando en el bus (app Java, dongle WiFi, otra sonda).")
        print("  En RS485 solo puede haber UN maestro: apague/desconecte los demas.")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# COMANDOS PRINCIPALES
# ══════════════════════════════════════════════════════════════════════════════

STATUS_TAG = {
    "ok": "OK",
    "exception": "EXC",
    "gateway": "GW",
    "garbage": "BAS",
    "silent": "-",
    "error": "ERR",
}


def parse_int(text: str) -> int:
    """Acepta decimal o hexadecimal (0x...)."""
    text = text.strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def parse_slaves(text: str) -> List[int]:
    """'1-10,31,247' -> [1..10, 31, 247]"""
    out: List[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(parse_int(a), parse_int(b) + 1))
        else:
            out.append(parse_int(part))
    return sorted({x for x in out if 1 <= x <= 247})


def reconnect(probe: ModbusTcpProbe) -> bool:
    probe.disconnect()
    ok, message = probe.connect()
    print(f"      (reconectando) {message}")
    return ok


def cmd_scan(
    probe: ModbusTcpProbe,
    slaves: List[int],
    func: int,
    address: int,
    probe_timeout: float,
) -> List[int]:
    """Barre slave IDs. Cuenta como 'vivo' un ID que responde datos O excepcion."""
    print()
    print(
        f"  Barriendo slave IDs {slaves[0]}..{slaves[-1]} ({len(slaves)} IDs, "
        f"{probe.framing.upper()}, FC{func:02d}, 0x{address:04X})"
    )
    print(f"  Peor caso si nadie responde: ~{len(slaves) * probe_timeout:.0f} s")
    counts: Dict[str, int] = {}
    found: List[int] = []
    for slave_id in slaves:
        r = probe.read(slave_id, address, 1, func, retries=0, timeout=probe_timeout)
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.status == "ok":
            found.append(slave_id)
            print(
                f"    ID {slave_id:<4} RESPONDE  (0x{address:04X} = {r.values[0]})"
                f"  [{r.latency_ms:.0f} ms]"
            )
        elif r.status == "exception":
            found.append(slave_id)
            print(f"    ID {slave_id:<4} VIVO, pero contesta {r.describe()}")
        elif r.status == "garbage":
            print(f"    ID {slave_id:<4} basura: {r.note}  RX={hexs(r.rx)}")
        elif r.status == "error":
            print(f"    ID {slave_id:<4} error: {r.note}")
            if not reconnect(probe):
                break
    if found:
        print(f"    Encontrados: {found}")
    else:
        print("    Ningun ID responde.")
        print_diagnosis(counts, probe.unsolicited)
    return found


def read_block_adaptive(
    probe: ModbusTcpProbe, slave_id: int, base: int, count: int, func: int
) -> Tuple[List[Optional[int]], Result]:
    """
    Lee un bloque. Si el equipo contesta excepcion de direccion/cantidad lo parte
    en mitades hasta aislar que direcciones SI existen. Lo que no se puede leer
    queda como None (nunca como 0).
    """
    r = probe.read(slave_id, base, count, func, retries=1)
    if r.status == "ok":
        return list(r.values or []), r
    if r.status == "exception" and r.exc_code in (0x02, 0x03) and count > 1:
        mid = count // 2
        left, rl = read_block_adaptive(probe, slave_id, base, mid, func)
        right, rr = read_block_adaptive(probe, slave_id, base + mid, count - mid, func)
        return left + right, (rl if rl.status != "ok" else rr)
    return [None] * count, r


def cmd_dump(
    probe: ModbusTcpProbe,
    slave_id: int,
    start: int,
    count: int,
    block: int = 60,
    func: int = FUNC_READ_HOLDING,
    full: bool = False,
):
    """Vuelca un rango de registros, partiendo en bloques."""
    print()
    print(
        f"  Volcando 0x{start:04X}..0x{start + count - 1:04X} ({count} registros) "
        f"en slave {slave_id}, FC{func:02d}, {probe.framing.upper()}..."
    )

    all_registers: List[Optional[int]] = []
    counts: Dict[str, int] = {}
    base = start
    remaining = count
    while remaining > 0:
        chunk = min(block, remaining)
        values, rep = read_block_adaptive(probe, slave_id, base, chunk, func)
        got = sum(1 for v in values if v is not None)
        if got == chunk:
            print(f"    0x{base:04X} +{chunk:<3} OK")
            counts["ok"] = counts.get("ok", 0) + 1
        elif got > 0:
            print(
                f"    0x{base:04X} +{chunk:<3} PARCIAL: {got}/{chunk} registros existen "
                f"(el resto: {rep.describe()})"
            )
            counts["ok"] = counts.get("ok", 0) + 1
        else:
            print(f"    0x{base:04X} +{chunk:<3} FALLO: {rep.describe()}")
            counts[rep.status] = counts.get(rep.status, 0) + 1
        all_registers.extend(values)
        base += chunk
        remaining -= chunk

    got_total = sum(1 for v in all_registers if v is not None)
    if got_total == 0:
        print()
        print("  No se pudo leer ningun registro.")
        print_diagnosis(counts, probe.unsolicited)
        return

    print(f"\n  Registros leidos: {got_total}/{count}")
    print_register_dump(all_registers, start, [CLASSIC_MAP, IVGM_8K_MAP], full)
    print_map_comparison(all_registers, start)
    print_verdict(all_registers, start)



# Zonas donde se ha visto actividad en equipos Felicity (tiempo real 0x1100,
# ajustes 0x2xxx, info del equipo 0xF800, BMS 0x13xx). "completo" barre todo.
ZONAS_CONOCIDAS = [
    (0x0000, 0x01FF),
    (0x1000, 0x17FF),
    (0x2000, 0x27FF),
    (0xF800, 0xF8FF),
]
SPACE_FULL = [(0x0000, 0xFFFF)]


def parse_ranges(text: str) -> List[Tuple[int, int]]:
    """'zonas' | 'completo' | '0x1000-0x13FF,0x2100-0x21FF'"""
    t = text.strip().lower()
    if t in ("zonas", ""):
        return list(ZONAS_CONOCIDAS)
    if t in ("completo", "todo", "full"):
        return list(SPACE_FULL)
    out: List[Tuple[int, int]] = []
    for part in text.split(","):
        a, b = part.split("-", 1)
        lo, hi = parse_int(a), parse_int(b)
        out.append((min(lo, hi), min(max(lo, hi), 0xFFFF)))
    return out


def explore_block(
    probe: ModbusTcpProbe,
    slave_id: int,
    base: int,
    count: int,
    func: int,
    stats: Dict[str, int],
    read_timeout: float,
) -> List[Optional[int]]:
    """
    Lee un bloque de forma economica:
      1. intenta leerlo entero;
      2. si el equipo contesta excepcion, MUESTREA 5 puntos sueltos: si ninguno
         existe, da el bloque por vacio (1 + 5 peticiones en vez de ~120);
      3. si hay algo, lo parte en mitades y repite; en bloques <= 4 lee de a uno.
    Limite honesto: un registro aislado que no caiga en los 5 puntos de muestreo
    de un bloque por lo demas vacio puede escaparse (use --start/--count ahi).
    """
    r = probe.read(slave_id, base, count, func, retries=1, timeout=read_timeout)
    stats["requests"] += 1
    stats[r.status] = stats.get(r.status, 0) + 1
    if r.status == "ok":
        return list(r.values or [])
    if r.status == "exception" and r.exc_code in (0x02, 0x03):
        if count == 1:
            return [None]
        if count > 4:
            offsets = sorted({0, count // 4, count // 2, (3 * count) // 4, count - 1})
            hit = False
            for off in offsets:
                rr = probe.read(slave_id, base + off, 1, func, retries=0, timeout=read_timeout)
                stats["requests"] += 1
                stats[rr.status] = stats.get(rr.status, 0) + 1
                if rr.status == "ok":
                    hit = True
                    break
            if not hit:
                stats["bloques_vacios"] = stats.get("bloques_vacios", 0) + 1
                return [None] * count
            mid = count // 2
            return explore_block(probe, slave_id, base, mid, func, stats, read_timeout) + \
                explore_block(probe, slave_id, base + mid, count - mid, func, stats, read_timeout)
        # 2..4 registros: de a uno
        out: List[Optional[int]] = []
        for off in range(count):
            out.extend(explore_block(probe, slave_id, base + off, 1, func, stats, read_timeout))
        return out
    if r.status == "exception" and r.exc_code == 0x01:
        stats["funcion_ilegal"] = 1
    return [None] * count


def group_regions(addresses: List[int]) -> List[Tuple[int, int]]:
    """[0x1100,0x1101,0x1105] -> [(0x1100,0x1101),(0x1105,0x1105)]"""
    regions: List[Tuple[int, int]] = []
    for a in sorted(addresses):
        if regions and a == regions[-1][1] + 1:
            regions[-1] = (regions[-1][0], a)
        else:
            regions.append((a, a))
    return regions


def labels_for(address: int) -> Tuple[str, str]:
    """Etiquetas de los dos mapas para una direccion (o '')."""
    def find(m: RegisterMap) -> Optional[FieldDef]:
        return next((f for f in m.fields.values() if f.address == address), None)
    c, i = find(CLASSIC_MAP), find(IVGM_8K_MAP)
    return (c.label if c else "", i.label if i else "")


def save_csv(path: str, found: Dict[int, int]):
    """Guarda TODOS los registros leidos (incluidos los que valen 0)."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["dir_hex", "dir_dec", "valor_dec", "valor_hex", "valor_con_signo",
                    "clasico_campo", "clasico_valor", "ivgm_campo", "ivgm_valor"])
        for address in sorted(found):
            v = found[address]
            c_f = next((f for f in CLASSIC_MAP.fields.values() if f.address == address), None)
            i_f = next((f for f in IVGM_8K_MAP.fields.values() if f.address == address), None)
            w.writerow([
                f"0x{address:04X}", address, v, f"0x{v:04X}", to_signed(v),
                c_f.label if c_f else "", fmt_field(v, c_f) if c_f else "",
                i_f.label if i_f else "", fmt_field(v, i_f) if i_f else "",
            ])


def cmd_todo(
    probe: ModbusTcpProbe,
    slave_id: int,
    func: int,
    ranges: List[Tuple[int, int]],
    block: int,
    probe_timeout: float,
    csv_path: str,
    full: bool,
):
    """Barre rangos de direcciones, junta TODO lo que exista y lo guarda en CSV."""
    total_regs = sum(hi - lo + 1 for lo, hi in ranges)
    est_blocks = sum(((hi - lo + 1) + block - 1) // block for lo, hi in ranges)
    print()
    print(f"  BARRIDO COMPLETO: slave {slave_id}, FC{func:02d}, {probe.framing.upper()}")
    print(f"  Rangos: " + ", ".join(f"0x{lo:04X}-0x{hi:04X}" for lo, hi in ranges)
          + f"  ({total_regs} direcciones, ~{est_blocks} bloques de {block})")
    est_s = est_blocks * 6 * 0.12
    print(f"  Solo LECTURAS (nunca escribe). Tiempo peor caso orientativo: ~{est_s:.0f} s "
          f"({est_s / 60:.1f} min). Ctrl+C para parar: se guarda lo leido hasta ese momento.")

    # Comprobacion previa: no gastar minutos si el equipo ni contesta
    pre = probe.read(slave_id, ranges[0][0], 1, func, retries=1, timeout=max(probe_timeout, 1.5))
    if pre.status in ("silent", "garbage", "error", "gateway"):
        print(f"\n  El equipo no responde a una lectura simple ({pre.describe()}).")
        print("  Primero logre comunicacion con --auto.")
        print_diagnosis({pre.status: 1}, probe.unsolicited)
        return

    stats: Dict[str, int] = {"requests": 0}
    found: Dict[int, int] = {}
    read_timeout = max(probe_timeout, 1.5)
    started = time.perf_counter()
    silent_run = 0
    interrupted = False
    try:
        for lo, hi in ranges:
            print(f"\n  Zona 0x{lo:04X}-0x{hi:04X} ...", end=" ", flush=True)
            before = len(found)
            base = lo
            done_blocks = 0
            while base <= hi:
                chunk = min(block, hi - base + 1)
                done_blocks += 1
                if done_blocks % 50 == 0:
                    print(f"{(base - lo) * 100 // (hi - lo + 1)}%", end=" ", flush=True)
                values = explore_block(probe, slave_id, base, chunk, func, stats, read_timeout)
                for i, v in enumerate(values):
                    if v is not None:
                        found[base + i] = v
                if stats.get("silent", 0) - silent_run >= 25 and not found:
                    raise RuntimeError("el equipo dejo de responder")
                silent_run = stats.get("silent", 0)
                if stats.get("funcion_ilegal"):
                    print("\n  El equipo dice FUNCION ILEGAL: pruebe --fc 4.")
                    raise RuntimeError("funcion ilegal")
                base += chunk
            print(f"{len(found) - before} registros")
    except KeyboardInterrupt:
        interrupted = True
        print("\n  Interrumpido: se guarda lo leido hasta ahora.")
    except RuntimeError as e:
        print(f"\n  Barrido detenido: {e}.")

    elapsed = time.perf_counter() - started
    print(f"\n  Terminado en {elapsed:.0f} s, {stats['requests']} peticiones"
          + (" (INCOMPLETO)" if interrupted else ""))

    if not found:
        print("  No se encontro ningun registro en esos rangos.")
        print_diagnosis({k: v for k, v in stats.items() if k in STATUS_TAG}, probe.unsolicited)
        return

    nonzero = [a for a, v in found.items() if v != 0]
    print(f"  Registros que existen: {len(found)}   (distintos de 0: {len(nonzero)})")
    print("\n  REGIONES CON DATOS")
    print("  " + "-" * 62)
    for lo, hi in group_regions(list(found)):
        n = hi - lo + 1
        nz = sum(1 for a in range(lo, hi + 1) if found[a] != 0)
        print(f"    0x{lo:04X}-0x{hi:04X}   {n:>4} registros   ({nz} distintos de 0)")

    print("\n  VALORES  (con signo = interpretacion int16; Clasico/IVGM = lo que dirian los mapas)")
    print("  " + "-" * 78)
    print(f"  {'Dir':<8}{'Dec':>7}  {'Hex':<8}{'Signo':>7}   {'Clasico':<22}{'IVGM-8K':<22}")
    hidden = 0
    for address in sorted(found):
        v = found[address]
        c_f = next((f for f in CLASSIC_MAP.fields.values() if f.address == address), None)
        i_f = next((f for f in IVGM_8K_MAP.fields.values() if f.address == address), None)
        if not full and v == 0 and c_f is None and i_f is None:
            hidden += 1
            continue
        c_txt = f"{c_f.label[:10]}={fmt_field(v, c_f)}" if c_f else "-"
        i_txt = f"{i_f.label[:10]}={fmt_field(v, i_f)}" if i_f else "-"
        print(f"  0x{address:04X}  {v:>7}  0x{v:04X}  {to_signed(v):>7}   {c_txt:<22}{i_txt:<22}")
    if hidden:
        print(f"  ({hidden} registros en 0 y sin mapa omitidos en pantalla; estan TODOS en el CSV)")

    save_csv(csv_path, found)
    print(f"\n  CSV con TODOS los registros: {csv_path}")
    print("  Abralo en Excel: compare con la pantalla del inversor (tension, SOC, PV,")
    print("  carga) para identificar que registro es cual y que escala lleva.\n")


def cmd_auto(
    probe: ModbusTcpProbe,
    slaves: List[int],
    funcs: List[int],
    probe_timeout: float,
    args: argparse.Namespace,
):
    """Prueba framing x slave x funcion x direccion hasta que algo responda."""
    framings = ["rtu", "mbap"]
    combos = len(framings) * len(slaves) * len(funcs) * len(AUTO_ADDRESSES)
    print()
    print(
        f"  AUTO: {combos} combinaciones (framing x slave x funcion x direccion), "
        f"peor caso ~{combos * probe_timeout:.0f} s"
    )
    print("  Leyenda: OK=datos  EXC=excepcion (equipo vivo)  GW=el conversor avisa que el")
    print("           inversor no responde  BAS=basura  -=silencio  ERR=error")

    counts: Dict[str, int] = {}
    found: Optional[Tuple[str, int, int, int]] = None
    alive: Optional[Tuple[str, int, int, int]] = None

    for index, framing in enumerate(framings):
        if index > 0:
            # Sesion TCP nueva: los bytes RTU pueden haber dejado a medias el
            # parser de un conversor en modo gateway.
            probe.disconnect()
            ok, _ = probe.connect()
            if not ok:
                print("    No se pudo reabrir la conexion TCP. Abortando.")
                print_diagnosis(counts, probe.unsolicited)
                return
        probe.framing = framing
        print(f"\n  [{framing.upper()}]")
        for slave_id in slaves:
            row = []
            for func in funcs:
                for address in AUTO_ADDRESSES:
                    r = probe.read(slave_id, address, 1, func, 0, probe_timeout)
                    counts[r.status] = counts.get(r.status, 0) + 1
                    row.append(f"{func:02d}@{address:04X}={STATUS_TAG[r.status]}")
                    if r.status == "error" and not reconnect(probe):
                        print("    No se pudo reconectar. Abortando.")
                        print_diagnosis(counts, probe.unsolicited)
                        return
                    if r.status == "ok":
                        found = (framing, slave_id, func, address)
                        break
                    if r.status == "exception" and alive is None:
                        alive = (framing, slave_id, func, address)
                if found:
                    break
            print(f"    slave {slave_id:<3} " + " ".join(row))
            if found:
                break
        if found:
            break

    if found:
        framing, slave_id, func, address = found
        probe.framing = framing
        print()
        print("  ENCONTRADO: el equipo responde con datos validos.")
        print(f"     framing = {framing}   slave = {slave_id}   funcion = {func}   direccion = 0x{address:04X}")
        print("  Para repetirlo:")
        print(
            f"     python verificar_rs485_v2.py --host {args.host} --port {args.port} "
            f"--framer {framing} --slave {slave_id} --fc {func} --start 0x1100 --count 80"
        )
        if not args.no_dump:
            cmd_dump(probe, slave_id, parse_int(args.start), args.count, args.block, func, args.full)
        return

    if alive is not None:
        framing, slave_id, func, address = alive
        probe.framing = framing
        print()
        print("  El equipo RESPONDE, pero solo con excepciones Modbus:")
        print(f"     framing = {framing}   slave = {slave_id}   funcion = {func}")
        print("  Voy a explorar que direcciones existen en el rango pedido...")
        if not args.no_dump:
            cmd_dump(probe, slave_id, parse_int(args.start), args.count, args.block, func, args.full)
        print_diagnosis(counts, probe.unsolicited)
        return

    print_diagnosis(counts, probe.unsolicited)


def cmd_raw(probe: ModbusTcpProbe, text: str, add_crc: bool):
    """Envia una trama escrita a mano y muestra la respuesta cruda."""
    cleaned = text.replace(",", " ").split()
    cleaned = [t[2:] if t.lower().startswith("0x") else t for t in cleaned]
    try:
        data = bytes.fromhex("".join(cleaned))
    except ValueError:
        print("  --raw: hexadecimal invalido. Ejemplo: --raw \"01 03 11 01 00 01\"")
        return
    if len(data) < 2:
        print("  --raw: la trama es demasiado corta.")
        return

    if add_crc:
        if probe.framing == "rtu":
            frame = data + calculate_crc(data)
        else:
            header = bytes(
                [0, probe._next_txid() & 0xFF, 0, 0, (len(data) >> 8) & 0xFF, len(data) & 0xFF]
            )
            frame = header + data
    else:
        frame = data

    print()
    print(f"  TX ({probe.framing.upper()}): {hexs(frame)}")
    rx = probe.send_raw(frame)
    print(f"  RX: {hexs(rx) if rx else '(nada)'}")

    # Interpretacion de mejor esfuerzo (solo lecturas 0x03/0x04)
    try:
        slave_id, func = data[0], data[1]
        count = (data[4] << 8) | data[5] if func in (3, 4) and len(data) >= 6 else 0
        if rx:
            r = classify(rx, slave_id, func, count, probe.framing)
            print(f"  Interpretacion: {r.describe()}")
            if r.status == "ok" and r.values:
                print("  Valores: " + "  ".join(f"{v}(0x{v:04X})" for v in r.values))
    except (IndexError, ValueError):
        pass
    print()


def cmd_sniff(probe: ModbusTcpProbe, seconds: float):
    """Solo escucha: sirve para ver si OTRO maestro habla en el bus."""
    print()
    print(f"  Escuchando {seconds:.0f} s sin enviar nada...")
    events = probe.listen(seconds)
    total = 0
    for when, chunk in events:
        total += len(chunk)
        print(f"    +{when:6.2f}s  {len(chunk):>3} bytes: {hexs(chunk)}")
    if not events:
        print("    Silencio total (normal si el inversor solo responde cuando le preguntan).")
    else:
        print(f"\n  Llegaron {total} bytes sin preguntar: hay otro maestro o el inversor")
        print("  transmite solo (apague la app Java / dongle WiFi y repita).")
    print()


def cmd_write(probe: ModbusTcpProbe, slave_id: int, address: int, value: int):
    """Escribe un registro con confirmacion."""
    print()
    print(f"  VA A ESCRIBIR: 0x{address:04X} = {value} en slave {slave_id}")
    print("  Esto modifica la configuracion del inversor.")
    answer = input("  Confirme con 'SI' para continuar: ").strip()
    if answer.upper() != "SI":
        print("  Cancelado.")
        return
    r = probe.write_single(slave_id, address, value)
    print(f"  {'OK' if r.status == 'ok' else 'FALLO'}: {r.describe()}  [{r.latency_ms:.0f} ms]")


# ══════════════════════════════════════════════════════════════════════════════
# PROGRAMA PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════


class Tee:
    """Copia todo lo que se imprime a un archivo (--out)."""

    def __init__(self, stream, path: str):
        self.stream = stream
        self.file = open(path, "w", encoding="utf-8")

    def write(self, text: str) -> int:
        self.stream.write(text)
        self.file.write(text)
        return len(text)

    def flush(self):
        self.stream.flush()
        self.file.flush()

    def close(self):
        self.file.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sonda de verificacion Modbus RTU sobre TCP/IP (v2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--host", default="192.168.1.50", help="IP del conversor")
    parser.add_argument("--port", type=int, default=502, help="Puerto TCP (502, 8899, 23...)")
    parser.add_argument(
        "--framer",
        choices=("mbap", "rtu"),
        default="mbap",
        help="mbap = Modbus TCP (conversor en modo gateway); "
        "rtu = trama RTU cruda tunelada por TCP (conversor transparente)",
    )
    parser.add_argument("--slave", type=int, default=1, help="Slave ID a consultar")
    parser.add_argument("--start", default="0x1100", help="Direccion inicial")
    parser.add_argument("--count", type=int, default=80, help="Cantidad de registros")
    parser.add_argument("--block", type=int, default=60, help="Tamano de bloque de lectura")
    parser.add_argument("--fc", type=int, choices=(3, 4), default=3,
                        help="Funcion: 3 = holding (default), 4 = input")
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="Timeout de lectura en segundos")
    parser.add_argument("--probe-timeout", type=float, default=0.8,
                        help="Timeout corto para --scan y --auto (segundos)")
    parser.add_argument("--slaves", default=None,
                        help="Slave IDs para --scan/--auto, ej: 1-10,31 "
                             "(scan: 1-32 por defecto; auto: 1-10)")
    parser.add_argument("--auto", action="store_true",
                        help="Prueba combinaciones solas y diagnostica")
    parser.add_argument("--quick", action="store_true",
                        help="Con --auto: solo slaves 1-3 y funcion 3")
    parser.add_argument("--no-dump", action="store_true",
                        help="Con --auto: no volcar registros al encontrar el equipo")
    parser.add_argument("--scan", action="store_true", help="Barre slave IDs")
    parser.add_argument("--todo", nargs="?", const="zonas", metavar="ZONA",
                        help="Lee TODOS los registros y los guarda en CSV. "
                             "ZONA: zonas (default) | completo (0x0000-0xFFFF, lento) | "
                             "rangos, ej: 0x1000-0x13FF,0x2000-0x21FF")
    parser.add_argument("--csv", metavar="ARCHIVO",
                        help="Con --todo: nombre del CSV (default registros_IP_fecha.csv)")
    parser.add_argument("--raw", metavar="HEX",
                        help="Envia una trama a mano. RTU: sin CRC (se agrega)")
    parser.add_argument("--no-crc", action="store_true",
                        help="Con --raw: enviar los bytes tal cual (ya incluyen CRC/MBAP)")
    parser.add_argument("--sniff", type=float, metavar="SEG",
                        help="Solo escucha SEG segundos")
    parser.add_argument("--write", nargs=2, metavar=("ADDR", "VALUE"),
                        help="Escribe un registro (peligroso, pide confirmacion)")
    parser.add_argument("--full", action="store_true",
                        help="Mostrar tambien registros en 0 sin mapa")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Mostrar cada trama enviada/recibida (hex)")
    parser.add_argument("--out", metavar="ARCHIVO",
                        help="Guardar tambien la salida en un archivo")
    return parser


def run(args: argparse.Namespace) -> int:
    probe = ModbusTcpProbe(args.host, args.port, args.framer, args.timeout, args.verbose)
    ok, message = probe.connect()
    if ok and args.auto:
        message = f"Conectado a {args.host}:{args.port} (modo auto: se prueban RTU y MBAP)"
    print(f"  {message}")
    if not ok:
        print("  Verifique IP y puerto en el panel web del conversor, y que su PC este")
        print("  en la misma red. Cierre otras herramientas que usen el conversor.")
        return 1

    try:
        if args.sniff is not None:
            cmd_sniff(probe, args.sniff)
        elif args.raw:
            cmd_raw(probe, args.raw, not args.no_crc)
        elif args.todo is not None:
            csv_path = args.csv or f"registros_{args.host.replace('.', '-')}_{datetime.now():%Y%m%d_%H%M%S}.csv"
            cmd_todo(probe, args.slave, args.fc, parse_ranges(args.todo), args.block,
                     args.probe_timeout, csv_path, args.full)
        elif args.write:
            cmd_write(probe, args.slave, parse_int(args.write[0]), parse_int(args.write[1]))
        elif args.auto:
            if args.quick:
                slaves = parse_slaves(args.slaves) if args.slaves else [1, 2, 3]
                funcs = [3]
            else:
                slaves = parse_slaves(args.slaves) if args.slaves else list(range(1, 11))
                funcs = [3, 4]
            cmd_auto(probe, slaves, funcs, args.probe_timeout, args)
        elif args.scan:
            slaves = parse_slaves(args.slaves) if args.slaves else list(range(1, 33))
            cmd_scan(probe, slaves, args.fc, parse_int(args.start), args.probe_timeout)
        else:
            cmd_dump(probe, args.slave, parse_int(args.start), args.count,
                     args.block, args.fc, args.full)
        if probe.unsolicited and not (args.auto or args.scan):
            print(f"  AVISO: llegaron {probe.unsolicited} bytes sin preguntar: hay otro")
            print("  maestro en el bus (app Java, dongle WiFi...). Solo puede haber uno.")
    finally:
        probe.disconnect()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    args = build_parser().parse_args(argv)

    tee: Optional[Tee] = None
    original_stdout = sys.stdout
    if args.out:
        tee = Tee(sys.stdout, args.out)
        sys.stdout = tee  # type: ignore[assignment]
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n  Interrumpido por el usuario.")
        return 130
    finally:
        sys.stdout = original_stdout
        if tee:
            tee.close()
            print(f"  Salida guardada en {args.out}")


if __name__ == "__main__":
    sys.exit(main())
