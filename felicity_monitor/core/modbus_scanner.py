"""
modbus_scanner.py — Escáner de registros Modbus para inversores Felicity
========================================================================

Este script escanea TODOS los registros Modbus del inversor para descubrir
parámetros ocultos o no documentados.

 USO:
   python modbus_scanner.py COM3

 GUARDA LOS RESULTADOS EN:
   scanner_results_[timestamp].txt

========================================================================
"""

import time
import json
from datetime import datetime
from typing import Optional, dict, list
from dataclasses import dataclass, asdict
import serial
import serial.tools.list_ports


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES MODBUS
# ══════════════════════════════════════════════════════════════════════════════

SLAVE_ADDRESS = 0x01
FUNCTION_READ = 0x03
FUNCTION_WRITE = 0x06
READ_TIMEOUT_MS = 1000


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE CRC
# ══════════════════════════════════════════════════════════════════════════════

def calculate_crc(data: bytes) -> bytes:
    """CRC-16 Modbus (polynomial 0xA001, initial 0xFFFF)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return bytes([crc & 0xFF, (crc >> 8) & 0xFF])


# ══════════════════════════════════════════════════════════════════════════════
# CLASES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RegisterInfo:
    """Información de un registro Modbus."""
    address: int
    value: int
    hex_value: str
    classification: str
    possible_real_value: str
    notes: str = ""


@dataclass
class ScanResult:
    """Resultado de un escaneo."""
    timestamp: str
    port: str
    baudrate: int
    total_scanned: int
    registers_found: list
    writable_test: list


class ModbusConnection:
    """Conexión Modbus RTU básica para scanning."""

    def __init__(self, port: str, baudrate: int = 2400, timeout: float = 2.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial: Optional[serial.Serial] = None

    def connect(self) -> tuple[bool, str]:
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
            )
            return True, f"Conectado a {self.port}"
        except serial.SerialException as e:
            return False, str(e)

    def disconnect(self):
        if self._serial and self._serial.is_open:
            self._serial.close()

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def read_holding_registers(self, start_address: int, count: int) -> Optional[list]:
        """Lee registros holding."""
        if not self.is_open:
            return None

        try:
            frame = bytearray([
                SLAVE_ADDRESS,
                FUNCTION_READ,
                (start_address >> 8) & 0xFF,
                start_address & 0xFF,
                (count >> 8) & 0xFF,
                count & 0xFF,
            ])
            crc = calculate_crc(bytes(frame))
            frame.extend(crc)

            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            self._serial.write(frame)

            # Leer respuesta
            buffer = bytearray()
            start_time = time.time()

            while len(buffer) < 3 + (count * 2) + 2:
                if (time.time() - start_time) * 1000 > READ_TIMEOUT_MS:
                    return None if len(buffer) < 5 else bytes(buffer)

                if self._serial.in_waiting > 0:
                    chunk = self._serial.read(min(self._serial.in_waiting, 64))
                    buffer.extend(chunk)
                else:
                    time.sleep(0.01)

            response = bytes(buffer)
            if len(response) < 5:
                return None

            if response[0] != SLAVE_ADDRESS or response[1] != FUNCTION_READ:
                return None

            if response[1] & 0x80:  # Exception
                return None

            byte_count = response[2]
            registers = []
            for i in range(count):
                offset = 3 + (i * 2)
                if offset + 1 < len(response):
                    value = (response[offset] << 8) | response[offset + 1]
                    registers.append(value)

            return registers

        except serial.SerialException:
            return None

    def write_single_register(self, address: int, value: int) -> tuple[bool, str]:
        """Escribe un registro (para probar si es escribible)."""
        if not self.is_open:
            return False, "No conectado"

        try:
            frame = bytearray([
                SLAVE_ADDRESS,
                FUNCTION_WRITE,
                (address >> 8) & 0xFF,
                address & 0xFF,
                (value >> 8) & 0xFF,
                value & 0xFF,
            ])
            crc = calculate_crc(bytes(frame))
            frame.extend(crc)

            self._serial.reset_input_buffer()
            self._serial.write(frame)
            time.sleep(0.2)

            # Leer respuesta
            response = self._serial.read(8)
            if len(response) >= 5 and response[0] == SLAVE_ADDRESS and response[1] == FUNCTION_WRITE:
                return True, "OK"
            return False, f"Respuesta inesperada: {response.hex()}"

        except serial.SerialException as e:
            return False, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# CLASIFICADOR DE VALORES
# ══════════════════════════════════════════════════════════════════════════════

def classify_value(value: int, address: int) -> tuple[str, str, str]:
    """
    Clasifica un valor según su rango y dirección.
    Retorna: (clasificación, valor_real, notas)
    """
    notes = []

    # Rangos de voltaje (típicamente /10)
    if 2000 <= value <= 7000:
        real_v = value / 10.0
        return ('voltage_x10', f"{real_v:.1f}V", "Voltaje (división por 10)")

    if 180 <= value <= 650:
        real_v = value / 100.0
        return ('voltage_x100', f"{real_v:.2f}V", "Voltaje batería (división por 100)")

    # Porcentajes
    if 0 <= value <= 100:
        return ('percentage', f"{value}%", "Porcentaje o enum")

    # Corrientes
    if 101 <= value <= 200:
        return ('current', f"{value}A", "Corriente en Amperios")

    # Temperatura
    if 0 <= value <= 150:
        return ('temperature', f"{value}°C", "Temperatura")

    # Enum modos (addresses conocidos)
    if address == 0x1101:
        modes = {0: "Power", 1: "Standby", 2: "Bypass", 3: "Battery", 4: "Fault", 5: "Line", 6: "Charging"}
        return ('mode', modes.get(value, f"Unknown({value})"), "Modo de trabajo")

    if address == 0x1102:
        stages = {0: "None", 1: "Bulk", 2: "Absorb", 3: "Float"}
        return ('charge_stage', stages.get(value, f"Unknown({value})"), "Estado de carga")

    # Flags/Status bits
    if address in [0x1103, 0x1104]:
        return ('flags', f"0x{value:04X}", "Flags de estado")

    # Default
    return ('unknown', f"0x{value:04X}", f"Valor raw: {value}")


# ══════════════════════════════════════════════════════════════════════════════
# ESCANERS
# ══════════════════════════════════════════════════════════════════════════════

def scan_block(conn: ModbusConnection, start: int, count: int) -> list[RegisterInfo]:
    """Escanea un bloque de registros."""
    results = []
    regs = conn.read_holding_registers(start, count)

    if regs is None:
        return results

    for i, value in enumerate(regs):
        address = start + i
        classification, real_value, notes = classify_value(value, address)

        results.append(RegisterInfo(
            address=address,
            value=value,
            hex_value=f"0x{address:04X}",
            classification=classification,
            possible_real_value=real_value,
            notes=notes
        ))

    return results


def full_scan(conn: ModbusConnection) -> dict:
    """
    Escaneo completo de todas las zonas.
    """
    results = {
        'timestamp': datetime.now().isoformat(),
        'zones': {}
    }

    # Zonas a escanear
    zones = [
        ('STATUS_KNOWN', 0x1101, 0x112A, "Zona de estado conocida"),
        ('SETTINGS_KNOWN', 0x211F, 0x2159, "Zona de settings conocida"),
        ('STATUS_EXTENDED', 0x1000, 0x1150, "Extensión zona status"),
        ('SETTINGS_EXTENDED', 0x2000, 0x2200, "Extensión zona settings"),
        ('LOW_RANGE', 0x0000, 0x0100, "Rango bajo"),
        ('HIGH_RANGE', 0x3000, 0x3100, "Rango alto"),
    ]

    print("\n" + "=" * 70)
    print("ESCANEANDO REGISTROS MODBUS")
    print("=" * 70)

    for zone_name, start, end, description in zones:
        print(f"\n📍 {zone_name}: 0x{start:04X} - 0x{end:04X}")
        print(f"   {description}")
        print("-" * 70)

        zone_results = []
        for addr in range(start, end + 1, 10):
            block_size = min(10, end - addr + 1)
            block_results = scan_block(conn, addr, block_size)
            zone_results.extend(block_results)

            for r in block_results:
                if r.value != 0 or r.address <= start + 5:
                    print(f"   0x{r.address:04X} | {r.value:5d} | {r.hex_value:8} | {r.classification:15} | {r.possible_real_value:12} | {r.notes}")

        results['zones'][zone_name] = [asdict(r) for r in zone_results]

    return results


def test_writable_registers(conn: ModbusConnection, registers: list) -> list:
    """
    Prueba si ciertos registros son escribibles.
    ATENCIÓN: Esto prueba escritura con valores seguros (0x0000 y 0xFFFF).
    """
    print("\n" + "=" * 70)
    print("PROBANDO REGISTROS ESCRIBIBLES")
    print("=" * 70)
    print("⚠️  ADVERTENCIA: Esta prueba escribe valores temporales en el inversor")
    print("   Se usan valores seguros (0x0000 y 0xFFFF) para no dañar configuración\n")

    writable = []
    non_writable = []

    # Solo probar registros de configuración conocidos
    test_addresses = [
        0x211F,  # Cut-off voltage
        0x2122,  # CV voltage
        0x2123,  # Float voltage
        0x212A,  # Output priority
        0x212C,  # Charge priority
        0x212E,  # Max charge current
        0x2130,  # Max AC charge current
        0x2156,  # Back to grid voltage
        0x2159,  # Back to battery voltage
    ]

    for addr in test_addresses:
        print(f"   Probando 0x{addr:04X}...", end=" ")

        # Primero leer valor actual
        regs = conn.read_holding_registers(addr, 1)
        if regs is None:
            print("❌ Sin respuesta")
            non_writable.append({'address': addr, 'error': 'Sin respuesta'})
            continue

        original_value = regs[0]

        # Probar escribiendo 0xFFFF (si es seguro)
        success, msg = conn.write_single_register(addr, 0xFFFF)

        if success:
            print(f"✅ ESCRIBIBLE (valor actual: {original_value})")
            writable.append({
                'address': addr,
                'original_value': original_value,
                'test_value': 0xFFFF
            })
        else:
            print(f"❌ No escribible ({msg})")
            non_writable.append({
                'address': addr,
                'original_value': original_value,
                'error': msg
            })

        time.sleep(0.3)

    print(f"\n📊 Resumen: {len(writable)} escribibles, {len(non_writable)} no escribibles")

    return {'writable': writable, 'non_writable': non_writable}


def save_results(results: dict, writable_test: dict, port: str, baudrate: int):
    """Guarda los resultados en un archivo."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"scanner_results_{timestamp}.txt"

    with open(filename, 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write("RESULTADOS DEL ESCANEO MODBUS - INVERSOR FELICITY\n")
        f.write("=" * 70 + "\n\n")

        f.write(f"Fecha/Hora: {results['timestamp']}\n")
        f.write(f"Puerto: {port}\n")
        f.write(f"Baudrate: {baudrate}\n\n")

        f.write("-" * 70 + "\n")
        f.write("REGISTROS ENCONTRADOS POR ZONA\n")
        f.write("-" * 70 + "\n\n")

        for zone_name, registers in results['zones'].items():
            f.write(f"\n### {zone_name} ###\n")
            f.write(f"{'Dirección':<12} {'Valor':<10} {'Hex':<10} {'Clasificación':<15} {'Valor Real':<12} {'Notas'}\n")
            f.write("-" * 80 + "\n")

            for reg in registers:
                if reg['value'] != 0 or 'KNOWN' in zone_name:
                    f.write(f"0x{reg['address']:04X}     {reg['value']:<10} {reg['hex_value']:<10} "
                            f"{reg['classification']:<15} {reg['possible_real_value']:<12} {reg['notes']}\n")

        f.write("\n" + "=" * 70 + "\n")
        f.write("REGISTROS ESCRIBIBLES\n")
        f.write("=" * 70 + "\n\n")

        f.write("### ESCRIBIBLES ###\n")
        for w in writable_test.get('writable', []):
            f.write(f"  0x{w['address']:04X} - Valor original: {w['original_value']}\n")

        f.write("\n### NO ESCRIBIBLES ###\n")
        for nw in writable_test.get('non_writable', []):
            f.write(f"  0x{nw['address']:04X} - Error: {nw.get('error', 'N/A')}\n")

        f.write("\n" + "=" * 70 + "\n")
        f.write("FIN DEL REPORTE\n")
        f.write("=" * 70 + "\n")

    print(f"\n✅ Resultados guardados en: {filename}")
    return filename


def print_summary(results: dict):
    """Imprime un resumen de los hallazgos."""
    print("\n" + "=" * 70)
    print("📋 RESUMEN DEL ESCANEO")
    print("=" * 70)

    all_registers = []
    for zone_registers in results['zones'].values():
        all_registers.extend(zone_registers)

    classified = {
        'voltage_x10': 0,
        'voltage_x100': 0,
        'percentage': 0,
        'current': 0,
        'temperature': 0,
        'mode': 0,
        'charge_stage': 0,
        'flags': 0,
        'unknown': 0,
    }

    for reg in all_registers:
        if reg['classification'] in classified:
            classified[reg['classification']] += 1

    print(f"\n  Total registros encontrados: {len(all_registers)}")
    print(f"\n  Clasificación:")
    print(f"    🔋 Voltajes (/10):      {classified['voltage_x10']}")
    print(f"    🔋 Voltajes batería:    {classified['voltage_x100']}")
    print(f"    📊 Porcentajes:         {classified['percentage']}")
    print(f"    ⚡ Corrientes:          {classified['current']}")
    print(f"    🌡️  Temperaturas:        {classified['temperature']}")
    print(f"    ⚙️  Modos:              {classified['mode']}")
    print(f"    🔄 Estados de carga:    {classified['charge_stage']}")
    print(f"    🚩 Flags:              {classified['flags']}")
    print(f"    ❓ Unknown:            {classified['unknown']}")

    # Mostrar registros de settings conocidos
    print("\n  📝 REGISTROS DE CONFIGURACIÓN (0x211F - 0x2159):")
    settings_zone = results['zones'].get('SETTINGS_KNOWN', [])
    for reg in settings_zone:
        if reg['value'] != 0:
            print(f"     0x{reg['address']:04X} = {reg['value']} ({reg['possible_real_value']}) - {reg['notes']}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    import sys

    if len(sys.argv) < 2:
        print("""
╔═════════════════════════════════════════════════════════════════════════════╗
║                    MODBUS REGISTER SCANNER                                   ║
║                    Inversores Felicity Solar                                 ║
╠═════════════════════════════════════════════════════════════════════════════╣
║                                                                             ║
║  USO:                                                                      ║
║    python modbus_scanner.py COM3                                            ║
║    python modbus_scanner.py COM3 9600                                       ║
║    python modbus_scanner.py /dev/ttyUSB0                                    ║
║                                                                             ║
║  RESULTADOS:                                                               ║
║    Se guardan en: scanner_results_[timestamp].txt                          ║
║                                                                             ║
╚═════════════════════════════════════════════════════════════════════════════╝
        """)
        sys.exit(1)

    port = sys.argv[1]
    baudrate = int(sys.argv[2]) if len(sys.argv) > 2 else 2400

    print(f"""
╔═════════════════════════════════════════════════════════════════════════════╗
║                    MODBUS REGISTER SCANNER                                   ║
║                    Inversores Felicity Solar                                 ║
╠═════════════════════════════════════════════════════════════════════════════╣
║  Puerto: {port:<60}║
║  Baudrate: {baudrate:<55}║
╚═════════════════════════════════════════════════════════════════════════════╝
    """)

    # Conectar
    conn = ModbusConnection(port, baudrate)
    ok, msg = conn.connect()

    if not ok:
        print(f"❌ Error de conexión: {msg}")
        print("\nPuertos disponibles:")
        for p in serial.tools.list_ports.comports():
            print(f"  - {p.device}")
        sys.exit(1)

    print(f"✅ {msg}\n")

    # Ejecutar escaneo completo
    results = full_scan(conn)

    # Probar escritura (opcional)
    print("\n")
    response = input("¿Desea probar si los registros son escribibles? (s/n): ").strip().lower()
    writable_test = {'writable': [], 'non_writable': []}

    if response == 's':
        writable_test = test_writable_registers(conn, [])

    # Guardar y resumir
    filename = save_results(results, writable_test, port, baudrate)
    print_summary(results)

    print(f"\n📁 Archivo de resultados: {filename}")
    conn.disconnect()

    print("\n✅ Escaneo completado!")


if __name__ == "__main__":
    main()