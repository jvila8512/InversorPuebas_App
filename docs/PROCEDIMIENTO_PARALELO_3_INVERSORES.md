# Procedimiento — Poner 3 inversores Felicity IVGM-8K en paralelo

**Objetivo:** que la app pueda leer los tres inversores por separado, cada uno con su ID Modbus.

**Situación actual (verificada el 11/11/2026):** los tres equipos tienen `0x2142 = 1` (ID de
fábrica). Los tres responden al slave 1, así que la app no puede distinguirlos.

---

## 0. La idea, en una línea

Modbus es maestro-esclavo puro: **cada inversor en el bus necesita su propia dirección**. El
inversor maestro **no** agrega los datos de los esclavos. Por eso hay que asignar un ID distinto
a cada equipo y luego leerlos en secuencia.

| Inversor | Rol | Parallel Address (0x2141) | Modbus ID (0x2142) |
|----------|-----|---------------------------|--------------------|
| #1 | Maestro | 1 | **1** |
| #2 | Esclavo 1 | 2 | **2** |
| #3 | Esclavo 2 | 3 | **3** |

---

## 1. Antes de tocar nada — verificá el estado actual

Con **un solo inversor conectado a la vez** (cable directo, o el gateway con un solo equipo en el
bus RS485):

```bash
python docs/prueba\ conexion/vtodo.py --host 192.168.1.10 --port 502 \
    --framer rtu --slave 1 --fc 3 --start 0x2140 --count 4
```

Leé la salida. Para el equipo maestro de tu instalación actual:

```
Direccion   Valor    Hex      Descripcion
0x2140      3        0x0003   Parallel Count      -> 3 inversores en paralelo
0x2141      1        0x0001   Parallel Address    -> 1 = maestro
0x2142      1        0x0001   Modbus ID           -> 1 (de fabrica)
0x2143      8000     0x1F40   Rated Power         -> 8000 W = 8 kW
```

> **Si `0x2140` dice 1 y no 3**, el equipo no tiene configurado el paralelo. Hay que configurar
> `0x2140 = 3` primero (ver sección 4).

---

## 2. Asigná el ID del inversor #2

1. **Desconectá físicamente** los otros dos inversores del bus RS485. Solo debe quedar el #2.
   Esto es fundamental: si los tres están conectados, el que tiene ID 1 va a "cantar" primero y
   te vas a estar comunicando con el equipo equivocado.
2. Conectá el inversor #2 al gateway (o directo por RS485).
3. En la app: pestaña **Conexión** → tipo **TCP/IP** → host `192.168.1.10`, puerto `502`,
   framing **RTU tunnelled** (o **Auto**), slave ID **1** (porque todavía tiene ID 1).
4. En el grupo **"Configuración de paralelo (IVGM-8K)"**:
   - Presioná **"Leer configuración"**. Debe mostrar `3` inversores, rol `Maestro`, ID `1`.
   - Poné el spinbox **"Asignar Modbus ID"** en **2**.
   - Presioná **"Asignar ID"**.
5. Confirmá el mensaje: *"✓ Modbus ID cambiado de 1 a 2"*.

Ahora el inversor #2 responde en el slave **2**.

### Repetir para el inversor #3

