# Arquitectura: VIES VAT Validator

## Visión General

La aplicación implementa un **validador de números VAT europeos** contra el servicio oficial **VIES** (Comisión Europea).

El proyecto sigue una **arquitectura en capas** que separa:
- **UI**: Interfaz Tkinter (responsable de interacción con usuario)
- **Core**: Lógica de validación, orquestación y modelos (independiente de UI)

```
┌─────────────────────────────────────────┐
│           UI Layer (app.py)             │
│  Tkinter widgets, Excel I/O, logs       │
└────────────┬────────────────────────────┘
             │
             ↓ callbacks
┌─────────────────────────────────────────┐
│        Core Layer (core/)                │
│  Validator, Scheduler, Models            │
└─────────────────────────────────────────┘
```

---

## Módulos Principales

### 1. `app.py` (UI Principal)

**Responsabilidad**: Punto de entrada y capa de presentación.

**Componentes clave**:
- `VATValidatorApp`: Clase principal de la aplicación
  - Construye la interfaz Tkinter con pestañas (Pendientes/Validados)
  - Maneja carga/descarga de archivos Excel
  - Renderiza tablas de VATs
  - Proporciona botones de acción (Validar, Reintentar, Exportar, Abrir VIES)
  - Muestra logs de actividad con niveles (OK/WARN/ERROR)
  
- `UIThreadCallbacks`: Adaptador de callbacks
  - Recibe notificaciones de workers (core scheduler)
  - Marshalling a thread principal via `root.after(0, callback)`
  - Garantiza thread-safety en actualizaciones de UI

- `Tooltip`: Helper para tooltips en widgets

**No hace**:
- ❌ Parsing de VAT
- ❌ Validación VIES
- ❌ Lógica de scheduling/workers
- ❌ Cálculo de reintentos

---

### 2. `core/models.py` (Datos y Estado)

**Responsabilidad**: Definiciones de datos, enumeraciones y funciones helper.

**Componentes**:

#### `VatStatus` (Enum)
Estados posibles de un VAT:
- `NEW`: Nuevo, sin procesar
- `VALIDATING`: En progreso
- `VALID`: Validado exitosamente contra VIES
- `INVALID`: Rechazado por VIES
- `THROTTLED`: VIES limitó automatizaciones (MS_MAX_CONCURRENT_REQ)
- `TIMEOUT`: No respondió a tiempo
- `ERROR`: Error genérico (SOAP/HTTP)
- `PENDING_MAX`: Alcanzó límite de intentos automáticos
- `INVALID_FORMAT`: VAT con formato incorrecto (no empieza por 2 letras)

#### `VatInfo` (Dataclass)
Información completa de un número VAT:
- **Identificación**: `vat_clean`, `country`, `number`, `nombre_excel`
- **Estado**: `status: VatStatus`
- **Datos VIES**: `vies_name`, `vies_address`
- **Metadata**: `attempts_hard`, `throttles`, `last_checked_at`, `last_error`, `next_retry_at`
- **Métodos helper**: `is_terminal()`, `is_retryable()`, `is_manual_only()`

#### Helper Functions
- `normalize_vat()`: Limpia VAT (espacios, mayúsculas, no-alfanuméricos)
- `parse_vat()`: Extrae (país, número, vat_clean) del string
- `get_vat_number_only()`: Obtiene número sin prefijo de país
- `status_label()`: Convierte VatStatus a label humano para UI (ej: "✓ Válido")
- `status_code()`: Devuelve código string canonical para exports (ej: "VALID")

#### Constants
- `PENDING_STATES`: VATs aún no validados finalmente
- `VALIDATED_STATES`: VATs con resultado final (VALID o INVALID)
- `TERMINAL_STATES`: Resultados finales o máximo alcanzado
- `RETRYABLE_STATES`: Pueden reintentar
- `MANUAL_ONLY_STATES`: Requieren acción manual del usuario

---

### 3. `core/validator.py` (Cliente VIES)

**Responsabilidad**: Comunicación con servicio VIES y clasificación de respuestas.

**Clase**: `ViesValidator`

**Método principal**: `validate_vat(country_code: str, vat_number: str) -> dict`
- Conecta a VIES via SOAP (zeep)
- Ejecuta `checkVat(countryCode, vatNumber)`
- Clasifica respuesta:
  - ✓ `VALID`: Empresa válida → devuelve nombre y dirección
  - ✗ `INVALID`: Rechazado por VIES
  - ⛔ `THROTTLED`: VIES limita (MS_MAX_CONCURRENT_REQ)
  - … `TIMEOUT`: Sin respuesta o error 5xx
  - ⚠ `ERROR`: Otros errores SOAP/HTTP

