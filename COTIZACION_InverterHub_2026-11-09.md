# COTIZACIÓN — Sistema de Monitoreo Multi-Inversor InverterHub

**Cliente:** *(a completar)*
**Proyecto:** InversorApp / InverterHub — monitoreo y control de inversores Felicity/Voltronic
**Equipo objetivo:** Inversor **Felicity IVGM8KLP2G1** (8 kW, RS485 + Modbus RTU) + inversor 5K existente (RS232)
**Fecha de emisión:** 9 de noviembre de 2026
**Vigencia de la oferta:** 30 días naturales
**Moneda de referencia:** USD (conversión a CUP según tasas oficiales del BCB del día de emisión)

---

## 1. Base de conversión monetaria

Tasas oficiales del **Banco Central de Cuba (BCB)**, vigentes el **9 de noviembre de 2026**, obtenidas de la API oficial `api.bc.gob.cu/v1/tasas-de-cambio/activas`:

| Segmento BCB | USD (CUP por unidad) |
|---|---|
| **Segmento I — Estatal** | **800.00** |
| **Segmento II — Especial** | **24.00** |
| **Segmento III — Población y FGNE** | **120.00** |

> **Importante:** la tasa aplicable depende del segmento del cliente. Una empresa estatal o una entidad que factura al sector estatal usa el **Segmento I (800 CUP/USD)**. Un cliente particular o FGNE usa el **Segmento III (120 CUP/USD)**. En este documento se detallan **los tres** para que el cliente elija el que corresponda.

**Tarifa de referencia del servicio profesional:** **USD 50/hora** (honorarios de ingeniería de software + integración con hardware). Esta tarifa es un **supuesto explícito** y puede ajustarse por acuerdo.

---

## 2. Resumen ejecutivo

El proyecto tiene **dos partes** que hoy están separadas y que esta cotización une:

1. **Puesta a punto del inversor IVGM8KLP2G1 por RS485 sobre un conversor TCP/IP ↔ RS485.** Hoy el app **no puede** leer este inversor: (a) envía tramas Modbus RTU "crudas" por el socket TCP y los conversores reales de campo esperan **Modbus TCP con cabecera MBAP**; (b) el **mapa de registros** que usa el app es el clásico Voltronic/Axpert (que sí le sirve al 5K) y **no coincide en ningún campo** con el mapa del IVGM-8K.
2. **Evolución del producto de software** hacia una plataforma multi-inversor, con dos caminos tecnológicos posibles: **evolución de la app Python/PyQt5 existente** u **reescritura en Java (Spring Boot) + React**.

Se entregan las **cuatro etapas pedidas**: (1) análisis de tecnologías y estudio de soluciones, (2) la solución en Java y en Python, (3) fase de pruebas, (4) puesta en marcha.

**Recomendación:** para este caso concreto (un inversor, un protocolo, un conversor), la **Opción A (evolución Python)** es la de mejor relación costo/beneficio. La **Opción B (Java + React)** solo se justifica si se necesita un producto multi-usuario, multi-sitio, con backend web servido a muchos clientes simultáneos.

---

## 3. Etapa 1 — Análisis de tecnologías y estudio de soluciones

### 3.1 Diagnóstico técnico del estado actual

| # | Hallazgo | Impacto |
|---|---|---|
| 1 | El transporte TCP del app (`core/modbus_tcp.py`) envía **Modbus RTU crudo** (slave + función + datos + CRC16) por un socket plano, **sin cabecera MBAP** | Los conversores de campo (Waveshare RS485 TO POE ETH (B), USR, Moxa) se configuran con **"Modbus TCP To RTU"**, o sea que esperan **MBAP**. Con el app tal cual, **no se comunican**. |
| 2 | El conversor documentado en campo (integración de referencia `partach/ha_felicity`) usa `AsyncModbusTcpClient` → **MBAP** y soporta además el modo RTU tunnelled (`--framer rtu`) | Confirma que hay **dos framings válidos** y que el app debe poder elegir. |
| 3 | El **mapa de registros del IVGM-8K** (del documento *"Inverter Communication Protocol — Series RS485"*) **no coincide** con el mapa clásico del app | El app mostraría **valores sin sentido** en el 8K. |
| 4 | La UI TCP expone solo **host / puerto / timeout**; el slave ID queda fijo en 1 | En un bus RS485 con más de un equipo, no se puede direccionar. |
| 5 | `verify_crc()` existe pero **nunca se llama** | En un bus multi-drop con ruido se aceptan tramas corruptas. |
| 6 | El app lee **43 registros de una sola vez** | A 2400 baud (T-REX) o en enlaces lentos, las lecturas largas fallan más que las cortas. |
| 7 | La detección automática está **deshabilitada** en modo TCP | No hay forma de descubrir baud/paridad/slave desde la UI. |
| 8 | El puerto por defecto es **502** con el texto "Gateway RS232→TCP" | 502 es el puerto de Modbus TCP; los conversores transparentes suelen usar otro. Texto engañoso. |

