# PRD: Extensión Multi-Inversor para Aplicación de Monitoreo Felicity

**Versión:** 1.0  
**Fecha:** 21/05/2026  
**Autor:** Equipo de Producto  
**Estado:** Propuesta para análisis  

---

## 1. Resumen Ejecutivo

La aplicación actual de monitoreo se conecta vía TCP/IP a un gateway RS232 y lee datos de un único inversor Felicity. Sin embargo, muchos clientes tienen instalaciones con múltiples inversores Felicity conectados en paralelo (hasta 10 unidades) para alcanzar mayores potencias (ej. 50kW con 10 inversores de 5kW).  

Esta propuesta extiende la funcionalidad de la aplicación para **soportar la lectura y visualización de todos los inversores conectados en paralelo**, a través del mismo gateway TCP/IP a RS232, sin necesidad de hardware adicional. Se añadirá una nueva pestaña que muestra:

- Resumen global del sistema (potencias totales, alertas, estado general)
- Tabla detallada con información individual de cada inversor (voltaje, corriente, potencia, fallos, etc.)

La funcionalidad será **configurable** (número de inversores, IDs, timeouts) y **totalmente compatible** con el modo de un solo inversor existente.

---

## 2. Contexto y Justificación

### 2.1. Situación actual

- La aplicación se conecta a un gateway **TCP/IP → RS232** (conector RJ45) que está cableado al puerto de comunicaciones de un inversor Felicity.
- El usuario puede visualizar datos en tiempo real de **un solo inversor** (el que responde a la dirección Modbus configurada, normalmente ID 1).
- Los inversores Felicity soportan trabajar en **paralelo** (máster-esclavo) y se comunican entre sí mediante sus puertos dedicados (cableado RJ45 en cadena).

### 2.2. Necesidad detectada

- Los clientes con múltiples inversores en paralelo desean **monitorizar el sistema completo** (suma de potencias, estados individuales, detección de fallos por unidad).
- Actualmente, para ver los datos de cada inversor tendrían que cambiar físicamente el cable de comunicaciones o usar múltiples gateways, lo cual es inviable.

### 2.3. Solución propuesta

Aprovechar la capacidad del inversor **máster** de reenviar peticiones Modbus a los esclavos a través de la red de paralelo. Desde la aplicación, solo necesitamos:

1. Enviar peticiones a diferentes IDs Modbus (1, 2, 3, … N) usando la **misma conexión TCP/IP** al gateway.
2. Implementar un **bucle de consultas** y agregar los datos.
3. Mostrar la información en una nueva pestaña.

**No se requiere ningún cambio en el hardware ni en el cableado existente.**

---

## 3. Alcance

### 3.1. Dentro del alcance

- Modificación del archivo de configuración para incluir parámetros multi-inversor.
- Implementación de un **motor de polling cíclico** (lectura secuencial de todos los IDs).
- Lógica de **agregación de datos** (sumas, promedios, detección de fallos).
- Nueva pestaña en la interfaz con dos secciones:
  - **Resumen global del sistema** (tarjetas con totales).
  - **Tabla detallada de cada inversor** (parámetros individuales).
- Actualización de la ayuda/documentación del usuario.

### 3.2. Fuera del alcance

- Escritura de comandos de control en inversores esclavos (solo lectura).
- Soporte para otros protocolos o marcas.
- Cambios en la topología física de comunicaciones (responsabilidad del cliente).

---

## 4. Requisitos Funcionales (RF)

