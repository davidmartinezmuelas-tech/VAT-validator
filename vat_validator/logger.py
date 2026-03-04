"""Sistema de logging para VIES VAT Validator.

Proporciona funcionalidad de logging con niveles múltiples (INFO, WARNING, ERROR, DEBUG)
escritura en archivo y console output.
"""

import logging
from pathlib import Path
from typing import Optional


class VatValidatorLogger:
    """Logger centralizado para la validación de VAT."""
    
    def __init__(self, log_dir: Optional[Path] = None):
        """Inicializa el sistema de logging.
        
        Args:
            log_dir: Directorio para guardar logs. Si es None, usa logs/ relativo.
        """
        if log_dir is None:
            log_dir = Path(__file__).parent.parent / "logs"
        
        log_dir.mkdir(parents=True, exist_ok=True)
        
        self.log_file = log_dir / "validation.log"
        self.logger = logging.getLogger("vat_validator")
        
        # Configura logger si no está ya configurado
        if not self.logger.handlers:
            self.logger.setLevel(logging.DEBUG)
            
            # Handler para archivo
            file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            
            # Handler para console
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # Formato
            formatter = logging.Formatter(
                "[%(asctime)s] %(levelname)-8s %(message)s",
                datefmt="%H:%M:%S"
            )
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)
    
    def info(self, message: str) -> None:
        """Registra mensaje de información."""
        self.logger.info(message)
    
    def warning(self, message: str) -> None:
        """Registra mensaje de advertencia."""
        self.logger.warning(message)
    
    def error(self, message: str) -> None:
        """Registra mensaje de error."""
        self.logger.error(message)
    
    def debug(self, message: str) -> None:
        """Registra mensaje de depuración."""
        self.logger.debug(message)
    
    def critical(self, message: str) -> None:
        """Registra mensaje crítico."""
        self.logger.critical(message)


# Instancia global por comodidad
_logger: Optional[VatValidatorLogger] = None


def get_logger() -> VatValidatorLogger:
    """Obtiene la instancia global de logger."""
    global _logger
    if _logger is None:
        _logger = VatValidatorLogger()
    return _logger


def init_logger(log_dir: Optional[Path] = None) -> VatValidatorLogger:
    """Inicializa el logger global.
    
    Args:
        log_dir: Directorio para guardar logs
        
    Returns:
        Instancia del logger
    """
    global _logger
    _logger = VatValidatorLogger(log_dir)
    return _logger
