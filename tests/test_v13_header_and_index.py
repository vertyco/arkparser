"""Regression tests for ASA v13 worldsave header and property array indices.

Two v13 defects, both verified against the public v13 sample saves shipped
with miragedmuk/AsaSavegameToolkit (tests/assets/version_13):

1. The SaveHeader name table lives at the absolute offset in the int32 right
   after the int16 version (C# ``SaveHeaderRecord.ReadPre14`` seeks there).
   A sequential read lands in the extra tables between the data files and
   the name table, so every v13 save failed with "implausible count".
2. The v13 legacy property tag is ``Size(4) + ArrayIndex(4) +
   HasPropertyGuid(1)`` (C# ``PropertyTag.ReadPre14``). The ArrayIndex was
   discarded, collapsing every static-array property (CurrentStatusValues,
   NumberOfLevelUpPointsApplied, ColorSetIndices, ...) onto index 0.
"""

from __future__ import annotations

import sqlite3
import struct
from pathlib import Path

from arkparser import WorldSave
from arkparser.common.binary_reader import BinaryReader
from arkparser.properties.base import PropertyHeader
from arkparser.properties.byte_property import ByteProperty
from arkparser.properties.compound import ArrayProperty, StructProperty
from arkparser.properties.primitives import BoolProperty, FloatProperty, IntProperty

_HASH_NONE = 162342434  # "None"
_HASH_INT = -201674127  # IntProperty


def _i16(value: int) -> bytes:
    return value.to_bytes(2, "little", signed=True)


def _i32(value: int) -> bytes:
    return value.to_bytes(4, "little", signed=True)


def _f64(value: float) -> bytes:
    return struct.pack("<d", value)


def _fstring(text: str) -> bytes:
    raw = text.encode("ascii") + b"\x00"
    return _i32(len(raw)) + raw


def _header(type_name: str) -> PropertyHeader:
    return PropertyHeader(name="x", type_name=type_name, data_size=0, index=0)


# =============================================================================
# SaveHeader: v13 name table is found by seeking, not by sequential read
# =============================================================================


def _v13_save_header(names: dict[int, str], gap: bytes) -> bytes:
    """Build a v13 SaveHeader blob with ``gap`` bytes before the name table."""
    body = _f64(1234.5)  # game_time
    body += _i32(582)  # version > 11 extra int32
    body += _i32(1) + _fstring("TheCenter_WP") + _i32(-1)  # data files
    body += gap  # extra v13 tables the sequential reader tripped over
    prefix_len = 2 + 4  # int16 version + int32 name-table offset
    offset = prefix_len + len(body)
    table = _i32(len(names))
    for key, value in names.items():
        table += _i32(key) + _fstring(value)
    return _i16(13) + _i32(offset) + body + table


def _write_asa_db(path: Path, save_header: bytes) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE custom (key TEXT PRIMARY KEY, value BLOB)")
        conn.execute("CREATE TABLE game (key BLOB PRIMARY KEY, value BLOB)")
        conn.execute("INSERT INTO custom VALUES ('SaveHeader', ?)", (save_header,))
        conn.commit()
    finally:
        conn.close()


def test_v13_save_header_seeks_to_name_table(tmp_path: Path) -> None:
    names = {_HASH_NONE: "None", 77: "/Game/Foo/Bar.Bar_C"}
    # The gap starts with a huge int32 so a sequential read would raise.
    gap = _i32(0x49646E41) + bytes(40)
    path = tmp_path / "TheCenter_WP.ark"
    _write_asa_db(path, _v13_save_header(names, gap))

    save = WorldSave.load(path)

    assert save.version == 13
    assert save.game_time == 1234.5
    assert save.data_files == ["TheCenter_WP"]
    assert save.name_table == {_HASH_NONE: "None", 77: "Bar_C"}


def test_v13_save_header_without_gap(tmp_path: Path) -> None:
    names = {_HASH_NONE: "None"}
    path = tmp_path / "Extinction_WP.ark"
    _write_asa_db(path, _v13_save_header(names, b""))

    save = WorldSave.load(path)

    assert save.name_table == {_HASH_NONE: "None"}


