# Procedimiento de prueba — Felicity IVGM8KLP2G1 por RS485/TCP

**Objetivo:** confirmar, contra el inversor real, que la cadena física y el mapa de registros están bien **antes** de conectar el 8K a la app.

**Herramienta:** `verificar_rs485.py` (raíz del repo, no depende de la app)

**Duración estimada:** 20–30 minutos

---

## 1. Checklist previo

- [ ] Inversor **IVGM8KLP2G1** encendido y con batería conectada
- [ ] Conversor **RS485 ↔ Ethernet** alimentado y en la misma red que la PC
- [ ] Cable RS485 conectado entre el inversor y el conversor
- [ ] La PC tiene red (aunque no tenga internet)
- [ ] Tenés a mano el modelo exacto del conversor (Waveshare / USR / Moxa / otro)
- [ ] Tenés a mano la etiqueta del inversor (para confirmar slave ID y modelo)

---

## 2. Diagrama de conexión

```
┌──────────────────┐   RS485    ┌────────────────────┐  Ethernet  ┌────────┐
│  IVGM8KLP2G1     │  A ──────▶ │  Conversor         │ ◀───────▶  │  PC    │
│  puerto RS485    │  B ──────▶ │  RS485 ↔ TCP       │            │        │
│  (A / B / GND)   │  GND ────▶ │  (IP fija/DHCP)    │            │        │
└──────────────────┘            └────────────────────┘            └────────┘
```

---

## 3. Cableado RS485

| En el inversor | En el conversor | Nota |
|---|---|---|
| **A** (o D+) | **A** (o D+) | respetar polaridad |
| **B** (o D−) | **B** (o D−) | |
| **GND** | **GND** | si el puerto lo tiene |

- **Par trenzado** para el par A/B (mejora la inmunidad al ruido).
- **Terminación de 120 Ω** entre A y B en el extremo lejano del bus (obligatoria en tramos largos).
- Si el inversor usa conector **RJ45**: el par A/B va a **pines 3 y 4** (los pines 5–6 son la alternativa documentada).

> ⚠️ **Error más común:** invertir A y B. Si la sonda no recibe nada, lo primero es swapper A/B.

---

## 4. Configuración del conversor

Valores de campo que funcionan:

| Parámetro | Valor |
|---|---|
| **Protocolo** | **Modbus TCP To RTU** |
| **Baud rate** | **9600** (IVGM) · 2400 (T-REX-5/6/10K) |
| **Paridad / Datos / Stop** | **N / 8 / 1** |
| **Slave ID** | **1** |
| Work Mode | TCP Server |
| No-Data-Restart | Enable, Restart Time 100 |
| Reconnect time | 12 s |
| Instruction Timeout | 224 |
| Multi-host | Enable |
| Pack Interval (solo módulos USR-D164) | **100** (con 20 se pierden paquetes) |

**Si el conversor es Waveshare**, además entrá a Vircom y verificá:
- Transfer Protocol = `Modbus_TCP_Protocol`
- RS485 Multi-host = ON
- RS485 bus conflict detection = ON

---

## 5. Descubrir la IP del conversor

```bash
# En Windows, mirá la tabla ARP / el panel de control de red del conversor
# (Cada fabricante tiene su herramienta: Vircom para Waveshare, etc.)

# Una vez que tengas la IP, verificá que la PC la ve:
ping <IP-del-conversor>

# Y que el puerto responde (502 por defecto):
# (si no tenés telnet/nc, usa el navegador: http://<IP-del-conversor>)
```

Anotá la IP: `____________________`

---

## 6. Ejecutar la sonda

Abrí una terminal en la carpeta del proyecto (`C:\Proyectos\Python\InversorApp\inversor_app`).

### Paso 1 — Volcado de registros (el más importante)

```bash
python verificar_rs485.py --host <IP-del-conversor> --framer mbap --slave 1 --count 120
```

### Paso 2 — Si no responde, probar el otro framing

```bash
python verificar_rs485.py --host <IP-del-conversor> --framer rtu --slave 1 --count 120
```

### Paso 3 — Si no sabés el slave ID, barrer

```bash
python verificar_rs485.py --host <IP-del-conversor> --framer mbap --scan
```

> El `--scan` recorre los IDs 1 a 247 e imprime cuáles responden. Si no responde ninguno, **el problema es físico** (cableado, baud, terminación o alimentación), no de software.

---

## 7. Cómo leer la salida