**Características**:
- **Thread-local pooling**: Reutiliza cliente SOAP por hilo (reduce latencia y TIMEOUTs)
- **Timeout**: 10 segundos por defecto
- **Manejo de errores**: Distingue entre limitaciones, timeouts y errores reales

---

### 4. `core/scheduler.py` (Orquestación Concurrente)

**Responsabilidad**: Gestiona validaciones concurrentes respetando límites de VIES.

**Clase**: `ValidationScheduler`

**Constructor**: `__init__(vat_data, callbacks, stop_event)`
- `vat_data`: Diccionario de VATs a validar
- `callbacks`: Interface `ValidationCallbacks` para notificar UI
- `stop_event`: Señal de parada para workers

**Método principal**: `validate_batch(items: List[Tuple[key, VatInfo]])`
- Crea workers concurrentes (máx 3 simultáneos)
- Implementa cola de prioridad (por ready_time)
- Aplica throttling global (250ms entre requests)
- Implementa cooldown por país (mini circuit-breaker)

**Características**:
- **Concurrencia**: Max 3 workers, respeta semáforos
- **Throttling**: 250ms separación mínima entre requests VIES
- **Cooldown por país**: Si VIES limita un país, espera antes de reintentar
- **Auto-retry corto**: 2 reintentos automáticos por VAT, deadline 25s (evita bucles)
- **Priority queue**: VATs listos (ready_time ≤ now) se procesan primero
- **Callbacks**: Emite notificaciones de progreso a UI en tiempo real

**Workers**:
- Procesan VATs de la cola
- Executar `validator.validate_vat(country, number)`
- Aplican lógica de reintento (respeta cooldown, límites)
- Llaman callbacks para notificar UI (thread-safe)
- Marcan VAT como PENDING_MAX si se alcanza límite

---

### 5. `core/callbacks.py` (Interfaz de Comunicación)

**Responsabilidad**: Define el contrato entre core workers y UI.

**Clase**: `ValidationCallbacks` (Abstract)

**Métodos**:
```python
on_vat_updated(key: CountryNumber, vat_info: VatInfo, result: dict) -> None
```
Notifica que un VAT fue procesado. Incluye resultado actualizado.

```python
on_progress(done: int, total: int) -> None
```
Notifica progreso de la validación (N de M procesados).

```python
on_banner_update(text: str, next_retry_seconds: Optional[int] = None) -> None
```
Actualiza banner con estado actual (ej: "Validando...", "Siguiente reintento en 5s").

```python
on_batch_finished(summary: BatchSummary) -> None
```
Notifica finalización del batch. Incluye resumen (done, total, valid, invalid, pending).

**Implementación en UI**: `UIThreadCallbacks` (en app.py)
- Todas las llamadas se marshalling a thread principal via `root.after(0, callback)`
- Garantiza que actualizaciones de widgets ocurran en thread principal

---

### 6. `ui_styles.py` (Tema y Estilos)

**Responsabilidad**: Constantes de tema para ttkbootstrap.

**Contenido**:
- Colores (background, foreground, accent)
- Fuentes y tamaños
- Espaciado y padding
- Estilos de widgets (buttons, labels, treeviews, etc.)
- Configuración de tooltips

**Propósito**: Centralizar estilo para facilitar cambios globales de tema.

---

## Flujo de Validación

### 1. Carga de Excel (Usuario)
```
Usuario pulsa "Cargar Excel"
    ↓
VATValidatorApp._on_load_file()
    ↓
Abre filedialog → selecciona .xlsx
    ↓
Detecta columna VAT/NIF (busca encabezados: "NIF", "VAT", "VAT NUMBER", etc.)
    ↓
Parse VAT: normalize → parse_vat() → tuple (country, number, vat_clean)
    ↓
Crea VatInfo(status=NEW) por cada fila
    ↓
Muestra en tabla "Pendientes" con estado "⏳ Pendiente"
```

### 2. Inicio Validación (Usuario pulsa "Validar")
```
Usuario pulsa botón "Validar"
    ↓
VATValidatorApp._validate_batch_worker() (thread separado)
    ↓
Crea ValidationScheduler con items, callbacks, stop_event
    ↓
Llama scheduler.validate_batch(items)
    ↓
Scheduler crea workers (hasta 3 concurrentes)
```

### 3. Procesamiento de VAT (Worker)
```
Worker obtiene VAT de cola (prioridad por ready_time)
    ↓
Respeta throttle global (250ms desde último request)
    ↓
Respeta cooldown por país (si estaba limitado, espera)
    ↓
ViesValidator.validate_vat(country, number)
    ↓
checkVat() SOAP call a VIES
    ↓
Clasifica respuesta:
   ✓ Valid → status=VALID, guarda nombre/dirección
   ✗ Invalid → status=INVALID
   ⛔ Throttled → status=THROTTLED, aplica cooldown por país
   … Timeout → status=TIMEOUT
   ⚠ Error → status=ERROR
```

