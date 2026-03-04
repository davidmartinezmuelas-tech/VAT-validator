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

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .models import VatInfo, VatStatus


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
        *,
        base_backoff_seconds: int = 2,
        max_backoff_seconds: int = 60,
        max_auto_retries: int = 2,
        max_hard_attempts: int = 3,
        deadline_seconds: Optional[int] = 25,
        throttle_jitter_min: float = 2.0,
        throttle_jitter_max: float = 7.0,
        throttle_jitter_escalation: float = 2.5,
        rng: Optional[random.Random] = None,
    ):
        """Inicializa política de reintentos.

        Args:
            base_backoff_seconds: Base para backoff exponencial (default: 2s)
            max_backoff_seconds: Tope máximo de backoff (default: 60s)
            max_auto_retries: Máximo de reintentos automáticos (default: 2)
            max_hard_attempts: Máximo de intentos duros antes de PENDING_MAX (default: 3)
            deadline_seconds: Deadline desde primer intento (default: 25s)
            throttle_jitter_min: Jitter mínimo para THROTTLED (default: 2s)
            throttle_jitter_max: Jitter máximo inicial para THROTTLED (default: 7s)
            throttle_jitter_escalation: Factor de escalamiento de jitter por throttle (default: 2.5)
            rng: Generador random (inyectable para tests deterministas)
        """
        self.base_backoff = base_backoff_seconds
        self.max_backoff = max_backoff_seconds
        self.max_auto = max_auto_retries
        self.max_hard = max_hard_attempts
        self.deadline_seconds = deadline_seconds
        self.throttle_jitter_min = throttle_jitter_min
        self.throttle_jitter_max = throttle_jitter_max
        self.throttle_escalation = throttle_jitter_escalation
        self.rng = rng or random.Random()

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
                return RetryDecision(False, None, "deadline_exceeded")

        # Verificar límite de reintentos automáticos
        if vat_info.auto_retry_count >= self.max_auto:
            vat_info.status = VatStatus.PENDING_MAX
            vat_info.next_retry_at = None
            return RetryDecision(False, None, "max_auto_retries")

        # Verificar límite de intentos duros (para TIMEOUT/ERROR)
        if vat_info.attempts_hard >= self.max_hard:
            vat_info.status = VatStatus.PENDING_MAX
            vat_info.next_retry_at = None
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
