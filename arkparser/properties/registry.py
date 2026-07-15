"""
Property Registry - Type Dispatch for Property Reading.

This module provides the central registry for reading properties from binary data.
It dispatches to the appropriate property class based on the type name in the header.
"""

from __future__ import annotations

import struct
import typing as t

from ..common.binary_reader import BinaryReader
from ..common.exceptions import ArkParseError, UnknownPropertyError
from ..structs import registry as struct_registry
from . import compound as compound_properties
from .base import NameTable, Property, PropertyHeader, read_property_header
from .byte_property import ByteProperty, EnumProperty
from .compound import ArrayProperty, MapProperty, StructProperty
from .primitives import (
    BoolProperty,
    DoubleProperty,
    FloatProperty,
    Int8Property,
    Int16Property,
    Int64Property,
    IntProperty,
    NameProperty,
    ObjectProperty,
    SoftObjectProperty,
    StrProperty,
    UInt16Property,
    UInt32Property,
    UInt64Property,
)

# Type alias for property reader functions
PropertyReader = t.Callable[[BinaryReader, PropertyHeader, bool], Property]

# Static upper bound on the number of properties in one object's property list
# (Power-of-10 rule 2). Real objects carry well under a few hundred; this only
# trips on a corrupt / non-terminating stream.
MAX_PROPERTIES_PER_LIST = 100_000


# Property types whose readers need the name table even outside worldsave
# mode. Frozenset: membership is tested once per parsed property (millions
# per save), and a hash probe beats a 6-string tuple scan.
_NEEDS_NAME_TABLE: frozenset[str] = frozenset({
    "ArrayProperty",
    "StructProperty",
    "MapProperty",
    "ByteProperty",
    "EnumProperty",
    "NameProperty",
    "ObjectProperty",
})

# Registry mapping type names to their reader classes
PROPERTY_REGISTRY: dict[str, type[Property]] = {
    # Numeric properties
    "Int8Property": Int8Property,
    "Int16Property": Int16Property,
    "IntProperty": IntProperty,
    "Int64Property": Int64Property,
    "UInt16Property": UInt16Property,
    "UInt32Property": UInt32Property,
    "UInt64Property": UInt64Property,
    "FloatProperty": FloatProperty,
    "DoubleProperty": DoubleProperty,
    # Boolean
    "BoolProperty": BoolProperty,
    # String/Name
    "StrProperty": StrProperty,
    "NameProperty": NameProperty,
    # Object reference
    "ObjectProperty": ObjectProperty,
    # Soft object reference (asset paths)
    "SoftObjectProperty": SoftObjectProperty,
    # Byte (can be raw or enum)
    "ByteProperty": ByteProperty,
    # Scoped enum - same wire layout as an enum-form ByteProperty
    "EnumProperty": EnumProperty,
    # Compound types
    "ArrayProperty": ArrayProperty,
    "StructProperty": StructProperty,
    "MapProperty": MapProperty,
}


def read_property(
    reader: BinaryReader,
    is_asa: bool = False,
    name_table: NameTable = None,
    worldsave_format: bool = False,
) -> Property | None:
    """
    Read a single property from the binary reader.

    Reads the property header, then dispatches to the appropriate
    property type's read method.

    Args:
        reader: The binary reader positioned at the property header.
        is_asa: True for ASA format, False for ASE.
        name_table: Optional name table for world saves.
                   - list: ASE format (1-based index)
                   - dict: ASA format (hash key)
        worldsave_format: True for ASA WorldSave SQLite object format.

    Returns:
        The parsed Property object, or None if the terminating "None" property
        was encountered.

    Raises:
        UnknownPropertyError: If the property type is not recognized.
    """
    header = read_property_header(reader, is_asa, name_table=name_table, worldsave_format=worldsave_format)

    # Check for terminator (read_property_header returns None for "None")
    if header is None:
        return None

    # Look up the property type in the registry
    property_class = PROPERTY_REGISTRY.get(header.type_name)

    if property_class is None:
        raise UnknownPropertyError(
            property_type=header.type_name,
            position=reader.position,
        )

    # Read the property value
    # In WorldSave format, all properties need the flag and name_table
    if worldsave_format:
        return property_class.read(reader, header, is_asa, name_table=name_table, worldsave_format=worldsave_format)
    if header.type_name in _NEEDS_NAME_TABLE:
        # These types need name_table even in non-worldsave mode
        return property_class.read(reader, header, is_asa, name_table=name_table, worldsave_format=worldsave_format)
    return property_class.read(reader, header, is_asa)