Mismo procedimiento, pero asignale el ID **3**. Y de paso, como ya vas a estar conectado a él,
corrigile el **Parallel Address** si hace falta (debería ser 2 si es el primer esclavo, o 3 si
el #2 ya está configurado como esclavo 1):

| Inversor | Parallel Address (0x2141) | Modbus ID (0x2142) |
|----------|---------------------------|--------------------|
| #1 maestro | 1 | 1 |
| #2 | 2 | 2 |
| #3 | 3 | 3 |

> ⚠️ **El Parallel Address y el Modbus ID son cosas distintas.** El Parallel Address define el
> rol en el paralelo (quién coordina la reparto de carga). El Modbus ID define a quién responde
> cada petición Modbus. Lo ideal es que coincidan, pero la app solo necesita el Modbus ID.

---

## 3. Verificá que los tres responden

Con los tres conectados al bus:

```bash
# Barrido de IDs para ver quién contesta
python docs/prueba\ conexion/vtodo.py --host 192.168.1.10 --port 502 \
    --framer rtu --scan 1-5
```

Esperado: los IDs **1, 2 y 3** responden con datos válidos. Si el 2 o el 3 no aparecen, ese
inversor todavía tiene el ID de fábrica o no está bien conectado al bus.

---

## 4. Si `0x2140` (Parallel Count) no dice 3

El Parallel Count se configura desde el **display táctil del inversor**, no por Modbus en esta
serie. En la pantalla del inversor, entrá al menú de paralelo / "Parallel Setting" y poné:

- **Parallel Count = 3**
- **Parallel Address = 1** (en el maestro), **2** y **3** en los esclavos

Después reiniciá el equipo (o activá "Save") y verificá por Modbus que `0x2140` ahora vale 3.

---

## 5. Configurá la app para leer los tres

En la app, pestaña **Conexión** → grupo **"Sistema Multi-Inversor (Paralelo)"**:

1. Marcá **"Habilitar modo multi-inversor"**. Aparece la pestaña **"⚡ Sistema en Paralelo"**.
2. En la tabla, dejá **3 filas**:

| Slave ID | Etiqueta | Perfil / Modelo |
|----------|----------|-----------------|
| 1 | Maestro | Felicity IVGM-8K — LiFePO4 48V |
| 2 | Esclavo 1 | Felicity IVGM-8K — LiFePO4 48V |
| 3 | Esclavo 2 | Felicity IVGM-8K — LiFePO4 48V |

   > El **Perfil / Modelo** define el **mapa de registros** de cada fila. Para el IVGM-8K tiene
   > que ser el perfil `Felicity IVGM-8K` (mapa `ivgm_8k`). Si le ponés el perfil "5K" (mapa
   > `classic`) vas a ver basura: ese layout no coincide con el del 8K.

3. **Intervalo de polling**: 5 segundos es lo recomendado. Con 3 inversores son 3 peticiones
   (o 6, porque el bloque de estado son 2 lecturas de 60 registros) por ciclo.
4. Conectá y mirá la pestaña **"Sistema en Paralelo"**.

---

## 6. Qué mirar en la tabla

| Columna | Significado | Valor esperado de referencia (11/11/2026, 10:20) |
|---------|-------------|--------------------------------------------------|
| ID | Slave ID | 1, 2, 3 |
| Estado | 🟢 / 🟠 / 🔴 / ⚫ | Los tres 🟢 Online |
| V.Bat | Tensión de batería | 53.5 V (los tres, comparten el bus de batería) |
| I.Bat | Corriente de batería | 34.8 A (repartida entre los tres) |
| P.Bat | Potencia de batería | 1866 W |
| SOC | Estado de carga | 49 % |
| P.AC | Potencia de salida | según la carga |
| V.AC | Tensión de salida | 244.9 V |
| PV1 | Tensión del|string PV1 | 300.9 V |
| P.PV | Potencia PV | 1928 W |
| T.Inv | Temperatura del inversor | 24 °C |
| T.Amb | Temperatura ambiente | 42 °C |
| Fallo | Código de falla | "Sin falla" |

### Si un inversor aparece Offline

- **Los tres responden al mismo ID** → falta asignar el Modbus ID (sección 2).
- **El ID es correcto pero no responde** → problema de cableado RS485 del ese equipo: revisá
  A/D+, B/D−, GND y la resistencia de terminación de 120 Ω en los extremos del bus.
- **Intermitente** → el banner ASCII del gateway ya no es problema (la app lo descarta), pero
  verificá que el timeout por ID sea suficiente (por defecto 800 ms; si el bus está largo,
  subilo).

---

## 7. Cancelar y volver atrás

Si necesitás que un inversor vuelva a ser maestro, asignale el Modbus ID **1** con el mismo
procedimiento de la sección 2.

---

## 8. Conceptos que conviene tener claros

- **Modbus no agrega.** El maestro no devuelve "los datos de los 3". Cada petición va a una
  dirección y solo contesta ese equipo.
- **Un ID por equipo en el mismo bus.** Si dos equipos comparten ID, ambos responden y las
  respuestas se pisan. Es la causa #1 de "veo datos que no coinciden".
- **El bus RS485 es un bus compartido.** A/B de todos en paralelo, GND común, y **120 Ω de
  terminación solo en los dos extremos** (no en cada equipo).
- **El gateway es transparente.** Por eso el framing es RTU y no MBAP: el gateway solo reenvía
  bytes, no los traduce.
- **0xFFFE no es un dato.** El firmware lo usa para "parámetro no configurado". La app lo ignora.
