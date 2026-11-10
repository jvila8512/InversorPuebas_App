# Protocolo de comunicación JK BMS

**Versión:** 2.5  
**Última actualización:** 2020-12-17  
**Autor:** echo

---

## Historial de versiones

| Versión | Fecha       | Descripción                                                                               | Autor |
|---------|-------------|-------------------------------------------------------------------------------------------|-------|
| V20191124 | 2019-11-24 | Primer borrador                                                                           |       |
| V20200325 | 2020-03-25 | Actualización de descripciones, cambio de 0xA10 a 0xD2, conmutador de cargador dedicado   |       |
| V20200325 | 2020-03-25 | Determinación de la velocidad de transmisión: 115200 baudios                              |       |
| V20200329 | 2020-03-29 | Optimización de tablas de instrucciones y redefinición del identificador de datos         |       |
| V20200329 | 2020-03-29 | Añadida instrucción para leer todos los datos a la vez                                    |       |
| V20200427 | 2020-04-27 | Escritura de ID y descripción de fecha de fabricación                                     |       |
| V20200429 | 2020-04-29 | Añadida dirección 0xB7: número de versión de software                                     |       |
| V20200429 | 2020-04-29 | Descripción detallada de las direcciones 0x8B y 0x8C                                       |       |
| V20200508 | 2020-05-08 | Modificación de la dirección 0x84: de 0.1A a 0.01A                                         |       |
| V20200512 | 2020-05-12 | Redefinición del nombre de la dirección 0x81: temperatura dentro de la caja de batería    |       |
| V20200512 | 2020-05-12 | Redefinición de nombres de 0xA0 y 0xA1                                                     |       |
| V20200512 | 2020-05-12 | Añadido bit de alarma en la dirección 0x8B                                                 |       |
| V20200526 | 2020-05-26 | Añadido ID de reinicio del sistema: 0xBB                                                   |       |
| V20200615 | 2020-06-15 | Añadido 0xB8 para indicar cambio de versión a V2.0                                        |       |
| V20200713 | 2020-07-13 | Añadido flag 0xBC para restaurar valores de fábrica, cambio de versión a V2.1             |       |
| V20200825 | 2020-08-25 | Añadidos 0xBF, 0xBE                                                                       |       |
| V2.4       | 2020-12-04 | Añadido 0xC0 para redefinir el campo de datos de corriente                                 |       |
| V2.5       | 2020-12-17 | Añadida descripción de campos necesarios para reporte                                      |       |

---

## 1. Descripción general

Este protocolo define la comunicación entre la plataforma de monitoreo y el terminal de batería (BMS), incluyendo el formato del mensaje, modo de transmisión y modo de comunicación.

---

## 2. Criterios de referencia

La comunicación utiliza:
- **2G GPRS** en transmisión TCP
- **4G** en GAT1
- Interfaz **Socket**
- Puerto serie **RS232 TTL**
- Formato de comunicación personalizado
- **Velocidad de transmisión:** 115200 baudios

---

## 3. Topología de red

Este protocolo se aplica en modos: **BMS, GPS, Bluetooth, PC** y comunicación punto a punto o en bus.

---

## 4. Contenido del protocolo

### 4.1. Reglas de comunicación

Durante la comunicación, el dispositivo puede tener:
- **Trama de reporte activo**
- **Trama de respuesta pasiva**

Consulte el formato de datos de comunicación para más detalles.

- El intervalo entre cada paquete debe ser **al menos 100 ms**.
- El paquete de respuesta más largo no debe exceder **5 segundos**.
- Transmisión periódica por difusión.
- En modo de reposo, el terminal de control envía información de activación para activar el BMS y luego comienza la comunicación.

---

### 4.2. Formato de la trama

Una trama es la unidad básica de transmisión de información. Incluye: carácter de inicio, longitud, palabra de comando, tipo de transmisión, campo de información, identificador de fin y suma de verificación.

El formato específico se muestra en la **Tabla 1**.

> **Nota:** Los bytes bajos están a la derecha y los bytes altos a la izquierda de la unidad de datos, a menos que se especifique lo contrario. El envío se realiza primero el byte alto y luego el bajo.

#### Tabla 1: Formato de trama

