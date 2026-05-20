"""Byte-level tests pinning ASA v13 vs v14 worldsave property layouts.

V13 saves (e.g. TheIsland_WP) use the legacy AsaSavegameToolkit body shape:
dataSize + position + typeRef + byte + value-specific. V14+ saves use a
different marker-based layout. These tests fix the canonical byte sequences
so regressions in either branch surface immediately.
"""

from __future__ import annotations

from arkparser.common.binary_reader import BinaryReader
from arkparser.properties.base import PropertyHeader
from arkparser.properties.byte_property import ByteProperty
from arkparser.properties.compound import ArrayProperty, MapProperty, StructProperty
from arkparser.properties.primitives import BoolProperty

# Canonical name-table hashes observed in real v13/v14 saves.
_HASH_NONE = 162342434  # "None"
_HASH_BOOL = 1300375210  # BoolProperty
_HASH_STRUCT = -89864592  # StructProperty
_HASH_ARRAY = 1493026155  # ArrayProperty
_HASH_INT = -201674127  # IntProperty
_HASH_ITEMID = 1495970001  # ItemID
_HASH_PAINTING_KV = 1631069175  # PaintingKeyValue


def _i32(value: int) -> str:
    """Little-endian signed int32 as a lowercase hex string."""
    return value.to_bytes(4, "little", signed=True).hex()


def _header(name: str = "x", type_name: str = "BoolProperty") -> PropertyHeader:
    return PropertyHeader(name=name, type_name=type_name, data_size=0, index=0)


# =============================================================================
# BoolProperty
# =============================================================================


def test_v13_bool_property_true() -> None:
    # pad(4) + length(4) + value_int16(2) = 10 bytes
    blob = bytes.fromhex("00000000" "00000000" "0100")
    r = BinaryReader(blob, save_version=13)
    prop = BoolProperty.read(r, _header(), worldsave_format=True, name_table={})
    assert prop.value is True
    assert r.position == 10, "v13 BoolProperty must consume exactly 10 bytes"


def test_v13_bool_property_false() -> None:
    blob = bytes.fromhex("00000000" "00000000" "0000")
    r = BinaryReader(blob, save_version=13)
    prop = BoolProperty.read(r, _header(), worldsave_format=True, name_table={})
    assert prop.value is False
    assert r.position == 10


def test_v14_bool_property_true_via_flag_bit4() -> None:
    # pad(4) + length(4) + flag(1, bit 4 set) = 9 bytes
    blob = bytes.fromhex("00000000" "00000000" "10")
    r = BinaryReader(blob, save_version=14)
    prop = BoolProperty.read(r, _header(), worldsave_format=True, name_table={})
    assert prop.value is True
    assert r.position == 9, "v14 BoolProperty must consume exactly 9 bytes"


def test_v14_bool_property_false() -> None:
    blob = bytes.fromhex("00000000" "00000000" "00")
    r = BinaryReader(blob, save_version=14)
    prop = BoolProperty.read(r, _header(), worldsave_format=True, name_table={})
    assert prop.value is False
    assert r.position == 9


def test_v14_bool_property_with_array_index() -> None:
    # flag has bit 0 set → arr_index follows
    blob = bytes.fromhex("00000000" "00000000" "11" "05000000")
    r = BinaryReader(blob, save_version=14)
    prop = BoolProperty.read(r, _header(), worldsave_format=True, name_table={})
    assert prop.value is True  # bit 4 set
    assert prop.index == 5
    assert r.position == 13


# =============================================================================
# ByteProperty
# =============================================================================


def test_v13_byte_property_raw_byte() -> None:
    # dataSize(4) + position(4) + byteType_id(4=None) + byteType_inst(4) +
    # positionByte(1) + value(1) = 18 bytes
    blob = bytes.fromhex(
        "00000000"  # dataSize
        "00000000"  # position
        + _i32(_HASH_NONE)  # byteType_id = None
        + "00000000"  # byteType_inst
        + "00"  # positionByte
        + "2a"  # value = 0x2a = 42
    )
    nt = {_HASH_NONE: "None"}
    r = BinaryReader(blob, save_version=13)
    prop = ByteProperty.read(
        r,
        _header(type_name="ByteProperty"),
        worldsave_format=True,
        name_table=nt,
    )
    assert prop.enum_name == "None"
    assert prop.byte_value == 42
    assert r.position == 18


