# PRD: Sistema de Monitoreo Multi-Inversor Solar

## SpringBoot Backend + React Frontend

---

## 1. Concepto y Visión

**Nombre del Proyecto:** InverterHub

**Visión:** Una plataforma empresarial para monitoreo y control de múltiples inversores solares, con soporte para conexiones locales (USB/RS232) y remotas (TCP/IP via converters). El sistema permite ver datos en tiempo real, configurar parámetros, y recibir alertas de forma centralizada.

**Personalidad:** Profesional, confiable, en tiempo real. Como un panel de control industrial moderno — datos claros, alertas precisas, zeroambigüedad.

---

## 2. Design Language

### 2.1 Estética
- **Referencia:** Dashboard industrial + diseño de energía limpia
- **Tono:** Profesional, técnico pero accesible
- **Filosofía:** Los datos son el protagonistas — la UI los presenta sin ruido

### 2.2 Paleta de Colores

```
PRIMARY COLORS:
─────────────────────────────────────────────────
Solar Green:      #27AE60  (energía solar, éxito)
Deep Blue:        #2C3E50  (fondo principal, confianza)
Power Orange:     #E67E22  (warnings, energía)
Alert Red:        #E74C3C  (errores, batería baja)

STATUS COLORS:
─────────────────────────────────────────────────
Online/OK:        #27AE60  (verde)
Warning:          #F39C12  (naranja)
Offline/Error:    #E74C3C  (rojo)
Unknown:          #7F8C8D  (gris)

SURFACE COLORS:
─────────────────────────────────────────────────
Background:       #0D1B2A  (azul oscuro profundo)
Surface:          #1B2838  (tarjetas)
Surface Light:    #243447  (hover states)
Text Primary:     #ECF0F1  (blanco suave)
Text Secondary:   #95A5A6  (gris claro)
Border:           #34495E  (bordes sutiles)

CHARTS:
─────────────────────────────────────────────────
PV Power:         #F1C40F  (amarillo solar)
Grid:             #3498DB  (azul red)
Battery:          #9B59B6  (púrpura)
Load:              #E74C3C  (rojo carga)
```

### 2.3 Tipografía

```
HEADERS:     'Inter', sans-serif (weight 600-700)
BODY:        'Inter', sans-serif (weight 400-500)
MONOSPACED:  'JetBrains Mono', monospace (para datos/números)
SIZES:       H1: 28px, H2: 22px, H3: 18px, Body: 14px, Small: 12px
```

### 2.4 Espaciado y Layout

```
SPACING SCALE: 4px base
─────────────────────────────────────────────
xs:   4px     (elementos muy juntos)
sm:   8px     (padding interno)
md:   16px    (entre componentes)
lg:   24px    (secciones)
xl:   32px    (separación de áreas)
xxl:  48px    (headers de sección)

GRID: 12 columnas, gap 24px, max-width 1440px
```

### 2.5 Motion

```
TRANSITIONS: 200ms ease-out (hover, active)
ANIMATIONS:   300ms ease-in-out (aparición de elementos)
CHARTS:       500ms ease-in-out (actualización de datos)
SKELETON:     pulse animation 1.5s infinite para loading states
```

---

## 3. Layout & Structure

### 3.1 Arquitectura de Páginas

