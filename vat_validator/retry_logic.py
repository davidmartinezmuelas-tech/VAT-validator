"""Lógica de reintento y scheduling para validación concurrente de VAT.

Implementa un planificador con workers concurrentes, throttling y circuit breaker por país.
La política de retry (backoff/jitter/deadlines) se delega a RetryPolicy.
"""

import logging
import time
import threading
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from .models import VatInfo, CountryNumber, VatStatus, VALIDATED_STATES
from .vies_client import ViesValidator
from .callbacks import ValidationCallbacks, BatchSummary
from .retry_policy import RetryPolicy
from .config import ViesConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class RetryScheduler:
    """Gestiona validación concurrente con throttling y circuit breaker por país.
    
    Coordina múltiples workers que validan VATs de forma paralela, respetando
    límites de concurrencia por país y throttling global entre requests.
    """
    
    def __init__(
        self,
        vat_data: Dict[CountryNumber, VatInfo],
        callbacks: ValidationCallbacks,
        stop_event: threading.Event,
        config: ViesConfig = None,
    ):
        """Inicializa el planificador.
        
        Args:
            vat_data: Diccionario de datos VAT a validar
            callbacks: Interface de callbacks para notificaciones worker → UI
            stop_event: Evento de threading para señal de parada
            config: Configuración de VIES (usa DEFAULT_CONFIG si None)
        """
        self.vat_data = vat_data
        self.callbacks = callbacks
        self.stop_event = stop_event
        self.config = config or DEFAULT_CONFIG
        
        self.validator = ViesValidator(config=self.config)
        self.retry_policy = RetryPolicy(config=self.config)
        
        # Concurrencia / throttle
        self._active_countries: set[str] = set()
        self._active_countries_lock = threading.Lock()
        self._throttle_lock = threading.Lock()
        self._last_request_time = 0.0
        
        # Rate limiter: sliding window de timestamps
        self._request_timestamps: deque = deque()  # timestamps de últimas N requests
        self._rate_limit_lock = threading.Lock()
        
        # Cooldown por país (mini circuit-breaker)
        self._country_cooldown_until: Dict[str, float] = {}
        
        if self.config.verbose_logging:
            logger.info(
                f"RetryScheduler initialized: max_workers={self.config.max_workers}, "
                f"max_rps={self.config.max_requests_per_second}, throttle_ms={self.config.throttle_ms}, "
                f"max_auto_retries={self.config.max_auto_retries}, deadline={self.config.deadline_seconds}s"
            )
    
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
                    # Rate limiter: máximo N requests por segundo (sliding window)
                    self._enforce_rate_limit()
                    
                    # Throttle global: separación mínima entre requests
                    with self._throttle_lock:
                        elapsed = time.time() - self._last_request_time
                        wait = (self.config.throttle_ms / 1000.0) - elapsed
                        if wait > 0:
                            if self.config.verbose_logging:
                                logger.debug(f"Throttle: waiting {wait*1000:.0f}ms")
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
                    prev_status = info.status  # Guardar para undo en UI
                    status = result.get("status")
                    info.status = status
                    
                    if status == VatStatus.THROTTLED:
                        info.throttles += 1
                        info.last_error = result.get("error", "MS_MAX_CONCURRENT_REQ")
                        self._country_cooldown_until[info.country] = time.time() + 2.0
                    elif status in {VatStatus.TIMEOUT, VatStatus.ERROR}:
                        info.attempts_hard += 1
                        info.last_error = result.get("error", "")
                    elif status == VatStatus.VALID:
                        # Campos de negocio de respuesta VIES (core los actualiza)
                        info.last_error = ""
                    elif status == VatStatus.INVALID:
                        info.last_error = ""
                    
                    # Aplicar política de retry (única fuente de verdad)
                    decision = self.retry_policy.apply_retry_decision(info)
                    
                    # Pasar prev_status a UI para undo stack
                    result["_prev_status"] = prev_status
                    
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
        num_workers = min(self.config.max_workers, max(1, total))
        if self.config.verbose_logging:
            logger.info(f"Starting {num_workers} worker threads for {total} VATs")
        
        for _ in range(num_workers):
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
    
    def _enforce_rate_limit(self) -> None:
        """Implementa rate limiting usando sliding window.
        
        Limita a max_requests_per_second requests por segundo.
        Bloquea el hilo actual si se excede el límite.
        """
        if self.config.max_requests_per_second <= 0:
            return  # Rate limiting desactivado
        
        with self._rate_limit_lock:
            now = time.time()
            window = 1.0  # ventana de 1 segundo
            
            # Eliminar timestamps fuera de la ventana
            while self._request_timestamps and (now - self._request_timestamps[0]) > window:
                self._request_timestamps.popleft()
            
            # Verificar si excedemos el límite
            if len(self._request_timestamps) >= self.config.max_requests_per_second:
                # Calcular cuánto esperar
                oldest = self._request_timestamps[0]
                wait_time = window - (now - oldest) + 0.01  # +10ms de margen
                
                if wait_time > 0:
                    if self.config.verbose_logging:
                        logger.debug(
                            f"Rate limit: {len(self._request_timestamps)} requests en ventana, "
                            f"esperando {wait_time*1000:.0f}ms"
                        )
                    time.sleep(wait_time)
                    now = time.time()
                    
                    # Re-limpiar ventana después de esperar
                    while self._request_timestamps and (now - self._request_timestamps[0]) > window:
                        self._request_timestamps.popleft()
            
            # Registrar esta request
            self._request_timestamps.append(now)