def read_properties(
    reader: BinaryReader,
    is_asa: bool = False,
    name_table: NameTable = None,
    worldsave_format: bool = False,
) -> list[Property]:
    """
    Read all properties until the "None" terminator.

    This reads properties in a loop until encountering a property
    named "None", which signals the end of the property list.

    Args:
        reader: The binary reader positioned at the first property.
        is_asa: True for ASA format, False for ASE.
        name_table: Optional name table for world saves.
                   - list: ASE format (1-based index)
                   - dict: ASA format (hash key)
        worldsave_format: True for ASA WorldSave SQLite object format.

    Returns:
        List of parsed Property objects.

    Raises:
        UnknownPropertyError: If any property type is not recognized.
        ArkParseError: If the list exceeds ``MAX_PROPERTIES_PER_LIST`` (a
            corrupt stream that never yields the "None" terminator).
    """
    properties: list[Property] = []

    # Power-of-10 rule 2: the loop is bounded by an explicit, statically-
    # provable iteration cap rather than relying on the "None" terminator /
    # EOF. No real object's property list approaches this; exceeding it means
    # the stream is corrupt and we should fail loudly, not spin.
    for _ in range(MAX_PROPERTIES_PER_LIST):
        prop = read_property(reader, is_asa, name_table=name_table, worldsave_format=worldsave_format)
        if prop is None:
            return properties
        properties.append(prop)
    raise ArkParseError(
        f"property list exceeded {MAX_PROPERTIES_PER_LIST} entries at "
        f"position {reader.position}; stream is likely corrupt"
    )


# Fixed value sizes (bytes) for v14+ worldsave simple properties whose readers
# consume ``_read_worldsave_simple_prefix`` followed by a constant-width value.
# Mirrors each reader's actual consumption (NOT the header's data_size field,
# which the real readers never use); byte-exactness vs the real readers is
# proven across every ASA fixture by
# ``references/scripts/verify_partial_walk.py``.
_FIXED_SIMPLE_SIZES: dict[str, int] = {
    "Int8Property": 1,
    "Int16Property": 2,
    "IntProperty": 4,
    "Int64Property": 8,
    "UInt16Property": 2,
    "UInt32Property": 4,
    "UInt64Property": 8,
    "FloatProperty": 4,
    "DoubleProperty": 8,
    "BoolProperty": 0,  # value lives in the prefix flag byte
    "NameProperty": 8,  # name-table ref: id(4) + instance(4)
    "SoftObjectProperty": 12,  # name-table ref (8) + padding (4)
}


# Fused unpackers for the partial walk's raw-buffer position arithmetic.
_S_PAIR = struct.Struct("<ii")
_S_I32 = struct.Struct("<i")