| Nº | Unidad de trama       | Longitud (bytes) | Nota                                                                               |
|----|-----------------------|------------------|------------------------------------------------------------------------------------|
| 1  | STX (inicio)          | 2                | 0x4E (78 "N"), 0x57 (87 "W")                                                        |
| 2  | LENGTH                | 2                | Longitud total de la trama (excluyendo STX)                                        |
| 3  | Número de terminal BMS | 4                | 4 bytes de ID                                                                      |
| 4  | Palabra de comando     | 1                | Ver tabla de comandos                                                              |
| 5  | Fuente de trama        | 1                | 0=BMS, 1=Bluetooth, 2=GPS, 3=PC                                                    |
| 6  | Tipo de transmisión    | 1                | 0=Solicitud, 1=Respuesta, 2=Reporte activo                                         |
| 7  | Unidad de información  | N                | Campo de información: identificador de datos + datos                               |
| 8  | Número de registro     | 4                | Byte alto: código aleatorio (reservado), 3 bytes bajos: número de secuencia        |
| 9  | Fin de identidad       | 1                | 0x68                                                                               |
| 10 | Suma de verificación   | 4                | Suma acumulada de todos los datos desde el inicio hasta el final. CRC16 no usado (alto 2 bytes a 0) |

---

### 4.3. Campo de inicio (STX)

Dos bytes: primer byte `0x4E`, segundo byte `0x57`.

### 4.4. Campo de longitud (LENGTH)

Dos bytes. Incluye todos los bytes de datos excepto los dos primeros caracteres (incluye el campo de longitud y la suma de verificación).

### 4.5. Número de terminal BMS

4 bytes: el byte más alto (por defecto 00) y los 3 bytes bajos son el número de terminal (ID de dimensión única).

### 4.6. Especificación de palabra de comando

Un byte que define la función de transmisión de esta trama.

| Código de comando | Ítem                 | Nota                                                                                  |
|-------------------|----------------------|---------------------------------------------------------------------------------------|
| **0x01**          | Instrucción de activación | Cuando el BMS está inactivo, el controlador envía este comando para activarlo.       |
| **0x02**          | Instrucción de escritura  | Configurar parámetros del BMS.                                                       |
| **0x03**          | Instrucción de lectura    | Leer datos identificadores del BMS.                                                  |
| **0x05**          | Instrucción de código de par | Para modificar parámetros, se requiere este comando previo.                         |
| **0x06**          | Leer todos los datos       | Leer todos los datos de la tabla de identificadores de una sola vez.                 |

### 4.7. Descripción de la fuente de trama

1 byte. Relativo al receptor:
- `0`: BMS
- `1`: Bluetooth
- `2`: GPS
- `3`: PC

### 4.8. Tipo de transmisión

1 byte:
- `0`: Trama de solicitud
- `1`: Trama de respuesta
- `2`: Reporte activo

> Si el iniciador es 5 (Bluetooth), 2 (GPS), 3 (PC) o 4 (BMS), la respuesta usará `1`.

### 4.9. Número de registro

4 bytes: el byte alto es código aleatorio (reservado para cifrado), los 3 bytes bajos son el número de secuencia del registro.

### 4.10. Campo de fin

Un byte: `0x68`

### 4.11. Campo de suma de verificación

4 bytes: suma acumulada de todos los datos desde el inicio hasta el final (incluyendo campos de inicio, longitud, etc.). CRC16 no se usa por ahora; los 2 bytes altos se llenan con `0`.

---

## 5. Formato de datos de comunicación

### 5.1. Ejemplo: lectura de datos GPS (completa o individual)

**Solicitud (PC → BMS):**

| Nº | Unidad               | Longitud | Valor (ejemplo)                              |
|----|----------------------|----------|----------------------------------------------|
| 1  | STX                  | 2        | 0x4E, 0x57                                   |
| 2  | LENGTH               | 2        | (depende de la trama)                        |
| 3  | Número terminal BMS  | 4        | ID del dispositivo                           |
| 4  | Palabra de comando   | 1        | 0x03 (lectura) o 0x06 (todos)                |
| 5  | Fuente de trama      | 1        | 3 (PC)                                       |
| 6  | Tipo de transmisión  | 1        | 0 (solicitud)                                |
| 7  | Identificador de datos | 1      | Código de identificación (Tabla 5.1) / 0x00 para lectura completa |
| 8  | Número de registro   | 4        | Código aleatorio (1 byte) + secuencia (3 bytes) |
| 9  | Fin                  | 1        | 0x68                                         |
| 10 | Suma de verificación | 4        | Suma acumulada                               |

**Respuesta (BMS → PC):**

