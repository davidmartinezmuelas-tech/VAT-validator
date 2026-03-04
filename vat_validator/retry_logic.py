"""Lógica de reintento y scheduling para validación concurrente de VAT.

Implementa un planificador con workers concurrentes, throttling y circuit breaker por país.
La política de retry (backoff/jitter/deadlines) se delega a RetryPolicy.
"""

import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .models import VatInfo, CountryNumber, VatStatus, VALIDATED_STATES
from .vies_client import ViesValidator
from .callbacks import ValidationCallbacks, BatchSummary
from .retry_policy import RetryPolicy


class RetryScheduler:
    """Gestiona validación concurrente con throttling y circuit breaker por país.
    
    Coordina múltiples workers que validan VATs de forma paralela, respetando
    límites de concurrencia por país y throttling global entre requests.
    """
    
    MAX_WORKERS = 3
    THROTTLE_MS = 250  # separación mínima entre requests
    
    def __init__(self, vat_data: Dict[CountryNumber, VatInfo], callbacks: ValidationCallbacks, stop_event: threading.Event):
        """Inicializa el planificador.
        
        Args:
            vat_data: Diccionario de datos VAT a validar
            callbacks: Interface de callbacks para notificaciones worker → UI
            stop_event: Evento de threading para señal de parada
        """
        self.vat_data = vat_data
        self.callbacks = callbacks
        self.stop_event = stop_event
        
        self.validator = ViesValidator()
        self.retry_policy = RetryPolicy(
            max_auto_retries=2,
            max_hard_attempts=3,
            deadline_seconds=25,
        )
        
        # Concurrencia / throttle
        self._active_countries: set[str] = set()
        self._active_countries_lock = threading.Lock()
        self._throttle_lock = threading.Lock()
        self._last_request_time = 0.0
        
        # Cooldown por país (mini circuit-breaker)
        self._country_cooldown_until: Dict[str, float] = {}
    
    def validate_batch(self, items: List[Tuple[CountryNumber, VatInfo]]) -> None:
        """Ejecuta validación para un lote de items VAT.
        
        Crea workers que procesan items en paralelo, respetando límites de concurrencia
        y throttling. Continúa hasta que todos los items alcanzan estado terminal
        o el usuario detiene la validación.
        
        Args:
            items: Lista de tuplas (key, VatInfo) a validar
        """
        total = len(items)
        completed = 0
        completed_lock = threading.Lock()
        
        # Keys que alcanzaron estado terminal en esta ejecución
        finished: set[CountryNumber] = set()
        
        # Queue scheduler: (ready_time, counter, key)
        pending: List[Tuple[float, int, CountryNumber]] = []
        seq = 0
        seq_lock = threading.Lock()
        
        def next_seq() -> int:
            nonlocal seq
            with seq_lock:
                seq += 1
                return seq
        
        now = time.time()
        for k, _info in items:
            pending.append((now, next_seq(), k))
        
        pending.sort(key=lambda x: (x[0], x[1]))
        
        def pop_ready() -> Optional[CountryNumber]:
            nonlocal pending
            if not pending:
                return None
            # encuentra primer item listo + país disponible
            current = time.time()
            scan = min(len(pending), 60)  # evita que los primeros bloqueen a otros países
            for idx, (ready, _c, key) in enumerate(pending[:scan]):
                info = self.vat_data.get(key)
                if not info:
                    pending.pop(idx)
                    return None
                if ready > current:
                    continue
                
                # cooldown por país (mini circuit breaker)
                cd_until = self._country_cooldown_until.get(info.country)
                if cd_until and cd_until > current:
                    continue
                
                with self._active_countries_lock:
                    if info.country in self._active_countries:
                        continue
                    self._active_countries.add(info.country)
                # remove
                pending.pop(idx)
                return key
            return None
        
        def mark_country_done(country: str) -> None:
            with self._active_countries_lock:
                self._active_countries.discard(country)
        
        def worker_loop():
            nonlocal completed
            while not self.stop_event.is_set():
                key = pop_ready()
                if key is None:
                    if not pending:
                        break
                    time.sleep(0.05)
                    continue
                
                info = self.vat_data.get(key)
                if not info:
                    mark_country_done(key[0])
                    continue
                
                try:
                    # Throttle global
                    with self._throttle_lock:
                        elapsed = time.time() - self._last_request_time
                        wait = (self.THROTTLE_MS / 1000.0) - elapsed
                        if wait > 0:
                            time.sleep(wait)
                        self._last_request_time = time.time()
                    
                    # Marca como VALIDATING
                    info.status = VatStatus.VALIDATING
                    
                    # Track first attempt
                    if info.first_attempt_at is None:
                        info.first_attempt_at = datetime.now()
                    
                    # Validate
                    result = self.validator.validate_vat(info.country, info.number)
                    
                    # Process result - actualizar status y contadores
                    status = result.get("status")
                    info.status = status
                    
                    if status == VatStatus.THROTTLED:
                        info.throttles += 1
                        info.last_error = result.get("error", "MS_MAX_CONCURRENT_REQ")
                        self._country_cooldown_until[info.country] = time.time() + 2.0
                    elif status in {VatStatus.TIMEOUT, VatStatus.ERROR}:
                        info.attempts_hard += 1
                        info.last_error = result.get("error", "")
                    
                    # Aplicar política de retry (única fuente de verdad)
                    decision = self.retry_policy.apply_retry_decision(info)
                    
                    # Procesar decisión
                    if status in {VatStatus.VALID, VatStatus.INVALID}:
                        # Estados terminales: finalizar
                        finished.add(key)
                    elif decision.should_retry and info.next_retry_at:
                        # Re-encolar con timestamp calculado por policy
                        next_ready = info.next_retry_at.timestamp()
                        pending.append((next_ready, next_seq(), key))
                        pending.sort(key=lambda x: (x[0], x[1]))
                    else:
                        # No se reintenta: finalizar (puede ser PENDING_MAX)
                        finished.add(key)
                    
                    # Notificar a UI
                    self.callbacks.on_vat_updated(key, info, result)
                    with completed_lock:
                        completed_local = completed + 1
                        completed = completed_local
                    self.callbacks.on_progress(completed_local, total)
                    mark_country_done(info.country)
                
                finally:
                    pass
        
        # Start workers
        threads = []
        for _ in range(min(self.MAX_WORKERS, max(1, total))):
            t = threading.Thread(target=worker_loop, daemon=True)
            t.start()
            threads.append(t)
        
        for t in threads:
            t.join()

        valid = sum(1 for v in self.vat_data.values() if v.status == VatStatus.VALID)
        invalid = sum(1 for v in self.vat_data.values() if v.status == VatStatus.INVALID)
        pending = sum(1 for v in self.vat_data.values() if v.status not in VALIDATED_STATES)
        self.callbacks.on_banner_update("", None)
        self.callbacks.on_batch_finished(
            BatchSummary(done=completed, total=total, valid=valid, invalid=invalid, pending=pending)
        )
