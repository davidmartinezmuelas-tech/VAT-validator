"""Funciones helper para validación de formato y lógica centralizada de VAT."""

from typing import Tuple, Optional
from .models import normalize_vat, parse_vat


def normalize_vat_format(vat) -> Optional[str]:
    """Normaliza un número VAT a formato estándar.
    
    Elimina espacios, caracteres especiales y convierte a mayúsculas.
    
    Args:
        vat: Número VAT sin procesar
        
    Returns:
        String normalizado o None si está vacío
    """
    return normalize_vat(vat)


def parse_vat_number(vat) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Parsea VAT en país, número y limpío.
    
    Extrae código de país (2 letras) y número del VAT.
    
    Args:
        vat: Número VAT sin procesar
        
    Returns:
        Tupla (país, número, vat_limpio)
    """
    return parse_vat(vat)


def validate_vat_format(vat_clean: Optional[str]) -> bool:
    """Valida que un VAT tenga formato válido.
    
    Un VAT válido debe:
    - No estar vacío
    - Empezar con 2 letras de código de país
    - Contener al menos 2 dígitos después del código
    
    Args:
        vat_clean: VAT normalizado (ej: 'ES12345678')
        
    Returns:
        True si el formato es válido, False en caso contrario
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
    """
    if not country or not number:
        return False
    return len(country) == 2 and country.isalpha() and len(number) > 0
