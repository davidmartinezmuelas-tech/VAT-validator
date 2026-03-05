# VIES VAT Validator (Desktop)

Aplicación de escritorio en **Python + Tkinter** para validar **números VAT europeos** contra el servicio oficial **VIES** (Comisión Europea) a partir de un Excel.

> **✨ Versión 2.1**: Tolerancia mejorada a throttling y timeouts - Reducción de errores hasta 80% mediante rate limiting inteligente, timeouts ajustables y reintentos optimizados. Ver [MEJORAS_TOLERANCIA_VIES.md](MEJORAS_TOLERANCIA_VIES.md)

> Nota: VIES es un servicio externo y a veces responde con limitaciones (por ejemplo `MS_MAX_CONCURRENT_REQ`) o timeouts. La app está optimizada para **minimizar throttling** con control de concurrencia (2 workers, 2 req/s) y **reintentos inteligentes** (backoff exponencial, deadline de 120s).

## Funcionalidades

- **Carga de Excel** (`.xlsx`) y detección automática de columna VAT/NIF (busca encabezados típicos: `NIF`, `VAT`, `VAT NUMBER`, etc.)
- **Validación automática al cargar** (no hace falta pulsar “Validar”)
- **Interfaz con pestañas**:
  - **Pendientes**: NEW/THROTTLED/TIMEOUT/ERROR/PENDING_MAX/INVALID_FORMAT
  - **Validados**: VALID/INVALID
- **Acción “Abrir VIES” por fila** cuando un VAT queda limitado o falla:
  - Copia al portapapeles el **número sin prefijo de país** (ej: `FR123...` → `123...`)
  - Muestra aviso con el **país** que debes seleccionar en VIES
  - Abre la web de VIES
- **Reintentar** pendientes “listos” (respeta la hora sugerida de reintento)
- **Exportación**:
  - Exportar todo
  - Exportar validados
  - Exportar pendientes
- **Registro de actividad** con formato más legible (niveles: OK/WARN/ERROR)
  - Auto-scroll (inteligente: si haces scroll manual hacia arriba se desactiva)
  - Limpiar / Copiar / Guardar log
- **Confirmación al salir**

## Requisitos

- Python **3.10+** (recomendado 3.11)
- Internet

## Instalación

```bash
python -m venv .venv
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1
# Linux/Mac
# source .venv/bin/activate

pip install -r requirements.txt
```

> Si PowerShell da error al activar el venv:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

## Arquitectura

El proyecto está organizado en dos capas: **UI** e **integración de negocio (core)**.

### Componentes

#### `app.py` (Punto de Entrada)
Interfaz de usuario basada en **Tkinter + ttkbootstrap**. Responsable de:
- Carga/descarga de Excel
- Renderizado de tablas de VATs (pendientes/validados)
- Botones de acción (Validar, Reintentar, Exportar, Abrir VIES)
- Logs y feedback visual
- Llamadas al core para iniciar validaciones

#### `core/validator.py` (Validación VIES)
Cliente **SOAP (zeep)** contra el servicio oficial VIES. Responsable de:
- Conectarse a VIES y ejecutar `checkVat()`
- Clasificar respuestas: VALID, INVALID, THROTTLED, TIMEOUT, ERROR, etc.
- Manejo de errores específicos (timeouts, limitaciones, etc.)
- Pool de conexiones thread-local para mejor rendimiento

#### `core/scheduler.py` (Orquestación Concurrente)
Ejecutor de validaciones con **trabajadores (workers)** concurrentes. Responsable de:
- Cola de prioridad usando `bisect`
- Máximo 3 workers simultáneos
- Throttling global (250ms entre requests)
- Cooldown por país (circuit breaker)
- Auto-retry con deadline (25s) y límite (2 intentos)
- Callbacks a la UI para notificar progreso y resultados

#### `ui_styles.py` (Estilos UI)
Constantes de tema y estilos de ttkbootstrap para mantener consistencia visual.

#### `core/models.py` (Datos y Helpers)
Dataclasses y utilidades:
- `VatInfo`: Información completa de un VAT
- `VatStatus`: Estado del VAT (VALID, THROTTLED, etc.)
- Funciones de parsing, normalización, helpers


## Flujo de Validación

### 1. Carga de Excel (Usuario)
```
Usuario pulsa "Cargar Excel"
  → Selecciona archivo .xlsx
  → App detecta columna VAT/NIF automáticamente
  → Parsea cada VAT (normaliza, extrae país + número)
  → Crea VatInfo con estado VALIDATING
  → Muestra VATs en tabla "Pendientes"
```

### 2. Validación (Automática al Cargar)
```
App inicia scheduler con items
  → Crea 3 workers concurrentes
  → Tabula VATs en cola de prioridad
  → Workers procesan VAT por VAT:
```

