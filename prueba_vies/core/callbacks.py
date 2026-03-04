"""Callback contracts for communication between core workers and UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import CountryNumber, VatInfo


@dataclass(frozen=True)
class BatchSummary:
    done: int
    total: int
    valid: int
    invalid: int
    pending: int


class ValidationCallbacks:
    """Callback interface invoked by core scheduler from worker threads."""

    def on_vat_updated(self, key: CountryNumber, vat_info: VatInfo, result: dict) -> None:
        pass

    def on_progress(self, done: int, total: int) -> None:
        pass

    def on_banner_update(self, text: str, next_retry_seconds: Optional[int] = None) -> None:
        pass

    def on_batch_finished(self, summary: BatchSummary) -> None:
        pass