| ID | Requisito | Prioridad |
|----|-----------|------------|
| **RF-01** | La aplicación DEBE leer un parámetro `TotalInverters` (entero 1..15) desde la configuración. Si no existe, asume `1` (modo actual). | Alta |
| **RF-02** | La aplicación DEBE permitir configurar el `StartInverterID` (por defecto 1) para flexibilidad. | Media |
| **RF-03** | Se DEBE añadir una nueva pestaña denominada **"Sistema en Paralelo"** (o nombre similar). | Alta |
| **RF-04** | La pestaña DEBE contener una sección de **resumen global** con: <br> - Potencia AC total (suma de `0x111E` de todos los inversores online)<br> - Potencia PV total (suma de `0x112A`)<br> - Potencia neta de batería (suma de `0x110A`)<br> - Voltaje promedio de batería (promedio de `0x1108`)<br> - Número de inversores activos / total configurados<br> - Alerta general si algún inversor tiene código de fallo ≠ 0 | Alta |
| **RF-05** | La pestaña DEBE contener una **tabla con una fila por cada ID** configurado. Cada fila mostrará: <br> - ID (dirección Modbus)<br> - Estado de conexión (Online / Offline / Falla)<br> - Modo de trabajo (`0x1101` decodificado)<br> - Voltaje de batería (`0x1108`)<br> - Corriente de batería (`0x1109`)<br> - Potencia de batería (`0x110A`)<br> - Potencia AC de salida (`0x111E`)<br> - Voltaje AC de salida (`0x1111`)<br> - Código de fallo (`0x1103`) y su descripción | Alta |
| **RF-06** | La aplicación DEBE leer de cada inversor los registros `0x1108,0x1109,0x110A,0x1111,0x1101,0x1103,0x111E,0x1126,0x112A` usando la función Modbus `0x03` (lectura de múltiples registros). | Alta |
| **RF-07** | El tiempo de espera (timeout) para cada petición DEBE ser configurable (ej. 500 ms). Si un ID no responde, se marcará como **Offline** y se continuará con el siguiente. | Alta |
| **RF-08** | Los valores crudos DEBEN ser transformados según el protocolo (`override`): división por 100 para voltaje/corriente, división por 10 para voltajes AC, manejo de signo para potencias y corriente. | Alta |
| **RF-09** | La tabla DEBE permitir **ordenar** por cualquier columna (ID, potencia, voltaje, etc.) y **resaltar** filas con fallos (color rojo) o advertencias (color naranja). | Media |
| **RF-10** | Al hacer clic en una fila de la tabla, la aplicación DEBE navegar a la pestaña de detalle de ese inversor (si ya existe la vista individual). | Baja |
| **RF-11** | El intervalo de actualización de la pestaña DEBE ser configurable (por defecto 5 segundos). | Media |

---

## 5. Requisitos No Funcionales (RNF)

| ID | Requisito | Prioridad |
|----|-----------|------------|
| **RNF-01** | El ciclo completo de consulta para 10 inversores NO DEBE exceder los 5 segundos en condiciones normales de red. | Alta |
| **RNF-02** | La nueva funcionalidad NO DEBE afectar el rendimiento de las otras pestañas (debe ejecutarse en un hilo o proceso separado). | Alta |
| **RNF-03** | El consumo de memoria adicional debe ser inferior a 50 MB para 10 inversores. | Media |
| **RNF-04** | La aplicación DEBE manejar reconexiones automáticas al gateway si se pierde la conexión TCP. | Media |
| **RNF-05** | La configuración multi-inversor DEBE ser persistente y poder modificarse sin reiniciar la aplicación (recargando la configuración en caliente). | Baja |

---

## 6. Diseño de la Interfaz de Usuario

### 6.1. Nueva pestaña: "Sistema en Paralelo"

La pestaña se dividirá en dos áreas principales:
#### 6.1.1. Área de resumen global (tarjetas)
┌────────────────────────────────────────────────────────────────────────────────┐
│ 🔋 RESUMEN DEL SISTEMA 🔄 5s │
├────────────────────────────────────────────────────────────────────────────────┤
│ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ │
│ │ ⚡ Potencia AC │ │ ☀️ Potencia PV │ │ 🔋 Pot. Batería │ │
│ │ 5220 W │ │ 3100 W │ │ -850 W │ │
│ └─────────────────┘ └─────────────────┘ └─────────────────┘ │
│ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────────────┐ │
│ │ 🔋 Voltaje prom.│ │ 🖥️ Activos │ │ ⚠️ Alertas │ │
│ │ 50.8 V │ │ 6 / 7 │ │ • Inv. 3: Batería baja │ │
│ └─────────────────┘ └─────────────────┘ │ • Inv. 5: Sobrecalentamiento │ │
│ └─────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────┘

text

#### 6.1.2. Tabla detallada de inversores

