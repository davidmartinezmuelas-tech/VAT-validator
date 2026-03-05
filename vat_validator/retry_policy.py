"""Política centralizada de reintentos y cálculo de backoff/jitter.

Responsabilidad única: Decidir next_retry_at basado en:
- Estado actual (THROTTLED, TIMEOUT, ERROR, etc.)
- Contador de intentos automáticos
- Contador de throttles
- Deadline global desde primer intento
- Backoff exponencial con jitter configurable

Esta es la única fuente de verdad para políticas de reintento.
La UI y el scheduler solo consultan/ejecutan decisiones, no las calculan.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .models import VatInfo, VatStatus
from .config import ViesConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryDecision:
    """Decisión de política de reintento."""

    should_retry: bool
    next_retry_at: Optional[datetime]
    reason: str


class RetryPolicy:
    """Política centralizada de reintentos para validación VAT.

    Implementa backoff exponencial con jitter y límites configurables.
    Todas las decisiones de retry se toman aquí, no en UI ni scheduler.
    """

    def __init__(
        self,
        config: ViesConfig = None,
        *,
        # Parámetros legacy para compatibilidad hacia atrás
        base_backoff_seconds: Optional[int] = None,
        max_backoff_seconds: Optional[int] = None,
        max_auto_retries: Optional[int] = None,
        max_hard_attempts: Optional[int] = None,
        deadline_seconds: Optional[int] = None,
        throttle_jitter_min: Optional[float] = None,
        throttle_jitter_max: Optional[float] = None,
        throttle_jitter_escalation: Optional[float] = None,
        rng: Optional[random.Random] = None,
    ):
        """Inicializa política de reintentos.

        Args:
            config: Configuración de VIES (usa DEFAULT_CONFIG si None)
            base_backoff_seconds: [LEGACY] Base para backoff (usa config si None)
            max_backoff_seconds: [LEGACY] Tope máximo de backoff
            max_auto_retries: [LEGACY] Máximo de reintentos automáticos
            max_hard_attempts: [LEGACY] Máximo de intentos duros
            deadline_seconds: [LEGACY] Deadline desde primer intento
            throttle_jitter_min: [LEGACY] Jitter mínimo para THROTTLED
            throttle_jitter_max: [LEGACY] Jitter máximo para THROTTLED
            throttle_jitter_escalation: [LEGACY] Factor de escalamiento
            rng: Generador random (inyectable para tests deterministas)
        """
        # Si se pasan parámetros legacy, crear config temporal
        if any(p is not None for p in [
            base_backoff_seconds, max_backoff_seconds, max_auto_retries,
            max_hard_attempts, deadline_seconds, throttle_jitter_min,
            throttle_jitter_max, throttle_jitter_escalation
        ]):
            # Usar config base y sobrescribir con parámetros legacy
            base_config = config or DEFAULT_CONFIG
            self.config = ViesConfig(
                connection_timeout=base_config.connection_timeout,
                read_timeout=base_config.read_timeout,
                max_workers=base_config.max_workers,
                max_requests_per_second=base_config.max_requests_per_second,
                throttle_ms=base_config.throttle_ms,
                max_auto_retries=max_auto_retries if max_auto_retries is not None else base_config.max_auto_retries,
                max_hard_attempts=max_hard_attempts if max_hard_attempts is not None else base_config.max_hard_attempts,
                deadline_seconds=deadline_seconds if deadline_seconds is not None else base_config.deadline_seconds,
                base_backoff_seconds=base_backoff_seconds if base_backoff_seconds is not None else base_config.base_backoff_seconds,
                max_backoff_seconds=max_backoff_seconds if max_backoff_seconds is not None else base_config.max_backoff_seconds,
                throttle_jitter_min=throttle_jitter_min if throttle_jitter_min is not None else base_config.throttle_jitter_min,
                throttle_jitter_max=throttle_jitter_max if throttle_jitter_max is not None else base_config.throttle_jitter_max,
                throttle_jitter_escalation=throttle_jitter_escalation if throttle_jitter_escalation is not None else base_config.throttle_jitter_escalation,
                verbose_logging=base_config.verbose_logging,
            )
        else:
            self.config = config or DEFAULT_CONFIG
        
        self.rng = rng or random.Random()
        
        # Cache parámetros para acceso rápido
        self.base_backoff = self.config.base_backoff_seconds
        self.max_backoff = self.config.max_backoff_seconds
        self.max_auto = self.config.max_auto_retries
        self.max_hard = self.config.max_hard_attempts
        self.deadline_seconds = self.config.deadline_seconds
        self.throttle_jitter_min = self.config.throttle_jitter_min
        self.throttle_jitter_max = self.config.throttle_jitter_max
        self.throttle_escalation = self.config.throttle_jitter_escalation

    def apply_retry_decision(
        self,
        vat_info: VatInfo,
        *,
        now: Optional[datetime] = None,
    ) -> RetryDecision:
        """Aplica política de reintento a VatInfo.

        Modifica vat_info IN-PLACE:
        - Actualiza next_retry_at
        - Incrementa auto_retry_count si procede
        - Puede marcar como PENDING_MAX si excede límites

        Args:
            vat_info: Información VAT a evaluar (se modifica in-place)
            now: Timestamp actual (inyectable para tests)

        Returns:
            RetryDecision con should_retry y razón
        """
        now = now or datetime.now()

        # Estados terminales: no reintentar
        if vat_info.status in {VatStatus.VALID, VatStatus.INVALID, VatStatus.INVALID_FORMAT}:
            vat_info.next_retry_at = None
            return RetryDecision(False, None, "terminal_status")

        # Solo reintentar estados temporales
        if vat_info.status not in {VatStatus.THROTTLED, VatStatus.TIMEOUT, VatStatus.ERROR}:
            vat_info.next_retry_at = None
            return RetryDecision(False, None, "non_retryable_status")

        # Verificar deadline global
        if self.deadline_seconds and vat_info.first_attempt_at:
            elapsed = (now - vat_info.first_attempt_at).total_seconds()
            if elapsed > self.deadline_seconds:
                vat_info.status = VatStatus.PENDING_MAX
                vat_info.next_retry_at = None
                if self.config.verbose_logging:
                    logger.warning(
                        f"VAT {vat_info.vat_clean}: NO VERIFICABLE (deadline {self.deadline_seconds}s excedido, "
                        f"elapsed={elapsed:.1f}s, attempts={vat_info.attempts_hard}, throttles={vat_info.throttles})"
                    )
                return RetryDecision(False, None, "deadline_exceeded")

        # Verificar límite de reintentos automáticos
        if vat_info.auto_retry_count >= self.max_auto:
            vat_info.status = VatStatus.PENDING_MAX
            vat_info.next_retry_at = None
            if self.config.verbose_logging:
                logger.warning(
                    f"VAT {vat_info.vat_clean}: NO VERIFICABLE (max_auto_retries={self.max_auto} alcanzado, "
                    f"attempts={vat_info.attempts_hard}, throttles={vat_info.throttles}, status={vat_info.status.name})"
                )
            return RetryDecision(False, None, "max_auto_retries")

        # Verificar límite de intentos duros (para TIMEOUT/ERROR)
        if vat_info.attempts_hard >= self.max_hard:
            vat_info.status = VatStatus.PENDING_MAX
            vat_info.next_retry_at = None
            if self.config.verbose_logging:
                logger.warning(
                    f"VAT {vat_info.vat_clean}: NO VERIFICABLE (max_hard_attempts={self.max_hard} alcanzado, "
                    f"throttles={vat_info.throttles}, status={vat_info.status.name})"
                )
            return RetryDecision(False, None, "max_hard_attempts")

        # Calcular delay según estado
        if vat_info.status == VatStatus.THROTTLED:
            delay_seconds = self._calculate_throttle_jitter(vat_info.throttles)
        else:
            # TIMEOUT/ERROR: backoff exponencial
            delay_seconds = self._calculate_backoff_seconds(vat_info.auto_retry_count)

        next_retry = now + timedelta(seconds=delay_seconds)

        # Incrementar contador y asignar
        vat_info.auto_retry_count += 1
        vat_info.next_retry_at = next_retry
        
        if self.config.verbose_logging:
            logger.info(
                f"VAT {vat_info.vat_clean}: Reintento programado en {delay_seconds:.1f}s "
                f"(status={vat_info.status.name}, auto_retry={vat_info.auto_retry_count}/{self.max_auto}, "
                f"hard={vat_info.attempts_hard}/{self.max_hard}, throttles={vat_info.throttles})"
            )

        return RetryDecision(True, next_retry, "auto_retry_scheduled")

    def _calculate_backoff_seconds(self, attempt: int) -> float:
        """Calcula backoff exponencial: 2^attempt con tope.

        Args:
            attempt: Número de intento (0-indexed)

        Returns:
            Segundos de espera (float)
        """
        value = self.base_backoff * (2**attempt)
        return min(value, self.max_backoff)

    def _calculate_throttle_jitter(self, throttle_count: int) -> float:
        """Calcula jitter aleatorio para THROTTLED con escalamiento.

        Escalamiento:
        - throttles=0-1: 2-7s
        - throttles=2:   5-12s
        - throttles=3+:  10-25s

        Args:
            throttle_count: Número de throttles recibidos

        Returns:
            Segundos de espera con jitter aleatorio
        """
        if throttle_count <= 1:
            min_jitter = self.throttle_jitter_min
            max_jitter = self.throttle_jitter_max
        elif throttle_count == 2:
            min_jitter = self.throttle_jitter_min * self.throttle_escalation
            max_jitter = self.throttle_jitter_max * 1.7
        else:
            min_jitter = self.throttle_jitter_min * 5
            max_jitter = self.throttle_jitter_max * 3.5

        return self.rng.uniform(min_jitter, max_jitter)
