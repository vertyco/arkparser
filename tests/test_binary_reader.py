"""Tests for low-level binary reading behavior."""

import random
import uuid

import pytest

from arkparser.common.binary_reader import BinaryReader, guid_str_le
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


class TestGuidStrLe:
    """guid_str_le must match str(uuid.UUID(bytes_le=...)) byte-for-byte."""

    def test_matches_uuid_module(self) -> None:
        rng = random.Random(1234)
        for _ in range(1000):
            raw = rng.randbytes(16)
            assert guid_str_le(raw) == str(uuid.UUID(bytes_le=raw))

    def test_known_value(self) -> None:
        raw = bytes(range(16))
        assert guid_str_le(raw) == str(uuid.UUID(bytes_le=raw))
        assert guid_str_le(b"\x00" * 16) == "00000000-0000-0000-0000-000000000000"
