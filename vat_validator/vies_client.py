"""Cliente SOAP VIES para validación de números VAT europeos."""

import logging
import threading
import requests
from zeep import Client
from zeep.exceptions import Fault, TransportError
from zeep.transports import Transport

from .models import VatStatus
from .config import ViesConfig, DEFAULT_CONFIG

logger = logging.getLogger(__name__)


class ViesValidator:
    """Maneja llamadas de API SOAP VIES con pool de conexiones thread-local.
    
    Valida números VAT contra el servicio oficial de la Comisión Europea.
    Implementa connection pooling por hilo para reducir latencia y timeouts.
    """
    
    VIES_WSDL = "https://ec.europa.eu/taxation_customs/vies/checkVatService.wsdl"
    VIES_WEB = "https://ec.europa.eu/taxation_customs/vies/"
    
    def __init__(self, config: ViesConfig = None):
        """Inicializa validador con almacenamiento thread-local para clientes.
        
        Args:
            config: Configuración de timeouts y parámetros (usa DEFAULT_CONFIG si None)
        """
        self._thread_local = threading.local()
        self.config = config or DEFAULT_CONFIG
    
    def validate_vat(self, country_code: str, vat_number: str) -> dict:
        """Valida VAT con el servicio VIES.
        
        Args:
            country_code: Código de país de 2 letras (ej: "ES")
            vat_number: Número VAT sin prefijo de país
            
        Returns:
            Dict con claves:
                - status: VatStatus
                - vies_name: nombre de empresa (si es válido)
                - vies_address: dirección de empresa (si es válido)
                - error: mensaje de error (si aplica)
        """
        # Reutiliza conexión por hilo para reducir latencia y TIMEOUTs.
        try:
            client = getattr(self._thread_local, "vies_client", None)
            if client is None:
                session = requests.Session()
                # Timeout total = connection + read
                total_timeout = self.config.connection_timeout + self.config.read_timeout
                transport = Transport(
                    session=session,
                    timeout=total_timeout,
                    operation_timeout=total_timeout
                )
                client = Client(wsdl=self.VIES_WSDL, transport=transport)
                self._thread_local.vies_client = client
                
                if self.config.verbose_logging:
                    logger.info(
                        f"VIES client initialized: conn_timeout={self.config.connection_timeout}s, "
                        f"read_timeout={self.config.read_timeout}s, total={total_timeout}s"
                    )

            result = client.service.checkVat(countryCode=country_code, vatNumber=vat_number)

            if result.valid:
                if self.config.verbose_logging:
                    logger.debug(f"VAT {country_code}{vat_number}: VALID")
                return {
                    "status": VatStatus.VALID,
                    "vies_name": str(result.name or ""),
                    "vies_address": str(result.address or ""),
                    "error": "",
                }
            if self.config.verbose_logging:
                logger.debug(f"VAT {country_code}{vat_number}: INVALID")
            return {"status": VatStatus.INVALID, "vies_name": "", "vies_address": "", "error": ""}

        except Fault as e:
            msg = str(getattr(e, "message", "")) or str(e)
            detail = str(getattr(e, "detail", ""))
            if "MS_MAX_CONCURRENT_REQ" in msg or "MS_MAX_CONCURRENT_REQ" in detail:
                if self.config.verbose_logging:
                    logger.warning(f"VAT {country_code}{vat_number}: THROTTLED (MS_MAX_CONCURRENT_REQ)")
                return {"status": VatStatus.THROTTLED, "error": "MS_MAX_CONCURRENT_REQ"}
            if "SERVICE_UNAVAILABLE" in msg or "SERVICE_UNAVAILABLE" in detail:
                if self.config.verbose_logging:
                    logger.warning(f"VAT {country_code}{vat_number}: TIMEOUT (SERVICE_UNAVAILABLE)")
                return {"status": VatStatus.TIMEOUT, "error": "SERVICE_UNAVAILABLE"}
            if self.config.verbose_logging:
                logger.error(f"VAT {country_code}{vat_number}: SOAP Fault - {msg[:80]}")
            return {"status": VatStatus.ERROR, "error": f"SOAP Fault: {msg[:120]}"}

        except TransportError as e:
            # 5xx suele ser temporal
            try:
                status_code = e.status_code
            except Exception:
                status_code = None
            if status_code in {502, 503, 504}:
                if self.config.verbose_logging:
                    logger.warning(f"VAT {country_code}{vat_number}: TIMEOUT (HTTP {status_code})")
                return {"status": VatStatus.TIMEOUT, "error": f"HTTP {status_code}"}
            if self.config.verbose_logging:
                logger.warning(f"VAT {country_code}{vat_number}: TIMEOUT (TransportError)")
            return {"status": VatStatus.TIMEOUT, "error": "TransportError"}

        except (requests.exceptions.Timeout, requests.exceptions.ConnectTimeout):
            if self.config.verbose_logging:
                logger.warning(
                    f"VAT {country_code}{vat_number}: TIMEOUT "
                    f"(conn={self.config.connection_timeout}s, read={self.config.read_timeout}s)"
                )
            return {"status": VatStatus.TIMEOUT, "error": "TIMEOUT"}

        except requests.exceptions.RequestException as e:
            if self.config.verbose_logging:
                logger.error(f"VAT {country_code}{vat_number}: Request error - {str(e)[:80]}")
            return {"status": VatStatus.ERROR, "error": f"Request error: {str(e)[:120]}"}

        except Exception as e:
            if self.config.verbose_logging:
                logger.error(f"VAT {country_code}{vat_number}: Unexpected error - {str(e)[:80]}")
            return {"status": VatStatus.ERROR, "error": f"Unexpected: {str(e)[:120]}"}

        finally:
            # La sesión se mantiene viva por hilo; se cerrará al terminar el proceso.
            pass
