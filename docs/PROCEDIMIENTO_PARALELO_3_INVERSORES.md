# Procedimiento — Poner 3 inversores Felicity IVGM-8K en paralelo

> **La app es un monitor de SOLO LECTURA.** No escribe nunca en el inversor:
> no cambia voltajes, no cambia prioridades, no cambia el ID Modbus. Solo lee
> (función Modbus 0x03). Todo lo que cambia en el equipo se configura desde el
> **display del inversor** o con `vtodo.py` por separado.

**Objetivo:** que la app pueda leer los tres inversores por separado, cada uno con su ID Modbus.

**Situación actual (verificada el 11/11/2026):** los tres equipos tienen `0x2142 = 1` (ID de
fábrica). Los tres responden al slave 1, así que la app no puede distinguirlos.

---

## 0. La idea, en una línea

Modbus es maestro-esclavo puro: **cada inversor en el bus necesita su propia dirección**. El
inversor maestro **no** agrega los datos de los esclavos. Por eso hay que asignar un ID distinto
a cada equipo y luego leerlos en secuencia.

La app hace exactamente eso por su cuenta: en cada ciclo de polling cambia el `slave_id` de la
petición y lee al inversor correspondiente. Lo único que necesitás hacer es **declarar qué IDs
existen** — y para eso está el botón **"Detectar en el bus"**, que los descubre solo.

| Inversor | Rol | Parallel Address (0x2141) | Modbus ID (0x2142) |
|----------|-----|---------------------------|--------------------|
| #1 | Maestro | 1 | **1** |
| #2 | Esclavo 1 | 2 | **2** |
| #3 | Esclavo 2 | 3 | **3** |

---

## 1. Configurá el ID de cada inversor (desde el display, NO desde la app)

Esto se hace **una vez**, por equipo, y es lo único que hay que hacer a mano.

1. Conectá **un solo inversor** a la vez (cable directo o el gateway con un único equipo en el
   bus). Si los tres están conectados, el que tiene ID 1 contesta primero y estarías
   comunicándote con el equivocado.
2. En el **display táctil del inversor**, entrá al menú de **paralelo / RS485 / Modbus address** y
   poné el ID que le corresponde:

   | Inversor | ID a poner |
   |----------|------------|
   | #1 (maestro) | 1 |
   | #2 | 2 |
   | #3 | 3 |

   Configurá también el **Parallel Address** (rol): 1 = maestro, 2 y 3 = esclavos. En muchos
   equipos el mismo menú define las dos cosas.

3. Guardá y reiniciá el inversor.

> **¿Tu modelo no expone el ID en el display?** Entonces usá `vtodo.py` conectado físicamente a
> ese equipo:
>
> ```bash
> python docs/prueba\ conexion/vtodo.py --host 192.168.1.10 --port 502 \
>     --framer rtu --slave 1 --write 0x2142 2
> ```
>
> `vtodo.py` es una herramienta de línea de comandos **fuera de la app**: escribe, pide
> confirmación y te avisa. La app no hace esto.

### Verificá que el cambio quedó

Con **un solo inversor** conectado:

```bash
python docs/prueba\ conexion/vtodo.py --host 192.168.1.10 --port 502 \
    --framer rtu --slave 2 --fc 3 --start 0x2140 --count 4
```

Si el equipo #2 ya tiene ID 2, hay que consultarlo con `--slave 2` (no 1). Deberías ver:

```
0x2140  = 3      Parallel Count      -> 3 inversores en paralelo
0x2141  = 2      Parallel Address    -> 2 = esclavo 1
0x2142  = 2      Modbus ID           -> 2  (el que le pusiste)
0x2143  = 8000   Rated Power         -> 8000 W = 8 kW
```

---

## 2. Detectá los inversores desde la app

1. Conectá los **tres** inversores al bus RS485 (A/D+, B/D−, GND; terminación 120 Ω solo en
   los dos extremos).
2. En la app, pestaña **Conexión** → tipo **TCP/IP** → host `192.168.1.10`, puerto `502`,
   framing **RTU tunnelled** (o **Auto**), slave ID **1**.
