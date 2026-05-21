# Guía de Diseño: Sistema de Monitoreo Multi-Inversor

## Arquitectura SpringBoot + React

---

## 1. Visión General del Sistema

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (React)                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Dashboard│  │ Settings │  │ Profiles │  │  Alerts  │  │  Reports │      │
│  │  (live)  │  │          │  │          │  │          │  │          │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
│       │             │             │             │             │             │
│       └─────────────┴─────────────┴─────────────┴─────────────┘             │
│                                    │                                        │
│                          WebSocket + REST API                               │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
┌─────────────────────────────────────┴───────────────────────────────────────┐
│                              BACKEND (SpringBoot)                            │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      API Layer (REST + WebSocket)                    │    │
│  │  /api/inverters     /api/inverters/{id}/status    /api/inverters/{id}/settings │
│  │  /api/inverters/{id}/write                                             │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                     │                                        │
│  ┌───────────────────────┬──────────┴──────────┬────────────────────────┐    │
│  │   Inverter Service    │   Connection Pool  │    BMS Service         │    │
│  │   (Command dispatch)  │   (TCP/Serial)      │    (JK BMS)           │    │
│  └───────────────────────┴────────────────────┴────────────────────────┘    │
│                                     │                                        │
│  ┌──────────────────────────────────┴────────────────────────────────────┐    │
│  │                    Protocol Adapters                                  │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                   │    │
│  │  │   PI30      │  │   ModbusRTU  │  │   Future... │                   │    │
│  │  │   (ASCII)   │  │   (Binary)   │  │             │                   │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                   │    │
│  └───────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐    │
│  │                   Data Persistence (JPA + SQLite/PostgreSQL)          │    │
│  │   InverterEntity | SettingsEntity | PVGenerationEntity | AlertEntity  │    │
│  └───────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    │                                   │
           ┌────────┴────────┐               ┌──────────┴────────┐
           │  TCP/IP Bridge  │               │   Direct Serial   │
           │  (Gateway)      │               │   (Local)        │
           └────────┬────────┘               └──────────┬────────┘
                    │                                 │
           ┌────────┴────────┐               ┌──────────┴────────┐
           │  Converter      │               │  USB-to-RS232    │
           │  TCP/IP↔RS232   │               │  (Direct)        │
           └────────┬────────┘               └──────────┬────────┘
                    │                                 │
           ┌────────┴─────────────────────────────────┴────────┐
           │                   INVERTERS                       │
           │  ┌─────────┐  ┌─────────┐  ┌─────────┐          │
           │  │ Felicity│  │ Axpert  │  │ Future  │           │
           │  │   #1    │  │   #2    │  │         │           │
           │  └─────────┘  └─────────┘  └─────────┘           │
           └─────────────────────────────────────────────────┘
