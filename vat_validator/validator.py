"""API pública del validador VAT.

Este módulo actúa como fachada limpia que re-exporta helpers de models.py.
Evita imports dispersos y proporciona API estática para componentes externos.

Ejemplos:
    >>> from vat_validator.validator import normalize_vat_format, parse_vat_number
    >>> vat_clean = normalize_vat_format('ES B12345678')
    >>> country, number, clean = parse_vat_number(vat_clean)
"""

from typing import Tuple, Optional

# Re-exports limpios desde models (fuente única de verdad)
from .models import (
    normalize_vat as normalize_vat_format,
    parse_vat as parse_vat_number,
    VatInfo,
    VatStatus,
    CountryNumber,
)


def validate_vat_format(vat_clean: Optional[str]) -> bool:
    """Valida que un VAT tenga formato válido.
    
    Un VAT válido debe:
    - No estar vacío
    - Empezar con 2 letras de código de país
    - Contener al menos 1 dígito después del código
    
    Args:
        vat_clean: VAT normalizado (ej: 'ES12345678')
        
    Returns:
        True si el formato es válido, False en caso contrario
        
    Ejemplos:
        >>> validate_vat_format('ES12345678')
        True
        >>> validate_vat_format('INVALID')
        False
        >>> validate_vat_format('ES')
        False
    """
    if not vat_clean or len(vat_clean) < 3:
        return False
    # Debe empezar con 2 letras (código país)
    country = vat_clean[:2]
    number = vat_clean[2:]
    return country.isalpha() and len(number) > 0


def check_vat_format(country: Optional[str], number: Optional[str]) -> bool:
    """Verifica si país y número tienen formato válido para VIES.
    
    Args:
        country: Código de país (2 letras)
        number: Número VAT sin prefijo
        
    Returns:
        True si ambos son válidos
        
    Ejemplos:
        >>> check_vat_format('ES', 'B12345678')
        True
        >>> check_vat_format('E', '12345678')
        False
        >>> check_vat_format(None, '12345678')
        False
    """
    if not country or not number:
        return False
    return len(country) == 2 and country.isalpha() and len(number) > 0


# API pública del módulo
__all__ = [
    "normalize_vat_format",
    "parse_vat_number",
    "validate_vat_format",
    "check_vat_format",
    "VatInfo",
    "VatStatus",
    "CountryNumber",
]