3. Presioná **"Conectar Modbus"**.
4. En el grupo **"Sistema Multi-Inversor (Paralelo)"**:
   - Marcá **"Habilitar modo multi-inversor"**.
   - Presioná **"Detectar en el bus"**.

   La app sondea las direcciones 1 a 16 con lecturas FC03 y llena la tabla con las que
   responden:

   ```
   ✓ 3 inversor(es) detectado(s): ID 1, ID 2, ID 3
   ```

   La tabla queda:

   | Slave ID | Etiqueta | Perfil / Modelo |
   |----------|----------|-----------------|
   | 1 | Maestro | Felicity IVGM-8K — LiFePO4 48V |
   | 2 | Esclavo 1 | Felicity IVGM-8K — LiFePO4 48V |
   | 3 | Esclavo 2 | Felicity IVGM-8K — LiFePO4 48V |

   > El **Perfil / Modelo** define el **mapa de registros** de cada fila. Para el IVGM-8K tiene
   > que ser el perfil `Felicity IVGM-8K` (mapa `ivgm_8k`). Si le ponés el perfil "5K" (mapa
   > `classic`) vas a ver basura: ese layout no coincide con el del 8K.

5. **Intervalo de polling**: 5 segundos es lo recomendado.

---

## 3. Qué mirar en la tabla

| Columna | Significado | Valor de referencia (11/11/2026, 10:20) |
|---------|-------------|------------------------------------------|
| ID | Slave ID | 1, 2, 3 |
| Estado | 🟢 / 🟠 / 🔴 / ⚫ | Los tres 🟢 Online |
| V.Bat | Tensión de batería | 53.5 V (los tres, comparten el bus de batería) |
| I.Bat | Corriente de batería | 34.8 A (repartida entre los tres) |
| P.Bat | Potencia de batería | 1866 W |
| SOC | Estado de carga | 49 % |
| P.AC | Potencia de salida | según la carga |
| V.AC | Tensión de salida | 244.9 V |
| PV1 | Tensión del string PV1 | 300.9 V |
| P.PV | Potencia PV | 1928 W |
| T.Inv | Temperatura del inversor | 24 °C |
| T.Amb | Temperatura ambiente | 42 °C |
| Fallo | Código de falla | "Sin falla" |

### Si un inversor aparece Offline

- **"Detectar en el bus" no lo encuentra** → el ID no es el que creés, o no está bien
  conectado al bus. Verificá con `vtodo.py --scan 1-16`.
- **El ID es correcto pero no responde** → problema de cableado RS485 de ese equipo: revisá
  A/D+, B/D−, GND y la resistencia de terminación.
- **Intermitente** → el banner ASCII del gateway ya no es problema (la app lo descarta), pero
  verificá que el timeout por ID sea suficiente (por defecto 800 ms; si el bus está largo,
  subilo).

---

## 4. El diagnóstico de paralelo (solo lectura)

El grupo **"Diagnóstico de paralelo (IVGM-8K) — SOLO LECTURA"** permite ver la configuración
de un inversor sin tocarlo:

- **"Leer configuración"** → lee `0x2140-0x2143` y muestra cuántos inversores hay en paralelo,
  el rol, el ID Modbus y la potencia nominal.

Es una lectura pura. Sirve para confirmar que el equipo #2 realmente quedó con ID 2.

---

## 5. Cancelar y volver atrás

Si necesitás que un inversor vuelva a ser maestro, configurale el ID 1 desde su display (o con
`vtodo.py`) y volvé a correr "Detectar en el bus".

---

## 6. Conceptos que conviene tener claros

- **Modbus no agrega.** El maestro no devuelve "los datos de los 3". Cada petición va a una
  dirección y solo contesta ese equipo.
- **Un ID por equipo en el mismo bus.** Si dos equipos comparten ID, ambos responden y las
  respuestas se pisan. Es la causa #1 de "veo datos que no coinciden".
- **El bus RS485 es un bus compartido.** A/B de todos en paralelo, GND común, y **120 Ω de
  terminación solo en los dos extremos** (no en cada equipo).
- **El gateway es transparente.** Por eso el framing es RTU y no MBAP: el gateway solo reenvía
  bytes, no los traduce.
- **0xFFFE no es un dato.** El firmware lo usa para "parámetro no configurado". La app lo ignora.
- **La app no escribe.** Ni voltajes, ni prioridades, ni IDs. Si necesitás cambiar algo, es en
  el display del inversor o con `vtodo.py`.
