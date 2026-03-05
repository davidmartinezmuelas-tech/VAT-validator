"""Script de ejemplo para configurar logging y personalizar parámetros VIES.

Este script muestra cómo ajustar la configuración de VIES para:
- Reducir throttling
- Mejorar timeouts
- Ajustar reintentos
- Activar logging diagnóstico
"""

import logging
from vat_validator import DEFAULT_CONFIG, ViesConfig

# Configurar logging detallado
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Activar logging diagnóstico de vat_validator
logging.getLogger('vat_validator').setLevel(logging.INFO)

# Ejemplo 1: Usar configuración por defecto (optimizada)
print("=== Configuración por defecto ===")
print(f"Max workers: {DEFAULT_CONFIG.max_workers}")
print(f"Max requests/s: {DEFAULT_CONFIG.max_requests_per_second}")
print(f"Connection timeout: {DEFAULT_CONFIG.connection_timeout}s")
print(f"Read timeout: {DEFAULT_CONFIG.read_timeout}s")
print(f"Max auto retries: {DEFAULT_CONFIG.max_auto_retries}")
print(f"Deadline: {DEFAULT_CONFIG.deadline_seconds}s")
print(f"Throttle jitter: {DEFAULT_CONFIG.throttle_jitter_min}-{DEFAULT_CONFIG.throttle_jitter_max}s")
print()

# Ejemplo 2: Configuración ultra-conservadora (para VIES muy sobrecargado)
ultra_safe_config = ViesConfig(
    max_workers=1,                    # Solo 1 worker
    max_requests_per_second=1.0,      # Máximo 1 request por segundo
    throttle_ms=1000,                 # 1 segundo entre requests
    connection_timeout=10.0,          # 10s para conectar
    read_timeout=20.0,                # 20s para leer
    max_auto_retries=8,               # Hasta 8 reintentos automáticos
    max_hard_attempts=10,             # 10 intentos duros
    deadline_seconds=180,             # 3 minutos de deadline
    throttle_jitter_min=5.0,          # 5-15s de jitter para throttled
    throttle_jitter_max=15.0,
    verbose_logging=True,
)

print("=== Configuración ultra-conservadora ===")
print(f"Max workers: {ultra_safe_config.max_workers}")
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
