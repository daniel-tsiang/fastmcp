"""Tests for FastMCP settings validation."""

import pytest
from pydantic import ValidationError

from fastmcp.settings import Settings


class TestPortValidation:
    def test_invalid_port_negative(self):
        with pytest.raises(ValidationError):
            Settings(port=-1)

    def test_invalid_port_zero(self):
        with pytest.raises(ValidationError):
            Settings(port=0)

    def test_invalid_port_too_high(self):
        with pytest.raises(ValidationError):
            Settings(port=99999)

    def test_valid_port_accepted(self):
        assert Settings(port=8080).port == 8080

    def test_valid_port_min(self):
        assert Settings(port=1).port == 1

    def test_valid_port_max(self):
        assert Settings(port=65535).port == 65535