### 4. Reintento Automático (si aplica)
```
Si status ∈ {THROTTLED, TIMEOUT, ERROR} y auto_retry_count < 2:
    ↓
Calcula next_retry_at = now + backoff
    ↓
Reinserta en cola con ready_time = next_retry_at
    ↓
Worker intenta futura vez cuando ready_time ≤ now
    
Si auto_retry_count ≥ 2 o deadline (25s) alcanzado:
    ↓
Estado → PENDING_MAX
    ↓
Requiere acción manual (usuario puede reintentar manualmente)
```

### 5. Callbacks a UI (Thread-Safe)
```
Worker llama: callbacks.on_vat_updated(key, vat_info, result)
    ↓
UIThreadCallbacks recibe (worker thread)
    ↓
Marshalling via root.after(0, _on_vat_updated_main_thread)
    ↓
Ejecución en thread principal Tkinter
    ↓
Actualiza tabla (mueve VAT entre tabs pending/validated)
    ↓
Actualiza logs con resultado
```

### 6. Resumen y Finalización
```
Cuando todos los items alcanzan terminal state:
    ↓
Scheduler emite BatchSummary(done, total, valid, invalid, pending)
    ↓
callbacks.on_batch_finished(summary)
    ↓
UI actualiza banner con resumen
    ↓
Usuario puede:
   - Exportar a Excel (status_code() → strings: VALID, INVALID, etc.)
   - Reintentar pendientes "listos" (ready_time ≤ now)
   - Salir (con confirmación)
```

---

## Características de Confiabilidad

### Anti-Bucle Infinito
- **Auto-retry limitado**: Max 2 reintentos automáticos por VAT
- **Deadline corto**: 25 segundos de intentos automáticos
- **PENDING_MAX**: Si no resolvió, se marca para manual
- **No bloquea UI**: Todo async en workers, callbacks marshalling

### Throttling y Cooldown
- **Throttle global**: 250ms mínimo entre requests VIES
- **Cooldown por país**: Si VIES limita un país, otros países esperan reintent
- **Circuit breaker ligero**: Respeta `next_retry_at` por VAT

### Thread Safety
- Locks para estructuras compartidas (`_active_countries`, `_throttle_lock`)
- Thread-local VIES clients (reduce contención)
- UI marshalling via `root.after(0, callback)` (garantiza ejecución en main thread)

---

## Extensibilidad

### Agregar un Validador Nuevo (no solo VIES)
1. Crear clase en `core/validators_new.py`
2. Implementar mismo interfaz: `validate_vat(country, number) -> dict`
3. En scheduler, usar la nueva clase en `_worker_process_vat()`

### Cambiar Tema
1. Editar constantes en `ui_styles.py`
2. Re-ejecutar app (aplicación auto-detecta cambios)

### Agregar Logging Estructurado
1. Reemplazar `print()` en `app.py` con módulo `logging`
2. Core ya usa docstrings, no hace print()

### CLI o Web API
1. Reutilizar `core/` directamente (independiente de UI)
2. Crear `cli.py` o `api.py` que use `ValidationScheduler` y callbacks personalizados

---

## Resumen de Dependencias

```
app.py (UI)
  ├─ core/models.py (VatStatus, VatInfo, helpers)
  ├─ core/validator.py (ViesValidator)
  ├─ core/scheduler.py (ValidationScheduler)
  ├─ core/callbacks.py (ValidationCallbacks)
  └─ ui_styles.py (estilos)

core/scheduler.py
  ├─ core/models.py
  ├─ core/validator.py
  └─ core/callbacks.py

core/validator.py
  └─ core/models.py

Dependencias externas:
  ├─ tkinter / ttkbootstrap (UI)
  ├─ openpyxl (Excel I/O)
  ├─ zeep (SOAP)
  └─ requests (HTTP)
```

---

## Flujo Observado

1. **Startup**: App carga, interfaz lista (sin VATs)
2. **Load Excel**: Usuario carga archivo → VATs aparecen en "Pendientes"
3. **Validate**: User pulsa botón → workers inician → VATs se validan
4. **Callbacks**: UI actualiza en tiempo real (tablas, logs, progress bar)
5. **Reintento**: Manual (usuario pulsa "Reintentar pendientes listos")
6. **Export**: Excel con campos: VAT_CLEAN, COUNTRY, NUMBER, STATUS, VIES_NAME, LAST_CHECKED_AT, etc.

---

## Notas Importantes

- **VIES es externo**: Puede limitar, fallar, responder lento. App lo maneja graciosamente.
- **No hay almacenamiento persistente**: Cada ejecución empieza limpia.
- **Manual override**: Usuario siempre tiene control (abrir VIES, reintentar, exportar).
- **UX amable**: No bloquea, muestra progreso, evita bucles infinitos.
