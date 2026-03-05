"""Configuración centralizada para validación VIES.

Parámetros ajustables para tolerancia a throttling, timeouts y concurrencia.

MODOS DISPONIBLES:
- FAST_CONFIG: Defecto. Termina rápido, no satura VIES, FAST-FAIL en países caídos.
- ROBUST_CONFIG: Máxima recuperación, reintentos agresivos, tolerancia alta a fallos.
"""

from dataclasses import dataclass


@dataclass
class ViesConfig:
    """Configuración de validación VIES.
    
    Parámetros optimizados para reducir throttling y timeouts.
    """
    
    # Timeouts de red (segundos)
    connection_timeout: float = 8.0  # Timeout para establecer conexión
    read_timeout: float = 15.0       # Timeout para lectura de respuesta
    
    # Control de concurrencia
    max_workers: int = 2             # Validaciones simultáneas (reducido de 3→2)
    max_requests_per_second: float = 2.0  # Rate limit global (nuevo)
    throttle_ms: int = 500           # Separación mínima entre requests (aumentado de 250→500ms)
    
    # Política de reintentos
    max_auto_retries: int = 5        # Reintentos automáticos (aumentado de 2→5)
    max_hard_attempts: int = 6       # Intentos duros totales (aumentado de 3→6)
    deadline_seconds: int = 120      # Deadline global (aumentado de 25→120s)
    
    # Backoff exponencial
    base_backoff_seconds: float = 2.0  # Base: 2s, 4s, 8s, 16s, 32s, 60s...
    max_backoff_seconds: float = 60.0  # Tope máximo
    
    # Jitter para throttling
    throttle_jitter_min: float = 3.0   # Jitter mínimo (aumentado de 2→3s)
    throttle_jitter_max: float = 10.0  # Jitter máximo (aumentado de 7→10s)
    throttle_jitter_escalation: float = 2.5
    
    # Logging diagnóstico
    verbose_logging: bool = True  # Activar logging detallado


# ===== MODO RÁPIDO (DEFAULT) =====
FAST_CONFIG = ViesConfig(
    connection_timeout=4.0,
    read_timeout=8.0,
    max_workers=2,
    max_requests_per_second=1.5,
    throttle_ms=300,
    max_auto_retries=2,
    max_hard_attempts=3,
    deadline_seconds=30,
    base_backoff_seconds=2.0,
    max_backoff_seconds=20.0,
    throttle_jitter_min=1.0,
    throttle_jitter_max=3.0,
    verbose_logging=True
)

# ===== MODO ROBUSTO =====
ROBUST_CONFIG = ViesConfig(
    connection_timeout=8.0,
    read_timeout=15.0,
    max_workers=2,
    max_requests_per_second=2.0,
    throttle_ms=500,
    max_auto_retries=5,
    max_hard_attempts=6,
    deadline_seconds=120,
    base_backoff_seconds=2.0,
    max_backoff_seconds=60.0,
    throttle_jitter_min=3.0,
    throttle_jitter_max=10.0,
    verbose_logging=True
)

# Instancia global por defecto (MODO RÁPIDO)
DEFAULT_CONFIG = FAST_CONFIG