| Nº | Unidad               | Longitud | Valor (ejemplo)                              |
|----|----------------------|----------|----------------------------------------------|
| 1  | STX                  | 2        | 0x4E, 0x57                                   |
| 2  | LENGTH               | 2        | ...                                          |
| 3  | Número terminal BMS  | 4        | ID del dispositivo                           |
| 4  | Palabra de comando   | 1        | 0x03 / 0x06                                  |
| 5  | Fuente de trama      | 1        | 0 (BMS)                                      |
| 6  | Tipo de transmisión  | 1        | 1 (respuesta)                                |
| 7  | Identificador + datos | 1+N     | Identificador + datos correspondientes       |
| 8  | Número de registro   | 4        | Mismo código que la solicitud                |
| 9  | Fin                  | 1        | 0x68                                         |
| 10 | Suma de verificación | 4        | Suma acumulada                               |

---

### 5.2. Ejemplo: escritura de datos GPS

**Solicitud (PC → BMS):** (estructura similar, comando 0x02)

**Respuesta (BMS → PC):** (similar a la respuesta de lectura, con el identificador de datos en lugar de identificador+datos, indicando éxito)

> **Nota:** Cuando se leen todos los datos, el identificador de datos en la solicitud es `0x00`.

---

### 5.3. Tabla de identificadores de datos del BMS (Tabla 5.1)