### 3.2 Comparación de mapas de registros

El app usa el mapa **clásico Voltronic/Axpert** (que funciona con el 5K). El IVGM-8K usa el mapa **nuevo "Series RS485"**:

| Magnitud | App actual (clásico) | IVGM-8K (real) |
|---|---|---|
| Modo de trabajo | 0x1101 | **0x1100** (WorkMode) |
| Estado 1–4 | — | 0x1101–0x1104 |
| Código de falla | 0x1103 | **0x110A** (0x1103 = State3) |
| Código de alarma | — | 0x1109 |
| Tensión batería | 0x1108 | **0x112C** (0x1108 = día de la semana) |
| Corriente batería | 0x1109 | **0x1130** (0x1109 = WarnCode) |
| Potencia batería | 0x110A | **0x1131** (0x110A = FaultCode) |
| SOC batería | — | 0x1138 |
| Tensión PV1 | 0x1126 | **0x1118** |
| Corriente PV1 | — | 0x111C |
| Potencia PV1 | 0x112A | **0x1128** |
| Carga (W) | 0x1120 (%) | **0x1120** (Home Load A, en W) |
| Tensión de red | 0x1117 | *a levantar del documento* |
| Ajustes | 0x211F–0x2159 | *a levantar del documento* |

> **Decisión de alcance:** se implementan **los dos mapas, seleccionables** (clásico para el 5K, IVGM-8K para el 8K). No se reemplaza uno por el otro.

### 3.3 Estudio de soluciones posibles

| Solución | Descripción | Pros | Contras | Veredicto |
|---|---|---|---|---|
| **S1. Conversor en modo transparente** | Configurar el gateway como "serial passthrough" y dejar el app como está | Cero cambio de código en el transporte | Requiere un gateway con ese modo; la UI sigue sin slave ID ni diagnóstico; el mapa del 8K sigue mal | **Complemento viable**, no resuelve el fondo |
| **S2. Agregar MBAP al app (Python)** | Framing conmutable RTU ↔ Modbus TCP + slave ID + CRC + doble mapa | Resuelve todo con cambios acotados; reutiliza todo el trabajo existente | Sigue siendo una app de escritorio PyQt5, no multi-usuario | **Recomendada (Opción A)** |
| **S3. Reescribir en Java + React** | Backend Spring Boot + frontend React según el PRD y la guía existentes | Producto web multi-usuario, multi-sitio, escalable; stack moderno | 3× el esfuerzo; hay que reimplementar protocolo, UI, persistencia y despliegue | **Opción B**, solo si el producto lo exige |
| **S4. Híbrida** | Backend Java para el servidor multi-usuario + app Python ligera en sitio | Escalabilidad + reutilización | Dos código-base que mantener | No cotizada aquí |

### 3.4 Entregables de la Etapa 1

- Informe técnico de diagnóstico (este documento, secciones 3.1 y 3.2).
- Matriz de decisión tecnológica (sección 3.3).
- Levantamiento del mapa de registros del IVGM-8K desde el documento de protocolo y su verificación contra el equipo real.
- Plan de trabajo y cronograma.

**Esfuerzo Etapa 1: 16 horas**

