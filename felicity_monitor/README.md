# Felicity Inverter Monitor

App PyQt5 para monitorear inversores híbridos Felicity 5K via RS232 / protocolo PI30.

## Estructura

```
felicity_monitor/
├── main.py                 ← Punto de entrada, UI PyQt5
├── setup_env.py            ← Crea venv e instala dependencias
├── core/
│   ├── protocol.py         ← Parser PI30: QPIGS, QPIRI, QMOD, QPIWS, Q1
│   └── serial_engine.py    ← Motor RS232, hilos de monitoreo y auto-detección
└── README.md
```

## Instalación rápida

```bash
# 1. Clonar / descargar el proyecto
cd felicity_monitor

# 2. Crear entorno virtual e instalar todo
python setup_env.py

# 3. Activar el entorno
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows

# 4. Ejecutar
python main.py
```

## Conexión física RS232

| Pin RS232 (DB9) | Cable | Inversor Felicity |
|---|---|---|
| Pin 2 (RX) | → | TX del inversor |
| Pin 3 (TX) | → | RX del inversor |
| Pin 5 (GND) | → | GND |

> Muchos inversores Felicity tienen un puerto RJ11 (teléfono).  
> Necesitas un adaptador RS232 → RJ11 con el pinout correcto.

## Parámetros por defecto

- Baud rate: **2400**
- Data bits: 8
- Paridad: None
- Stop bits: 1

Usa el botón **Auto-detectar** si no sabes la velocidad exacta.

## API REST

Una vez iniciado desde la pestaña "API & Exportar":

```
GET http://localhost:8000/datos          # Todos los valores
GET http://localhost:8000/datos/bateria  # Solo batería
GET http://localhost:8000/datos/solar    # Solo panel solar
GET http://localhost:8000/datos/red      # Solo red eléctrica
GET http://localhost:8000/health         # Estado del servidor
```

## Comandos PI30 soportados

| Comando | Descripción |
|---|---|
| QPIGS | Estado general en tiempo real (20+ campos) |
| QPIRI | Parámetros de configuración del inversor |
| QMOD | Modo de operación actual |
| QPIWS | Estado de alarmas (32 bits) |
| Q1 | Estado cargador solar + temperaturas |
| QPI | Identificación del protocolo |
| QVFW | Versión de firmware |
| QID | Número de serie |

## Datos en tiempo real (QPIGS)

| Campo | Unidad | Descripción |
|---|---|---|
| grid_voltage | V | Tensión de la red eléctrica |
| grid_frequency | Hz | Frecuencia de red |
| output_voltage | V | Tensión de salida al hogar |
| output_watts | W | Potencia activa de salida |
| load_percent | % | Porcentaje de carga del inversor |
| battery_voltage | V | Voltaje actual de batería |
| battery_capacity | % | Estado de carga SOC |
| pv_voltage | V | Voltaje del panel solar |
| pv_current | A | Corriente del panel solar |
| pv_power | W | Potencia solar (calculada) |
| heatsink_temp | °C | Temperatura del disipador |
