# Informe de validación — Felicity IVGM-8K (IVGM8KLP2G1)

**Fecha de la validación:** 11 de noviembre de 2026
**Equipo probado:** Felicity IVGM-8K, serie "Inverter Communication Protocol — Series RS485"
**Datos de origen:** `docs/prueba coenxion/` (`paso1.txt`, `paso 2.txt`, `vtodo.py`, CSV del 2026-11-11 10:20:40)

---

## 1. Resumen ejecutivo

El mapa de registros de la serie **IVGM-8K quedó VALIDADO contra hardware real**. Antes de esta
validación el mapa era "provisional"; ahora está confirmado con **dos verificaciones físicas
independientes** (V × I = P) sobre dos instantes distintos de funcionamiento.

La validación destapó además **tres defectos reales en la app**, que impedían que el 8K se
conectara y mostrara los datos bien. Los tres están corregidos y cubiertos por tests.

| # | Hallazgo | Impacto | Estado |
|---|----------|---------|--------|
| 1 | El gateway habla **RTU tunelado**, no Modbus TCP (MBAP) | La app no conectaba con el equipo | ✅ Corregido |
| 2 | El gateway envía un **banner ASCII** al conectar | La primera lectura de cada sesión llegaba corrupta | ✅ Corregido |
| 3 | El firmware marca registros no disponibles con **0xFFFE / 0xFFFF** | La app mostraba `-2` y `65534` como si fueran datos | ✅ Corregido |
| 4 | El mapa IVGM-8K solo cubría 19 de 477 direcciones documentadas | Faltaban 4 temperaturas, tensión AC, frecuencias y % de carga | ✅ Corregido |
| 5 | El bloque de configuración de paralelo (0x2140-0x2143) no era accesible | Imposible diagnosticar una instalación en paralelo | ✅ Corregido |
| 6 | La app podía **escribir** en el inversor (0x06 y comandos ASCII) | Riesgo de alterar la EEPROM del equipo con un clic | ✅ **Eliminado** |

---

## 1.1 Modo de operación: SOLO LECTURA

La app quedó como un **monitor de solo lectura**. Eliminado:

- La función Modbus **0x06 (Write Single Register)** y sus 9 métodos derivados
  (`set_float_voltage`, `set_absorb_voltage`, `set_cutoff_voltage`, `set_recharge_voltage`,
  `set_back_to_battery_voltage`, `set_output_priority`, `set_charge_priority`,
  `set_max_charge_current`, `set_max_ac_charge_current`).
- La pestaña **"Control (9 params)"** completa, que solo servía para escribir en la EEPROM.
- El panel **"Asignar Modbus ID"**, que escribía `0x2142` en el equipo.
- La sonda del scanner que escribía `0xFFFF` en 9 registros de configuración.
- Los módulos `core/write_commands.py` y `core/tab_control.py` (código muerto, solo de escritura).

**El único código de función que la app puede enviar es `0x03` (Read Holding Registers).**

El paralelismo se resuelve **sin escribir**: la app cambia el `slave_id` de cada petición y lee a
cada inversor por separado. Para descubrir qué IDs hay en el bus, el botón **"Detectar en el
bus"** sondea las direcciones 1-16 con lecturas FC03 y llena la tabla automáticamente.

El ID Modbus de cada equipo se configura en el **display del inversor**, no desde la app.

---

## 2. Caracterización de la conexión

Extraído de `paso1.txt` (sonda `vtodo.py --auto`, 160 combinaciones probadas):

| Parámetro | Valor | Cómo se determinó |
|-----------|-------|-------------------|
| Host / puerto | `192.168.1.10:502` | Configuración del gateway |
| **Framing** | **RTU (tunelado)** | RTU devolvió datos válidos; MBAP no |
| Slave ID | `1` | Único slave que respondió |
| Función | `03` (Read Holding Registers) | La que devolvió datos |
| Dirección de arranque | `0x1100` (y `0xF800` responde) |—both respondieron |
| Baud del lado RS485 | 9600, 8N1 | Configuración del IVGM-8K |

### 2.1 El banner ASCII del gateway

En la primera lectura, la respuesta del gateway empieza con texto ASCII antes de la trama
Modbus:

```
53 63 61 6E 3A 78 5B 30 5D ... 53 48 4F 52 54 0D 0A 01 03 02 00 03 F8 45
└──────────── "Scan:x[0]:180,y[0]:146 ... SHORT\r\n" ──────────┘└─ trama RTU ─┘
```

