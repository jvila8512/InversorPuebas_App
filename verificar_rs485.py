#!/usr/bin/env python3
"""
verificar_rs485.py — Sonda de verificacion Modbus RTU sobre TCP/IP
==================================================================
Herramienta independiente (no depende de la app) para verificar, contra el
inversor real, la cadena completa:

    inversor --(RS485)--> conversor --(TCP)--> esta sonda

Responde estas preguntas antes de tocar la app:
  1. ¿El cableado y la terminacion estan bien?
  2. ¿El conversor espera RTU crudo o Modbus TCP (MBAP)?
  3. ¿Que slave ID responde?
  4. ¿Que mapa de registros tiene este equipo: clasico o IVGM-8K?

Uso:
    python verificar_rs485.py --host 192.168.1.50 --port 502
    python verificar_rs485.py --host 192.168.1.50 --framer rtu --scan
    python verificar_rs485.py --host 192.168.1.50 --slave 1 --start 0x1100 --count 80

Autor: InversorApp
Fecha: 2026-11-09
Version: 1.1 (fixes: dead exception check, fast _recv, probe_slave, verdict)
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
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
# NOTA: battery_soc se ha añadido como PROVISIONAL (0x110B) para que el
#       veredicto pueda usar coherencia cruzada. Confirmar contra hardware.
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
        "battery_soc":      FieldDef(0x110B, "Battery SOC", 1.0, False, "%"),  # PROVISIONAL
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
# CONSTRUCCION DE TRAMAS
# ══════════════════════════════════════════════════════════════════════════════

FUNC_READ_HOLDING = 0x03
FUNC_WRITE_SINGLE = 0x06


def build_read_holding(
    slave_id: int,
    start_address: int,
    count: int,
    framing: str = "mbap",
    transaction_id: int = 1,
) -> bytes:
    """Construye la trama de lectura de registros holding (funcion 0x03)."""
    pdu = bytes(
        [
            FUNC_READ_HOLDING,
            (start_address >> 8) & 0xFF,
            start_address & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
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
    elif framing == "rtu":
        payload = bytes([slave_id]) + pdu
        return payload + calculate_crc(payload)
    raise ValueError(f"Framing no soportado: {framing}")


def build_write_single(
    slave_id: int,
    register_address: int,
    value: int,
    framing: str = "mbap",
    transaction_id: int = 1,
) -> bytes:
    """Construye la trama de escritura de un registro (funcion 0x06)."""
    pdu = bytes(
        [
            FUNC_WRITE_SINGLE,
            (register_address >> 8) & 0xFF,
            register_address & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ]
    )
    if framing == "mbap":
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
    elif framing == "rtu":
        payload = bytes([slave_id]) + pdu
        return payload + calculate_crc(payload)
    raise ValueError(f"Framing no soportado: {framing}")


def parse_read_response(
    response: bytes,
    slave_id: int,
    count: int,
    framing: str,
) -> Optional[List[int]]:
    """
    Interpreta la respuesta de una lectura.
    Devuelve la lista de valores (int) o None si la trama no es valida.

    FIX v1.1: el chequeo de excepcion Modbus (bit 0x80) se hace ANTES de
    comparar el function code, para evitar codigo muerto y diagnosticar mejor.
    """
    if not response:
        return None

    # Indice del byte de funcion segun framing
    idx_func = 1 if framing == "rtu" else 7
    if len(response) <= idx_func:
        return None

    # Excepcion Modbus: bit 0x80 activo en el function code.
    # Devolvemos None (comportamiento actual), pero el diagnostico
    # esta disponible via probe_slave().
    if response[idx_func] & 0x80:
        return None

    if framing == "mbap":
        if len(response) < 8:
            return None
        # MBAP: txid(2) + protoid(2) + len(2) + unit(1) + pdu...
        if response[2:4] != b"\x00\x00":
            return None
        unit_id = response[6]
        pdu = response[7:]
        if unit_id != slave_id:
            return None
        if len(pdu) < 2 or pdu[0] != FUNC_READ_HOLDING:
            return None
        byte_count = pdu[1]
        data = pdu[2:2 + byte_count]
    else:
        if len(response) < 5:
            return None
        if response[0] != slave_id:
            return None
        if not verify_crc(response):
            return None
        if response[1] != FUNC_READ_HOLDING:
            return None
        byte_count = response[2]
        data = response[3:3 + byte_count]

    if len(data) < count * 2:
        return None

    registers = []
    for i in range(count):
        offset = i * 2
        registers.append((data[offset] << 8) | data[offset + 1])
    return registers


# ══════════════════════════════════════════════════════════════════════════════
# TRANSPORTE TCP
# ══════════════════════════════════════════════════════════════════════════════


class ModbusTcpProbe:
    """Sonda Modbus RTU sobre TCP con framing conmutable."""

    # FIX v1.1: timeout inter-byte corto para respuestas cortas (excepciones)
    INTER_BYTE_TIMEOUT = 0.2

    def __init__(
        self,
        host: str,
        port: int = 502,
        framing: str = "mbap",
        timeout: float = 3.0,
    ):
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
        except socket.timeout:
            self._socket = None
            return False, f"Timeout conectando a {self.host}:{self.port}"
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

    def probe_slave(self, slave_id: int) -> Tuple[bool, str]:
        """
        FIX v1.1: sondea un slave ID y distingue:
          - (False, "Sin respuesta")       -> esclavo muerto o mal cableado
          - (True,  "Respuesta OK ...")    -> esclavo vivo con datos
          - (True,  "Excepcion 0xNN ...")  -> esclavo VIVO pero rechaza la lectura
        """
        if self._socket is None:
            return False, "Sin conexion"

        frame = build_read_holding(
            slave_id, 0x1100, 1, self.framing, self._next_txid()
        )
        # Tamano esperado: RTU = 5 (normal) o 5 (excepcion), MBAP = 9 o 9
        expected = 5 if self.framing == "rtu" else 9
        try:
            self._socket.sendall(frame)
            resp = self._recv(expected)
        except OSError as e:
            return False, str(e)

        if not resp:
            return False, "Sin respuesta"

        idx_func = 1 if self.framing == "rtu" else 7
        if len(resp) <= idx_func:
            return False, "Respuesta truncada"

        if resp[idx_func] & 0x80:
            idx_code = idx_func + 1
            code = resp[idx_code] if len(resp) > idx_code else 0xFF
            return True, f"Excepcion 0x{code:02X} (esclavo vivo)"

        # Respuesta normal: extraer primer registro
        if self.framing == "rtu":
            value = (resp[3] << 8) | resp[4] if len(resp) >= 5 else 0
        else:
            value = (resp[9] << 8) | resp[10] if len(resp) >= 11 else 0
        return True, f"Respuesta OK (0x1100={value})"

    def read_holding_registers(
        self,
        slave_id: int,
        start_address: int,
        count: int,
        retries: int = 2,
    ) -> Tuple[Optional[List[int]], float]:
        """
        Lee registros. Devuelve (valores, latencia_ms) o (None, latencia_ms).
        """
        if self._socket is None:
            return None, 0.0

        frame = build_read_holding(
            slave_id, start_address, count, self.framing, self._next_txid()
        )
        expected = (
            3 + (count * 2) + 2
            if self.framing == "rtu"
            else 7 + 2 + (count * 2)
        )

        for _ in range(retries + 1):
            started = time.perf_counter()
            try:
                self._socket.sendall(frame)
                response = self._recv(expected)
            except OSError:
                continue
            latency = (time.perf_counter() - started) * 1000
            if response is None:
                continue
            values = parse_read_response(response, slave_id, count, self.framing)
            if values is not None:
                return values, latency
        return None, 0.0

    def _recv(self, expected_bytes: int) -> Optional[bytes]:
        """
        Recibe bytes del socket.

        FIX v1.1: el timeout completo se aplica SOLO al primer byte.
        Los bytes siguientes usan un timeout inter-byte corto (0.2 s),
        de modo que una respuesta corta (p.ej. excepcion de 5 bytes cuando
        se esperaban 125) retorna en ~200 ms en lugar de agotar los 3 s.
        Esto acelera drasticamente --scan.
        """
        if self._socket is None:
            return None

        original_timeout = self._socket.gettimeout()
        buffer = bytearray()
        try:
            # 1) Primer byte: timeout completo
            self._socket.settimeout(self.timeout)
            try:
                first = self._socket.recv(min(expected_bytes, 256))
            except socket.timeout:
                return None
            if not first:
                return None
            buffer.extend(first)

            # 2) Bytes restantes: timeout inter-byte corto
            self._socket.settimeout(self.INTER_BYTE_TIMEOUT)
            while len(buffer) < expected_bytes:
                try:
                    chunk = self._socket.recv(
                        min(expected_bytes - len(buffer), 256)
                    )
                except socket.timeout:
                    break  # fin natural: respuesta corta (p.ej. excepcion)
                except OSError:
                    return bytes(buffer) if buffer else None
                if not chunk:
                    break
                buffer.extend(chunk)
        finally:
            # Restaurar timeout original
            try:
                self._socket.settimeout(original_timeout)
            except OSError:
                pass

        return bytes(buffer) if buffer else None

    def write_single_register(
        self,
        slave_id: int,
        register_address: int,
        value: int,
    ) -> Tuple[bool, float, str]:
        """Escribe un registro. Devuelve (ok, latencia_ms, mensaje)."""
        if self._socket is None:
            return False, 0.0, "Sin conexion"

        frame = build_write_single(
            slave_id, register_address, value, self.framing, self._next_txid()
        )
        started = time.perf_counter()
        try:
            self._socket.sendall(frame)
            response = self._recv(8 if self.framing == "rtu" else 12)
        except OSError as e:
            return False, 0.0, str(e)

        latency = (time.perf_counter() - started) * 1000
        if response is None or len(response) < 5:
            return False, latency, "Sin respuesta"

        if self.framing == "rtu":
            if not verify_crc(response):
                return False, latency, "CRC invalido"
            if response[0] != slave_id:
                return False, latency, "Slave ID no coincide"
            if response[1] & 0x80:
                return False, latency, f"Excepcion Modbus: codigo {response[2]}"
            return True, latency, "OK"

        if response[6] != slave_id:
            return False, latency, "Slave ID no coincide"
        if response[7] & 0x80:
            return False, latency, f"Excepcion Modbus: codigo {response[9]}"
        return True, latency, "OK"


# ══════════════════════════════════════════════════════════════════════════════
# UTILIDADES DE INTERPRETACION
# ══════════════════════════════════════════════════════════════════════════════


def to_signed(value: int) -> int:
    """Convierte un valor de 16 bits sin signo a con signo."""
    return value - 0x10000 if value >= 0x8000 else value


def decode_registers(registers: List[int], start_address: int) -> Dict[int, int]:
    """Genera un diccionario {address: valor} a partir de una lista."""
    return {start_address + i: value for i, value in enumerate(registers)}


def print_register_dump(
    registers: List[int],
    start_address: int,
    maps: Optional[List[RegisterMap]] = None,
):
    """Imprime el volcado de registros e interpreta con cada mapa."""
    by_address = decode_registers(registers, start_address)

    print()
    print("  Direccion   Valor    Hex      " + "".join(
        f"{m.name:<12}" for m in (maps or [])
    ))
    print("  " + "-" * (28 + 12 * len(maps or [])))

    for address in sorted(by_address):
        value = by_address[address]
        cells = []
        for m in (maps or []):
            field = None
            for f in m.fields.values():
                if f.address == address:
                    field = f
                    break
            if field is None:
                cells.append("·")
                continue
            if field.signed:
                shown = to_signed(value) * field.scale
            else:
                shown = value * field.scale
            if field.scale == 1.0:
                cells.append(f"{shown:.0f}{field.unit}")
            else:
                cells.append(f"{shown:.2f}{field.unit}")
        print(
            f"  0x{address:04X}      {value:<7} 0x{value:04X}   "
            + "".join(f"{c:<12}" for c in cells)
        )


def print_map_comparison(registers: List[int], start_address: int):
    """Compara la interpretacion de los dos mapas para los campos clave."""
    by_address = decode_registers(registers, start_address)

    print()
    print("  COMPARACION DE MAPAS")
    print("  " + "-" * 62)
    print(f"  {'Campo':<20}{'Clasico':<22}{'IVGM-8K':<22}")
    print("  " + "-" * 62)

    keys = sorted(set(CLASSIC_MAP.fields) | set(IVGM_8K_MAP.fields))
    for key in keys:
        classic = CLASSIC_MAP.fields.get(key)
        ivgm = IVGM_8K_MAP.fields.get(key)
        if classic is None and ivgm is None:
            continue
        c_val = ""
        i_val = ""
        for field, target in ((classic, "c"), (ivgm, "i")):
            if field is None:
                continue
            value = by_address.get(field.address)
            if value is None:
                continue
            shown = (
                to_signed(value) * field.scale
                if field.signed
                else value * field.scale
            )
            text = (
                f"{shown:.0f}{field.unit}"
                if field.scale == 1.0
                else f"{shown:.2f}{field.unit}"
            )
            if target == "c":
                c_val = text
            else:
                i_val = text
        print(f"  {key:<20}{c_val:<22}{i_val:<22}")


def print_verdict(registers: List[int], start_address: int):
    """
    Intenta adivinar el mapa correcto segun la coherencia fisica de los valores.

    FIX v1.1: usa 3 heuristicas por mapa (bateria, SOC, PV) y coherencia
    cruzada (bateria entre 40-63 V y PV entre 100-600 V) para mayor fiabilidad.
    """
    by_address = decode_registers(registers, start_address)

    def plausible(value: float, low: float, high: float) -> bool:
        return low <= value <= high

    # ── Heuristicas IVGM-8K ───────────────────────────────────────────────
    ivgm_ok = 0
    ivgm_total = 0

    ivgm_bat = by_address.get(0x112C)
    ivgm_total += 1
    if ivgm_bat is not None and plausible(ivgm_bat * 0.1, 40.0, 63.0):
        ivgm_ok += 1

    ivgm_soc = by_address.get(0x1138)
    ivgm_total += 1
    if ivgm_soc is not None and plausible(ivgm_soc * 0.1, 0.0, 100.0):
        ivgm_ok += 1

    ivgm_pv = by_address.get(0x1118)
    ivgm_total += 1
    if ivgm_pv is not None and plausible(ivgm_pv * 0.1, 100.0, 600.0):
        ivgm_ok += 1

    # ── Heuristicas Clasico ───────────────────────────────────────────────
    cl_ok = 0
    cl_total = 0

    cl_bat = by_address.get(0x1108)
    cl_total += 1
    if cl_bat is not None and plausible(cl_bat * 0.01, 40.0, 63.0):
        cl_ok += 1

    cl_soc = by_address.get(0x110B)
    cl_total += 1
    if cl_soc is not None and plausible(cl_soc, 0.0, 100.0):
        cl_ok += 1

    cl_pv = by_address.get(0x1126)
    cl_total += 1
    if cl_pv is not None and plausible(cl_pv * 0.1, 100.0, 600.0):
        cl_ok += 1

    print()
    print("  VEREDICTO")
    print("  " + "-" * 62)
    print(f"  Coherencia IVGM-8K : {ivgm_ok}/{ivgm_total} valores plausibles")
    print(f"  Coherencia Clasico : {cl_ok}/{cl_total} valores plausibles")
    if ivgm_ok > cl_ok:
        print("  -> El mapa IVGM-8K parece el correcto para este equipo.")
    elif cl_ok > ivgm_ok:
        print("  -> El mapa CLASICO parece el correcto para este equipo.")
    else:
        print("  -> No se puede determinar. Compare los valores con la pantalla")
        print("     del inversor (tension de bateria, SOC, PV, red, carga).")
    print("  NOTA: battery_soc en CLASSIC_MAP es PROVISIONAL (0x110B).")
    print("        Si el veredicto es ambiguo, valide con el display del inversor.")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# COMANDOS PRINCIPALES
# ══════════════════════════════════════════════════════════════════════════════


def cmd_scan(probe: ModbusTcpProbe, start: int = 1, end: int = 247) -> List[int]:
    """
    Barre los slave IDs y devuelve los que responden.

    FIX v1.1: usa probe_slave() para detectar tambien esclavos que responden
    con EXCEPCION Modbus (p.ej. direccion 0x1100 no valida en ese modelo).
    Antes se marcaban como muertos (falso negativo).
    """
    print()
    print(f"  Barriendo slave IDs {start}..{end} ({probe.framing.upper()})...")
    found: List[int] = []
    for slave_id in range(start, end + 1):
        alive, detail = probe.probe_slave(slave_id)
        if alive:
            found.append(slave_id)
            print(f"    ID {slave_id:<4} {detail}")
    if not found:
        print("    Ningun ID responde.")
        print("    Revise: cableado, terminacion, baud, framing y alimentacion.")
        print("    Pruebe tambien --framer rtu si esta usando mbap.")
    else:
        print(f"    Encontrados: {found}")
    return found


def cmd_dump(
    probe: ModbusTcpProbe,
    slave_id: int,
    start: int,
    count: int,
    block: int = 60,
):
    """Vuelca un rango de registros, partiendo en bloques."""
    print()
    print(
        f"  Volcando 0x{start:04X}..0x{start + count - 1:04X} "
        f"({count} registros) en slave {slave_id}..."
    )

    all_registers: List[int] = []
    base = start
    remaining = count
    while remaining > 0:
        chunk = min(block, remaining)
        values, latency = probe.read_holding_registers(slave_id, base, chunk)
        if values is None:
            print(f"    Fallo en 0x{base:04X} ({chunk} registros) [{latency:.0f} ms]")
            all_registers.extend([0] * chunk)
        else:
            all_registers.extend(values)
            print(f"    0x{base:04X} +{chunk:<3} OK  [{latency:.0f} ms]")
        base += chunk
        remaining -= chunk

    print_register_dump(all_registers, start, [CLASSIC_MAP, IVGM_8K_MAP])
    print_map_comparison(all_registers, start)
    print_verdict(all_registers, start)


def cmd_write(probe: ModbusTcpProbe, slave_id: int, address: int, value: int):
    """Escribe un registro con confirmacion."""
    print()
    print(f"  VA A ESCRIBIR: 0x{address:04X} = {value} en slave {slave_id}")
    print("  Esto modifica la configuracion del inversor.")
    answer = input("  Confirme con 'SI' para continuar: ").strip()
    if answer.upper() != "SI":
        print("  Cancelado.")
        return
    ok, latency, message = probe.write_single_register(slave_id, address, value)
    estado = "OK" if ok else "FALLO"
    print(f"  {estado}: {message}  [{latency:.0f} ms]")


def parse_int(text: str) -> int:
    """Acepta decimal o hexadecimal (0x...)."""
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sonda de verificacion Modbus RTU sobre TCP/IP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--host", default="192.168.1.50", help="IP del conversor")
    parser.add_argument("--port", type=int, default=502, help="Puerto TCP")
    parser.add_argument(
        "--framer",
        choices=("mbap", "rtu"),
        default="mbap",
        help="mbap = Modbus TCP (lo esperan los conversores de campo); "
             "rtu = trama RTU cruda tunnelada por TCP",
    )
    parser.add_argument("--slave", type=int, default=1, help="Slave ID a consultar")
    parser.add_argument("--start", default="0x1100", help="Direccion inicial")
    parser.add_argument("--count", type=int, default=80, help="Cantidad de registros")
    parser.add_argument("--block", type=int, default=60, help="Tamano de bloque de lectura")
    parser.add_argument("--scan", action="store_true", help="Barre slave IDs 1..247")
    parser.add_argument("--timeout", type=float, default=3.0, help="Timeout en segundos")
    parser.add_argument(
        "--write",
        nargs=2,
        metavar=("ADDR", "VALUE"),
        help="Escribe un registro (peligroso, pide confirmacion)",
    )
    args = parser.parse_args(argv)

    probe = ModbusTcpProbe(args.host, args.port, args.framer, args.timeout)
    ok, message = probe.connect()
    print(f"  {message}")
    if not ok:
        return 1

    try:
        if args.scan:
            cmd_scan(probe)
        elif args.write:
            address = parse_int(args.write[0])
            value = parse_int(args.write[1])
            cmd_write(probe, args.slave, address, value)
        else:
            cmd_dump(probe, args.slave, parse_int(args.start), args.count, args.block)
    finally:
        probe.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())