```

---


### 2.2 Modbus RTU (Protocolo binario) — Proyecto C#

**Usado por:** El proyecto Felicity-Inverter-Monitor-master

**Características:**
- Comunicación binaria (bytes)
- Registros de 16 bits (holding registers)
- Función 0x03: Read Holding Registers
- Función 0x06: Write Single Register
- CRC-16 estándar (polinomio 0xA001)

**Parámetros de conexión:**
```
Baudrate:  2400
Paridad:   None
Data bits: 8
Stop bits: 1
Slave ID:  0x01
```

**Registros de estado (0x1101 - 0x112A):**
```
Dirección   Offset  Descripción                    Conversión
0x1101       0      Modo de trabajo                 enum
0x1102       1      Estado de carga                 enum
0x1108       7      Voltaje batería                 / 100
0x1109       8      Corriente batería               signed, abs()
0x110A       9      Potencia batería                signed
0x1111       16     Voltaje salida AC               / 10
0x1117       22     Voltaje red                     / 10
0x111E       29     Potencia de carga               raw
0x1120       31     Porcentaje de carga             raw
0x1126       37     Voltaje PV                      / 10
0x112A       41     Potencia PV                     signed
```

**Registros de configuración (0x211F - 0x2159):**
```
Dirección   Offset  Descripción
0x211F       0      Voltaje corte por descarga
0x2122       3      Voltaje carga C.V
0x2123       4      Voltaje flotante
0x212A       11     Prioridad fuente salida
0x212C       13     Prioridad fuente carga
0x212E       15     Corriente máx carga
0x2130       17     Corriente máx AC
0x2156       55     Voltaje regreso a red
0x2159       58     Voltaje regreso a batería
```

---

## 3. Arquitectura de Conexión

### 3.1 Conexiones disponibles

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TOPOLOGÍA DE CONEXIÓN                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  OPCIÓN A: Serial Directo (USB→RS232→RJ45)                                  │
│  ─────────────────────────────────────────────────────────────────          │
│  ┌────────┐    ┌──────────────┐    ┌────────┐                              │
│  │ PC     │────│ USB→RS232    │────│ RJ45   │─────► Inversor              │
│  │        │    │ (FTDI/CH340) │    │ Cable  │                              │
│  └────────┘    └──────────────┘    └────────┘                              │
│                                                                             │
│  Puerto: COM3 (Win) / /dev/ttyUSB0 (Linux)                                 │
│  Baudrate: 2400                                                              │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  OPCIÓN B: TCP/IP Bridge (Gateway) ─► FUTURO                               │
│  ─────────────────────────────────────────────────────────────────          │
│  ┌────────┐    ┌──────────────┐    ┌────────┐    ┌──────────────┐          │
│  │ Server │────│ Ethernet     │────│ Bridge │────│ RJ45         │──► Inv  │
│  │        │    │              │    │ TCP/RS │    │              │          │
│  └────────┘    └──────────────┘    └────────┘    └──────────────┘          │
│                                                                             │
│  Bridge típico: USR-TCP232-300 o similar                                   │
│  Config: TCP Server mode, 2400 baud                                         │
│  Puerto: 8899 (típico)                                                      │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  OPCIÓN C: Multi-inversor con switch                                        │
│  ─────────────────────────────────────────────────────────────────          │
│  ┌────────────┐                                                            │
│  │  Switch    │                                                             │
│  │  Ethernet  │                                                             │
│  └─────┬──────┘                                                            │
│        │                                                                   │
│   ┌────┴────┐   ┌────┴────┐   ┌────┴────┐                                │
│   │ TCP/RS   │   │ TCP/RS   │   │ TCP/RS   │                               │
│   │ Bridge #1│   │ Bridge #2│   │ Bridge #3│  ...                        │
│   └────┬────┘   └────┬────┘   └────┬────┘                                │
│        │              │              │                                      │
│        └──────────────┴──────────────┘                                     │
│                      │                                                      │
│                ┌─────┴─────┐                                                │
│                │ Inversor  │                                                │
│                │   #1      │                                                │
│                └───────────┘                                                │
│                                                                             │
│  Cada bridge en diferente IP/puerto.                                        │
│  Slave ID diferente en cada inversor.                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Diseño de la Base de Datos

### 4.1 Entidades JPA

```java
// src/main/java/com/inverter/model/Inverter.java
@Entity
@Table(name = "inverters")
public class Inverter {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    @Column(unique = true)
    private String name;
    
    private String type; // "FELICITY", "AXPERT", etc.
    private String protocol; // "PI30", "MODBUS"
    
    // Configuración de conexión
    private String connectionType; // "SERIAL", "TCP"
    private String host; // IP si es TCP
    private Integer port; // Puerto TCP
    private String serialPort; // COM3 o /dev/ttyUSB0
    private Integer baudrate;
    private Integer slaveId; // Para Modbus
    
    // Estado
    private boolean active;
    private Instant lastSeen;
    
    // Relaciones
    @OneToOne(mappedBy = "inverter", cascade = CascadeType.ALL)
    private InverterSettings settings;
    
    @OneToOne(mappedBy = "inverter", cascade = CascadeType.ALL)
    private InverterStatus status;
}
```

```java
// src/main/java/com/inverter/model/InverterStatus.java
@Entity
public class InverterStatus {
    @Id
    private Long inverterId;
    
    private Double batteryVoltage;
    private Integer batterySoc;
    private Double pvVoltage;
    private Double pvPower;
    private Integer gridVoltage;
    private Integer loadWatts;
    private Integer loadPercent;
    private String workingMode;
    private String chargeMode;
    private Double heatsinkTemp;
    
    private Instant timestamp;
}
```

```java
// src/main/java/com/inverter/model/InverterSettings.java
@Entity
public class InverterSettings {
    @Id
    private Long inverterId;
    