### 3. Procesamiento de Cada VAT
```
Worker obtiene VAT de la cola
  ├─ Respeta throttle global (250ms desde último request)
  ├─ Respeta cooldown por país (si estaba limitado)
  └─ Llama ViesValidator.validate_vat(country, number)
       ├─ VIES responde VALID → Guarda nombre/dirección
       ├─ VIES responde INVALID
       ├─ VIES limita (MS_MAX_CONCURRENT_REQ) → Status THROTTLED, cooldown por país
       ├─ VIES timeout → Status TIMEOUT
       └─ Error genérico → Status ERROR

Si estado retryable (THROTTLED, TIMEOUT, ERROR):
  ├─ auto_retry_count < 2 y deadline (25s) no alcanzado
  └─ Reinserta en cola con next_retry_at = now + backoff
  
Si auto_retry_count ≥ 2 o deadline alcanzado:
  └─ Status PENDING_MAX (requiere acción manual)
```

### 4. Actualización de UI (Thread-Safe)
```
Worker emite callback: on_vat_updated(key, vat_info, result)
  → UIThreadCallbacks marshalling via root.after(0, ...)
  → Ejecución en thread principal Tkinter
  → Actualiza tabla:
      ├─ Si VALID/INVALID: mueve a pestaña "Validados"
      └─ Si aún PENDING: permanece en "Pendientes"
  → Actualiza logs con resultado (OK/WARN/ERROR)
```

### 5. Resumen y Finalización
```
Cuando todos VATs alcanzan estado terminal:
  → Scheduler emite BatchSummary(done, total, valid, invalid, pending)
  → UI actualiza banner con resumen final
  
Usuario puede:
  ├─ Exportar a Excel (status_code() → strings: VALID, INVALID, THROTTLED, etc.)
  ├─ Reintentar pendientes "listos" (que cumplieron next_retry_at)
  ├─ Abrir VIES manualmente para VATs limitados/fallidos
  └─ Salir (con confirmación)
```

---


## Ejecutar

```bash
python main.py
```

## Uso

1. Pulsa **“Cargar Excel”** y elige tu archivo.
2. La validación empieza automáticamente.
3. Revisa los resultados:
   - Los **VALID/INVALID** pasan a la pestaña **Validados**.
   - Los **THROTTLED/TIMEOUT/ERROR** se quedan en **Pendientes**.
4. Si un VAT queda limitado o falla, usa **“[[ Abrir VIES ]]”**:
   - Se copia el número (sin prefijo) y se abre VIES.
5. Si procede, pulsa **“Reintentar”** para revalidar los pendientes que ya estén “listos”.
## Configuración Avanzada

La aplicación usa parámetros optimizados por defecto (ver [MEJORAS_TOLERANCIA_VIES.md](MEJORAS_TOLERANCIA_VIES.md)), pero puedes personalizarlos:

### Configuración por defecto (recomendada)
```python
# No requiere cambios - parámetros optimizados:
- Max workers: 2 (validaciones simultáneas)
- Rate limit: 2.0 requests/segundo
- Timeout: 8s conexión + 15s lectura = 23s total
- Max reintentos: 5 automáticos, 6 intentos duros
- Deadline: 120 segundos
- Logging: activado
```

### Personalización (si VIES está muy sobrecargado)
```python
# Editar antes de main.py o crear script custom
from vat_validator import DEFAULT_CONFIG

DEFAULT_CONFIG.max_workers = 1              # Más conservador
DEFAULT_CONFIG.max_requests_per_second = 1.0
DEFAULT_CONFIG.max_auto_retries = 8
DEFAULT_CONFIG.deadline_seconds = 180       # 3 minutos
DEFAULT_CONFIG.verbose_logging = True       # Logs detallados
```

Ver [example_config.py](example_config.py) para ejemplos completos.

### Activar logging diagnóstico
```python
import logging
logging.basicConfig(level=logging.INFO)
logging.getLogger('vat_validator').setLevel(logging.INFO)
```
## Estados

- `VALID` / `INVALID`: respuesta final de VIES
- `THROTTLED`: VIES limita la automatización (`MS_MAX_CONCURRENT_REQ`)
- `TIMEOUT`: no respondió a tiempo
- `ERROR`: error genérico (SOAP/HTTP)
- `PENDING_MAX`: se alcanzó el máximo de intentos “duros” (no entra en bucle)
- `INVALID_FORMAT`: VAT con formato incorrecto (no empieza por 2 letras, etc.)

## Exportación

El Excel de salida incluye:

- `VAT_CLEAN`, `COUNTRY`, `NUMBER`, `NOMBRE_EXCEL`
- `STATUS`, `ATTEMPTS`, `THROTTLES`
- `LAST_CHECKED_AT`, `NEXT_RETRY_AT`
- `VIES_NAME`, `VIES_ADDRESS`, `ERROR`

## Stack

- GUI: **Tkinter / ttk**
- UI Theme: **ttkbootstrap**
- Excel: **openpyxl**
- SOAP (VIES): **zeep**
- HTTP: **requests**

## Limitaciones conocidas

- El servicio VIES **no garantiza** estabilidad para validación masiva automatizada (puede limitar por país o por carga).
- La opción “Abrir VIES” es el **fallback profesional**: rápida, trazable y evita bloquear el proceso.

---

MIT
