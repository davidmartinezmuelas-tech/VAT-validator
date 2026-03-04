"""Tests para RetryPolicy - fuente única de verdad para cálculo de reintentos."""

import random
from datetime import datetime, timedelta

import pytest

from vat_validator.models import VatInfo, VatStatus
from vat_validator.retry_policy import RetryPolicy, RetryDecision


class TestRetryPolicy:
    """Tests para política centralizada de reintentos."""

    def test_terminal_status_no_retry(self):
        """Estados terminales (VALID, INVALID) no reintentan."""
        policy = RetryPolicy()
        now = datetime(2026, 3, 4, 12, 0, 0)

        for status in [VatStatus.VALID, VatStatus.INVALID, VatStatus.INVALID_FORMAT]:
            vat = VatInfo(
                vat_clean="ESB12345678",
                country="ES",
                number="B12345678",
                status=status,
                auto_retry_count=0,
            )

            decision = policy.apply_retry_decision(vat, now=now)

            assert decision.should_retry is False
            assert vat.next_retry_at is None
            assert "terminal" in decision.reason or "non_retryable" in decision.reason

    def test_timeout_backoff_exponential(self):
        """TIMEOUT/ERROR usan backoff exponencial: 2^attempt."""
        rng = random.Random(42)  # Seed determinista
        policy = RetryPolicy(
            base_backoff_seconds=2, max_backoff_seconds=60, max_auto_retries=5, rng=rng
        )
        now = datetime(2026, 3, 4, 12, 0, 0)

        vat = VatInfo(
            vat_clean="ESB12345678",
            country="ES",
            number="B12345678",
            status=VatStatus.TIMEOUT,
            auto_retry_count=0,
            attempts_hard=0,
            first_attempt_at=now,
        )

        # Primer reintento: 2^0 = 1, base_backoff * 1 = 2s
        decision = policy.apply_retry_decision(vat, now=now)
        assert decision.should_retry is True
        assert vat.auto_retry_count == 1
        assert vat.next_retry_at == now + timedelta(seconds=2)

        # Segundo reintento: 2^1 = 2, base_backoff * 2 = 4s
        vat.auto_retry_count = 1
        vat.status = VatStatus.ERROR
        decision = policy.apply_retry_decision(vat, now=now)
        assert decision.should_retry is True
        assert vat.auto_retry_count == 2
        assert vat.next_retry_at == now + timedelta(seconds=4)

        # Tercer reintento: 2^2 = 4, base_backoff * 4 = 8s
        vat.auto_retry_count = 2
        decision = policy.apply_retry_decision(vat, now=now)
        assert decision.should_retry is True
        assert vat.auto_retry_count == 3
        assert vat.next_retry_at == now + timedelta(seconds=8)

    def test_max_backoff_respected(self):
        """Backoff no excede max_backoff_seconds."""
        policy = RetryPolicy(base_backoff_seconds=2, max_backoff_seconds=10)
        now = datetime(2026, 3, 4, 12, 0, 0)

        vat = VatInfo(
            vat_clean="ESB12345678",
            country="ES",
            number="B12345678",
            status=VatStatus.TIMEOUT,
            auto_retry_count=10,  # 2^10 = 1024, pero tope es 10
            attempts_hard=0,
            first_attempt_at=now,
        )

        decision = policy.apply_retry_decision(vat, now=now)
        assert decision.should_retry is True
        # 2 * 2^10 = 2048, pero max es 10
        expected_delay = timedelta(seconds=10)
        assert vat.next_retry_at == now + expected_delay

    def test_throttled_jitter_escalation(self):
        """THROTTLED escala jitter según contador de throttles."""
        rng = random.Random(0)  # Seed determinista
        policy = RetryPolicy(
            throttle_jitter_min=2.0,
            throttle_jitter_max=7.0,
            throttle_jitter_escalation=2.5,
            rng=rng,
        )
        now = datetime(2026, 3, 4, 12, 0, 0)

        # throttles=0 o 1: rango [2, 7]
        vat = VatInfo(
            vat_clean="ESB12345678",
            country="ES",
            number="B12345678",
            status=VatStatus.THROTTLED,
            auto_retry_count=0,
            throttles=1,
            first_attempt_at=now,
        )

        decision = policy.apply_retry_decision(vat, now=now)
        assert decision.should_retry is True
        delay1 = (vat.next_retry_at - now).total_seconds()
        assert 2.0 <= delay1 <= 7.0

        # throttles=2: rango escalado [5, ~12]
        vat.status = VatStatus.THROTTLED
        vat.throttles = 2
        vat.auto_retry_count = 0  # Reset para test
        decision = policy.apply_retry_decision(vat, now=now)
        assert decision.should_retry is True
        delay2 = (vat.next_retry_at - now).total_seconds()
        assert delay2 >= 5.0  # Escalado

        # throttles=3+: rango mayor [10, 25]
        vat.status = VatStatus.THROTTLED
        vat.throttles = 3
        vat.auto_retry_count = 0
        decision = policy.apply_retry_decision(vat, now=now)
        assert decision.should_retry is True
        delay3 = (vat.next_retry_at - now).total_seconds()
        assert delay3 >= 10.0

    def test_max_auto_retries_enforced(self):
        """Límite de reintentos automáticos marca PENDING_MAX."""
        policy = RetryPolicy(max_auto_retries=2)
        now = datetime(2026, 3, 4, 12, 0, 0)

        vat = VatInfo(
            vat_clean="ESB12345678",
            country="ES",
            number="B12345678",
            status=VatStatus.TIMEOUT,
            auto_retry_count=2,  # Ya alcanzó el límite
            attempts_hard=1,
            first_attempt_at=now,
        )

        decision = policy.apply_retry_decision(vat, now=now)

        assert decision.should_retry is False
        assert decision.reason == "max_auto_retries"
        assert vat.status == VatStatus.PENDING_MAX
        assert vat.next_retry_at is None

    def test_max_hard_attempts_enforced(self):
        """Límite de intentos duros marca PENDING_MAX."""
        policy = RetryPolicy(max_hard_attempts=3)
        now = datetime(2026, 3, 4, 12, 0, 0)

        vat = VatInfo(
            vat_clean="ESB12345678",
            country="ES",
            number="B12345678",
            status=VatStatus.ERROR,
            auto_retry_count=0,
            attempts_hard=3,  # Alcanzó límite de intentos duros
            first_attempt_at=now,
        )

        decision = policy.apply_retry_decision(vat, now=now)

        assert decision.should_retry is False
        assert decision.reason == "max_hard_attempts"
        assert vat.status == VatStatus.PENDING_MAX
        assert vat.next_retry_at is None

    def test_deadline_exceeded(self):
        """Deadline global marca PENDING_MAX si se excede."""
        policy = RetryPolicy(deadline_seconds=25)
        now = datetime(2026, 3, 4, 12, 0, 0)
        first_attempt = now - timedelta(seconds=30)  # 30s atrás, excede deadline de 25s

        vat = VatInfo(
            vat_clean="ESB12345678",
            country="ES",
            number="B12345678",
            status=VatStatus.TIMEOUT,
            auto_retry_count=0,
            attempts_hard=1,
            first_attempt_at=first_attempt,
        )

        decision = policy.apply_retry_decision(vat, now=now)

        assert decision.should_retry is False
        assert decision.reason == "deadline_exceeded"
        assert vat.status == VatStatus.PENDING_MAX
        assert vat.next_retry_at is None

    def test_deadline_not_exceeded(self):
        """Dentro del deadline, continúa reintentando."""
        policy = RetryPolicy(deadline_seconds=25)
        now = datetime(2026, 3, 4, 12, 0, 0)
        first_attempt = now - timedelta(seconds=10)  # 10s atrás, dentro de deadline

        vat = VatInfo(
            vat_clean="ESB12345678",
            country="ES",
            number="B12345678",
            status=VatStatus.TIMEOUT,
            auto_retry_count=0,
            attempts_hard=1,
            first_attempt_at=first_attempt,
        )

        decision = policy.apply_retry_decision(vat, now=now)

        assert decision.should_retry is True
        assert vat.next_retry_at is not None

    def test_auto_retry_count_incremented(self):
        """Cada retry incrementa auto_retry_count."""
        policy = RetryPolicy()
        now = datetime(2026, 3, 4, 12, 0, 0)

        vat = VatInfo(
            vat_clean="ESB12345678",
            country="ES",
            number="B12345678",
            status=VatStatus.TIMEOUT,
            auto_retry_count=0,
            attempts_hard=0,
            first_attempt_at=now,
        )

        assert vat.auto_retry_count == 0

        policy.apply_retry_decision(vat, now=now)
        assert vat.auto_retry_count == 1

        vat.status = VatStatus.ERROR
        policy.apply_retry_decision(vat, now=now)
        assert vat.auto_retry_count == 2

    def test_deterministic_jitter_with_seed(self):
        """Jitter es determinista con rng seeded."""
        rng1 = random.Random(123)
        policy1 = RetryPolicy(rng=rng1)

        rng2 = random.Random(123)
        policy2 = RetryPolicy(rng=rng2)

        now = datetime(2026, 3, 4, 12, 0, 0)

        vat1 = VatInfo(
            vat_clean="ESB12345678",
            country="ES",
            number="B12345678",
            status=VatStatus.THROTTLED,
            auto_retry_count=0,
            throttles=1,
            first_attempt_at=now,
        )

        vat2 = VatInfo(
            vat_clean="ESB12345678",
            country="ES",
            number="B12345678",
            status=VatStatus.THROTTLED,
            auto_retry_count=0,
            throttles=1,
            first_attempt_at=now,
        )

        policy1.apply_retry_decision(vat1, now=now)
        policy2.apply_retry_decision(vat2, now=now)

        # Mismo seed → mismo resultado
        assert vat1.next_retry_at == vat2.next_retry_at
