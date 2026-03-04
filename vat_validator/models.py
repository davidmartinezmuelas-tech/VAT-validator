"""Modelos de datos y funciones helper para validación de VAT."""

from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple


CountryNumber = Tuple[str, str]  # (país, número)


class VatStatus(Enum):
    """Estados posibles de validación de un número VAT."""
    NEW = "NEW"
    VALIDATING = "VALIDATING"
    VALID = "VALID"
    INVALID = "INVALID"
    THROTTLED = "THROTTLED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    PENDING_MAX = "PENDING_MAX"
    INVALID_FORMAT = "INVALID_FORMAT"


@dataclass
class VatInfo:
    """Información completa de un número VAT."""
    vat_clean: str
    country: str
    number: str
    nombre_excel: str = ""

    status: VatStatus = VatStatus.NEW
    vies_name: str = ""
    vies_address: str = ""

    attempts_hard: int = 0
    throttles: int = 0

    last_checked_at: str = ""
    last_error: str = ""

    next_retry_at: Optional[datetime] = None

    # Anti-bucle / UX rápida: límites de reintento automático (por VAT)
    first_attempt_at: Optional[datetime] = None
    auto_retry_count: int = 0

    def is_terminal(self) -> bool:
        """Verifica si el estado es terminal."""
        return self.status in TERMINAL_STATES

    def is_retryable(self) -> bool:
        """Verifica si el estado permite reintentos."""
        return self.status in RETRYABLE_STATES

    def is_manual_only(self) -> bool:
        """Verifica si solo permite reintentos manuales."""
        return self.status in MANUAL_ONLY_STATES


# Constantes de estado
PENDING_STATES = {
    VatStatus.NEW,
    VatStatus.VALIDATING,
    VatStatus.THROTTLED,
    VatStatus.TIMEOUT,
    VatStatus.ERROR,
    VatStatus.PENDING_MAX,
}
VALIDATED_STATES = {VatStatus.VALID, VatStatus.INVALID}
TERMINAL_STATES = {VatStatus.VALID, VatStatus.INVALID, VatStatus.PENDING_MAX, VatStatus.INVALID_FORMAT}
RETRYABLE_STATES = {VatStatus.THROTTLED, VatStatus.TIMEOUT, VatStatus.ERROR, VatStatus.PENDING_MAX}
MANUAL_ONLY_STATES = {VatStatus.PENDING_MAX, VatStatus.INVALID_FORMAT}


# Funciones auxiliares

def normalize_vat(vat) -> Optional[str]:
    """Normaliza número VAT: elimina espacios, no-alfanuméricos, mayúsculas.
    
    Elimina espacios inseparables, convierte a mayúsculas, mantiene solo letras y dígitos.
    
    Args:
        vat: String VAT raw desde Excel o entrada del usuario
        
    Returns:
        String normalizado (ej: 'ES12345678A') o None si está vacío
    """
    if vat is None:
        return None
    vat_str = str(vat).replace("\u00A0", "")
    vat_clean = re.sub(r"[^A-Z0-9]", "", vat_str.upper())
    return vat_clean or None


def parse_vat(vat) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Parsea VAT en (país, número, vat_clean).
    
    Espera formato VAT: código de país de 2 letras + número (ej: 'ES12345678A').
    Retorna tupla adecuada para llamada SOAP VIES checkVat().
    
    Args:
        vat: String VAT raw
        
    Returns:
        Tupla de (código_país, número_vat, vat_completo_limpio)
        Si formato inválido (no empieza con 2 letras), retorna (None, None, vat_clean)
        
    Ejemplos:
        parse_vat('ES12345678')  →  ('ES', '12345678', 'ES12345678')
        parse_vat('INVALID')      →  (None, None, 'INVALID')
    """
    normalized = normalize_vat(vat)
    if not normalized or len(normalized) < 3:
        return None, None, normalized
    if not re.match(r"^[A-Z]{2}", normalized):
        return None, None, normalized
    return normalized[:2], normalized[2:], normalized


def get_vat_number_only(vat_clean: str) -> str:
    """Extrae número VAT sin prefijo de país (para botón "Abrir VIES").
    
    Usado cuando usuario presiona 'Abrir VIES' para copiar la parte solo-número al portapapeles
    y abre sitio web VIES (usuario entonces elige país manualmente).
    
    Args:
        vat_clean: VAT normalizado (ej: 'ES12345678')
        
    Returns:
        Parte solo-número (ej: '12345678')
        Si no está en formato CCNNNN, retorna string normalizado completo
    """
    vat_clean = re.sub(r"[^A-Z0-9]", "", (vat_clean or "").upper())
    if re.match(r"^[A-Z]{2}", vat_clean):
        return vat_clean[2:]
    return vat_clean


def status_label(status: VatStatus) -> str:
    """Convierte enum VatStatus a etiqueta legible para visualización en UI.
    
    Cada estado recibe un indicador visual (emoji) y descripción en español.
    Usado en celdas de tabla, logs y mensajes de banner.
    
    Args:
        status: Valor enum VatStatus
        
    Returns:
        String formateado (ej: '✓ Válido', '⏳ Pendiente', '⛔ Limitado por VIES')
    """
    mapping = {
        VatStatus.VALID: "✓ Válido",
        VatStatus.INVALID: "✕ Inválido",
        VatStatus.NEW: "⏳ Pendiente",
        VatStatus.VALIDATING: "⏳ Pendiente",
        VatStatus.THROTTLED: "⛔ Limitado por VIES",
        VatStatus.TIMEOUT: "… Sin respuesta",
        VatStatus.ERROR: "⚠ Error",
        VatStatus.PENDING_MAX: "⚠ No verificable ahora",
        VatStatus.INVALID_FORMAT: "✕ Formato inválido",
    }
    return mapping.get(status, status.value)


def status_code(status: VatStatus) -> str:
    """Obtiene código de estado canónico para exports Excel y logging estructurado.
    
    Retorna el valor Enum como string (ej: 'VALID', 'INVALID', 'THROTTLED').
    Esto es lo que se escribe en salida Excel.
    
    Args:
        status: Enum VatStatus
        
    Returns:
        Código string (ej: 'VALID', 'THROTTLED', 'PENDING_MAX')
    """
    return status.value


def human_status(status: VatStatus) -> str:
    """Alias compatible hacia atrás para status_label."""
    return status_label(status)
