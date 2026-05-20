"""Tests for low-level binary reading behavior."""

import pytest

from arkparser.common.binary_reader import BinaryReader
from arkparser.common.exceptions import EndOfDataError


class TestBinaryReader:
    """Regression tests for primitive reads and truncation handling."""

    def test_truncated_int32_raises_end_of_data(self) -> None:
        reader = BinaryReader.from_bytes(b"\x01\x02")
        with pytest.raises(EndOfDataError):
            reader.read_int32()

    def test_truncated_float_raises_end_of_data(self) -> None:
        reader = BinaryReader.from_bytes(b"\x00\x00\x80")
        with pytest.raises(EndOfDataError):
            reader.read_float()

    def test_truncated_double_raises_end_of_data(self) -> None:
        reader = BinaryReader.from_bytes(b"\x00" * 7)
        with pytest.raises(EndOfDataError):
            reader.read_double()