    private String batteryType;
    private Integer batteryBankVoltage;
    
    // Voltajes configurados
    private Double floatVoltage;
    private Double absorbVoltage;
    private Double rechargeVoltage;
    private Double shutdownVoltage;
    
    // Prioridades
    private Integer outputPriority; // 0=Utility, 1=Solar, 2=SBU
    private Integer chargePriority; // 0=Utility, 1=Solar, 2=Both, 3=SolarOnly
    
    // Corrientes
    private Integer maxChargeCurrent;
    private Integer maxAcChargeCurrent;
}
```

```java
// src/main/java/com/inverter/model/PVGenerationRecord.java
@Entity
@Table(name = "pv_generation")
public class PVGenerationRecord {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    
    private Long inverterId;
    private LocalDate date;
    private LocalTime hour;
    private Double wattHours;
    
    @Index
    private Instant createdAt;
}
```

---

## 5. Diseño de la API REST

### 5.1 Endpoints

```
BASE URL: /api/v1

INVERSORES
─────────────────────────────────────────────────────────────────────────────
GET    /inverters                    → Lista todos los inversores
POST   /inverters                    → Crear nuevo inversor
GET    /inverters/{id}               → Detalle de un inversor
PUT    /inverters/{id}               → Actualizar configuración
DELETE /inverters/{id}               → Eliminar inversor
POST   /inverters/{id}/connect       → Conectar al inversor
POST   /inverters/{id}/disconnect   → Desconectar

STATUS (lectura en tiempo real)
─────────────────────────────────────────────────────────────────────────────
GET    /inverters/{id}/status        → Estado actual del inversor
GET    /inverters/{id}/status/poll   → Poll manual (force refresh)
WebSocket /ws/inverters/{id}/status  → Streaming de status en tiempo real

CONFIGURACIÓN
─────────────────────────────────────────────────────────────────────────────
GET    /inverters/{id}/settings      → Obtener settings del inversor
PUT    /inverters/{id}/settings      → Actualizar settings
GET    /inverters/{id}/settings/qpiri → Leer settings directamente del inversor

ESCRITURA
─────────────────────────────────────────────────────────────────────────────
POST   /inverters/{id}/write/priority    → Cambiar prioridad salida
     Body: { "priority": "SOLAR_FIRST" }
     
POST   /inverters/{id}/write/voltage     → Cambiar voltaje
     Body: { "type": "FLOAT", "value": 54.0 }
     
POST   /inverters/{id}/write/buzzer       → Activar/desactivar buzzer
     Body: { "enabled": true }

GENERACIÓN PV
─────────────────────────────────────────────────────────────────────────────
GET    /inverters/{id}/pv-generation?date=2024-01-15
GET    /inverters/{id}/pv-generation/range?from=...&to=...

ALERTAS
─────────────────────────────────────────────────────────────────────────────
GET    /inverters/{id}/alerts
GET    /inverters/{id}/alerts/unread
POST   /inverters/{id}/alerts/{alertId}/acknowledge
```

### 5.2 Ejemplos de requests

```bash
# Crear inversor
POST /api/v1/inverters
{
  "name": "Inversor Casa",
  "type": "FELICITY",
  "protocol": "MODBUS",
  "connectionType": "TCP",
  "host": "192.168.1.100",
  "port": 8899,
  "slaveId": 1,
  "batteryType": "LiFePO4",
  "batteryBankVoltage": 48
}

# Cambiar prioridad
POST /api/v1/inverters/1/write/priority
{
  "priority": "SOLAR_FIRST"  // UTILITY_FIRST, SOLAR_FIRST, SBU
}

# Cambiar voltaje de flotación
POST /api/v1/inverters/1/write/voltage
{
  "type": "FLOAT",          // FLOAT, ABSORB, RECHARGE, SHUTDOWN
  "value": 54.0
}
```

### 5.3 Respuestas

```json
// GET /inverters/1/status
{
  "inverterId": 1,
  "inverterName": "Inversor Casa",
  "connected": true,
  "timestamp": "2024-01-15T14:30:00Z",
  "data": {
    "gridVoltage": 237.5,
    "gridFrequency": 50.0,
    "outputVoltage": 230.4,
    "outputFrequency": 50.0,
    "outputWatts": 980,
    "loadPercent": 45,
    "batteryVoltage": 54.2,
    "batterySoc": 85,
    "batteryChargeAmps": 0,
    "batteryDischargeAmps": 12,
    "pvVoltage": 142.5,
    "pvCurrent": 3.5,
    "pvPower": 498,
    "heatsinkTempCelsius": 35,
    "workingMode": "BATTERY",
    "chargeMode": "FLOAT"
  }
}