| Uso | Identificador | Nombre                        | Bytes | Tipo      | Descripción                                                                                                                                                                                                                     |
|-----|---------------|-------------------------------|-------|-----------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| R   | 0x79          | Voltaje de cada celda         | 3*N   | HEX       | Primer byte: número de celda; los dos siguientes: voltaje en mV. En lectura completa, 0x79 va seguido de un byte de longitud y luego grupos de 3 bytes por celda.                                                               |
| R   | 0x80          | Temperatura del tubo de potencia | 2     | HEX       | 0-140 (-40 a 100 °C). Valores >100 representan temperaturas negativas (100 = referencia, ej. 101 = -1°C).                                                                                                                       |
| R   | 0x81          | Temperatura dentro de la caja  | 2     | HEX       | Misma codificación que 0x80.                                                                                                                                                                                                   |
| R   | 0x82          | Temperatura de la batería      | 2     | HEX       | Misma codificación.                                                                                                                                                                                                             |
| R   | 0x83          | Voltaje total de la batería    | 2     | HEX       | Unidad: 0.01 V. Ej: 3500 → 35.00 V. Mínimo: 10 mV.                                                                                                                                                                              |
| R   | 0x84          | Corriente                      | 2     | HEX       | **Unidad:** 0.01 A (10 mA). Bit más alto: `0` = descarga, `1` = carga. <br> Ej: descarga 20A → 2000 (0x07D0); carga 20A → 34768 (0x87D0). <br> *Nota: versión 0xC0 redefine este campo.*                                        |
| R   | 0x85          | Capacidad remanente (SOC)      | 1     | HEX       | 0-100%                                                                                                                                                                                                                          |
| R   | 0x86          | Número de sensores de temperatura | 1   | HEX       |                                                                                                                                                                                                                                 |
| R   | 0x87          | Ciclos de uso de la batería    | 2     | HEX       |                                                                                                                                                                                                                                 |
| R   | 0x89          | Capacidad total acumulada      | 4     | HEX       | En Ah.                                                                                                                                                                                                                          |
| R   | 0x8A          | Número total de celdas         | 2     | HEX       |                                                                                                                                                                                                                                 |
| R   | 0x8B          | Mensaje de alarma              | 2     | HEX       | Ver tabla de bits de alarma a continuación.                                                                                                                                                                                     |
| R   | 0x8C          | Estado de la batería           | 2     | HEX       | Bit 0: MOS carga (1=on), Bit 1: MOS descarga (1=on), Bit 2: ecualización (1=on), Bit 3: batería caída (1=normal, 0=caída).                                                                                                      |
| RW  | 0x8E          | Protección sobrevoltaje total  | 2     | HEX       | 1000-15000 (10 mV). Unidad: 10 mV.                                                                                                                                                                                              |
| RW  | 0x8F          | Protección subtensión total    | 2     | HEX       | 1000-15000 (10 mV).                                                                                                                                                                                                             |
| RW  | 0x90          | Protección sobrevoltaje por celda | 2   | HEX       | 1000-4500 mV.                                                                                                                                                                                                                   |
| RW  | 0x91          | Voltaje de recuperación por sobretensión | 2 | HEX | 1000-4500 mV.                                                                                                                                                                                                                 |
| RW  | 0x92          | Retardo protección sobretensión | 2     | HEX       | 1-60 segundos.                                                                                                                                                                                                                  |
| RW  | 0x93          | Protección subtensión por celda | 2     | HEX       | 1000-4500 mV.                                                                                                                                                                                                                   |
| RW  | 0x94          | Voltaje de recuperación por subtensión | 2 | HEX | 1000-4500 mV.                                                                                                                                                                                                                 |
| RW  | 0x95          | Retardo protección subtensión  | 2     | HEX       | 1-60 segundos.                                                                                                                                                                                                                  |
| RW  | 0x96          | Diferencial de presión entre celdas | 2 | HEX   | 0-1000 mV.                                                                                                                                                                                                                      |
| RW  | 0x97          | Protección sobrecorriente descarga | 2 | HEX   | 1-1000 A.                                                                                                                                                                                                                       |
| RW  | 0x98          | Retardo sobrecorriente descarga | 2     | HEX       | 1-60 segundos.                                                                                                                                                                                                                  |
| RW  | 0x99          | Protección sobrecorriente carga | 2     | HEX       | 1-1000 A.                                                                                                                                                                                                                       |
| RW  | 0x9A          | Retardo sobrecorriente carga   | 2     | HEX       | 1-60 segundos.                                                                                                                                                                                                                  |
| RW  | 0x9B          | Voltaje de inicio de ecualización | 2 | HEX     | 2000-4500 mV.                                                                                                                                                                                                                   |
| RW  | 0x9C          | Diferencial de apertura de ecualización | 2 | HEX | 10-1000 mV.                                                                                                                                                                                                                     |
| RW  | 0x9D          | Interruptor de ecualización activa | 1   | HEX       | 0=off, 1=on.                                                                                                                                                                                                                    |
| RW  | 0x9E          | Protección temperatura tubo potencia | 2 | HEX   | 0-100 °C.                                                                                                                                                                                                                       |
| RW  | 0x9F          | Valor de recuperación temp. tubo | 2   | HEX       | 0-100 °C.                                                                                                                                                                                                                       |
| RW  | 0xA0          | Protección temperatura caja     | 2     | HEX       | 40-100 °C.                                                                                                                                                                                                                      |
| RW  | 0xA1          | Recuperación temperatura caja   | 2     | HEX       | 40-100 °C.                                                                                                                                                                                                                      |
| RW  | 0xA2          | Diferencial de temperatura protección | 2 | HEX | 5-20 °C.                                                                                                                                                                                                                       |
| RW  | 0xA3          | Protección alta temperatura carga | 2   | HEX       | 0-100 °C.                                                                                                                                                                                                                       |
| RW  | 0xA4          | Protección alta temperatura descarga | 2 | HEX | 0-100 °C.                                                                                                                                                                                                                       |
| RW  | 0xA5          | Protección baja temperatura carga | 2  | HEX       | -45 a +25 °C (sin signo, usar offset).                                                                                                                                                                                          |
| RW  | 0xA6          | Recuperación baja temperatura carga | 2 | HEX   | -45 a +25 °C.                                                                                                                                                                                                                   |
| RW  | 0xA7          | Protección baja temperatura descarga | 2 | HEX | -45 a +25 °C.                                                                                                                                                                                                                   |
| RW  | 0xA8          | Recuperación baja temperatura descarga | 2 | HEX | -45 a +25 °C.                                                                                                                                                                                                                 |
| RW  | 0xA9          | Configuración número de celdas  | 1     | HEX       | 3-32.                                                                                                                                                                                                                           |
| RW  | 0xAA          | Configuración capacidad batería | 4     | HEX       | En Ah.                                                                                                                                                                                                                          |
| RW  | 0xAB          | Interruptor MOS carga           | 1     | HEX       | 0=apagar, 1=abrir.                                                                                                                                                                                                              |
| RW  | 0xAC          | Interruptor MOS descarga        | 1     | HEX       | 0=apagar, 1=abrir.                                                                                                                                                                                                              |
| RW  | 0xAD          | Calibración de corriente        | 2     | HEX       | 100 mA - 20000 mA.                                                                                                                                                                                                              |
| RW  | 0xAE          | Dirección de placa protectora   | 1     | HEX       | Reservado para cascada.                                                                                                                                                                                                         |
| RW  | 0xAF          | Tipo de batería                 | 1     | HEX       | 0=LiFePO4, 1=ternaria, 2=titanato de litio.                                                                                                                                                                                     |
| RW  | 0xB0          | Tiempo de espera de reposo      | 2     | HEX       | Segundos.                                                                                                                                                                                                                       |
| RW  | 0xB1          | Valor de alarma de baja capacidad | 1   | HEX       | 0-80%.                                                                                                                                                                                                                          |
| RW  | 0xB2          | Contraseña de cambio de parámetros | 10 | HEX     | Solo referencia.                                                                                                                                                                                                                |
| RW  | 0xB3          | Interruptor de cargador especial | 1    | HEX       | 0=off, 1=on.                                                                                                                                                                                                                    |
| RW  | 0xB4          | Código ID del dispositivo       | 8     | caracter  | Ej: "60300001" (60=voltaje nominal, 3=material ternario, 00001=serial).                                                                                                                                                         |
| RW  | 0xB5          | Fecha de fabricación            | 4     | caracter  | Ej: "2004" (20=año, 04=mes).                                                                                                                                                                                                    |
| RW  | 0xB6          | Tiempo de trabajo del sistema   | 4     | HEX       | Unidad: puntos (borrado de fábrica).                                                                                                                                                                                             |
| R   | 0xB7          | Número de versión de software   | 15    | caracter  | Ej: "NW_1_0_0_200428".                                                                                                                                                                                                          |
| RW  | 0xB8          | Iniciar calibración de corriente| 1     | HEX       | 1=iniciar, 0=cerrar.                                                                                                                                                                                                            |
| RW  | 0xB9          | Capacidad real de la batería    | 4     | HEX       | En Ah.                                                                                                                                                                                                                          |
| RW  | 0xBA          | Nombre del fabricante ID        | 24    | caracter  | Ej: "BT3072020120000200521001" (ver desglose en nota).                                                                                                                                                                           |
| W   | 0xBB          | Reiniciar sistema               | 1     | HEX       | 1=reiniciar.                                                                                                                                                                                                                    |
| W   | 0xBC          | Restaurar datos de fábrica      | 1     | HEX       | 1=restaurar (solo parámetros base).                                                                                                                                                                                              |
| W   | 0xBD          | Identificación de actualización remota | 1 | HEX   | 1=iniciar.                                                                                                                                                                                                                      |
| W   | 0xBE          | Apagar GPS por bajo voltaje de celda | 2 | HEX | Unidad: mV.                                                                                                                                                                                                                     |
| W   | 0xBF          | Recuperar GPS por voltaje de celda | 2 | HEX   | Unidad: mV.                                                                                                                                                                                                                     |
| R   | 0xC0          | Número de versión del protocolo | 1     | HEX       | 0x00 por defecto, 0x01 redefine 0x84 a 10 mA con bit alto para signo.                                                                                                                                                           |