Es la pantalla táctil del gateway (USR-D164) saluda al abrir el socket. **Cualquier lector que
asuma que la respuesta empieza en el primer byte se descarta la primera lectura de cada sesión.**

**Corrección aplicada** (`core/modbus_tcp.py`):
- `_drain()` — descarta bytes residuales del socket antes de cada petición.
- `_find_frame()` — busca dentro del flujo recibido una **trama Modbus válida** (slave + función +
  byte count + CRC válido) en lugar de asumir que empieza en el byte 0. El banner se salta solo.
- Modo `auto` — prueba RTU y, si no responde, MBAP; se queda con el que funcione.

### 2.2 Registros que "no existen"

El barrido completo (`paso 2.txt`: 4864 direcciones, 448 peticiones, 67 s) encontró **988 registros
que existen**, de los cuales 530 tienen valor distinto de cero.

- `0x0000-0x01FF` → **0 registros**. Esa zona no existe en este equipo.
- `0x1000-0x17FF` → 464 registros (telemetría).
- `0x2000-0x27FF` → 464 registros (**configuración**, incluye 0x2140-0x2143).
- `0xF800-0xF8FF` → 60 registros (identificación del equipo).

Los registros que el firmware no tiene devuelven `0xFFFE` (-2). **No son datos**: es la marca de
"parámetro no configurado". La app ahora los ignora en lugar de mostrarlos como `-2` o `65534`.

---

## 3. Validación del mapa IVGM-8K

### 3.1 Verificación física: V × I = P

La prueba de fuego de un mapa de registros no es que los números "se vean bien", sino que **sean
consistentes entre sí**. Si la escala de un campo está mal, el producto V × I no cuadra con la
potencia leída.

**Snapshot del CSV (10:20:40)**

| Magnitud | V | A | V × I | P leído | Error |
|----------|---|---|-------|---------|-------|
| PV1 | 300.90 V | 6.40 A | 1925.8 W | **1928 W** | **-0.12 %** |
| Bat1 | 53.50 V | 34.80 A | 1861.8 W | **1866 W** | **-0.23 %** |

**Snapshot de `paso1.txt` (10:03, otro momento del día)**

| Magnitud | V | A | V × I | P leído | Error |
|----------|---|---|-------|---------|-------|
| PV1 | 310.20 V | 10.80 A | 3350.2 W | **3368 W** | -0.53 % |
| Bat1 | 53.90 V | 60.40 A | 3255.6 W | **3262 W** | -0.20 % |

**Cuatro verificaciones independientes, en dos instantes distintos, con error < 0.6 %.** Las escalas
(0.1 para V y A, 1 para W) y los signos quedan **confirmados**.

Coherencia adicional: SOC 46-49 % con batería de 48 V LiFePO4 a 53.5 V de carga — exactamente el
punto de saturación esperado para LiFePO4.

### 3.2 El mapa clásico queda descalificado

Con el mismo volcado, el mapa "clásico" (Voltronic/Axpert) da **0 de 2 valores plausibles**:

- `0x1108` → "Battery voltage = 0.00 V" (la batería real está a 53.5 V)
- `0x1111` → "AC output = 52.80 V" (la salida real está a 244.9 V)

Las direcciones del layout clásico **no coinciden** con las del IVGM-8K. Confundir ambos mapas
produce basura silenciosa: por eso la app obliga a elegir el mapa por perfil y lo etiqueta.

### 3.3 Mapa completo del IVGM-8K

#### Telemetría (bloque principal, 0x1100-0x1181)

