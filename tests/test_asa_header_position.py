"""Byte-level pin for ASA non-worldsave property header semantics.

ASA non-worldsave files (.arkprofile, .arktribe, cloud inventory) write
``[name_string][type_string][data_size:int32][position:int32]`` per property.
The second int32 is a *position* marker (per AsaPropertyRegistry.cs), NOT an
array index. Reading it as an array index leaks bogus indices into
``normalize_indexed_data`` and causes scalar fields like ``PlayerDataID`` to
surface as ``{position: value}`` dicts.

These tests fix the canonical bytes and assert:
- ``PropertyHeader.position`` carries the raw second int32 on ASA reads.
- ``PropertyHeader.index`` is 0 on ASA non-worldsave reads.
- ``PropertyHeader.index`` carries the raw second int32 on ASE reads (unchanged).
"""

from __future__ import annotations

from arkparser.common.binary_reader import BinaryReader
from arkparser.properties.base import read_property_header
from arkparser.properties.primitives import IntProperty


def _string_bytes(s: str) -> bytes:
    """ARK-style length-prefixed null-terminated string."""
    data = s.encode("latin-1") + b"\x00"
    return len(data).to_bytes(4, "little", signed=True) + data


def _i32_le(value: int) -> bytes:
    return value.to_bytes(4, "little", signed=True)


def _build_asa_header_blob(name: str, type_name: str, data_size: int, position: int) -> bytes:
    return (
        _string_bytes(name)
        + _string_bytes(type_name)
        + _i32_le(data_size)
        + _i32_le(position)
    )


def test_asa_header_stores_second_int32_as_position_not_index() -> None:
    blob = _build_asa_header_blob("PlayerDataID", "UInt64Property", data_size=8, position=8)
    reader = BinaryReader(blob)
    header = read_property_header(reader, is_asa=True)
    assert header is not None
    assert header.name == "PlayerDataID"
    assert header.type_name == "UInt64Property"
    assert header.data_size == 8
    assert header.position == 8, "ASA second int32 must land on .position"
    assert header.index == 0, "ASA must not leak position into .index"


def test_asa_header_position_zero_when_file_writes_zero() -> None:
    blob = _build_asa_header_blob("Score", "IntProperty", data_size=4, position=0)
    reader = BinaryReader(blob)
    header = read_property_header(reader, is_asa=True)
    assert header is not None
    assert header.position == 0
    assert header.index == 0


def test_ase_header_keeps_second_int32_as_index() -> None:
    """ASE files use the same physical layout but the second int32 is the
    array index. Make sure the ASE branch is unchanged."""
    blob = _build_asa_header_blob("Health", "FloatProperty", data_size=4, position=3)
    reader = BinaryReader(blob)
    header = read_property_header(reader, is_asa=False)
    assert header is not None
    assert header.index == 3, "ASE second int32 IS the array index"
    assert header.position == 0


def test_asa_simple_property_index_defaults_to_zero() -> None:
    """End-to-end: an ASA IntProperty whose header carries position=8 should
    produce a Property with index=0 (not 8). This is the regression that
    caused ``Profile.player_id`` to come back as ``{8: ...}``."""
    header_blob = _build_asa_header_blob("Health", "IntProperty", data_size=4, position=8)
    body_blob = bytes([0x00]) + _i32_le(42)  # extra_byte=0 (no arr_index), value=42
    reader = BinaryReader(header_blob + body_blob)
    header = read_property_header(reader, is_asa=True)
    assert header is not None
    prop = IntProperty.read(reader, header, is_asa=True)
    assert prop.value == 42
    assert prop.index == 0, "ASA Property.index must default to 0 when extra_byte bit 0 is clear"


def test_asa_simple_property_picks_up_real_array_index_from_extra_byte() -> None:
    """When extra_byte bit 0 IS set, the next int32 IS the real array slot."""
    header_blob = _build_asa_header_blob("Stat", "IntProperty", data_size=4, position=8)
    body_blob = bytes([0x01]) + _i32_le(5) + _i32_le(77)  # extra_byte=1, arr_idx=5, value=77
    reader = BinaryReader(header_blob + body_blob)
    header = read_property_header(reader, is_asa=True)
    assert header is not None
    prop = IntProperty.read(reader, header, is_asa=True)
    assert prop.value == 77
    assert prop.index == 5