```
┌─────────────────────────────────────────────────────────────────────────┐
│  HEADER: Logo + Navigation + User Menu                                  │
├──────────┬──────────────────────────────────────────────────────────────┤
│          │                                                              │
│  SIDEBAR │  MAIN CONTENT AREA                                          │
│          │  ┌────────────────────────────────────────────────────┐    │
│  - Dash  │  │  Page Title + Actions                              │    │
│  - Inv   │  ├────────────────────────────────────────────────────┤    │
│  - Set   │  │                                                    │    │
│  - Alerts│  │  Page Content (cards, tables, forms)               │    │
│  - Rpts  │  │                                                    │    │
│          │  │                                                    │    │
│          │  └────────────────────────────────────────────────────┘    │
│          │                                                              │
├──────────┴──────────────────────────────────────────────────────────────┤
│  FOOTER: Connection status + Last update + Version                     │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Páginas Principales

#### Dashboard (/)
- Cards con métricas clave de cada inversor
- Gráfico de generación PV en tiempo real
- Estado del sistema (número de inversores online/offline)
- Últimas alertas

#### Lista de Inversores (/inverters)
- Tabla con todos los inversores: nombre, tipo, estado, última lectura
- Filtros: estado, tipo, grupo
- Acciones: ver detalles, editar, eliminar

#### Detalle de Inversor (/inverters/:id)
- **Tabs:**
  - Overview: métricas en tiempo real + gráfico
  - Settings: configuración actual
  - Write: panel de control (cambiar voltajes, prioridades)
  - History: histórico de datos y gráficos

#### Configuración (/settings)
- Configuración global del sistema
- Gestión de tipos de batería
- Rangos de voltaje por defecto

#### Alertas (/alerts)
- Lista de alertas con severidad
- Historial de alertas resueltas
- Configuración de thresholds

---

## 4. Features & Interactions

### 4.1 Conexión a Inversores

**Métodos de conexión:**
1. **Serial Directo:** USB→RS232→RJ45 (puerto COM configurable)
2. **TCP/IP Bridge:** Converter TCP/RS232 (IP:puerto)

**Flujo de conexión:**
```
Usuario selecciona inversor → Click "Conectar"
     ↓
Backend intenta conexión (timeout 5s)
     ↓
┌─────────────────────────────────────┐
│ Éxito:                             │
│ - Status cambia a "Online"         │
│ - Inicia polling (cada 3s)         │
│ - WebSocket envía updates          │
│                                     │
│ Error:                             │
│ - Muestra mensaje de error         │
│ - Sugiere verificar cable/puerto    │
│ - Opción de reintentar             │
└─────────────────────────────────────┘
```

**Interacciones:**
- Hover en botón "Conectar" → tooltip con último estado
- Click en "Desconectar" → confirmación si hay writes pendientes
- Icono de estado en tiempo real (pulsing cuando receive datos)

### 4.2 Monitoreo en Tiempo Real

**Métricas mostradas:**
| Métrica | Unidad | Fuente |
|---------|--------|--------|
| Voltaje red | V | QPIGS[0] / Modbus 0x1117 |
| Frecuencia red | Hz | QPIGS[1] |
| Voltaje salida | V | QPIGS[2] / Modbus 0x1111 |
| Potencia salida | W | QPIGS[5] / Modbus 0x111E |
| Carga % | % | QPIGS[6] / Modbus 0x1120 |
| Voltaje batería | V | QPIGS[8] / Modbus 0x1108 |
| SOC batería | % | QPIGS[10] |
| Corriente batería | A | QPIGS[9] / Modbus 0x1109 |
| Potencia batería | W | QPIGS[9] / Modbus 0x110A |
| Voltaje PV | V | QPIGS[13] / Modbus 0x1126 |
| Corriente PV | A | QPIGS[12] |
| Potencia PV | W | QPIGS[19] / Modbus 0x112A |
| Temperatura | °C | QPIGS[11] |

**Actualización:**
- Polling cada 3 segundos (configurable)
- WebSocket para actualizar UI sin reload
- Animación suave en cambios de valores
- Color coding: verde → naranja → rojo según thresholds

### 4.3 Gráficos en Tiempo Real

**PV Generation Chart:**
- Línea temporal de potencia solar (últimas 24h)
- Área bajo la curva coloreada
- Tooltip con hora y valor exacto
- Zoom in/out con selector de rango

**Battery State Chart:**
- Voltaje y SOC superpuestos
- Bandas de color para zonas (flotación, absorción, etc.)

**Actualización de charts:**
- Datos nuevos aparecen a la derecha
- Scroll automático
- Historial mantiene los últimos 24h en memoria

### 4.4 Control y Escritura

**Parámetros editables:**

| Parámetro | Comandos PI30 | Registros Modbus |
|-----------|---------------|------------------|
| Prioridad salida | POP00/01/02 | 0x212A |
| Prioridad carga | PCP00/01/02/03 | 0x212C |
| Voltaje flotación | PBFTxx.x | 0x2123 |
| Voltaje absorción | PCVVxx.x | 0x2122 |
| Voltaje recarga | PBCVxx.x | 0x2156 |
| Voltaje shutdown | PSDVxx.x | 0x211F |
| Buzzer | PEa/PDa | N/A |

**Flujo de escritura:**
```
Usuario cambia valor → Click "Aplicar"
     ↓
