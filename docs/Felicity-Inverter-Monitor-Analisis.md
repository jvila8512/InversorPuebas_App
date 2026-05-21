# Análisis Técnico: Felicity-Inverter-Monitor

**Fecha del análisis:** 19 de Mayo de 2026  
**Repositorio:** `Felicity-Inverter-Monitor-master`  
**Tecnología:** .NET 6/7/8, Blazor WebAssembly, FastEndpoints, System.IO.Ports

---

## 1. Resumen Ejecutivo

Esta aplicación es un sistema de monitoreo en tiempo real para **inversores FelicitySolar** y **BMS JK (Jikong)** mediante comunicación serial (RS232/RS485).

- **Cliente:** Blazor WebAssembly (SPA) alojado en el mismo servidor.
- **Servidor:** API REST ligera usando **FastEndpoints**.
- **Comunicación:** Serial directa (puerto COM en Windows, `/dev/ttyUSB*` en Linux).
- **Persistencia:** SQLite (para historial de generación PV) y configuración en JSON.

---

## 2. Arquitectura del Sistema

### 2.1 Estructura de Proyectos

```
src/
├── Server/                 # API Backend + Lógica de Comunicación
│   ├── BatteryService/     # Servicio BMS JK
│   ├── InverterService/    # Servicio Inversor Felicity
│   ├── Endpoints/          # Endpoints de FastEndpoints
│   ├── Persistance/        # SQLite & Settings
│   └── Program.cs          # Inyección de dependencias
├── Client/                 # Blazor WASM Frontend
│   ├── Pages/              # Dashboard, BMS, Settings
│   └── AppState/           # Estado global del cliente
├── Shared/                 # Modelos de datos compartidos
│   └── Models/             # InverterStatus, BMSStatus, etc.
└── InverterMonWindow/      # (Opcional) App de escritorio WinForms
```

### 2.2 Flujo de Datos

1. **Background Services:**
   - `StatusRetriever`: Se conecta al inversor cada ~2s, lee registros Modbus, actualiza `InverterStatus`.
   - `JkBms`: Se conecta al BMS, lee tramas RS485, actualiza `BMSStatus` cada ~1s.
2. **API Endpoints:**
   - `/api/get-status`: Stream de datos del inversor.
   - `/api/bms-status`: Stream de datos del BMS.
   - `/api/settings/*`: Lectura/escritura de configuraciones.
3. **Cliente Blazor:**
   - Consume los streams HTTP con `ResponseStreamingEnabled`.
   - Actualiza la UI en tiempo real sin recargas.

---

## 3. Comunicación con Inversores Felicity (Modbus RTU)

### 3.1 Configuración del Puerto Serial
- **BaudRate:** 2400 bps
- **Paridad:** None
- **DataBits:** 8
- **StopBits:** One
- **Dirección del Slave:** 0x01 (Hardcoded)
- **Timeout:** 1000ms

**Código Clave (`FelicityInverter.cs`):**
```csharp
_serialPort = new(portName, 2400, Parity.None, 8, StopBits.One);
```

### 3.2 Protocolo Modbus Implementado

La aplicación implementa un cliente Modbus RTU personalizado sin librerías externas.

#### Funciones Utilizadas:
1. **0x03 (Read Holding Registers):** Para leer estado y configuración.
2. **0x06 (Write Single Register):** Para modificar parámetros.

#### Cálculo de CRC-16 (Modbus)
Se implementa un algoritmo CRC-16 estándar (polinomio 0xA001):
```csharp
ushort CalculateCrc(byte[] data, int length) {
    ushort crc = 0xFFFF;
    for (var pos = 0; pos < length; pos++) {
        crc ^= data[pos];
        for (var i = 0; i < 8; i++) {
            if ((crc & 0x0001) != 0) {
                crc >>= 1;
                crc ^= 0xA001;
            } else crc >>= 1;
        }
    }
    return crc;
}
```

### 3.3 Registros de Estado (Read)
- **Rango:** `0x1101` a `0x112A` (42 registros).
- **Datos Extraídos:**
  - `0x1101`: Working Mode (Modo de trabajo)
  - `0x1102`: Charge Mode (Modo de carga)
  - `0x1108`: Battery Voltage (Tensión batería) -> `valor / 100`
  - `0x1109`: Battery Current (Corriente) -> Signed (positivo=carga, negativo=descarga)
  - `0x110A`: Battery Power (Potencia)
  - `0x1111`: Output Voltage (Tensión salida AC)
  - `0x1117`: Grid Voltage (Tensión red)
  - `0x111E`: Load Watts (Potencia carga)
  - `0x1120`: Load Percentage (%)
  - `0x1126`: PV Input Voltage (Tensión PV)
  - `0x112A`: PV Input Power (Potencia PV)

### 3.4 Registros de Configuración (Read/Write)
- **Rango:** `0x211F` a `0x2159`.
- **Parámetros Modificables:**
  - Tensión de corte de batería.
  - Tensión de carga CV.
  - Tensión de flotación.
  - Prioridad de salida (SOL/RED/BAT).
  - Prioridad de carga.
  - Corrientes máximas.

**Escritura de Configuración:**
Se construye un frame de 8 bytes:
`[Slave][0x06][AddrHi][AddrLo][ValHi][ValLo][CRC Lo][CRC Hi]`

---

## 4. Comunicación con BMS JK (JK-BMS-RS485)

