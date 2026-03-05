"""Configuración centralizada para validación VIES.

Parámetros ajustables para tolerancia a throttling, timeouts y concurrencia.
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


# Instancia global (modificable antes de iniciar validación)
DEFAULT_CONFIG = ViesConfig()