Validación en frontend (rango, coherencia)
     ↓
Confirmación con mensaje: "Se escribirá en EEPROM del inversor"
     ↓
Envío de comando via API
     ↓
Espera de ACK/NAK (timeout 3s)
     ↓
┌────────────────────────────────────┐
│ ACK:                               │
│ - Badge verde con latency          │
│ - Log de comando                  │
│ - Refresh de settings             │
│                                     │
│ NAK:                               │
│ - Badge rojo con error             │
│ - Mensaje descriptivo              │
│ - Log del error                    │
└────────────────────────────────────┘
```

**Validaciones en frontend:**
- Float > Absorb (coherencia de voltajes)
- Absorb > Float > Recarga > Shutdown
- Valor dentro de rango del tipo de batería

### 4.5 Sistema de Alertas

**Tipos de alerta:**
- `CRITICAL`: Inversor offline, batería muy baja, sobretemperatura
- `WARNING`: Batería baja, carga alta, inversor responde lento
- `INFO`: Cambio de modo, reconexión, settings actualizados

**Notificaciones:**
- Badge en header con contador
- Toast notifications para alertas críticas
- Historial persistente

**Thresholds configurables:**
```json
{
  "batteryLowWarning": 20,
  "batteryLowCritical": 10,
  "temperatureWarning": 60,
  "temperatureCritical": 70,
  "loadHighWarning": 80,
  "loadHighCritical": 95
}
```

### 4.6 Estados de Error

| Estado | UI | Acción |
|--------|-----|--------|
| Inversor offline | Card con borde rojo, icono desconectado | "Reintentar" button |
| Timeout polling | Badge "Sin respuesta" en timestamp | Auto-retry con backoff |
| Error de escritura | Toast con mensaje específico | "Ver detalles" expandible |
| BMS desconectado | Warning badge en Battery section | Mostrar último estado válido |
| Sin datos | Skeleton loading, mensaje "Esperando datos..." | — |

---

## 5. Component Inventory

### 5.1 Componentes Base

#### Button
```
Variants: primary, secondary, danger, ghost
States: default, hover, active, disabled, loading
Sizes: sm (32px), md (40px), lg (48px)
```

#### Card
```
Variants: default, elevated, bordered
States: default, hover (para click), selected
```

#### MetricCard
```
Structure: Title + Value + Unit
Variants: simple, with-sparkline, with-gauge
States: normal, warning, critical, loading, offline
```

#### StatusBadge
```
Variants: online (green), offline (red), warning (orange), unknown (gray)
Variants con pulsing animation para "conectado recientemente"
```

#### Input / Select
```
States: default, focus, error, disabled
Con mensaje de error debajo
```

#### Table
```
Features: sortable columns, pagination, row selection
Row hover state
Empty state con mensaje
```

#### Modal
```
Sizes: sm (400px), md (600px), lg (800px)
Header + Body + Footer con actions
Overlay oscuro, click fuera para cerrar
```

### 5.2 Componentes de Dominio

#### InverterCard
```
Muestra: nombre, tipo, estado, métricas clave
Acciones: conectar, desconectar, ver detalles
Estados: online, offline, connecting, error
```

#### BatteryGauge
```
SVG circular o lineal
Colores según SOC: >50% verde, 20-50% naranja, <20% rojo
Muestra porcentaje y voltaje
```

#### PowerFlowDiagram
```
Representación visual: PV → Battería → Carga/Red
Flechas proporcionales a potencia real
Animación de flujo
```

#### VoltageChart
```
Línea temporal con zonas coloreadas
Flotación (verde), Absorción (amarillo), Descarga (naranja)
Tooltip con valores
```

#### CommandLog
```
Tabla: timestamp, comando, response, latency, status
Filtrable por tipo de comando
Exportable a CSV
```

### 5.3 Estados de Loading

#### Skeleton
```
Para: cards, tables, charts
Animación pulse suave
```

#### Spinner
```
Para: botones, acciones
Se reemplaza por icono de check/error al completar
```

---

## 6. Technical Approach

### 6.1 Arquitectura General

```
┌──────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                         │
│  SPA → Vite + React 18 + TypeScript                             │
│  State: Zustand + TanStack Query                                │
│  HTTP: Axios                                                    │
│  WebSocket: native                                              │
└────────────────────────────┬───────────────────────────────────┘
                             │ HTTP/WebSocket
