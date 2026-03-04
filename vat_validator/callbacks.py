"""Contratos de callbacks para comunicación entre workers de core y UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import CountryNumber, VatInfo


@dataclass(frozen=True)
class BatchSummary:
    """Resumen de resultados tras completar un lote de validación."""
    done: int
    total: int
    valid: int
    invalid: int
    pending: int


class ValidationCallbacks:
    """Interface de callbacks invocada por el planificador de core desde worker threads.
    
    Proporciona mecanismo de notificación para que el schedulador (ejecutando en threads
    workers) pueda notificar cambios a la UI (ejecutando en thread principal).
    """

    def on_vat_updated(self, key: CountryNumber, vat_info: VatInfo, result: dict) -> None:
        """Notifica que un VAT ha sido validado.
        
        Llamado cuando la validación de un VAT se completa (exitosa o con error).
        """
        pass

    def on_progress(self, done: int, total: int) -> None:
        """Notifica progreso de validación.
        
        Args:
            done: Número de VATs completados
            total: Número total de VATs a validar
        """
        pass

    def on_banner_update(self, text: str, next_retry_seconds: Optional[int] = None) -> None:
        """Actualiza mensaje de banner con estado y próximo reintento.
        
        Args:
            text: Mensaje a mostrar
            next_retry_seconds: Segundos hasta próximo reintento (opcional)
        """
        pass

    def on_batch_finished(self, summary: BatchSummary) -> None:
        """Notifica que el lote completo ha terminado.
        
        Args:
            summary: Resumen con conteos finales
        """
        pass