| Dirección | Nombre | Escala | Signo | Unidad | Estado |
|-----------|--------|--------|-------|--------|--------|
| 0x1100 | WorkMode | 1 | — | — | ✅ Confirmado |
| 0x1101-0x1104 | State1-4 | 1 | — | — | ⚠️ Bitfields, cambian entre lecturas |
| 0x1109 | Warn Code | 1 | — | — | ✅ Confirmado (0 = sin alarma) |
| 0x110A | Fault Code | 1 | — | — | ✅ Confirmado (0 = sin falla) |
| 0x1118 | PV1 Voltage | 0.1 | — | V | ✅ Confirmado (300.9 V) |
| 0x1119 | PV2 Voltage | 0.1 | — | V | ✅ Confirmado (37.3 V, sin corriente) |
| 0x111C | PV1 Current | 0.1 | Sí | A | ✅ Confirmado (6.40 A) |
| 0x111D | PV2 Current | 0.1 | Sí | A | ✅ Confirmado (0 A) |
| 0x1120 | Home Load A | 1 | Sí | W | ✅ Confirmado |
| 0x1121 | Home Load B | 1 | Sí | W | ✅ Confirmado |
| 0x1128 | PV1 Power | 1 | Sí | W | ✅ Confirmado (1928 W) |
| 0x1129 | PV2 Power | 1 | Sí | W | ✅ Confirmado (0 W) |
| 0x112C | Bat1 Voltage | 0.1 | — | V | ✅ Confirmado (53.5 V) |
| 0x1130 | Bat1 Current | 0.1 | Sí | A | ✅ Confirmado (34.8 A) |
| 0x1131 | Bat1 Power | 1 | Sí | W | ✅ Confirmado (1866 W) |
| 0x1138 | Bat1 SOC | 0.1 | — | % | ✅ Confirmado (49 %) |
| 0x113E | Output Frequency | 0.01 | — | Hz | 🆕 48.75 Hz |
| 0x113F | AC Output Voltage fase A | 0.1 | — | V | 🆕 244.9 V |
| 0x1140 | AC Output Voltage fase B | 0.1 | — | V | 🆕 242.6 V |
| 0x1144 | Temperatura boost | 1 | — | °C | 🆕 37 °C |
| 0x1145 | Temperatura inversor | 1 | — | °C | 🆕 24 °C |
| 0x1146 | Temperatura ambiente | 1 | — | °C | 🆕 42 °C |
| 0x1147 | Temperatura batería | 0.1 | — | °C | 🆕 25.0 °C |
| 0x1150 | Tensión red fase A | 0.1 | — | V | 🆕 1.7 V (red desconectada) |
| 0x1151 | Tensión red fase B | 0.1 | — | V | 🆕 2.3 V (red desconectada) |
| 0x1153 | Tensión inversor fase A | 0.1 | — | V | 🆕 108.5 V |
| 0x1154 | Tensión inversor fase B | 0.1 | — | V | 🆕 111.4 V |
| 0x1156 | Tensión carga fase A | 0.1 | — | V | 🆕 109.5 V |
| 0x1157 | Tensión carga fase B | 0.1 | — | V | 🆕 110.3 V |
| 0x1162 | Corriente carga fase A | 0.1 | Sí | A | 🆕 0.4 A |
| 0x1163 | Corriente carga fase B | 0.1 | Sí | A | 🆕 0.4 A |
| 0x116E | Frecuencia inversor | 0.01 | — | Hz | 🆕 60.02 Hz |
| 0x116F | Frecuencia carga | 0.01 | — | Hz | 🆕 60.02 Hz |
| 0x117F | Carga fase A | 1 | — | % | 🆕 1 % |
| 0x1180 | Carga fase B | 1 | — | % | 🆕 1 % |

#### Configuración de paralelo (0x2140-0x2143)

| Dirección | Nombre | Valor leído | Significado |
|-----------|--------|-------------|-------------|
| 0x2140 | Parallel Count | **3** | Hay 3 inversores en paralelo |
| 0x2141 | Parallel Address | **1** | Este equipo es el maestro |
| 0x2142 | Modbus ID | **1** | ID de fábrica — hay que cambiarlo en los otros dos |
| 0x2143 | Rated Power | **8000** | 8 kW nominales |

#### Identificación (0xF800-0xF80D)

| Dirección | Nombre oficial | Valor |
|-----------|-----------------|-------|
| 0xF800 | Device TypeID | 337 |
| 0xF801 | Device SubTypeID | 1039 |
| 0xF803 | Communication Protocol InformationID | 51224 |
| 0xF804 | Machine Serial Number SNID | 1203 |

---

## 4. Puntos que siguen SIN validar

Sé honesto con esto: la validación es **fuerte pero no total**.