| Tarea | Horas |
|---|---|
| Relevamiento y verificación del protocolo IVGM-8K contra hardware | 8 |
| Análisis comparativo de tecnologías (Python vs Java) y matriz de decisión | 4 |
| Documentación técnica y plan de trabajo | 4 |

---

## 4. Etapa 2 — La solución

### 4.1 Opción A — Evolución de la app Python/PyQt5 (recomendada)

Se conserva todo lo que ya funciona (6.216 líneas en `felicity_monitor/`, 13 archivos) y se corrigen los puntos críticos.

**A.1 Capa de transporte Modbus (cambio acotado en `core/modbus_tcp.py`)**
- Framing **conmutable**: `RTU` (trama cruda) ↔ `MODBUS_TCP` (cabecera MBAP de 7 bytes: transaction id, protocol id = 0, length, unit id).
- Campo **Slave ID** editable (1–247) para el modo TCP y para el modo serie.
- **Verificación de CRC** en todas las respuestas (hoy `verify_crc()` existe pero no se llama).
- Timeouts y reintentos parametrizables por conexión.

**A.2 Doble mapa de registros (`core/felicity_modbus.py` + nuevo `core/register_maps.py`)**
- Definición de mapas como **datos**, no como código disperso: `CLASSIC` (clásico Voltronic/Axpert) e `IVGM_8K` (nuevo Series RS485).
- **Selector de mapa** en la UI, por inversor.
- Capa de normalización para que el resto del app no cambie.

**A.3 Gestión de lecturas robusta**
- **Partición de bloques** (lecturas ≤ 120 registros) y **bisección** de bloques que fallan.
- Reintentos con backoff exponencial (1s, 2s, 4s, 8s, tope 30s).
- **Descarte de registros que nunca responden** tras N intentos.
- Corte de lectura largo en enlaces de 2400 baud.

**A.4 Interfaz de usuario**
- Nuevo panel de conexión: tipo (RS232/TCP), host, puerto, **framing**, **slave ID**, baud, paridad, stop, timeout.
- Selector de **mapa de registros** por inversor.
- Pestaña de **diagnóstico** con volcado de registros en vivo (equivalente al `--framer` del dump de referencia).

**A.5 Backend / servidor**
- Extender el servidor FastAPI existente: endpoints de estado, ajustes, escritura, alertas.
- WebSocket para actualizaciones en vivo (hoy el app ya usa hilos PyQt5 con señales).
- Persistencia local (SQLite) para histórico y configuración.

| Tarea | Horas |
|---|---|
| Transporte Modbus: framing MBAP/RTU, slave ID, CRC | 24 |
| Doble mapa de registros + selector | 32 |
| Gestión de lecturas (partición, reintentos, backoff) | 16 |
| UI (conexión, mapa, diagnóstico) | 16 |
| Backend FastAPI + WebSocket + persistencia | 24 |
| Integración y ajuste fino | 8 |
| **Subtotal** | **120** |

### 4.2 Opción B — Reescritura en Java (Spring Boot) + React

Basada en el **PRD_Impl_SpringBoot_React.md** y el **SPRINGBOOT_REACT_GUIDE.md** ya presentes en el repositorio.

**Stack:**
- **Backend:** Spring Boot 3.x, Java 17+, Gradle (Kotlin DSL), Spring WebFlux o MVC, Spring WebSocket + STOMP, Spring Data JPA, PostgreSQL 15 (H2 para pruebas), Docker + Docker Compose.
- **Frontend:** React 18 + TypeScript, Vite, Zustand, TanStack Query, React Router v6, Tailwind CSS, Recharts.
- **Tests:** JUnit 5 + Mockito.
- **CI/CD:** GitHub Actions.

**Adaptación obligatoria a este caso:** el PRD y la guía están escritos sobre el **mapa clásico** y marcan el puente TCP/IP como "FUTURO". Para el IVGM-8K hay que: (1) agregar el **mapa IVGM-8K** junto al clásico, (2) implementar el **framing MBAP** (el PRD no lo menciona), (3) implementar **slave ID**, **CRC** y **partición de bloques** (el PRD solo dice "validar checksum, descartar frame inválido"), y (4) adelantar el soporte TCP/IP de la Fase 5 a la Fase 1.