| ID | Estado | Modo | V.Bat (V) | I.Bat (A) | P.Bat (W) | P.AC (W) | V.AC (V) | Fallo |
|----|--------|------|-----------|-----------|-----------|----------|----------|-------|
| 1  | 🟢 Online | Line | 51.2 | -12.5 | -640 | 1200 | 230.1 | - |
| 2  | 🟢 Online | Line | 51.3 | -11.8 | -605 | 1150 | 229.8 | - |
| 3  | 🟠 Warning | Battery | 49.8 | +5.2 | +260 | 800 | 228.5 | Batería baja (01) |
| 4  | ⚫ Offline | - | - | - | - | - | - | Timeout |
| 5  | 🔴 Fault | Fault | 0.0 | 0.0 | 0 | 0 | 0 | Sobrecalentamiento (09) |
| 6  | 🟢 Online | PV Charge | 51.4 | -10.2 | -524 | 1050 | 230.0 | - |
| 7  | 🟢 Online | Line | 51.0 | -11.0 | -561 | 1100 | 229.9 | - |

**Leyenda:** 🟢 Online sin fallos | 🟠 Online con advertencia | 🔴 Falla crítica | ⚫ Sin comunicación

### 6.2. Comportamiento de actualización

- Los datos se actualizan automáticamente cada `PollInterval` segundos (configurable).
- Durante la actualización, la tabla muestra un indicador de carga.
- Si algún inversor deja de responder durante 3 ciclos consecutivos, se marca como "Offline" y se muestra un mensaje de alerta persistente.

---

## 7. Detalle técnico de implementación

### 7.1. Parámetros de configuración

Se añadirán al archivo de configuración (ej. `appsettings.json` o `.env`) las siguientes claves:

```json
{
  "ModbusGateway": {
    "IpAddress": "192.168.1.100",
    "Port": 502,
    "TimeoutMs": 800
  },
  "MultiInverter": {
    "Enabled": true,
    "TotalInverters": 7,
    "StartId": 1,
    "PollIntervalSec": 5,
    "RetryOnTimeout": 1
  }
}
### 7.2. Lógica de lectura (pseudo-código)

```python
# Ejemplo en Python, adaptable a otros lenguajes
def poll_all_inverters(config):
    results = []
    for inv_id in range(config.start_id, config.start_id + config.total_inverters):
        try:
            # Leer bloque de registros 0x1100-0x1111 (13 registros? Ajustar)
            block = client.read_holding_registers(0x1100, 13, slave=inv_id)
            if block.isError():
                results.append({"id": inv_id, "status": "error"})
                continue

            # Decodificar según offsets del protocolo
            working_mode = block.registers[1]    # 0x1101
            fault_code = block.registers[3]      # 0x1103
            v_bat = block.registers[8] / 100.0   # 0x1108
            i_bat = block.registers[9] / 100.0   # 0x1109
            p_bat = block.registers[10]          # 0x110A
            v_ac_out = block.registers[17] / 10.0 # 0x1111 (si está en el bloque)

            # Leer otros registros por separado si no están en bloque
            p_ac = client.read_holding_registers(0x111E, 1, slave=inv_id).registers[0]
            p_pv = client.read_holding_registers(0x112A, 1, slave=inv_id).registers[0]

            results.append({
                "id": inv_id, "status": "online",
                "mode": working_mode, "fault": fault_code,
                "v_bat": v_bat, "i_bat": i_bat, "p_bat": p_bat,
                "v_ac_out": v_ac_out, "p_ac": p_ac, "p_pv": p_pv
            })
        except Exception as e:
            results.append({"id": inv_id, "status": "offline", "error": str(e)})
    return results
7.3. Decodificación de modos y fallos
Según el protocolo proporcionado:

Modo (0x1101)	Descripción
0	PowerOnMode
1	StandbyMode
2	BypassMode
3	BatteryMode
4	FaultMode
5	LineMode
6	PVChargeMode
Los códigos de fallo (0x1103) se extraerán de la tabla "high frequency inverter fault alarm table" (documento aparte, pero debe integrarse en la aplicación).