// GET /inverters/1/settings
{
  "batteryType": "LiFePO4",
  "batteryBankVoltage": 48,
  "floatVoltage": 54.0,
  "absorbVoltage": 56.8,
  "rechargeVoltage": 48.0,
  "shutdownVoltage": 44.0,
  "outputPriority": "SOLAR_FIRST",
  "chargePriority": "SOLAR_PLUS_UTILITY",
  "maxChargeCurrent": 60,
  "maxAcChargeCurrent": 30
}
```

---

## 6. Modelo de Dominio - Services

### 6.1 Service Interfaces

```java
public interface InverterProtocol {
    // Conexión
    boolean connect();
    void disconnect();
    boolean isConnected();
    
    // Lectura
    InverterStatus readStatus();
    InverterSettings readSettings();
    List<String> readWarnings();
    String readMode();
    
    // Escritura
    WriteResult setOutputPriority(OutputPriority priority);
    WriteResult setFloatVoltage(double voltage);
    WriteResult setAbsorbVoltage(double voltage);
    WriteResult setRechargeVoltage(double voltage);
    WriteResult setShutdownVoltage(double voltage);
    WriteResult setBuzzer(boolean enabled);
}

public interface ConnectionPool {
    Connection getConnection(Inverter inverter);
    void releaseConnection(Long inverterId);
    void closeAll();
}

public interface InverterService {
    // CRUD
    Inverter create(InverterRequest request);
    Optional<Inverter> findById(Long id);
    List<Inverter> findAll();
    Inverter update(Long id, InverterRequest request);
    void delete(Long id);
    
    // Conexión
    void connect(Long id);
    void disconnect(Long id);
    
    // Operaciones
    InverterStatus getStatus(Long id);
    void refreshStatus(Long id); // força poll
    InverterSettings getSettings(Long id);
    void updateSettings(Long id, SettingsRequest request);
    
    // Streaming
    Flux<InverterStatus> streamStatus(Long id);
}
```

### 6.2 Implementaciones de Protocolo

```
┌─────────────────────────┐
│   InverterProtocol      │  (interface)
│   <<interface>>         │
├─────────────────────────┤
│ + connect()             │
│ + disconnect()          │
│ + readStatus()          │
│ + readSettings()        │
│ + writeXXX()            │
└────────────┬────────────┘
             │
   ┌─────────┴─────────┐
   │                   │
   ▼                   ▼