| Fase (según la guía) | Contenido | Horas |
|---|---|---|
| Fase 1 — Core | Proyecto Spring Boot + JPA + H2; entidades; CRUD; adaptador PI30; API REST; tests unitarios | 96 |
| Fase 2 — Monitoreo | Servicio de polling en segundo plano; WebSocket; dashboard React; métricas en vivo | 80 |
| Fase 3 — Control | Endpoints de escritura; validación; UI de control; log de comandos | 80 |
| Fase 4 — Persistencia | Migración a PostgreSQL; histórico PV; reportes; alertas | 40 |
| Fase 5 — Multi-inversor | Pool de conexiones; UI multi-inversor; **soporte TCP/IP + RS485**; balanceador de polling | 80 |
| **Subtotal** | | **376** |

**Adiciones específicas del IVGM-8K (no previstas en el PRD):**

| Tarea | Horas |
|---|---|
| Framing MBAP + RTU conmutable + slave ID | 16 |
| Doble mapa de registros (clásico + IVGM-8K) | 24 |
| CRC obligatorio + partición de bloques + backoff | 16 |
| **Subtotal adicional** | **56** |

**Total Opción B: 432 horas**

### 4.3 Comparación de las dos opciones

| Criterio | Opción A (Python) | Opción B (Java + React) |
|---|---|---|
| Horas | 252 (incluye Etapas 1, 3 y 4) | 490 (incluye Etapas 1, 3 y 4) |
| Costo de ingeniería | menor | ~1.9× |
| Tiempo de entrega | ~7–8 semanas | ~12–14 semanas |
| Curva de aprendizaje | ya dominada por el equipo | stack nuevo |
| Multi-usuario / multi-sitio | limitado | nativo |
| Escalabilidad a 100+ inversores | requiere rediseño | prevista en el PRD |
| Riesgo técnico | bajo (se parte de código que funciona) | medio (stack nuevo, protocolo a reimplementar) |
| Reutilización del trabajo actual | total | solo la lógica de protocolo |

---

## 5. Etapa 3 — Fase de pruebas

### 5.1 Estrategia

| Tipo | Alcance | Herramientas |
|---|---|---|
| **Unitarias** | Framing MBAP/RTU, CRC, parseo de ambos mapas, conversiones de escala, firmas | Python: `pytest` · Java: JUnit 5 + Mockito |
| **Simulador de inversor** | Un "inversor falso" que responde Modbus RTU/TCP con valores conocidos, para probar sin hardware | `pymodbus` (Python) / `j2mod` (Java) |
| **Integración con hardware real** | Banco de pruebas con el IVGM8KLP2G1 + conversor RS485↔TCP | Herramientas propias de diagnóstico |
| **Regresión** | Verificar que el 5K (mapa clásico) siga funcionando después de los cambios | Idem |
| **Aceptación** | Comparar los valores leídos contra la pantalla del inversor en el mismo instante | Protocolo de validación firmado |

### 5.2 Entregables

- Plan de pruebas y matriz de casos.
- Simulador de inversor (reutilizable en producción como "modo demo").
- Informe de resultados con evidencias.
- Protocolo de aceptación firmado por el cliente.

**Esfuerzo Etapa 3**

| Tarea | Horas |
|---|---|
| Plan de pruebas y casos | 8 |
| Simulador de inversor (mock Modbus) | 24 |
| Pruebas unitarias de protocolo y mapas | 24 |
| Pruebas de integración con hardware real | 16 |
| Regresión sobre el 5K | 8 |
| Informe y protocolo de aceptación | 8 |
| **Subtotal Opción A** | **88** |
| Adición Opción B (tests de frontend + API) | 24 |
| **Subtotal Opción B** | **112** |

---

## 6. Etapa 4 — Puesta en marcha

### 6.1 Configuración del conversor RS485 ↔ TCP/IP

Valores de campo que funcionan (documentados por la integración de referencia y el fabricante):

