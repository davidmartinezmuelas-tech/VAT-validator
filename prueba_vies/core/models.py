"""Data models and helper functions for VAT validation."""

from __future__ import annotations
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple


CountryNumber = Tuple[str, str]  # (country, number)


class VatStatus(Enum):
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
    """Information about a VAT number."""
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
        return self.status in TERMINAL_STATES

    def is_retryable(self) -> bool:
        return self.status in RETRYABLE_STATES

    def is_manual_only(self) -> bool:
        return self.status in MANUAL_ONLY_STATES


# Estado constants
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


# Helper functions

def normalize_vat(vat) -> Optional[str]:
    """Normalize VAT number: remove spaces, non-alphanumeric, uppercase."""
    if vat is None:
        return None
    vat_str = str(vat).replace("\u00A0", "")
    vat_clean = re.sub(r"[^A-Z0-9]", "", vat_str.upper())
    return vat_clean or None


def parse_vat(vat) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse VAT into (country, number, vat_clean).
    
    Returns:
        Tuple of (country_code, vat_number, full_vat_clean)
        If invalid format, returns (None, None, vat_clean)
    """
    normalized = normalize_vat(vat)
    if not normalized or len(normalized) < 3:
        return None, None, normalized
    if not re.match(r"^[A-Z]{2}", normalized):
        return None, None, normalized
    return normalized[:2], normalized[2:], normalized


def get_vat_number_only(vat_clean: str) -> str:
    """Get VAT number without country prefix."""
    vat_clean = re.sub(r"[^A-Z0-9]", "", (vat_clean or "").upper())
    if re.match(r"^[A-Z]{2}", vat_clean):
        return vat_clean[2:]
    return vat_clean


def status_label(status: VatStatus) -> str:
    """Convert VatStatus to human-readable label for UI (sin cambios de textos)."""
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
    """Get canonical status code string for exports/logs."""
    return status.value


def human_status(status: VatStatus) -> str:
    """Backward-compatible alias for status_label."""
    return status_label(status)