7.4. Manejo de timeouts
Dado que el gateway TCP/IP a RS232 no responde con un error Modbus si el ID no existe, la librería cliente lanzará una excepción de timeout. La aplicación capturará esa excepción y continuará con el siguiente ID. Se recomienda un timeout no superior a 800 ms para no ralentizar el ciclo.

8. Flujo de trabajo del usuario
El usuario actualiza la configuración de la aplicación indicando MultiInverter.Enabled = true y TotalInverters = 7 (o el número que tenga).

Al iniciar la aplicación, aparece la nueva pestaña "Sistema en Paralelo".

La aplicación comienza a consultar cíclicamente los IDs desde 1 hasta 7.

En la pestaña se muestran los datos globales y la tabla con los 7 inversores.

Si un inversor deja de responder, aparece como "Offline" y se genera una alerta.

El usuario puede hacer clic en cualquier fila para ver los detalles históricos o gráficos de ese inversor (si esa funcionalidad ya existe en otra pestaña).

Si el usuario vuelve a configurar TotalInverters = 1 o deshabilita la función, la pestaña se oculta (o muestra un mensaje "Modo mono-inversor activo").

9. Criterios de aceptación
La aplicación lee correctamente los parámetros multi-inversor desde la configuración.

Aparece la nueva pestaña cuando Enabled=true y TotalInverters>1.

Todos los inversores configurados son consultados secuencialmente sin bloquear la UI.

Los datos mostrados en la tabla coinciden con los valores reales de cada inversor (validación en sitio de pruebas con al menos 3 inversores).

Los totales (suma de potencias, promedio de voltajes) son correctos.

Los fallos y advertencias se muestran con el color y el texto adecuado.

Un timeout en un ID no impide la lectura del siguiente.

El rendimiento es aceptable (ciclo completo < 5s para 10 inversores).

La funcionalidad existente de un solo inversor sigue funcionando sin cambios.

10. Riesgos y mitigación
Riesgo	Probabilidad	Impacto	Mitigación
El inversor máster no reenvía peticiones a IDs diferentes al suyo	Media	Alto	Verificar con el fabricante; alternativa: leer todos los datos del máster (si los consolida) si existe un registro agregado.
Timeouts excesivos ralentizan el sistema	Baja	Medio	Hacer timeouts configurables y bajos (500ms). Implementar consultas en paralelo con múltiples conexiones TCP (si el gateway lo soporta).
El gateway TCP/IP a RS232 no soporta cambios rápidos de ID	Baja	Medio	Usar una única conexión y esperar el tiempo necesario entre peticiones (small delay).
Diferentes modelos de inversor tienen diferente mapa de registros	Media	Media	Hacer que la lista de registros sea configurable por modelo, o leer dinámicamente el DeviceType (0xF800) antes de iniciar el polling.
11. Plan de pruebas sugerido
Pruebas unitarias – Simular un cliente Modbus falso que responde con datos conocidos para verificar la agregación y decodificación.

Pruebas de integración – Conectar a un banco de pruebas de al menos 3 inversores Felicity en paralelo, configurar la aplicación con TotalInverters=3 y validar los datos visuales contra mediciones directas (multímetro, pinza).

Pruebas de tolerancia a fallos – Desconectar físicamente un inversor de la red de paralelo y verificar que se marca como Offline y no afecta a los demás.

Pruebas de rendimiento – Medir el tiempo de ciclo para 1, 5, 10 y 15 inversores, asegurando que cumple RNF-01.

Pruebas de regresión – Verificar que la funcionalidad de un solo inversor (con TotalInverters=1 o sin parámetros) sigue funcionando exactamente igual que antes.

12. Entregables
Código fuente modificado (backend de polling + nueva pestaña).

Archivo de configuración de ejemplo actualizado.

Documentación de usuario actualizada (incluyendo cómo configurar y usar la función multi-inversor).

Informe de pruebas.

13. Aprobaciones
Rol	Nombre	Firma	Fecha
Product Owner			
Technical Lead			
QA Lead			
Historial de cambios

Versión	Fecha	Autor	Cambios
1.0	21/05/2026	Equipo de Producto	Creación inicial del documento
text