┌────────────────────────────┴───────────────────────────────────┐
│                         BACKEND (SpringBoot)                    │
│  Java 17+ / Kotlin                                             │
│  Spring WebFlux (reactivo) o Spring MVC                        │
└────────────────────────────┬───────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
   ┌──────┴──────┐    ┌──────┴──────┐    ┌──────┴──────┐
   │ PI30        │    │ ModbusRTU   │    │ Future...   │
   │ Adapter     │    │ Adapter     │    │             │
   └─────────────┘    └─────────────┘    └─────────────┘
```

### 6.2 Backend - Stack

```
CORE:
- Spring Boot 3.2+
- Java 17 LTS
- Gradle Kotlin DSL

DATA:
- Spring Data JPA
- PostgreSQL 15 (production)
- H2 (development)

REACTIVE:
- Spring WebFlux (para streaming)
- Project Reactor (Flux, Mono)

WEBSOCKET:
- Spring WebSocket
- STOMP protocol

TESTING:
- JUnit 5 + Mockito
- Testcontainers para PostgreSQL

PACKAGING:
- Docker + Docker Compose
- JAR executable
```

### 6.3 Frontend - Stack

```
CORE:
- React 18
- TypeScript 5
- Vite

STATE:
- Zustand (estado global simple)
- TanStack Query (server state, caching)

ROUTING:
- React Router v6

STYLING:
- Tailwind CSS
- Lucide React (iconos)

CHARTS:
- Recharts (principal)
- Chart.js (alternativo)

HTTP:
- Axios + interceptors

WEB SOCKET:
- native WebSocket API
- Zustand para estado derivado
```

### 6.4 Modelo de Datos

```java
// Core Entities
Inverter
├── id: Long (PK)
├── name: String (unique)
├── type: Enum (FELICITY, AXPERT, SOLIS, etc.)
├── protocol: Enum (PI30, MODBUS_RTU)
├── connectionConfig: JSON
│   ├── type: SERIAL | TCP
│   ├── port: String (COM3, /dev/ttyUSB0)
│   ├── host: String (IP)
│   ├── port: Integer
│   ├── baudrate: Integer (default 2400)
│   ├── slaveId: Integer (default 1)
├── active: Boolean
└── createdAt, updatedAt: Timestamp

InverterStatus
├── inverterId: Long (PK, FK)
├── batteryVoltage: Double
├── batterySoc: Integer
├── pvVoltage: Double
├── pvPower: Double
├── gridVoltage: Double
├── loadWatts: Integer
├── loadPercent: Integer
├── workingMode: String
├── chargeMode: String
├── heatsinkTemp: Double
├── timestamp: Instant
└── createdAt: Instant

InverterSettings
├── inverterId: Long (PK, FK)
├── batteryType: String
├── batteryBankVoltage: Integer
├── floatVoltage: Double
├── absorbVoltage: Double
├── rechargeVoltage: Double
├── shutdownVoltage: Double
├── outputPriority: Integer
├── chargePriority: Integer
└── timestamp: Instant

Alert
├── id: Long (PK)
├── inverterId: Long (FK)
├── type: Enum (CRITICAL, WARNING, INFO)
├── code: String
├── message: String
├── acknowledged: Boolean
├── acknowledgedAt: Instant
├── createdAt: Instant

PVGenerationRecord (para histórico)
├── id: Long (PK)
├── inverterId: Long (FK)
├── date: LocalDate
├── hour: Integer (0-23)
├── wattHours: Double
└── createdAt: Instant
```

### 6.5 API Endpoints

```yaml
# OpenAPI spec (simplified)

/api/v1/inverters:
  get:
    summary: List all inverters
    responses:
      200:
        body: InverterSummary[]
  
  post:
    summary: Create new inverter
    body: InverterCreateRequest
    responses:
      201: Inverter

/api/v1/inverters/{id}:
  get: Inverter
  put: Inverter (update config)
  delete: 204

/api/v1/inverters/{id}/connect:
  post: ConnectionResult

/api/v1/inverters/{id}/disconnect:
  post: void

/api/v1/inverters/{id}/status:
  get: InverterStatus (current)

/api/v1/inverters/{id}/settings:
  get: InverterSettings
  put: InverterSettings (update)

