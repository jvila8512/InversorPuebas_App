# Guía de Prueba - InversorMonitor

## Objetivo
Probar la conexión RS232 con diferentes inversoresos usando el protocolo PI30.

---

## 1. Conexión Física

###Cable RS232
```
PC (USB/RS232) ←→ Inversor
     │               │
    TXD ←───────────→ RXD
    RXD ←───────────→ TXD
    GND ←───────────→ GND
```

**Nota:** Algunos inversores usan cable cruzado (TXD↔RXD), otros directo.

###Configuración por Defecto
| Parámetro | Valor |
|----------|-------|
| Baud Rate | 2400 |
| Data Bits | 8 |
| Parity | None |
| Stop Bits | 1 |
| Timeout | 2 seg |

---

## 2. Comandos PI30 del Sistema

### Comandos de Lectura (Query)
| Comando | Función | Respuesta |
|---------|--------|----------|
| `QPIGS` | Estado general | 20+ campos (grid, battery, PV, load) |
| `QPIRI` | Parámetros config | Valores de configuración |
| `QMOD` | Modo actual | Power On, Standby, Line, Battery, Fault |
| `QPIWS` | Alarmas | 32 bits de alarmas |
| `Q1` | Estado cargador solar | Datos del MPPT |
| `QPI` | ID protocolo | Identificación |
| `QVFW` | Firmware | Versión firmware |
| `QID` | Número serie | ID único |

### Formato de Trama
```
Comando: (QPIGS<CRC><CR>
Ejemplo: (QPIGS\xD7\r
```

- `(` = Inicio de trama
- `<CRC>` = 2 bytes CRC-16 (Modbus)
- `\r` = Fin de trama

---

## 3. Procedimiento de Prueba

### Paso 1: Conectar el Inversor
1. Conectar cable RS232 al inversor
2. Conectar USB al PC
3. Ejecutar InversorMonitor.exe

### Paso 2: Detectar Puerto
1. Ir a pestaña **Conexión**
2. Click en **🔍 Auto-detectar** o seleccionar puerto manual
3. Verificar que aparece el puerto COM

### Paso 3: Conectar
1. Click en **Conectar**
2. Esperar a que cambie a "Conectado"
3. Ver indicadores en tiempo real

### Paso 4: Verificar Datos
1. Ir a pestaña **Monitor**
2. Observar datos de QPIGS:
   - Grid voltage (V)
   - Grid frequency (Hz)
   - Battery voltage (V)
   - Battery charge (%)
   - PV voltage (V)
   - PV current (A)
   - Load (W)

---

## 4. Modelos Soportados

### Modelos Verificados
- **Axpert** (todos los modelos)
- **Voltronic**
- **Felicity/solar**
- **EPEver** (serie Tracer)
- **UTimes** (BM serie)

### Modelos con PI30 Compatible
- Inversores con protocolo "PI30"
- Algunos modelos Growatt
- Algunos modelos Schneider

---

## 5. Troubleshooting

### Sin Comunicación
| Problema | Solución |
|----------|---------|
| No detecta puerto | Verificar driver USB/TTL |
| Timeout | Verificar baud rate (2400 por defecto) |
| Caracteres raros | Verificar baud rate/paridad |
| Conexión pero sin datos | Probar cable cruzado |

### Errores Comunes
| Error | Causa | Solución |
|-------|-------|----------|
| `N/A` en todos campos | Inversor en modo Standby | Cambiar a modo Line/Battery |
| Error CRC | Ruido en línea | Verificar conexión |
| Timeout | Cable incorrecto | Probar cable cruzado |

---

## 6. Prueba de Comandos Manuales

En la pestaña **Monitor**:
1. Enviar comando directo en campo de texto
2. Click **Enviar**
3. Ver respuesta en log

Ejemplos:
```
QPIGS  → Estado general
QPIRI  → Parámetros
QMOD   → Modo actual
QPIWS  → Alarmas
```

---

## 7. Prueba de Múltiples Inversores

### Para probar con diferentes modelos:
1. **Inversor 1**: Conectar, verificar datos, desconectar
2. **Inversor 2**: Repetir proceso
3. Guardar perfiles para cada modelo

### Guardar Perfil
1. Configurar conexión para el modelo
2. Ir a **Perfiles**
3. Click **Guardar perfil**
4. Nombre: "Modelo_X"

---

## 8. Datos Esperados por Modelo

### Axpert VM/KS/PLUS
- Grid: 220-240V, 50-60Hz
- Battery: 48V (24V/48V selectable)
- PV: 60-150V max

### Felicity/solar
- Similar a Axpert
- Protocolo PI30 idéntico

### EPEver Tracer
- RS485 (no RS232 directo)
- Requiere adaptador RS232→RS485

---

## 9. Validación Final

✅ Checklist de funciona:
- [ ] Puerto COM detectado
- [ ] Conexión establecida
- [ ] QPIGS devuelve datos
- [ ] QMOD muestra modo
- [ ] QPIRI muestra parámetros
- [ ] Monitor en tiempo real

Si todos los items marcados → **Sistema OK**