# =============================================================================
# Property tags: v13 ArrayIndex becomes Property.index
# =============================================================================


def test_v13_int_property_keeps_array_index() -> None:
    # Size(4) + ArrayIndex(4) + HasPropertyGuid(1) + value(4)
    blob = _i32(4) + _i32(3) + b"\x00" + _i32(-7)
    r = BinaryReader(blob, save_version=13)
    prop = IntProperty.read(r, _header("IntProperty"), worldsave_format=True, name_table={})
    assert prop.index == 3
    assert prop.value == -7
    assert r.position == len(blob)


def test_v13_float_property_skips_property_guid() -> None:
    # HasPropertyGuid != 0 -> a 16-byte GUID precedes the value.
    blob = _i32(4) + _i32(5) + b"\x01" + bytes(range(16)) + bytes.fromhex("0000803f")
    r = BinaryReader(blob, save_version=13)
    prop = FloatProperty.read(r, _header("FloatProperty"), worldsave_format=True, name_table={})
    assert prop.index == 5
    assert prop.value == 1.0
    assert r.position == len(blob)


def test_v13_bool_property_keeps_array_index() -> None:
    blob = _i32(0) + _i32(2) + b"\x01\x00"
    r = BinaryReader(blob, save_version=13)
    prop = BoolProperty.read(r, _header("BoolProperty"), worldsave_format=True, name_table={})
    assert prop.index == 2
    assert prop.value is True
    assert r.position == 10


def test_v13_raw_byte_property_keeps_array_index() -> None:
    # ColorSetIndices-style raw byte at slot 4.
    blob = _i32(1) + _i32(4) + _i32(_HASH_NONE) + _i32(0) + b"\x00" + b"\x2a"
    r = BinaryReader(blob, save_version=13)
    prop = ByteProperty.read(
        r, _header("ByteProperty"), worldsave_format=True, name_table={_HASH_NONE: "None"}
    )
    assert prop.index == 4
    assert prop.byte_value == 42
    assert r.position == len(blob)


def test_v13_array_property_keeps_array_index() -> None:
    blob = (
        _i32(8)  # dataSize = count(4) + 1 int
        + _i32(1)  # ArrayIndex
        + _i32(_HASH_INT)
        + _i32(0)
        + b"\x00"
        + _i32(1)  # arrayLength
        + _i32(99)
    )
    r = BinaryReader(blob, save_version=13)
    prop = ArrayProperty.read(
        r, _header("ArrayProperty"), worldsave_format=True, name_table={_HASH_INT: "IntProperty"}
    )
    assert prop.index == 1
    assert prop.value == [99]


def test_v13_struct_property_keeps_array_index() -> None:
    struct_hash = 4242
    blob = (
        _i32(8)  # dataSize: the 'None' terminator name ref
        + _i32(2)  # ArrayIndex
        + _i32(struct_hash)
        + _i32(0)
        + b"\x00"
        + bytes(16)
        + _i32(_HASH_NONE)
        + _i32(0)
    )
    nt = {_HASH_NONE: "None", struct_hash: "CustomStruct"}
    r = BinaryReader(blob, save_version=13)
    prop = StructProperty.read(r, _header("StructProperty"), worldsave_format=True, name_table=nt)
    assert prop.index == 2
    assert prop.struct_type == "CustomStruct"
    assert r.position == len(blob)


def test_v14_int_property_index_unchanged() -> None:
    # v14: padding(4) + size(4) + flag(1) [+ index(4) if flag & 1] + value.
    blob = _i32(0) + _i32(4) + b"\x01" + _i32(6) + _i32(11)
    r = BinaryReader(blob, save_version=14)
    prop = IntProperty.read(r, _header("IntProperty"), worldsave_format=True, name_table={})
    assert prop.index == 6
    assert prop.value == 11
    assert r.position == len(blob)
