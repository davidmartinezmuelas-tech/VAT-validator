"""VIES validation logic and SOAP client management."""

import threading
import requests
from zeep import Client
from zeep.exceptions import Fault, TransportError
from zeep.transports import Transport

from .models import VatStatus


class ViesValidator:
    """Handles VIES SOAP API calls with thread-local connection pooling."""
    
    VIES_WSDL = "https://ec.europa.eu/taxation_customs/vies/checkVatService.wsdl"
    VIES_WEB = "https://ec.europa.eu/taxation_customs/vies/"
    TIMEOUT = 10
    
    def __init__(self):
        """Initialize validator with thread-local storage for clients."""
        self._thread_local = threading.local()
    
    def validate_vat(self, country_code: str, vat_number: str) -> dict:
        """Validate VAT with VIES service.
        
        Args:
            country_code: 2-letter country code (e.g., "ES")
            vat_number: VAT number without country prefix
            
        Returns:
            Dict with keys:
                - status: VatStatus
                - vies_name: company name (if valid)
                - vies_address: company address (if valid)
                - error: error message (if applicable)
        """
        # Reutilizamos conexión por hilo para reducir latencia y TIMEOUTs.
        try:
            client = getattr(self._thread_local, "vies_client", None)
            if client is None:
                session = requests.Session()
                transport = Transport(session=session, timeout=self.TIMEOUT, operation_timeout=self.TIMEOUT)
                client = Client(wsdl=self.VIES_WSDL, transport=transport)
                self._thread_local.vies_client = client

            result = client.service.checkVat(countryCode=country_code, vatNumber=vat_number)

            if result.valid:
                return {
                    "status": VatStatus.VALID,
                    "vies_name": str(result.name or ""),
                    "vies_address": str(result.address or ""),
                    "error": "",
                }
            return {"status": VatStatus.INVALID, "vies_name": "", "vies_address": "", "error": ""}

        except Fault as e:
            msg = str(getattr(e, "message", "")) or str(e)
            detail = str(getattr(e, "detail", ""))
            if "MS_MAX_CONCURRENT_REQ" in msg or "MS_MAX_CONCURRENT_REQ" in detail:
                return {"status": VatStatus.THROTTLED, "error": "MS_MAX_CONCURRENT_REQ"}
            if "SERVICE_UNAVAILABLE" in msg or "SERVICE_UNAVAILABLE" in detail:
                return {"status": VatStatus.TIMEOUT, "error": "SERVICE_UNAVAILABLE"}
            return {"status": VatStatus.ERROR, "error": f"SOAP Fault: {msg[:120]}"}

        except TransportError as e:
            # 5xx suele ser temporal
            try:
                status_code = e.status_code
            except Exception:
                status_code = None
            if status_code in {502, 503, 504}:
                return {"status": VatStatus.TIMEOUT, "error": f"HTTP {status_code}"}
            return {"status": VatStatus.TIMEOUT, "error": "TransportError"}

        except (requests.exceptions.Timeout, requests.exceptions.ConnectTimeout):
            return {"status": VatStatus.TIMEOUT, "error": "TIMEOUT"}

        except requests.exceptions.RequestException as e:
            return {"status": VatStatus.ERROR, "error": f"Request error: {str(e)[:120]}"}

        except Exception as e:
            return {"status": VatStatus.ERROR, "error": f"Unexpected: {str(e)[:120]}"}

        finally:
            # La sesión se mantiene viva por hilo; se cerrará al terminar el proceso.
            pass
