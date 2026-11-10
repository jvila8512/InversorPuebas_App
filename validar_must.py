#!/usr/bin/env python3
"""
validar_must.py — Sonda de validacion Modbus RTU para inversores MUST
=====================================================================
Valida contra el equipo real:
  1. El cableado (RS232 o RS485)
  2. Los parametros de linea (baud, paridad)
  3. El slave ID
  4. El mapa de registros (Bloque D: 0x6271-0x6293)

Soporta dos transportes:
  - RS232 directo:      --port COM3
  - RS485 via gateway:  --host 192.168.1.50 --tcp-port 502 --framing mbap
  - RS485 via USB:      --port COM4 --iface rs485

Uso:
    # RS232
    python validar_must.py --port COM3 --iface rs232

    # RS485 con gateway TCP (modo "Modbus TCP To RTU")
    python validar_must.py --host 192.168.1.50 --iface rs485 --framing mbap

    # RS485 con adaptador USB
    python validar_must.py --port COM4 --iface rs485

    # Buscar el slave ID
    python validar_must.py --host 192.168.1.50 --scan

Autor: InversorApp
Fecha: 2026-11-10
IMPORTANTE: el mapa MUST esta SIN VALIDAR contra hardware. Esta sonda existe
para confirmarlo. Compare los valores con la pantalla del inversor.
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
# MAPA DE REGISTROS MUST ("Bloque D" — telemetria)
# ══════════════════════════════════════════════════════════════════════════════
# ATENCION: sin validar contra hardware. Fuente: aggsoft "PV Inverter 3600".

MUST_START = 0x6271
MUST_COUNT = 0x6293 - 0x6271 + 1   # 35 registros

MUST_FIELDS: Dict[int, Tuple[str, str, float, bool, str]] = {
    0x6271: ("working_mode",        "Inverter Work State",       1.0,  False, ""),
    0x6275: ("battery_voltage",     "Battery Voltage",           0.1,  False, "V"),
    0x6276: ("output_voltage",      "Inverter Output Voltage",   0.1,  False, "V"),
    0x6277: ("grid_voltage",        "Grid Voltage",              0.1,  False, "V"),
    0x6279: ("battery_current",     "Battery Current",           0.1,  True,  "A"),
    0x627A: ("output_current",      "Inverter Output Current",   0.1,  True,  "A"),
    0x627D: ("inverter_power",      "Inverter Power",            1.0,  True,  "W"),
    0x627E: ("grid_power",          "Grid Power",                1.0,  True,  "W"),
    0x627F: ("output_active_power", "Load Power",                1.0,  True,  "W"),
    0x6280: ("load_percent",        "System Load Percentage",    1.0,  False, "%"),
    0x6283: ("battery_soc",         "Battery Capacity (SOC)",    1.0,  False, "%"),
}


# ══════════════════════════════════════════════════════════════════════════════
# CRC-16 MODBUS
# ══════════════════════════════════════════════════════════════════════════════

def calculate_crc(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def verify_crc(frame: bytes) -> bool:
    return len(frame) >= 3 and calculate_crc(frame[:-2]) == frame[-2:]


# ══════════════════════════════════════════════════════════════════════════════
# TRAMAS MODBUS
# ══════════════════════════════════════════════════════════════════════════════

FUNC_READ_HOLDING = 0x03
FUNC_WRITE_SINGLE = 0x06


def build_read_holding(slave_id: int, start: int, count: int,
                       framing: str = "mbap", txid: int = 1) -> bytes:
    pdu = bytes([FUNC_READ_HOLDING,
                 (start >> 8) & 0xFF, start & 0xFF,
                 (count >> 8) & 0xFF, count & 0xFF])
    if framing == "mbap":
        header = bytes([(txid >> 8) & 0xFF, txid & 0xFF, 0x00, 0x00,
                        0x00, len(pdu) + 1])
        return header + bytes([slave_id]) + pdu
    payload = bytes([slave_id]) + pdu
    return payload + calculate_crc(payload)


def parse_read_response(response: bytes, slave_id: int, count: int,
                        framing: str) -> Optional[List[int]]:
    if not response:
        return None

    if framing == "mbap":
        if len(response) < 9 or response[2:4] != b"\x00\x00":
            return None
        if response[6] != slave_id:
            return None
        pdu = response[7:]
        if len(pdu) < 2 or pdu[0] != FUNC_READ_HOLDING:
            return None
        if pdu[0] & 0x80:
            return None
        data = pdu[2:2 + pdu[1]]
    else:
        if len(response) < 5 or response[0] != slave_id:
            return None
        if not verify_crc(response):
            return None
        if response[1] != FUNC_READ_HOLDING:
            return None
        if response[1] & 0x80:
            return None
        data = response[3:3 + response[2]]

    if len(data) < count * 2:
        return None
    return [(data[i * 2] << 8) | data[i * 2 + 1] for i in range(count)]


# ══════════════════════════════════════════════════════════════════════════════
# TRANSPORTES
# ══════════════════════════════════════════════════════════════════════════════

class SerialTransport:
    """RS232 directo o RS485 mediante adaptador USB (aparece como COM)."""

    def __init__(self, port: str, baudrate: int = 2400, parity: str = "N",
                 stopbits: int = 1, bytesize: int = 8, timeout: float = 2.0):
        if serial is None:
            raise RuntimeError("pyserial no esta instalado: pip install pyserial")
        self.port = port
        self.baudrate = baudrate
        self.parity = {"N": serial.PARITY_NONE, "E": serial.PARITY_EVEN,
                       "O": serial.PARITY_ODD}.get(parity, serial.PARITY_NONE)
        self.stopbits = stopbits
        self.bytesize = bytesize
        self.timeout = timeout
        self._ser = None

    def connect(self) -> Tuple[bool, str]:
        try:
            self._ser = serial.Serial(
                port=self.port, baudrate=self.baudrate, parity=self.parity,
                stopbits=self.stopbits, bytesize=self.bytesize,
                timeout=self.timeout, write_timeout=1.0,
            )
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

    def read_holding_registers(self, slave_id: int, start: int, count: int,
                               retries: int = 2) -> Tuple[Optional[List[int]], float]:
        for _ in range(retries + 1):
            frame = build_read_holding(slave_id, start, count, "rtu")
            try:
                self._ser.reset_input_buffer()
                t0 = time.perf_counter()
                self._ser.write(frame)
                response = self._recv(5 + count * 2)
                latency = (time.perf_counter() - t0) * 1000
            except Exception:
                continue
            if response is None:
                continue
            values = parse_read_response(response, slave_id, count, "rtu")
            if values is not None:
                return values, latency
        return None, 0.0

    def _recv(self, expected: int) -> Optional[bytes]:
        """Lee exactamente `expected` bytes (no registros)."""
        buffer = bytearray()
        deadline = time.perf_counter() + self.timeout
        while len(buffer) < expected and time.perf_counter() < deadline:
            chunk = self._ser.read(min(expected - len(buffer), 256))
            if chunk:
                buffer.extend(chunk)
            elif buffer:
                break
        return bytes(buffer) if buffer else None


class TcpTransport:
    """RS485 (o RS232) a traves de un gateway TCP/IP."""

    def __init__(self, host: str, port: int = 502, framing: str = "mbap",
                 timeout: float = 3.0):
        self.host = host
        self.port = port
        self.framing = framing
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._txid = 0

    def connect(self) -> Tuple[bool, str]:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect((self.host, self.port))
            return True, (f"Conectado a {self.host}:{self.port} "
                          f"(Modbus {self.framing.upper()})")
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

    def read_holding_registers(self, slave_id: int, start: int, count: int,
                               retries: int = 2) -> Tuple[Optional[List[int]], float]:
        self._txid = (self._txid + 1) & 0xFFFF
        frame = build_read_holding(slave_id, start, count, self.framing, self._txid)
        expected = (9 if self.framing == "mbap" else 5) + count * 2

        for _ in range(retries + 1):
            try:
                t0 = time.perf_counter()
                self._sock.sendall(frame)
                response = self._recv(expected)
                latency = (time.perf_counter() - t0) * 1000
            except Exception:
                continue
            if response is None:
                continue
            values = parse_read_response(response, slave_id, count, self.framing)
            if values is not None:
                return values, latency
        return None, 0.0

    def _recv(self, expected: int) -> Optional[bytes]:
        buffer = bytearray()
        deadline = time.perf_counter() + self.timeout
        while len(buffer) < expected and time.perf_counter() < deadline:
            try:
                chunk = self._sock.recv(min(expected - len(buffer), 256))
            except socket.timeout:
                break
            except OSError:
                return None
            if not chunk:
                return None
            buffer.extend(chunk)
        return bytes(buffer) if buffer else None


# ══════════════════════════════════════════════════════════════════════════════
# INTERPRETACION Y VEREDICTO
# ══════════════════════════════════════════════════════════════════════════════

def to_signed(value: int) -> int:
    return value - 0x10000 if value >= 0x8000 else value


def interpret(registers: List[int], start: int) -> Dict[int, int]:
    return {start + i: v for i, v in enumerate(registers)}


def print_report(registers: List[int], start: int, latency: float):
    """Imprime el volcado con la interpretacion del mapa MUST."""
    by_address = interpret(registers, start)

    print()
    print("  Volcado de registros MUST (Bloque D)")
    print("  " + "=" * 62)
    print(f"  {'Direccion':<12}{'Valor':<8}{'Hex':<8}{'Campo':<26}{'Interpretacion'}")
    print("  " + "-" * 62)

    for addr in sorted(by_address):
        value = by_address[addr]
        field = MUST_FIELDS.get(addr)
        if field is None:
            print(f"  0x{addr:04X}      {value:<8}0x{value:04X}   {'—':<26}—")
            continue
        key, label, scale, signed, unit = field
        shown = to_signed(value) * scale if signed else value * scale
        text = f"{shown:.2f}{unit}" if scale != 1.0 else f"{shown:.0f}{unit}"
        print(f"  0x{addr:04X}      {value:<8}0x{value:04X}   {label:<26}{text}")

    print(f"\n  Latencia de lectura: {latency:.0f} ms")


def verdict(registers: List[int], start: int) -> List[str]:
    """Chequeos de coherencia fisica del mapa MUST."""
    by_address = interpret(registers, start)
    notas = []

    def get(key: str) -> Optional[float]:
        for addr, (k, _l, _s, _sg, _u) in MUST_FIELDS.items():
            if k == key:
                v = by_address.get(addr)
                if v is None:
                    return None
                _k, _l, scale, signed, _u = MUST_FIELDS[addr]
                return (to_signed(v) if signed else v) * scale
        return None

    bat = get("battery_voltage")
    soc = get("battery_soc")
    load = get("load_percent")
    grid = get("grid_voltage")

    if bat is not None:
        ok = 30.0 <= bat <= 70.0
        notas.append(f"  [{'OK ' if ok else '?? '}] Bateria {bat:.1f} V "
                     f"(esperado 30-70 V)")
    if soc is not None:
        ok = 0.0 <= soc <= 100.0
        notas.append(f"  [{'OK ' if ok else '?? '}] SOC {soc:.0f} % "
                     f"(esperado 0-100 %)")
    if load is not None:
        ok = 0.0 <= load <= 100.0
        notas.append(f"  [{'OK ' if ok else '?? '}] Carga {load:.0f} % "
                     f"(esperado 0-100 %)")
    if grid is not None:
        ok = 0.0 <= grid <= 300.0
        notas.append(f"  [{'OK ' if ok else '?? '}] Red {grid:.1f} V "
                     f"(esperado 0-300 V)")

    return notas


# ══════════════════════════════════════════════════════════════════════════════
# COMANDOS
# ══════════════════════════════════════════════════════════════════════════════

def cmd_scan(transport, start: int = 1, end: int = 31):
    """Barre slave IDs. MUST usa 1-31 (31 es broadcast)."""
    print()
    print(f"  Barriendo slave IDs {start}..{end}...")
    encontrados = []
    for slave_id in range(start, end + 1):
        values, latency = transport.read_holding_registers(
            slave_id, MUST_START, 1
        )
        if values is not None:
            encontrados.append(slave_id)
            print(f"    ID {slave_id:<4} responde (0x{MUST_START:04X} = {values[0]}) "
                  f"[{latency:.0f} ms]")
    if not encontrados:
        print("    Ningun ID responde.")
        print("    Revisar: cableado, terminacion 120 ohm, baud, paridad, "
              "alimentacion.")
    else:
        print(f"    Encontrados: {encontrados}")
    return encontrados


def cmd_dump(transport, slave_id: int, start: int = MUST_START,
             count: int = MUST_COUNT, block: int = 35):
    """Vuelca el bloque de telemetria MUST."""
    print()
    print(f"  Volcando 0x{start:04X}..0x{start + count - 1:04X} "
          f"({count} registros) en slave {slave_id}...")

    all_registers: List[int] = []
    base = start
    remaining = count
    ultima_latencia = 0.0

    while remaining > 0:
        chunk = min(block, remaining)
        values, latency = transport.read_holding_registers(slave_id, base, chunk)
        ultima_latencia = latency
        if values is None:
            print(f"    Fallo en 0x{base:04X} ({chunk} registros)")
            all_registers.extend([0] * chunk)
        else:
            all_registers.extend(values)
            print(f"    0x{base:04X} +{chunk:<3} OK [{latency:.0f} ms]")
        base += chunk
        remaining -= chunk

    print_report(all_registers, start, ultima_latencia)

    print()
    print("  VEREDICTO")
    print("  " + "-" * 62)
    for nota in verdict(all_registers, start):
        print(nota)
    print()
    print("  Compare estos valores con la pantalla del inversor.")
    print("  Si no coinciden, el mapa MUST (0x6271-0x6293) debe corregirse.")
    print()


def verify_write_response(response: Optional[bytes], framing: str, slave_id: int,
                          address: int, value: int) -> Tuple[bool, str]:
    """Valida el eco de la escritura (func, slave, direccion, valor, CRC)."""
    if not response:
        return False, "sin respuesta"
    if framing == "mbap":
        if len(response) < 12:
            return False, f"respuesta incompleta ({len(response)} bytes, se esperaban 12)"
        if response[2:4] != b"\x00\x00":
            return False, "protocol id != 0 (no es Modbus TCP)"
        if response[6] != slave_id:
            return False, f"slave {response[6]} != {slave_id}"
        func_index = 7
    else:
        if len(response) < 8:
            return False, f"respuesta incompleta ({len(response)} bytes, se esperaban 8)"
        if not verify_crc(response):
            return False, "CRC invalido"
        if response[0] != slave_id:
            return False, f"slave {response[0]} != {slave_id}"
        func_index = 1

    if response[func_index] != FUNC_WRITE_SINGLE:
        return False, (f"codigo de funcion {response[func_index]} "
                       f"!= {FUNC_WRITE_SINGLE} (0x06)")
    echo_addr = (response[func_index + 1] << 8) | response[func_index + 2]
    echo_val = (response[func_index + 3] << 8) | response[func_index + 4]
    if echo_addr != address:
        return False, f"direccion eco {echo_addr:#06x} != {address:#06x}"
    if echo_val != value:
        return False, f"valor eco {echo_val} != {value}"
    return True, "eco correcto"


def cmd_write(transport, slave_id: int, address: int, value: int):
    """Escribe un registro (peligroso, pide confirmacion)."""
    print()
    print(f"  VA A ESCRIBIR: 0x{address:04X} = {value} en slave {slave_id}")
    if input("  Confirme con 'SI': ").strip().upper() != "SI":
        print("  Cancelado.")
        return
    pdu = bytes([FUNC_WRITE_SINGLE,
                 (address >> 8) & 0xFF, address & 0xFF,
                 (value >> 8) & 0xFF, value & 0xFF])
    if isinstance(transport, TcpTransport):
        framing = transport.framing
        transport._txid = (transport._txid + 1) & 0xFFFF
        txid = transport._txid
        header = bytes([(txid >> 8) & 0xFF, txid & 0xFF, 0x00, 0x00,
                        0x00, len(pdu) + 1])
        payload = header + bytes([slave_id]) + pdu
        expected = 12
    else:
        framing = "rtu"
        payload = bytes([slave_id]) + pdu
        payload += calculate_crc(payload)
        expected = 8

    try:
        t0 = time.perf_counter()
        if isinstance(transport, TcpTransport):
            transport._sock.sendall(payload)
            response = transport._recv(expected)
        else:
            transport._ser.reset_input_buffer()
            transport._ser.write(payload)
            response = transport._recv(expected)
        latency = (time.perf_counter() - t0) * 1000
    except Exception as e:
        print(f"  FALLO: {e}")
        return

    ok, detalle = verify_write_response(response, framing, slave_id, address, value)
    print(f"  {'OK' if ok else 'FALLO'} [{latency:.0f} ms]  {detalle}")


def parse_int(text: str) -> int:
    return int(text, 16) if text.lower().startswith("0x") else int(text)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Sonda de validacion Modbus RTU para inversores MUST",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    grupo_transporte = p.add_argument_group("transporte")
    grupo_transporte.add_argument("--port", help="Puerto serie (RS232 o USB-RS485)")
    grupo_transporte.add_argument("--host", help="IP del gateway TCP")
    grupo_transporte.add_argument("--tcp-port", type=int, default=502,
                                  help="Puerto TCP del gateway (defecto 502)")
    grupo_transporte.add_argument("--framing", choices=("mbap", "rtu"),
                                  default="mbap",
                                  help="mbap = Modbus TCP (gateway 'Modbus TCP "
                                       "To RTU'); rtu = RTU tunelado (gateway "
                                       "transparente)")
    grupo_transporte.add_argument("--iface", choices=("rs232", "rs485"),
                                  default="rs485",
                                  help="Tipo de interfaz fisica")

    grupo_linea = p.add_argument_group("linea serie")
    grupo_linea.add_argument("--baud", type=int, default=2400)
    grupo_linea.add_argument("--parity", default="N", choices=("N", "E", "O"))
    grupo_linea.add_argument("--stopbits", type=int, default=1)
    grupo_linea.add_argument("--timeout", type=float, default=2.0)

    grupo_accion = p.add_argument_group("accion")
    grupo_accion.add_argument("--slave", type=int, default=1)
    grupo_accion.add_argument("--scan", action="store_true",
                              help="Barre slave IDs 1..31")
    grupo_accion.add_argument("--start", default="0x6271")
    grupo_accion.add_argument("--count", type=int, default=MUST_COUNT)
    grupo_accion.add_argument("--write", nargs=2, metavar=("ADDR", "VALUE"))

    args = p.parse_args(argv)

    # Transporte
    if args.host:
        transport = TcpTransport(args.host, args.tcp_port, args.framing,
                                 args.timeout)
    elif args.port:
        transport = SerialTransport(args.port, args.baud, args.parity,
                                    args.stopbits, timeout=args.timeout)
    else:
        p.error("Especifica --port (serie) o --host (gateway TCP)")

    print(f"  Interfaz: {args.iface.upper()}")
    if args.iface == "rs485":
        print("  Cableado RS485: A=D+ / B=D- / GND, terminacion 120 ohm.")

    ok, msg = transport.connect()
    print(f"  {msg}")
    if not ok:
        return 1

    try:
        if args.scan:
            cmd_scan(transport)
        elif args.write:
            cmd_write(transport, args.slave, parse_int(args.write[0]),
                      parse_int(args.write[1]))
        else:
            cmd_dump(transport, args.slave, parse_int(args.start), args.count)
    finally:
        transport.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
