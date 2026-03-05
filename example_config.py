"""Script de ejemplo para configurar logging y personalizar parámetros VIES.

Este script muestra cómo ajustar la configuración de VIES para:
- Usar MODO RÁPIDO (default): termina rápido, no satura VIES
- Usar MODO ROBUSTO: máxima recuperación, tolera fallos temporales
- Implementar FAST-FAIL para países caídos (MS_UNAVAILABLE)
- Reducir throttling y mejorar timeouts
"""

import logging
from vat_validator import DEFAULT_CONFIG, ViesConfig
from vat_validator.config import FAST_CONFIG, ROBUST_CONFIG

# Configurar logging detallado
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Activar logging diagnóstico de vat_validator
logging.getLogger('vat_validator').setLevel(logging.INFO)

# ===== MODO RÁPIDO (DEFAULT) =====
print("=== MODO RÁPIDO (DEFAULT) ===")
print("Objetivo: Terminar lotes rápido sin saturar VIES")
print(f"Timeouts: {FAST_CONFIG.connection_timeout}s conn + {FAST_CONFIG.read_timeout}s read = {FAST_CONFIG.connection_timeout + FAST_CONFIG.read_timeout}s total")
print(f"Max workers: {FAST_CONFIG.max_workers}")
print(f"Max requests/s: {FAST_CONFIG.max_requests_per_second}")
print(f"Max auto retries: {FAST_CONFIG.max_auto_retries}")
print(f"Deadline: {FAST_CONFIG.deadline_seconds}s")
print(f"FAST-FAIL en MS_UNAVAILABLE: ✅ (país caído = no reintentar)")
print()

# ===== MODO ROBUSTO (OPTIONAL) =====
print("=== MODO ROBUSTO (OPCIONAL) ===")
print("Objetivo: Máxima recuperación, tolera más fallos temporales")
print(f"Timeouts: {ROBUST_CONFIG.connection_timeout}s conn + {ROBUST_CONFIG.read_timeout}s read = {ROBUST_CONFIG.connection_timeout + ROBUST_CONFIG.read_timeout}s total")
print(f"Max workers: {ROBUST_CONFIG.max_workers}")
print(f"Max requests/s: {ROBUST_CONFIG.max_requests_per_second}")
print(f"Max auto retries: {ROBUST_CONFIG.max_auto_retries}")
print(f"Deadline: {ROBUST_CONFIG.deadline_seconds}s")
print()

# Ejemplo de uso: cambiar a MODO ROBUSTO
# from vat_validator.ui.interface import VATValidatorApp
# app = VATValidatorApp(root)
# app.vies_validator.config = ROBUST_CONFIG  # Cambiar a MODO ROBUSTO

# ===== CONFIGURACIÓN PERSONALIZADA =====
# Configuración ultra-conservadora (para VIES muy sobrecargado)
ultra_safe_config = ViesConfig(
    max_workers=1,                    # Solo 1 worker para no sobrecargar
    max_requests_per_second=0.5,      # Máximo 1 request cada 2 segundos
    throttle_ms=2000,                 # 2 segundos entre requests
    connection_timeout=10.0,          # 10s para conectar
    read_timeout=20.0,                # 20s para leer
    max_auto_retries=8,               # Hasta 8 reintentos automáticos
    max_hard_attempts=10,             # 10 intentos duros
    deadline_seconds=180,             # 3 minutos de deadline
    throttle_jitter_min=5.0,          # 5-15s de jitter para throttled
    throttle_jitter_max=15.0,
    verbose_logging=True,
)

print("=== Configuración ultra-conservadora (personalizada) ===")
print(f"Max workers: {ultra_safe_config.max_workers}")
print(f"Max requests/s: {ultra_safe_config.max_requests_per_second}")
print(f"Max requests/s: {ultra_safe_config.max_requests_per_second}")
print(f"Total timeout: {ultra_safe_config.connection_timeout + ultra_safe_config.read_timeout}s")
print(f"Max reintentos: {ultra_safe_config.max_auto_retries}")
print()

# Ejemplo 3: Configuración agresiva (para VIES poco cargado)
aggressive_config = ViesConfig(
    max_workers=5,                    # 5 workers
    max_requests_per_second=5.0,      # 5 requests por segundo
    throttle_ms=200,                  # 200ms entre requests
    connection_timeout=6.0,
    read_timeout=12.0,
    max_auto_retries=3,
    max_hard_attempts=4,
    deadline_seconds=60,
    verbose_logging=False,  # Menos logs
)

print("=== Configuración agresiva ===")
print(f"Max workers: {aggressive_config.max_workers}")
print(f"Max requests/s: {aggressive_config.max_requests_per_second}")
print()

# Para usar una configuración personalizada en tu aplicación:
# 1. Crea tu ViesConfig
# 2. Pásala al crear RetryScheduler:
#    scheduler = RetryScheduler(vat_data, callbacks, stop_event, config=ultra_safe_config)
#
# O modifica DEFAULT_CONFIG antes de iniciar la app:
#    DEFAULT_CONFIG.max_workers = 1
#    DEFAULT_CONFIG.verbose_logging = True