def test_v13_byte_property_enum_value() -> None:
    # byteType_id resolves to enum type name; value is a name-table ref
    enum_type_hash = 12345
    enum_value_hash = 67890
    blob = bytes.fromhex(
        "00000000"  # dataSize
        + "00000000"  # position
        + _i32(enum_type_hash)  # byteType_id
        + "00000000"  # byteType_inst
        + "00"  # positionByte
        + _i32(enum_value_hash)  # enum_value_id
        + "00000000"  # enum_value_inst
    )
    nt = {enum_type_hash: "MyEnum", enum_value_hash: "EnumValue_A"}
    r = BinaryReader(blob, save_version=13)
    prop = ByteProperty.read(
        r,
        _header(type_name="ByteProperty"),
        worldsave_format=True,
        name_table=nt,
    )
    assert prop.enum_name == "MyEnum"
    assert prop.enum_value == "EnumValue_A"
    assert r.position == 25


# =============================================================================
# StructProperty
# =============================================================================


def test_v13_struct_property_empty_property_list() -> None:
    # Empty PropertyList struct: dataSize = 8 bytes (just the None terminator).
    # Validates v13 preamble (33 bytes) + clamping to data_end.
    struct_type_hash = 999_888
    blob = bytes.fromhex(
        "08000000"  # dataSize = 8 (None hash + name_inst = terminator)
        + "00000000"  # position
        + _i32(struct_type_hash)
        + "00000000"  # struct_type_inst
        + "00"  # positionByte
        + ("00" * 16)  # skip 16
        + _i32(_HASH_NONE)  # name_id = None → terminator
        + "00000000"  # name_inst
    )
    nt = {struct_type_hash: "__UnknownTestStruct", _HASH_NONE: "None"}
    r = BinaryReader(blob, save_version=13)
    prop = StructProperty.read(
        r,
        _header(type_name="StructProperty"),
        worldsave_format=True,
        name_table=nt,
    )
    assert prop.struct_type == "__UnknownTestStruct"
    # Preamble (33) + dataSize (8) = 41 total.
    assert r.position == 41


# =============================================================================
# ArrayProperty
# =============================================================================


def test_v13_array_property_empty_struct_array() -> None:
    # Empty struct array: preamble + arrayLength=0, no struct sub-header.
    blob = bytes.fromhex(
        "04000000"  # dataSize = 4 (just the count field)
        + "00000000"  # position
        + _i32(_HASH_STRUCT)  # element_type
        + "00000000"  # element_type_inst
        + "00"  # endOfStruct byte
        + "00000000"  # arrayLength = 0
    )
    nt = {_HASH_STRUCT: "StructProperty"}
    r = BinaryReader(blob, save_version=13)
    prop = ArrayProperty.read(
        r,
        _header(type_name="ArrayProperty"),
        worldsave_format=True,
        name_table=nt,
    )
    assert prop.array_type == "StructProperty"
    assert len(prop.value) == 0
    # 21-byte preamble for empty array (no struct sub-header path because count == 0)
    assert r.position == 21


def test_v13_array_property_primitive_int_array() -> None:
    # arrayLength=2 of IntProperty → reads 2× int32 values
    blob = bytes.fromhex(
        "0c000000"  # dataSize = 12 (count(4) + 2×int(4))
        + "00000000"  # position
        + _i32(_HASH_INT)  # element_type
        + "00000000"  # element_type_inst
        + "00"  # endOfStruct byte
        + "02000000"  # arrayLength = 2
        + "0a000000"  # element [0] = 10
        + "14000000"  # element [1] = 20
    )
    nt = {_HASH_INT: "IntProperty"}
    r = BinaryReader(blob, save_version=13)
    prop = ArrayProperty.read(
        r,
        _header(type_name="ArrayProperty"),
        worldsave_format=True,
        name_table=nt,
    )
    assert prop.array_type == "IntProperty"
    assert prop.value == [10, 20]


# =============================================================================
# MapProperty
# =============================================================================


def test_v13_map_property_empty() -> None:
    # Empty map: dataSize counts only the trailing skipCount+mapCount fields
    blob = bytes.fromhex(
        "08000000"  # dataSize = 8 (= skipCount(4) + mapCount(4) only)
        + "00000000"  # position
        + _i32(_HASH_INT)  # key type
        + "00000000"  # key type instance
        + _i32(_HASH_INT)  # value type
        + "00000000"  # value type instance
        + "00"  # byte_unknown
        + "00000000"  # skipCount
        + "00000000"  # mapCount = 0
    )
    nt = {_HASH_INT: "IntProperty"}
    r = BinaryReader(blob, save_version=13)
    prop = MapProperty.read(
        r,
        _header(type_name="MapProperty"),
        worldsave_format=True,
        name_table=nt,
    )
    assert prop.key_type == "IntProperty"
    assert prop.value_type == "IntProperty"
    assert prop._entries == {}
    # 33-byte fixed preamble for empty map
    assert r.position == 33