---

### 5.4. Tabla de bits de alarma (dirección 0x8B)

| Bit | Descripción                               | 1 = Alarma, 0 = Normal |
|-----|-------------------------------------------|------------------------|
| 0   | Baja capacidad (alarma)                   | Sí                     |
| 1   | Sobrecalentamiento del tubo MOS           | Sí                     |
| 2   | Sobretensión de carga                     | Sí                     |
| 3   | Subtensión de descarga                    | Sí                     |
| 4   | Sobretemperatura de la batería            | Sí                     |
| 5   | Sobrecorriente de carga                   | Sí                     |
| 6   | Sobrecorriente de descarga                | Sí                     |
| 7   | Diferencial de presión entre celdas       | Sí                     |
| 8   | Sobretemperatura en la caja               | Sí                     |
| 9   | Baja temperatura de la batería            | Sí                     |
| 10  | Sobretensión de unidad (celda)            | Sí                     |
| 11  | Subtensión de unidad (celda)              | Sí                     |
| 12  | Protección 309_A                          | Sí                     |
| 13  | Protección 309_B                          | Sí                     |
| 14  | Reservado                                 | -                      |
| 15  | Reservado                                 | -                      |

Ejemplo: `0x0001` → Alarma de baja capacidad.

---

### 5.5. Notas importantes

1. **Todos los campos marcados con R o RW en 0x79 ~ 0xB9 deben ser reportados.** Si alguna versión antigua no los reporta, se recomienda actualizar. En caso contrario, contactar al soporte técnico.
2. **0xBA** (ID del fabricante) es obligatorio para aplicaciones de armarios de intercambio de baterías.

---

## 6. Recomendaciones de implementación

- Velocidad: **115200 bps**.
- Tiempo entre paquetes: **mínimo 100 ms**.
- Tiempo máximo de respuesta: **5 segundos**.
- Suma de verificación: acumulativa sobre todos los bytes desde STX hasta el fin (incluyendo longitud y campo de verificación). Los dos bytes altos de la suma de verificación se reservan para CRC16 (por ahora cero).
- Los números de registro deben ser incrementales para cada nuevo envío; el byte alto puede ser aleatorio.

---

*Fin del documento.*