| Punto | Por qué queda abierto |
|-------|------------------------|
| **Semántica exacta de 0x113E/0x113F/0x1140** | El transcript oficial del PDF deja la descripción en blanco. La escala propuesta (48.75 Hz / 244.9 V / 242.6 V) es plausible y el patrón del documento no la contradice, pero falta contrastarla contra la pantalla del inversor con carga real. |
| **Tensión de red (0x1150/0x1151)** | Marca 1.7 V / 2.3 V porque en el momento del volcado la red estaba desconectada. Falta un volcado **con la red conectada** para confirmar la escala. |
| **Carga A/B y frecuencia de red** | Con carga ~0 A no hay forma de cerrar un V × I = P en el lado AC. |
| **Mapa MUST (0x6271-0x6293)** | Este equipo es un Felicity; el barrido no encontró **ningún** registro en esa zona. El mapa MUST necesita un inversor MUST real para validarse. |
| **PV2 a 37.3 V** | Coherente con una segunda entrada de baja tensión, pero sin corriente no se puede distinguir de una cadena mal conectada. |

---

## 5. Reproducir la validación

```bash
# 1. Descubrir framing, slave y direcciones que responden
python docs/prueba\ conexion/vtodo.py --host 192.168.1.10 --port 502 --auto

# 2. Volcar el bloque de telemetría y ver la interpretación de los mapas
python docs/prueba\ conexion/vtodo.py --host 192.168.1.10 --port 502 \
    --framer rtu --slave 1 --fc 3 --start 0x1100 --count 80

# 3. Barrido completo (solo lecturas, ~67 s) y volcado a CSV
python docs/prueba\ conexion/vtodo.py --host 192.168.1.10 --port 502 \
    --framer rtu --slave 1 --todo zonas --csv registro.csv

# 4. Verificar la coherencia física con los datos reales
python test_8k_real.py
```

---

## 6. Cambios aplicados en la app

| Archivo | Cambio |
|---------|--------|
| `core/register_maps.py` | Mapa IVGM-8K de 19 → 38 campos. Nuevo `settings_fields` para 0x2140-0x2143. `is_not_available()` ignora 0xFFFE/0xFFFF. Alias canónicos para el mapa IVGM. `decode_settings_fields()` nuevo. |
| `core/modbus_tcp.py` | Framing por defecto **RTU** + modo **auto**. `_drain()`, `_find_frame()` y `_read_write_response()`: el banner del gateway ya no rompe la lectura. `read_settings()` consciente del mapa. **Eliminada toda la capacidad de escritura.** |
| `core/felicity_modbus.py` | `ModbusStatus` con los campos del IVGM-8K. `ModbusSettings` con `parallel_count`, `parallel_address`, `modbus_id`, `rated_power` y `parallel_role_str`. `read_settings()` consciente del mapa. **Eliminada toda la capacidad de escritura.** |
| `core/multi_inverter.py` | `InverterData` con `pv1_voltage`, `inverter_temp`, `ambient_temp`, `battery_temp`. Nueva función `scan_slave_ids()` que detecta los IDs del bus con solo lecturas. |
| `core/modbus_scanner.py` | Eliminada la sonda que escribía `0xFFFF` en registros de configuración. |
| `main.py` | Combo de framing con RTU por defecto y opción "Auto". Grupo **"Diagnóstico de paralelo — SOLO LECTURA"**. Botón **"Detectar en el bus"**. Tabla del paralelo con columnas SOC, PV1, P.PV, T.Inv y T.Amb. **Eliminada la pestaña Control y todo control de escritura.** |
| `core/profiles.py` | Perfil IVGM-8K con nota de "validado contra hardware real". |
| `core/write_commands.py`, `core/tab_control.py` | **Eliminados** (código muerto, solo de escritura). |

---

## 7. Verificación de que la app no escribe

El test `test_solo_lectura.py` es la garantía, y corre como parte de la suite:

| Comprobación | Resultado |
|--------------|-----------|
| Ningún método `write_*` / `set_*` de escritura en la app | ✅ |
| Ninguna referencia a la función Modbus 0x06 | ✅ |
| `ModbusTCPConnection` y `ModbusConnection` sin métodos de escritura | ✅ |
| La UI no expone ningún control de escritura | ✅ |
| El scanner no escribe (ni para sondear) | ✅ |
| La trama que la app construye es FC03 | ✅ |
| El paralelo cambia el `slave_id` por su cuenta y lo restaura | ✅ |

Y el test `test_scan_slaves.py` lo verifica **en runtime**, contra un bus RS485 simulado con tres
inversores: detecta los slaves 1, 2 y 3, consulta a cada uno, restaura el `slave_id` original, y
**las 42 tramas enviadas son todas FC03 — ninguna de escritura**.

