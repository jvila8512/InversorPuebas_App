# Datos devueltos por el inversor de alta frecuencia (protocolo MODBUS)

Este documento lista todos los registros que el inversor puede enviar en una trama de respuesta, ya sea de lectura (`0x03`) o de escritura (`0x06`, `0x10`). Los valores están accesibles mediante las direcciones indicadas.

## 1. Información del dispositivo (solo lectura)

| Dirección (Hex) | Tamaño (Words) | Nombre | Tipo | Unidad | Descripción |
|----------------|----------------|--------|------|--------|-------------|
| 0xF800 | 1 | Tipo de equipo | INT16U | - | Siempre `0x50` (inversor de alta frecuencia) |
| 0xF801 | 1 | Subtipo | INT16U | - | `0x0204` = 3024 (3000VA/24V)<br>`0x0408` = 5048 (5000VA/48V) |
| 0xF804 | 5 | Número de serie | INT16U | - | 5 palabras: SN[0..4]. Ejemplo: `[0x0135, 0x4820, 0x2500, 0x0100, 0x0000]` → 0135482025000100 |
| 0xF80B | 1 | Versión firmware CPU1 | INT16U | - | `0xFFFF` = inválido |
| 0xF80C | 1 | Versión firmware CPU2 | INT16U | - | `0xFFFF` = inválido |

## 2. Datos en tiempo real (solo lectura)

| Dirección (Hex) | Tamaño | Nombre | Tipo | Unidad | Rango / Descripción |
|----------------|--------|--------|------|--------|---------------------|
| 0x1100 | 1 | SettingDataSn | INT16U | - | Número de cambios en parámetros de configuración |
| 0x1101 | 1 | Modo de trabajo | INT16U | - | 0=PowerOn, 1=Standby, 2=Bypass, 3=Batería, 4=Fallo, 5=Red, 6=Carga PV |
| 0x1102 | 1 | Etapa de carga | INT16U | - | 0=No carga, 1=Carga constante, 2=Carga tensión cte, 3=Carga flotante |
| 0x1103 | 1 | Código de fallo | INT16U | - | Ver tabla específica (no incluida) |
| 0x1104 | 1 | PowerFlowMsg | INT16U | - | Bits: b15=batería conectada, b14=red normal, b13=PV normal, b12=carga permitida, b11b10=flujo batería (00=nada,01=carga,10=descarga), b9b8=flujo red (00=nada,01=toma,10=inyección), b7=MPPT activo, b6=carga conectada, b0=soporte flujo |
| 0x1108 | 1 | Voltaje de batería | INT16U | 0.1 V | Ej: 240 → 24.0 V |
| 0x1109 | 1 | Corriente de batería | INT16S | 0.1 A | Positiva = descarga, negativa = carga |
| 0x110A | 1 | Potencia de batería | INT16S | 1 W | Positiva = descarga, negativa = carga |
| 0x1111 | 1 | Voltaje de salida AC | INT16U | 0.1 V | Tensión de salida del inversor |
| 0x1117 | 1 | Voltaje de entrada AC | INT16U | 0.1 V | Tensión de red |
| 0x1119 | 1 | Frecuencia de entrada AC | INT16U | 0.01 Hz | Ej: 5000 → 50.00 Hz |
| 0x111E | 1 | Potencia activa de salida | INT16S | 1 W | Potencia real entregada a la carga |
| 0x111F | 1 | Potencia aparente de salida | INT16U | 1 VA | |
| 0x1120 | 1 | Porcentaje de carga | INT16U | 1 % | 0–100% |
| 0x1126 | 1 | Voltaje de entrada PV | INT16U | 0.1 V | Tensión de paneles solares |
| 0x112A | 1 | Potencia de entrada PV | INT16S | 1 W | Potencia generada por PV |

## 3. Parámetros de configuración (lectura/escritura)

| Dirección (Hex) | Tamaño | Nombre | Tipo | Unidad | Rango / Descripción | Valores típicos |
|----------------|--------|--------|------|--------|---------------------|-----------------|
| 0x211F | 1 | Voltaje de corte batería | INT16U | 0.1 V | 3024: 21.0–27.0 V<br>5048: 42.0–54.0 V | 420 → 42.0 V |
| 0x2122 | 1 | Voltaje carga absorción | INT16U | 0.1 V | 3024: 24.0–30.0 V<br>5048: 48.0–60.0 V | 576 → 57.6 V |
| 0x2123 | 1 | Voltaje carga flotante | INT16U | 0.1 V | 3024: 24.0–30.0 V<br>5048: 48.0–60.0 V | 544 → 54.4 V |
| 0x2129 | 1 | Frecuencia de salida | INT8U | - | 0=50 Hz, 1=60 Hz | 0 |
| 0x212A | 1 | Prioridad fuente salida | INT8U | - | 0=Red primero, 1=PV primero, 2=PV+Bat+Red | 0 |
| 0x212B | 1 | Modo aplicación | INT8U | - | 0=APL, 1=UPS | 0 |
| 0x212C | 1 | Prioridad fuente carga | INT8U | - | 1=PV primero, 2=PV+Red, 3=Solo PV | 1 |
| 0x212D | 1 | Tipo de batería | INT8U | - | 0=Gel, 1=Flooded, 2=Usuario, 3=LiFePO₄ | 0 |
| 0x212E | 1 | Corriente máx. carga total | INT8U | 1 A | 10–100 A | 60 |
| 0x2130 | 1 | Corriente máx. carga red | INT8U | 1 A | 10–100 A | 30 |
| 0x2131 | 1 | Buzzer | INT8U | - | 0=Desactivado, 1=Activado | 1 |
| 0x2133 | 1 | Reinicio por sobrecarga | INT8U | - | 0=No, 1=Sí | 0 |
| 0x2134 | 1 | Reinicio por sobretemp. | INT8U | - | 0=No, 1=Sí | 1 |
| 0x2135 | 1 | Retroiluminación LCD | INT8U | - | 0=Apagada, 1=Encendida | 0 |
| 0x2137 | 1 | Bypass por sobrecarga | INT8U | - | 0=No, 1=Sí | 0 |
| 0x2156 | 1 | Voltaje retorno carga | INT16U | 0.1 V | 3024: 22.0–27.0 V<br>5048: 44.0–54.0 V | 460 → 46.0 V |
| 0x2159 | 1 | Voltaje retorno descarga | INT16U | 0.1 V | 3024: 24.0–30.1 V (30.1=FULL)<br>5048: 48.0–60.1 V | 540 → 54.0 V |

## Ejemplo de trama de respuesta (lectura de voltaje y corriente de batería)

**Petición (leer registros 0x1108 y 0x1109):**