/api/v1/inverters/{id}/write:
  post: WriteCommandRequest
  responses:
    200: WriteResult
    400: WriteError

/api/v1/inverters/{id}/alerts:
  get: Alert[]

/api/v1/inverters/{id}/pv-generation:
  get:
    params: date (LocalDate)
    responses: PVGenerationRecord[]

# WebSocket
/ws/inverters/{id}/status:
  → stream: InverterStatus (cada 3s)
```

### 6.6 Protocol Adapters

```java
// Interface
public interface InverterProtocol {
    boolean connect();
    void disconnect();
    boolean isConnected();
    
    InverterStatus readStatus();
    InverterSettings readSettings();
    String readMode();
    List<String> readWarnings();
    
    WriteResult writeOutputPriority(OutputPriority p);
    WriteResult writeFloatVoltage(double v);
    WriteResult writeAbsorbVoltage(double v);
    WriteResult writeRechargeVoltage(double v);
    WriteResult writeShutdownVoltage(double v);
    WriteResult writeBuzzer(boolean enabled);
}

// Implementations
PI30Protocol (ASCII, comandos de texto)
ModbusRTUProtocol (binary, registros)
```

### 6.7 Polling Service

```java
@Service
public class PollingService {
    // Cada inversor tiene su propio scheduled task
    // Intervalo configurable por inversor (default 3s)
    // Reintento con exponential backoff si falla
    // Desconexión automática si N errores consecutivos
}
```

### 6.8 Docker Setup

```yaml
# docker-compose.yml
services:
  backend:
    build: ./backend
    ports:
      - "8080:8080"
    environment:
      - SPRING_PROFILES_ACTIVE=prod
      - SPRING_DATASOURCE_URL=jdbc:postgresql://db:5432/inverterhub
    depends_on:
      - db
  
  frontend:
    build: ./frontend
    ports:
      - "3000:80"
    depends_on:
      - backend
  
  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=inverterhub
      - POSTGRES_USER=inverter
      - POSTGRES_PASSWORD=xxx
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

---

## 7. Roadmap de Implementación

### Sprint 1: Foundation (2 semanas)
- [ ] Setup proyecto SpringBoot con Gradle
- [ ] Configurar PostgreSQL + JPA entities
- [ ] Implementar PI30 Protocol Adapter
- [ ] CRUD básico de inversores
- [ ] Tests unitarios de protocolo

### Sprint 2: Monitoreo Core (2 semanas)
- [ ] Polling service con scheduling
- [ ] WebSocket para streaming status
- [ ] Setup React con Vite
- [ ] Dashboard básico con métricas
- [ ] Gráficos con Recharts

### Sprint 3: Control (2 semanas)
- [ ] Endpoints de escritura
- [ ] Validación de parámetros
- [ ] Panel de control en React
- [ ] Logs de comandos
- [ ] Feedback visual (ACK/NAK)

### Sprint 4: Multi-Inversor (2 semanas)
- [ ] Connection pool
- [ ] ModbusRTU Protocol Adapter
- [ ] UI multi-inversor
- [ ] TCP/IP bridge support

### Sprint 5: Polish (1 semana)
- [ ] Sistema de alertas
- [ ] Históricos y reportes
- [ ] Responsive design
- [ ] Docker deployment

---

## 8. Constraints & Assumptions

### Constraints
- Inversor único por ahora, multi-inversor en fase 2
- Protocolo PI30 como baseline, ModbusRTU como extensión
- Conexión serial local o TCP bridge (no conexión directa a internet)

### Assumptions
- Java 17 LTS disponible en servidor
- PostgreSQL 15 para producción
- React 18 compatible con browsers target
- El inversor acepta comandos de escritura (verificar con test)

### Edge Cases
- Inversor offline: mostrar último estado conocido + timestamp
- Timeout en escritura: reintentar 2x, luego error
- Datos corruptos: validar checksum, descartar frame inválido
- Múltiples writes simultáneos: queue con mutex por inversor

---

## 9. Métricas de Éxito

| Métrica | Target |
|---------|--------|
| Tiempo de polling | < 500ms promedio |
| Uptime del sistema | > 99% |
| Errores de conexión | < 1% de polls |
| Tiempo de respuesta API | < 200ms p95 |
| Cobertura de tests | > 80% |
| Lighthouse score | > 90 performance |