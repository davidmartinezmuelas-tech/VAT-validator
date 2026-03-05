"""VIES VAT Validator - Librería centralizada para validación de números VAT europeos.

Proporciona validación contra el servicio oficial VIES de la Comisión Europea.
"""

from .models import (
    VatStatus,
    VatInfo,
    CountryNumber,
    normalize_vat,
    parse_vat,
    get_vat_number_only,
    status_label,
    status_code,
)
from .vies_client import ViesValidator
from .validator import (
    normalize_vat_format,
    parse_vat_number,
    validate_vat_format,
    check_vat_format,
)
from .excel_handler import load_excel, save_excel, detect_vat_column
from .retry_logic import RetryScheduler
from .retry_policy import RetryPolicy
from .logger import VatValidatorLogger, get_logger, init_logger
from .callbacks import ValidationCallbacks, BatchSummary
from .config import ViesConfig, DEFAULT_CONFIG

__version__ = "2.0.0"
__author__ = "David"

__all__ = [
    # Modelos
    "VatStatus",
    "VatInfo",
    "CountryNumber",
    # Validación
    "ViesValidator",
    "normalize_vat",
    "normalize_vat_format",
    "parse_vat",
    "parse_vat_number",
    "validate_vat_format",
    "check_vat_format",
    "get_vat_number_only",
    "status_label",
    "status_code",
    # Excel
    "load_excel",
    "save_excel",
    "detect_vat_column",
    # Scheduling
    "RetryScheduler",
    "RetryPolicy",
    # Logging
    "VatValidatorLogger",
    "get_logger",
    "init_logger",
    # Callbacks
    "ValidationCallbacks",
    "BatchSummary",
    # Configuración
    "ViesConfig",
    "DEFAULT_CONFIG",
]