### 3.1 Configuración del Puerto Serial
- **Puerto por defecto:** `/dev/ttyUSB0` (Linux) o configurable en `appsettings.json`.
- **BaudRate:** 9600 bps (implícito en la librería `SerialPortLib`).
- **Polling:** Cada 1000ms.

### 4.2 Protocolo Propietario JK
No usa Modbus estándar. Usa un protocolo binario propietario con trama de encabezado.

**Estructura de la Trama de Respuesta:**
1. **Encabezado:** Se saltan los primeros 10 bytes (`data[11..]`).
2. **Contador de Celdas:** Byte en la posición 1 del resto de datos (`res[1] / 3` = número de celdas).
3. **Voltaje de Celdas:** 3 bytes por celda (ID + 2 bytes de voltaje).
4. **Temperaturas:**
   - MOS FET Temp.
   - Sensor 1.
   - Sensor 2.
5. **Tensión de Paquete:** 2 bytes (`/ 100` = Voltaje).
6. **Corriente:** 2 bytes (Bit 15 indica sentido: 0=Descarga, 1=Carga).
7. **Capacidad:** Porcentaje (%) y Capacidad total (Ah).

**Código Clave (`JK-BMS-RS485-Service.cs`):**
```csharp
var res = data[11..];       // Saltar cabecera
var cellCount = res[1] / 3; // 3 bytes por celda

// Lectura de celdas
for (byte i = 1; i <= cellCount; i++)
    Status.Cells[i] = res.Read2Bytes(pos += 3) / 1000f;

// Tensión y Corriente
Status.PackVoltage = res.Read2Bytes(pos += 3) / 100f;
var rawVal = res.Read2Bytes(pos += 3);
Status.IsCharging = Convert.ToBoolean(...); // Bit 15
```

### 4.3 Datos Monitorizados del BMS
- **Voltaje total del pack.**
- **Corriente promedio** (se usa una cola de 5 lecturas para suavizar).
- **Estado de carga (SOC %).**
- **Temperaturas** (MOS, Sensor 1, Sensor 2).
- **Desequilibrio de celdas** (Máx, Mín, Delta).
- **Tiempo estimado** hasta carga/descarga completa.
- **Alertas** (Warnings/Protecciones activas).

---

## 5. Modelos de Datos Compartidos

### 5.1 `InverterStatus` (Shared/Models)
Propiedades clave calculadas:
- `GridUsageWatts`: `LoadWatts + BatteryChargeWatts - (PVInputWatt + BatteryDischargeWatts)`
- `BatteryChargeCRate`: `BatteryChargeCurrent / BatteryCapacity`
- `PVInputWattHour`: Acumulador de energía solar en tiempo real.

### 5.2 `BMSStatus` (Shared/Models)
Propiedades clave calculadas:
- `AvailableCapacity`: `PackCapacity * CapacityPct / 100`
- `AvgCellVoltage`: Promedio de todas las celdas.
- `CellDiff`: Diferencia entre celda máxima y mínima.
- `GetTimeString()`: Calcula la hora estimada de finalización de carga/descarga (zona horaria fija IST).

---

## 6. Configuración y Despliegue

### 6.1 appsettings.json
```json
{
  "LaunchSettings": {
    "DeviceAddress": "COM3",       // Puerto del Inversor
    "JkBmsAddress": "/dev/ttyUSB0", // Puerto del BMS
    "WebPort": 80                  // Puerto del servidor web
  }
}
```

### 6.2 Servicio systemd (Linux)
El README incluye la configuración para ejecutar el servidor como servicio automático:
- Archivo: `/etc/systemd/system/invertermon.service`
- Dependencia: `After=dev-ttyUSB1.device`
- Reinicio automático: `Restart=always`

### 6.3 Firewall
- Puerto por defecto: **80**.
- Necesario abrir si hay firewall activo.

---

## 7. Puntos Críticos y Observaciones

1. **Sin Librería Modbus:** La implementación del protocolo Modbus es manual (cálculo de CRC, construcción de frames). Esto permite control total pero requiere mantenimiento si el protocolo cambia.
2. **Protocolo BMS Propietario:** La comunicación con el BMS depende estrictamente del formato de trama de JK. Cualquier cambio en el firmware del BMS podría romper la lectura.
3. **Suavizado de Corriente:** Se implementa una cola (`AmpValQueue`) de 5 lecturas para la corriente del BMS, lo que indica que el dato original es muy ruidoso.
4. **Zona Horaria Fija:** El cálculo de tiempo restante en el BMS está hardcodeado a IST (India Standard Time +5:30). Esto es un bug si se usa en otras zonas.
5. **Streaming HTTP:** El cliente usa streaming HTTP para evitar recargas de página, pero el código comenta que hay un bug en Blazor WASM que obliga a mantener la conexión abierta para evitar fugas de memoria.
6. **Dummy Data:** En modo desarrollo (`env.IsDevelopment()`), el BMS devuelve datos falsos para permitir probar la UI sin hardware.

---

## 8. Archivos de Protocolo Referenciados

En el repositorio existen documentos PDF (no extraídos) que contienen los detalles técnicos:
- `src/Server/InverterService/protocol doc/modbus-protocol.pdf`
- `src/Server/BatteryService/protocol docs/jk-protocol.pdf`

Estos documentos probablemente contengan la tabla completa de registros y la especificación oficial de las tramas.