def read_properties_partial(
    reader: BinaryReader,
    name_table: dict[int, str],
    wanted: frozenset[str],
) -> tuple[list[Property], set[str]]:
    """Walk one v14+ ASA worldsave property block, decoding only ``wanted``.

    Pre: ``reader`` is positioned at the first property of a v14+ worldsave
    object blob (``reader.save_version >= 14``); ``name_table`` is the save's
    FName dict. Post: the reader lands exactly where ``read_properties`` would
    (byte-exactness proven per fixture by ``verify_partial_walk.py``); returns
    the decoded properties plus the set of names that were present but
    skipped. Types without an inlined skip rule are fully read and discarded,
    so correctness never depends on the skip table being complete.

    v13 callers must use ``read_properties`` (no live v13 fixture exists to
    verify the skip table against); ``WorldSave`` routes accordingly.

    Power-of-10 boundary: this is the hottest lazy-ASA frame (hundreds of
    thousands of blocks, millions of properties per export), so the skip
    table is inlined into the loop on the raw buffer instead of split into
    helpers; rule 4 (function length) yields to the hot-path exemption.
    Skips run as pure position arithmetic: a malformed length surfaces as
    struct.error / EndOfDataError at the next read, which callers already
    treat as a per-object parse failure (mirroring the eager pass).
    """
    assert reader.save_version >= 14, "partial walk is v14+ only"
    assert isinstance(name_table, dict), "ASA name table required"
    properties: list[Property] = []
    skipped: set[str] = set()
    buf = reader._buf
    pos = reader.position
    end = reader.size
    nt_get = name_table.get
    fixed_get = _FIXED_SIMPLE_SIZES.get
    unpack_pair = _S_PAIR.unpack_from
    unpack_i32 = _S_I32.unpack_from

    # Power-of-10 rule 2: same explicit bound as read_properties.
    for _ in range(MAX_PROPERTIES_PER_LIST):
        if end - pos < 8:
            reader.position = pos
            return properties, skipped
        name_id, name_instance = unpack_pair(buf, pos)
        pos += 8
        name = nt_get(name_id)
        if name == "None":
            reader.position = pos
            return properties, skipped
        if name is None:
            name = f"__UNKNOWN_NAME_{name_id}__"
        type_id, _type_instance = unpack_pair(buf, pos)
        pos += 8
        type_name = nt_get(type_id, "")

        if name not in wanted:
            fixed = fixed_get(type_name)
            if fixed is not None:
                # pad(4) + data_size(4) + flag(1) [+ index(4)] + fixed value.
                flag = buf[pos + 8]
                pos += 9 + fixed + (4 if flag & 0x01 else 0)
                skipped.add(name)
                continue
            if type_name == "StrProperty":
                flag = buf[pos + 8]
                pos += 9 + (4 if flag & 0x01 else 0)
                (str_len,) = unpack_i32(buf, pos)
                pos += 4 + (-str_len * 2 if str_len < 0 else str_len)
                skipped.add(name)
                continue
            if type_name == "ObjectProperty":
                # prefix + uint16 marker: 1 = name ref (8), else GUID (16).
                flag = buf[pos + 8]
                pos += 9 + (4 if flag & 0x01 else 0)
                marker = buf[pos] | (buf[pos + 1] << 8)
                pos += 2 + (8 if marker == 1 else 16)
                skipped.add(name)
                continue
            if type_name == "StructProperty":
                # header1(4) + 24 fixed + extra name groups + size(4) +
                # flag(1) [+ index(4)] + body(size).
                (header1,) = unpack_i32(buf, pos)
                pos += 28
                if header1 > 1:
                    pos += (header1 - 1) * 12
                (data_size,) = unpack_i32(buf, pos)
                flag = buf[pos + 4]
                pos += 5 + (4 if flag & 0x01 else 0) + data_size
                skipped.add(name)
                continue
            if type_name == "ArrayProperty":
                (elem_id,) = unpack_i32(buf, pos + 4)
                if nt_get(elem_id, "") == "StructProperty":
                    # ah(4) elem(4) zeros(4) sub_header(4) + 24 fixed +
                    # extra name groups + byte_len(4) + flag(1) + body.
                    (sub_header,) = unpack_i32(buf, pos + 12)
                    pos += 40
                    if sub_header > 1:
                        pos += (sub_header - 1) * 12
                    (byte_len,) = unpack_i32(buf, pos)
                    pos += 5 + byte_len
                else:
                    # ah(4) elem(4) zeros(8) + byte_len(4) + idx(1) + body.
                    (byte_len,) = unpack_i32(buf, pos + 16)
                    pos += 21 + byte_len
                skipped.add(name)
                continue
            if type_name == "ByteProperty":
                (marker,) = unpack_i32(buf, pos)
                if marker == 0:
                    # marker(4) + size(4) + flag(1) [+ index(4)] + value(1).
                    flag = buf[pos + 8]
                    pos += 10 + (4 if flag & 0x01 else 0)
                else:
                    # marker(4) + enum_type(8) + marker2(4) + bp(8) + zeros(4)
                    # + size(4) + flag(1) + enum value ref (8).
                    pos += 41
                skipped.add(name)
                continue
            # No inlined skip rule (MapProperty, unknown): full read below.

        property_class = PROPERTY_REGISTRY.get(type_name)
        if property_class is None:
            raise UnknownPropertyError(property_type=type_name, position=pos)
        header = PropertyHeader(
            name=name,
            type_name=type_name,
            data_size=0,
            index=name_instance - 1 if name_instance > 0 else 0,
        )
        reader.position = pos
        prop = property_class.read(
            reader, header, True, name_table=name_table, worldsave_format=True
        )
        pos = reader.position
        if name in wanted:
            properties.append(prop)
        else:
            # Unskippable type: parsed for byte-exact positioning, then dropped.
            skipped.add(name)
    raise ArkParseError(
        f"property list exceeded {MAX_PROPERTIES_PER_LIST} entries at "
        f"position {reader.position}; stream is likely corrupt"
    )


def read_properties_as_dict(
    reader: BinaryReader,
    is_asa: bool = False,
) -> dict[str, Property | list[Property]]:
    """
    Read all properties and return as a dictionary.

    Properties with the same name (different indices) are grouped into lists.

    Args:
        reader: The binary reader positioned at the first property.
        is_asa: True for ASA format, False for ASE.

    Returns:
        Dictionary mapping property names to Property objects or lists of them.
    """
    properties = read_properties(reader, is_asa)
    result: dict[str, Property | list[Property]] = {}

    for prop in properties:
        if prop.name in result:
            existing = result[prop.name]
            if isinstance(existing, list):
                existing.append(prop)
            else:
                result[prop.name] = [existing, prop]
        else:
            result[prop.name] = prop

    return result


def get_property_value(
    properties: dict[str, Property | list[Property]],
    name: str,
    default: t.Any = None,
    index: int | None = None,
) -> t.Any:
    """
    Get a property value from a properties dictionary.

    Helper function for easily extracting values from parsed properties.

    Args:
        properties: Dictionary of properties from read_properties_as_dict.
        name: The property name to look up.
        default: Default value if property not found.
        index: Specific index to retrieve if there are multiple properties
               with the same name. None returns the first/only one.

    Returns:
        The property value, or the default if not found.
    """
    if name not in properties:
        return default

    prop_or_list = properties[name]

    if isinstance(prop_or_list, list):
        if index is not None:
            # Find the property with the matching index
            for prop in prop_or_list:
                if prop.index == index:
                    return prop.value
            return default
        else:
            # Return the first one
            return prop_or_list[0].value if prop_or_list else default
    else:
        if index is not None and prop_or_list.index != index:
            return default
        return prop_or_list.value


compound_properties.set_property_reader(read_property)
compound_properties.set_properties_reader(read_properties)
struct_registry.set_property_reader(read_property)