| Parámetro | Valor |
|---|---|
| **Protocolo** | **Modbus TCP To RTU** (si el app usa MBAP) — o *transparente/passthrough* (si el app usa RTU crudo) |
| **Baud rate** | **9600** para IVGM · 2400 para T-REX-5/6/10K |
| **Paridad / datos / stop** | **N / 8 / 1** |
| **Slave ID** | **1** (verificar en el LCD del inversor) |
| Work Mode | TCP Server |
| No-Data-Restart | Enable, Restart Time 100 |
| Reconnect time | 12 s |
| Instruction Timeout | 224 |
| Multi-host | Enable |
| Pack Interval (solo módulos USR-D164) | **100** (con 20 se pierden paquetes) |
| Vircom (solo Waveshare) | Transfer Protocol = Modbus_TCP_Protocol · RS485 Multi-host · bus conflict detection |

### 6.2 Cableado RS485

- **A = D+**, **B = D−**, y **GND** (si el puerto lo tiene).
- **Resistencia de terminación de 120 Ω** entre A y B en el extremo lejano del bus (tramos largos).
- Par trenzado para el par A/B.
- En el conector RJ45 del inversor: el par A/B va a **pines 3 y 4** (pines 5–6 como alternativa).

### 6.3 Tareas de puesta en marcha

| Tarea | Horas |
|---|---|
| Instalación y configuración del conversor (red, protocolo, baud, slave) | 8 |
| Cableado, terminación y verificación de continuidad | 4 |
| Puesta en marcha en sitio con el inversor real | 8 |
| Validación de valores contra la pantalla del inversor | 4 |
| Capacitación y manual de operación | 8 |
| Soporte de arranque (garantía 30 días) | 8 |
| **Subtotal** | **40** |

---

## 7. Plan específico para el inversor Felicity IVGM8KLP2G1

Este es el plan técnico concreto, paso a paso:

1. **Confirmar el protocolo del equipo.** Verificar en el LCD del inversor el **slave ID** y los parámetros de comunicación. Confirmar que el puerto RS485 habla **Modbus RTU** (no PI30 textual).
2. **Levantar el mapa de registros completo del IVGM-8K** desde el documento *"Inverter Communication Protocol — Series RS485"* (el de la familia IVGM, ya identificado) y **verificarlo contra el equipo real** con un volcado de registros.
3. **Implementar el mapa `IVGM_8K`** junto al mapa clásico, con selector en la UI.
4. **Agregar el framing MBAP** al transporte TCP (conmutable con RTU crudo), para poder usar el conversor en su modo nativo "Modbus TCP To RTU".
5. **Agregar slave ID** configurable (hoy está fijo en 1).
6. **Activar la verificación de CRC** en todas las respuestas.
7. **Partir las lecturas** en bloques chicos con bisección ante fallos (clave a 2400 baud).
8. **Configurar el conversor**: 9600 baud, 8N1, slave 1, protocolo Modbus TCP To RTU, timeout 224, multi-host ON.
9. **Validar con el equipo real**: leer los registros y comparar con la pantalla del inversor (tensión de batería, SOC, PV, red, carga).
10. **Probar la escritura** con un parámetro de bajo riesgo y verificar el efecto en el inversor.

**Riesgo principal:** el documento de protocolo del IVGM-8K no está validado contra hardware por la integración de referencia (lo marcan como "provisional"). Por eso el paso 2 es **obligatorio** y no se puede saltear: si el mapa no se verifica contra el equipo real, el trabajo de desarrollo puede hacerse sobre datos equivocados.

---

## 8. Presupuesto

### 8.1 Opción A — Evolución Python (recomendada)

| Etapa | Horas | Tarifa | USD |
|---|---|---|---|
| Etapa 1 — Análisis y estudio | 16 | 50 | 800 |
| Etapa 2 — Solución (Python) | 120 | 50 | 6.000 |
| Etapa 3 — Pruebas | 88 | 50 | 4.400 |
| Etapa 4 — Puesta en marcha | 40 | 50 | 2.000 |
| **Subtotal ingeniería** | **264** | | **13.200** |
| Hardware (sección 8.3) | | | 120 |
| **TOTAL OPCIÓN A** | | | **13.320** |

### 8.2 Opción B — Reescritura Java + React