La sonda imprime tres bloques:

### 7.1 Tabla de registros

```
  Direccion   Valor    Hex      classic      ivgm_8k
  0x1100      3        0x0003   ·            3
  0x1108      5123     0x1403   51.23V       11.90V
  0x110A      2500     0x09C4   2500W        0
  0x112C      512      0x0200   ·            51.20V
  0x1138      875      0x036B   ·            87.50%
```

- `·` = ese mapa no define ese registro.
- Compará **la columna `ivgm_8k` contra la pantalla del inversor** (batería, SOC, PV, red, carga).

### 7.2 Comparación de mapas

Muestra los campos clave con la interpretación de **ambos** mapas, lado a lado.

### 7.3 Veredicto

La sonda estima por coherencia física cuál mapa encaja:

```
  Coherencia IVGM-8K : 2/2 valores plausibles
  Coherencia Clasico : 0/2 valores plausibles
  -> El mapa IVGM-8K parece el correcto para este equipo.
```

---

## 8. Validación obligatoria contra la pantalla

**Anotá los valores de la pantalla del inversor en el mismo momento** de la lectura:

| Magnitud | Pantalla del inversor | Sonda (columna ivgm_8k) | ¿Coincide? |
|---|---|---|---|
| Tensión batería | | | |
| SOC | | | |
| Tensión PV | | | |
| Potencia PV | | | |
| Tensión de red | | | |
| Frecuencia de red | | | |
| Carga | | | |
| Código de falla | | | |

> Si coinciden → **el mapa IVGM-8K está confirmado** y se puede avanzar con la app.
> Si no coinciden → hay que revisar el mapa registro por registro antes de seguir.

---

## 9. Solución de problemas

| Síntoma | Causa probable | Acción |
|---|---|---|
| No responde ningún ID | Cable A/B invertido | Swappear A y B |
| | Baud incorrecto | Verificar 9600 en el conversor |
| | Falta terminación 120 Ω | Poner la terminación |
| | Conversor mal configurado | Revisar "Modbus TCP To RTU" |
| | Sin alimentación del inversor | Verificar breaker / batería |
| Responde con MBAP pero no con RTU | El conversor está en modo Modbus TCP | Usar `--framer mbap` (es lo correcto) |
| Responde con RTU pero no con MBAP | El conversor está en modo transparente | Usar `--framer rtu` |
| Responde un ID raro | Slave ID distinto de 1 | Usar `--scan` y ajustar |
| Valores incoherentes | Mapa equivocado | Revisar la comparación de mapas |
| Lecturas intermitentes | Enlace ruidoso / tramo largo | Revisar cable, terminación y "Pack Interval" |

---

## 10. Conectar el 8K a la app (después de validar)

1. Abrir `dist\FelicityInverterMonitor_2026-11-09.exe`
2. Pestaña **Conexión** → tipo **TCP/IP**
3. **Framing:** `Modbus TCP (MBAP)` (o `RTU tunnelled` si tu conversor es transparente)
4. **Host / Puerto:** la IP del conversor (502)
5. **Slave ID:** el que hayas confirmado
6. Habilitar **modo multi-inversor** → en la tabla dejar:
   - `1 · 5K existente · Clásico`
   - `2 · 8K IVGM · IVGM-8K (Felicity Series RS485)`
7. **Conectar**
8. Pestaña **Sistema en Paralelo** → tabla con los valores de ambos inversores

---

## 11. Qué enviar para interpretar los resultados

Cuando corras la sonda, guardá la salida completa y mandá:

1. **La salida del volcado** (Paso 1) — copiar y pegar, o el archivo si lo guardaste:
   ```bash
   python verificar_rs485.py --host <IP> --framer mbap --slave 1 --count 120 > salida_rs485.txt
   ```
2. **Modelo exacto del conversor**
3. **Los valores de la pantalla del inversor** (sección 8)
4. **El slave ID que responde** (si lo averiguaste con `--scan`)

Con eso se confirma el mapa y se avanza.

---

## 12. Parámetros confirmados (para anotar)

```
Modelo inversor:     IVGM8KLP2G1
Modelo conversor:    ____________________
IP conversor:        ____________________
Puerto:              ____________________
Framing:             ____________________
Slave ID:            ____________________
Baud:                9600
Paridad / Datos / Stop: N / 8 / 1
Mapa confirmado:     ____________________
```

---

*Documento generado el 10 de noviembre de 2026.*
