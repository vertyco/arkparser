"""
Property Registry - Type Dispatch for Property Reading.

This module provides the central registry for reading properties from binary data.
It dispatches to the appropriate property class based on the type name in the header.
"""

from __future__ import annotations

import typing as t

from ..common.binary_reader import BinaryReader
from ..common.exceptions import UnknownPropertyError
from .base import NameTable, Property, PropertyHeader, read_property_header
from .byte_property import ByteProperty
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
    elif header.type_name in (
        "ArrayProperty",
        "StructProperty",
        "MapProperty",
        "ByteProperty",
        "NameProperty",
        "ObjectProperty",
    ):
        # These types need name_table even in non-worldsave mode
        return property_class.read(reader, header, is_asa, name_table=name_table, worldsave_format=worldsave_format)
    else:
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
    """
    properties: list[Property] = []

    while True:
        prop = read_property(reader, is_asa, name_table=name_table, worldsave_format=worldsave_format)
        if prop is None:
            break
        properties.append(prop)

    return properties


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
