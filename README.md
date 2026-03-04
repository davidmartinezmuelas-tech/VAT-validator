# VIES VAT Validator (Desktop)

Aplicación de escritorio en **Python + Tkinter** para validar **números VAT europeos** contra el servicio oficial **VIES** (Comisión Europea) a partir de un Excel.

> Nota: VIES es un servicio externo y a veces responde con limitaciones (por ejemplo `MS_MAX_CONCURRENT_REQ`) o timeouts. La app está diseñada para **no quedarse en bucles infinitos** y ofrecer una **salida manual rápida** cuando VIES limita.

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
- Excel: **openpyxl**
- SOAP (VIES): **zeep**
- HTTP: **requests**

## Limitaciones conocidas

- El servicio VIES **no garantiza** estabilidad para validación masiva automatizada (puede limitar por país o por carga).
- La opción “Abrir VIES” es el **fallback profesional**: rápida, trazable y evita bloquear el proceso.

---

MIT