| Etapa | Horas | Tarifa | USD |
|---|---|---|---|
| Etapa 1 — Análisis y estudio | 16 | 50 | 800 |
| Etapa 2 — Solución (Java + React) | 432 | 50 | 21.600 |
| Etapa 3 — Pruebas | 112 | 50 | 5.600 |
| Etapa 4 — Puesta en marcha | 40 | 50 | 2.000 |
| **Subtotal ingeniería** | **600** | | **30.000** |
| Hardware (sección 8.3) | | | 120 |
| **TOTAL OPCIÓN B** | | | **30.120** |

### 8.3 Hardware

| Ítem | Modelo sugerido | Precio USD | Obs. |
|---|---|---|---|
| Conversor RS485 ↔ Ethernet | Waveshare RS485 TO POE ETH (B) o equivalente (USR, Moxa) | 60 – 90 | rango de referencia, a confirmar según modelo exacto |
| Adaptador USB → RS485 aislado con RJ45 | Waveshare USB TO RS485 (E) | 12 – 18 | para pruebas y para el puerto RJ45 del inversor |
| Adaptador USB → RS485 (no aislado) | Waveshare USB TO RS485 (B) | **7,99** | **precio verificado en waveshare.com el 09/11/2026** |
| Cable RS485 + terminación 120 Ω + conectores | — | 15 – 25 | según longitud |
| Protección de línea (TVS / surge) + borneras | — | 10 – 15 | recomendado en entornos industriales |
| **Total hardware (estimado)** | | **~120** | |

> Los precios de hardware son de referencia y se confirmarán al momento de la compra. El único precio **verificado** es el del adaptador Waveshare USB TO RS485 (B).

### 8.4 Conversión a CUP

**Opción A — total USD 13.320**

| Segmento BCB | Tasa | Total CUP |
|---|---|---|
| I — Estatal | 800 | **10.656.000** |
| III — Población y FGNE | 120 | **1.598.400** |
| II — Especial | 24 | **319.680** |

**Opción B — total USD 30.120**

| Segmento BCB | Tasa | Total CUP |
|---|---|---|
| I — Estatal | 800 | **24.096.000** |
| III — Población y FGNE | 120 | **3.614.400** |
| II — Especial | 24 | **722.880** |

---

## 9. Supuestos y exclusiones

**Supuestos**
- La tarifa de ingeniería es de **USD 50/hora**. Es un supuesto explícito: si el cliente tiene otra tarifa acordada, se recalcula en segundos.
- El trabajo se ejecuta con **disponibilidad del equipo físico** (inversor + conversor) para las pruebas y la puesta en marcha.
- El cliente provee acceso al inversor, al conversor y a la documentación del equipo.
- No se incluyen costos de envío ni de importación del hardware.
- No se incluyen impuestos ni comisiones bancarias por transferencia.

**Exclusiones**
- Desarrollo de firmware del inversor o del conversor.
- Obras eléctricas de cableado estructurado (solo se incluye el cableado del tramo RS485).
- Licencias de software de terceros (todas las librerías propuestas son open source).
- Soporte post-garantía (se cotiza aparte, ver sección 10).
- Conectividad a internet ni configuración de red más allá del tramo local.

**Forma de pago sugerida**
- 40% al inicio, 30% al completar la Etapa 2, 20% al completar la Etapa 3, 10% contra la puesta en marcha y aceptación.

**Vigencia:** 30 días naturales desde la fecha de emisión.

---

## 10. Soporte posterior (opcional, no incluido)

| Modalidad | Cobertura | Precio |
|---|---|---|
| Soporte por hora | Horas sueltas de ajuste/evolución | USD 50/h |
| Mantenimiento mensual | Seguimiento, ajustes menores, respuesta en 48 h | a convenir |
| Ampliación a más inversores | Integración de equipos adicionales | a convenir |

---

## 11. Firmas

| | Cliente | Prestador del servicio |
|---|---|---|
| Nombre | | |
| Cargo | | |
| Firma | | |
| Fecha | | |

---

*Documento generado el 9 de noviembre de 2026. Tasas de cambio: Banco Central de Cuba (API oficial). Precios de hardware: verificados donde se indica; el resto son rangos de referencia.*
