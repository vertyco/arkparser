"""Byte-level tests for BinaryReader additions (save_version, int32 pair)."""

from __future__ import annotations

from arkparser.common.binary_reader import BinaryReader


def test_save_version_defaults_to_zero() -> None:
    r = BinaryReader(b"\x00" * 4)
    assert r.save_version == 0


def test_save_version_preserved() -> None:
    r = BinaryReader(b"\x00" * 4, save_version=13)
    assert r.save_version == 13


def test_save_version_passes_through_memoryview_input() -> None:
    r = BinaryReader(memoryview(b"\x00" * 4), save_version=14)
    assert r.save_version == 14
    # memoryview input is materialized to bytes
    assert isinstance(r._buf, bytes)


def test_read_int32_pair_two_values() -> None:
    # <ii unpack: 0x00000001, 0x00000002
    r = BinaryReader(bytes.fromhex("01000000 02000000".replace(" ", "")))
    a, b = r.read_int32_pair()
    assert a == 1
    assert b == 2
    assert r.position == 8


def test_read_int32_pair_negative() -> None:
    # -1, -2 in little-endian signed int32
    r = BinaryReader(bytes.fromhex("ffffffff feffffff"))
    a, b = r.read_int32_pair()
    assert a == -1
    assert b == -2


def test_read_int32_pair_advances_eight_bytes() -> None:
    r = BinaryReader(b"\x00" * 16)
    r.read_int32_pair()
    r.read_int32_pair()
    assert r.position == 16


def test_from_bytes_factory_accepts_memoryview() -> None:
    mv = memoryview(b"\x01\x02\x03\x04")
    r = BinaryReader.from_bytes(mv)
    assert r.read_uint8() == 1