┌────────────┐  ┌─────────────┐
│  PI30      │  │  ModbusRTU  │
│  Protocol  │  │  Protocol   │
├────────────┤  ├─────────────┤
│ Usado por: │  │ Usado por:  │
│ - Felicity │  │ - Felicity  │
│ - Axpert   │  │   (C#)      │
│ - etc.     │  │             │
└────────────┘  └─────────────┘
```

---

## 7. Frontend React - Arquitectura

### 7.1 Estructura del Proyecto

```
frontend/
├── public/
├── src/
│   ├── api/                    # Cliente API
│   │   ├── apiClient.ts       # Axios instance
│   │   ├── inverterApi.ts     # Endpoints de inversores
│   │   └── types.ts          # Tipos TypeScript
│   │
│   ├── components/            # Componentes reutilizables
│   │   ├── common/
│   │   │   ├── Card.tsx
│   │   │   ├── MetricCard.tsx
│   │   │   ├── StatusBadge.tsx
│   │   │   └── LoadingSpinner.tsx
│   │   │
│   │   ├── dashboard/
│   │   │   ├── LiveMetrics.tsx
│   │   │   ├── PVChart.tsx
│   │   │   ├── BatteryGauge.tsx
│   │   │   └── SystemStatus.tsx
│   │   │
│   │   └── inverter/
│   │       ├── InverterCard.tsx
│   │       ├── ConnectionStatus.tsx
│   │       └── SettingsPanel.tsx
│   │
│   ├── hooks/                  # Custom hooks
│   │   ├── useInverter.ts
│   │   ├── useWebSocket.ts
│   │   └── useStatusStream.ts
│   │
│   ├── pages/                  # Páginas/rutas
│   │   ├── Dashboard.tsx
│   │   ├── InverterList.tsx
│   │   ├── InverterDetail.tsx
│   │   ├── Settings.tsx
│   │   └── Alerts.tsx
│   │
│   ├── store/                  # Estado global (Zustand/Redux)
│   │   ├── inverterStore.ts
│   │   └── alertStore.ts
│   │
│   ├── types/                  # Tipos compartidos
│   │   └── inverter.ts
│   │
│   ├── utils/                  # Utilidades
│   │   ├── formatters.ts
│   │   └── validators.ts
│   │
│   └── App.tsx
├── package.json
└── tsconfig.json
```

### 7.2 Hooks Principales

```typescript
// useStatusStream.ts - WebSocket para status en tiempo real
export function useStatusStream(inverterId: number) {
  const [status, setStatus] = useState<InverterStatus | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8080/ws/inverters/${inverterId}/status`);

    ws.onopen = () => setConnected(true);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setStatus(data);
    };
    ws.onclose = () => setConnected(false);

    return () => ws.close();
  }, [inverterId]);

  return { status, connected };
}

// useInverter.ts - Hook completo para CRUD
export function useInverter(id: number) {
  const [inverter, setInverter] = useState<Inverter>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchInverter = async () => {
    try {
      const data = await inverterApi.get(id);
      setInverter(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchInverter();
  }, [id]);

  const connect = async () => {
    await inverterApi.connect(id);
  };

  const disconnect = async () => {
    await inverterApi.disconnect(id);
  };

  return { inverter, loading, error, connect, disconnect, refetch: fetchInverter };
}
```

### 7.3 Componentes Clave

```typescript
// MetricCard.tsx
interface MetricCardProps {
  title: string;
  value: number | null;
  unit: string;
  warningThreshold?: number;
  criticalThreshold?: number;
}

export function MetricCard({ title, value, unit, warningThreshold, criticalThreshold }: MetricCardProps) {
  const color = value === null ? '#555' 
    : criticalThreshold && value >= criticalThreshold ? '#e74c3c'
    : warningThreshold && value >= warningThreshold ? '#f39c12'
    : '#00d2ff';

  return (
    <div className="metric-card">
      <span className="metric-title">{title}</span>
      <span className="metric-value" style={{ color }}>
        {value !== null ? value.toFixed(1) : '—'}
      </span>
      <span className="metric-unit">{unit}</span>
    </div>
  );
}

// BatteryGauge.tsx
export function BatteryGauge({ soc, voltage }: { soc: number; voltage: number }) {
  const color = soc > 50 ? '#27ae60' : soc > 20 ? '#f39c12' : '#e74c3c';

  return (
    <div className="battery-gauge">
      <div className="gauge-body" style={{ width: `${soc}%`, background: color }} />
      <span>{soc}%</span>
      <span>{voltage.toFixed(1)}V</span>
    </div>
  );
}
```

---

## 8. Consideraciones de Escalabilidad

### 8.1 Multi-inversor

```
┌─────────────────────────────────────────────────────────────────┐
│                      Connection Pool Manager                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐              │
│  │ Inverter #1 │ │ Inverter #2 │ │ Inverter #N │              │
│  │ TCP:192.168.│ │ Serial COM4 │ │ TCP:192.168.│              │
│  │    1.100    │ │             │ │    1.102    │              │
│  ├─────────────┤ ├─────────────┤ ├─────────────┤              │
│  │  PI30       │ │  ModbusRTU  │ │  ModbusRTU  │              │
│  │  Protocol   │ │  Protocol   │ │  Protocol   │              │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘              │
│         │               │               │                      │
│         └───────────────┴───────────────┘                      │
│                         │                                        │
│              ┌──────────┴──────────┐                            │
│              │   Connection Pool    │                            │
│              │   (Reuse channels)  │                            │
│              └─────────────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 Thread Safety

- El pool de conexiones debe ser thread-safe
- Cada inversor puede tener su propio thread de polling
- Usar ScheduledExecutorService para polling intervals
- Batch writes para evitar saturar el canal

### 8.3 Reintentos y Reconexión

```java
// ReconnectionStrategy.java
public interface ReconnectionStrategy {
    Duration getNextDelay(int attempt);
    boolean shouldRetry(int attempt, Exception e);
}

// Default: exponential backoff con jitter
public class ExponentialBackoffStrategy implements ReconnectionStrategy {
    @Override
    public Duration getNextDelay(int attempt) {
        // 1s, 2s, 4s, 8s, 16s, max 30s
        long millis = Math.min(1000L * (1L << attempt), 30_000);
        return Duration.ofMillis(millis + (long)(Math.random() * 1000));
    }
}
```

---

## 9. Roadmap de Implementación

### Fase 1: Core (2-3 semanas)
- [ ] Proyecto SpringBoot con JPA + H2 (para testing)
- [ ] Entity Inverter, InverterStatus, InverterSettings
- [ ] Repositorios CRUD básicos
- [ ] PI30 Protocol Adapter (basado en tu proyecto Python)
- [ ] REST API para CRUD de inversores
- [ ] Tests unitarios del protocolo

### Fase 2: Monitoreo (2 semanas)
- [ ] Background polling service
- [ ] WebSocket para streaming de status
- [ ] Dashboard React básico
- [ ] Live metrics con gráficos

### Fase 3: Control (2 semanas)
- [ ] Endpoints de escritura
- [ ] Validación de valores
- [ ] UI de control (voltajes, prioridades)
- [ ] Logs de comandos

### Fase 4: Persistencia (1 semana)
- [ ] Migrar a PostgreSQL (production)
- [ ] Almacenamiento de histórico PV
- [ ] Generación de reportes
- [ ] Sistema de alertas

### Fase 5: Multi-inversor (2 semanas)
- [ ] Connection pool refactoring
- [ ] UI multi-inversor
- [ ] TCP/IP bridge support
- [ ] Balanceador de polling

---

## 10. Stack Tecnológico Recomendado

### Backend
- **Framework:** Spring Boot 3.x
- **Language:** Java 17+ o Kotlin
- **Build:** Gradle (Kotlin DSL)
- **DB:** PostgreSQL (production), H2 (dev)
- **Web:** Spring WebFlux (reactivo) o Spring MVC
- **WebSocket:** Spring WebSocket + STOMP
- **Testing:** JUnit 5 + Mockito

### Frontend
- **Framework:** React 18+ con TypeScript
- **Build:** Vite
- **State:** Zustand (lightweight) o Redux Toolkit
- **Styling:** Tailwind CSS o Material UI
- **Charts:** Recharts o Chart.js
- **HTTP:** Axios o TanStack Query
- **WebSocket:** nativo o socket.io-client

### Infrastructure
- **Container:** Docker + Docker Compose
- **CI/CD:** GitHub Actions
- **Monitoring:** Micrometer + Prometheus (opcional)

---

## 11. Referencias de Implementación

### De tu proyecto Python (PI30)
- `felicity_monitor/core/protocol.py` — CRC y parseo de comandos PI30
- `felicity_monitor/core/serial_engine.py` — Comunicación serial
- `felicity_monitor/core/write_commands.py` — Comandos de escritura con validación

### Del proyecto C# (Modbus RTU)
- `Felicity-Inverter-Monitor-master/src/Server/InverterService/FelicityInverter.cs` — Implementación Modbus completa
- `Felicity-Inverter-Monitor-master/src/Server/InverterService/StatusRetriever.cs` — Polling service
- Registros específicos en la sección 2.2 de este documento

---

## 12. FAQ - Preguntas Frecuentes


**P: ¿Cómo manejo inversores offline?**
R: El status tiene `lastSeen`. Si no hay update en X minutos, marcar como offline. Reintentar conexión con backoff.

**P: ¿Qué pasa si el inversor no responde durante escritura?**
R: Timeout de 2s, reintentar 2 veces, luego retornar error. No hacer writes concurrentes.

**P: ¿Cómo escalo a 100 inversores?**
R: Pool de conexiones por tipo, threads dedicados por inversor, queue de comandos para evitar floods.

**P: ¿Soporta BMS JK?**
R: Sí, igual que el proyecto C#. Agregar `JkBms` entity y su propio protocol adapter.