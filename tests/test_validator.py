"""Tests unitarios para módulos de validación VAT.

Proporciona tests básicos con pytest para las funciones de normalización,
parseo, validación de formato y mocking de VIES.
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from vat_validator.models import (
    VatStatus,
    VatInfo,
    normalize_vat,
    parse_vat,
    get_vat_number_only,
    status_label,
    status_code,
)
from vat_validator.validator import (
    normalize_vat_format,
    parse_vat_number,
    validate_vat_format,
    check_vat_format,
)
from vat_validator.vies_client import ViesValidator


class TestNormalizeVat:
    """Tests para función normalize_vat."""
    
    def test_normalize_vat_basic(self):
        """Test normalización básica."""
        result = normalize_vat("ES12345678A")
        assert result == "ES12345678A"
    
    def test_normalize_vat_lowercase(self):
        """Test conversión a mayúsculas."""
        result = normalize_vat("es12345678a")
        assert result == "ES12345678A"
    
    def test_normalize_vat_with_spaces(self):
        """Test eliminación de espacios."""
        result = normalize_vat("ES 1234 5678 A")
        assert result == "ES12345678A"
    
    def test_normalize_vat_with_hyphens(self):
        """Test eliminación de guiones."""
        result = normalize_vat("ES-1234-5678-A")
        assert result == "ES12345678A"
    
    def test_normalize_vat_none(self):
        """Test valor None."""
        result = normalize_vat(None)
        assert result is None
    
    def test_normalize_vat_empty_string(self):
        """Test string vacío."""
        result = normalize_vat("")
        assert result is None


class TestParseVat:
    """Tests para función parse_vat."""
    
    def test_parse_vat_valid(self):
        """Test parseo válido."""
        country, number, clean = parse_vat("ES12345678A")
        assert country == "ES"
        assert number == "12345678A"
        assert clean == "ES12345678A"
    
    def test_parse_vat_different_country(self):
        """Test con país diferente."""
        country, number, clean = parse_vat("FR98765432")
        assert country == "FR"
        assert number == "98765432"
        assert clean == "FR98765432"
    
    def test_parse_vat_invalid_format(self):
        """Test formato inválido (no empieza con 2 letras)."""
        country, number, clean = parse_vat("INVALID123")
        assert country is None
        assert number is None
        assert clean == "INVALID123"
    
    def test_parse_vat_too_short(self):
        """Test VAT muy corto."""
        country, number, clean = parse_vat("ES")
        assert country is None
        assert number is None
        assert clean == "ES"


class TestValidateVatFormat:
    """Tests para función validate_vat_format."""
    
    def test_validate_vat_format_valid(self):
        """Test formato válido."""
        result = validate_vat_format("ES12345678A")
        assert result is True
    
    def test_validate_vat_format_invalid_country(self):
        """Test código país inválido (números)."""
        result = validate_vat_format("1212345678A")
        assert result is False
    
    def test_validate_vat_format_no_number(self):
        """Test sin número."""
        result = validate_vat_format("ES")
        assert result is False
    
    def test_validate_vat_format_none(self):
        """Test None."""
        result = validate_vat_format(None)
        assert result is False
    
    def test_validate_vat_format_empty(self):
        """Test vacío."""
        result = validate_vat_format("")
        assert result is False


class TestCheckVatFormat:
    """Tests para función check_vat_format."""
    
    def test_check_vat_format_valid(self):
        """Test país y número válidos."""
        result = check_vat_format("ES", "12345678A")
        assert result is True
    
    def test_check_vat_format_no_country(self):
        """Test sin país."""
        result = check_vat_format(None, "12345678A")
        assert result is False
    
    def test_check_vat_format_no_number(self):
        """Test sin número."""
        result = check_vat_format("ES", None)
        assert result is False
    
    def test_check_vat_format_invalid_country_length(self):
        """Test país con longitud incorrecta."""
        result = check_vat_format("ESPANA", "12345678A")
        assert result is False


class TestStatusFunctions:
    """Tests para funciones de estado."""
    
    def test_status_label_valid(self):
        """Test etiqueta para estado VALID."""
        label = status_label(VatStatus.VALID)
        assert "Válido" in label
        assert "✓" in label
    
    def test_status_label_invalid(self):
        """Test etiqueta para estado INVALID."""
        label = status_label(VatStatus.INVALID)
        assert "Inválido" in label
    
    def test_status_code_valid(self):
        """Test código para estado VALID."""
        code = status_code(VatStatus.VALID)
        assert code == "VALID"
    
    def test_status_code_throttled(self):
        """Test código para estado THROTTLED."""
        code = status_code(VatStatus.THROTTLED)
        assert code == "THROTTLED"


class TestGetVatNumberOnly:
    """Tests para función get_vat_number_only."""
    
    def test_get_vat_number_only_valid(self):
        """Test extracción de número."""
        number = get_vat_number_only("ES12345678A")
        assert number == "12345678A"
    
    def test_get_vat_number_only_invalid_format(self):
        """Test con formato inválido."""
        number = get_vat_number_only("INVALID123")
        assert number == "INVALID123"
    
    def test_get_vat_number_only_none(self):
        """Test con None."""
        number = get_vat_number_only(None)
        assert number == ""


class TestVatInfo:
    """Tests para clase VatInfo."""
    
    def test_vat_info_creation(self):
        """Test creación de VatInfo."""
        info = VatInfo(
            vat_clean="ES12345678A",
            country="ES",
            number="12345678A",
            nombre_excel="Empresa Test"
        )
        assert info.vat_clean == "ES12345678A"
        assert info.status == VatStatus.NEW
        assert info.is_terminal() is False
    
    def test_vat_info_is_terminal(self):
        """Test método is_terminal."""
        info = VatInfo(
            vat_clean="ES12345678A",
            country="ES",
            number="12345678A",
            status=VatStatus.VALID
        )
        assert info.is_terminal() is True
    
    def test_vat_info_is_retryable(self):
        """Test método is_retryable."""
        info = VatInfo(
            vat_clean="ES12345678A",
            country="ES",
            number="12345678A",
            status=VatStatus.THROTTLED
        )
        assert info.is_retryable() is True


class TestViesValidator:
    """Tests para ViesValidator con mocks."""
    
    @patch('vat_validator.vies_client.Client')
    def test_validate_vat_valid(self, mock_client_class):
        """Test validación exitosa."""
        # Setup mock
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_result = Mock()
        mock_result.valid = True
        mock_result.name = "Test Company"
        mock_result.address = "Test Address"
        mock_client.service.checkVat.return_value = mock_result
        
        # Test
        validator = ViesValidator()
        result = validator.validate_vat("ES", "12345678A")
        
        assert result["status"] == VatStatus.VALID
        assert result["vies_name"] == "Test Company"
        assert result["vies_address"] == "Test Address"
    
    @patch('vat_validator.vies_client.Client')
    def test_validate_vat_invalid(self, mock_client_class):
        """Test VAT inválido."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        mock_result = Mock()
        mock_result.valid = False
        mock_client.service.checkVat.return_value = mock_result
        
        validator = ViesValidator()
        result = validator.validate_vat("ES", "00000000Z")
        
        assert result["status"] == VatStatus.INVALID
        assert result["vies_name"] == ""
        assert result["vies_address"] == ""
    
    @patch('vat_validator.vies_client.Client')
    def test_validate_vat_throttled(self, mock_client_class):
        """Test limitación de concurrencia."""
        from zeep.exceptions import Fault
        
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Simula Fault con MS_MAX_CONCURRENT_REQ
        fault = Fault("MS_MAX_CONCURRENT_REQ", Mock())
        mock_client.service.checkVat.side_effect = fault
        
        validator = ViesValidator()
        result = validator.validate_vat("ES", "12345678A")
        
        assert result["status"] == VatStatus.THROTTLED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
