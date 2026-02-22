"""
Struct Registry - Type Dispatch for Struct Reading.

This module provides the central registry for reading structs from binary data.
It dispatches to the appropriate struct class based on the struct type name.
"""

from __future__ import annotations

import typing as t

from ..common.binary_reader import BinaryReader
from .base import Struct
from .colors import Color, LinearColor
from .misc import CustomItemDataRef, Guid, UniqueNetIdRepl
from .property_list import StructPropertyList
from .vectors import IntPoint, IntVector, Quat, Rotator, Vector, Vector2D

# Type alias for struct reader functions
StructReader = t.Callable[[BinaryReader, bool], Struct]


# Registry mapping struct type names to their classes
STRUCT_REGISTRY: dict[str, type[Struct]] = {
    # Vectors and transforms
    "Vector": Vector,
    "Vector2D": Vector2D,
    "Rotator": Rotator,
    "Quat": Quat,
    "IntPoint": IntPoint,
    "IntVector": IntVector,
    # Colors
    "Color": Color,
    "LinearColor": LinearColor,
    # Misc
    "UniqueNetIdRepl": UniqueNetIdRepl,
    "Guid": Guid,
    "CustomItemDataRef": CustomItemDataRef,
}


# Some array names map to specific struct types
# Used when reading struct arrays where the element type isn't explicitly stated
ARRAY_NAME_TO_STRUCT_TYPE: dict[str, str] = {
    "CustomColors": "Color",
    "CustomColours_60_7D3267C846B277953C0C41AEBD54FBCB": "LinearColor",
}


def read_struct(
    reader: BinaryReader,
    struct_type: str,
    is_asa: bool = False,
    has_index_prefix: bool = False,
    name_table: list[str] | None = None,
    worldsave_format: bool = False,
) -> Struct:
    """
    Read a struct from the binary reader.

    Dispatches to the appropriate struct class based on the type name.
    Unknown struct types are read as property lists.

    Args:
        reader: The binary reader positioned at the struct data.
        struct_type: The struct type name (e.g., "Vector", "Color").
        is_asa: True for ASA format, False for ASE.
        has_index_prefix: True if struct data starts with an int32 array index
            (common in ASA indexed struct properties after the first element).
        name_table: Optional name table for world saves (version 6+).
        worldsave_format: True for ASA WorldSave SQLite object format.

    Returns:
        The parsed Struct object.
    """
    # Skip the array index prefix if present (ASA indexed struct properties)
    if has_index_prefix:
        _array_index = reader.read_int32()

    # Look up the struct type in the registry
    struct_class = STRUCT_REGISTRY.get(struct_type)

    if struct_class is not None:
        # Native struct - use the class's read method
        result = struct_class.read(reader, is_asa, worldsave_format=worldsave_format)
        # Note: Unlike property lists, native structs do NOT have a trailing
        # null byte - the StructProperty extra_byte is read before this function
        # is called, and the struct data is exactly data_size bytes.
        return result
    else:
        # Unknown struct type - read as property list
        return StructPropertyList.read(
            reader,
            is_asa,
            struct_type=struct_type,
            name_table=name_table,
            worldsave_format=worldsave_format,
        )


def read_struct_for_array(
    reader: BinaryReader,
    array_name: str,
    is_asa: bool = False,
    name_table: list[str] | None = None,
) -> Struct:
    """
    Read a struct element from a struct array.

    Uses the array name to determine the struct type if possible.
    For unknown array names, reads as property list.

    Args:
        reader: The binary reader positioned at the struct data.
        array_name: The name of the array property.
        is_asa: True for ASA format, False for ASE.
        name_table: Optional name table for world saves (version 6+).

    Returns:
        The parsed Struct object.
    """
    # Try to map array name to struct type
    struct_type = ARRAY_NAME_TO_STRUCT_TYPE.get(array_name)

    if struct_type:
        # Known array type
        return read_struct(reader, struct_type, is_asa, name_table=name_table)
    else:
        # Unknown array - read as property list
        return StructPropertyList.read(reader, is_asa, struct_type="PropertyList", name_table=name_table)


def is_native_struct(struct_type: str) -> bool:
    """Check if a struct type is a known native struct."""
    return struct_type in STRUCT_REGISTRY


def get_array_struct_type(array_name: str) -> str | None:
    """Get the struct type for a named array, if known."""
    return ARRAY_NAME_TO_STRUCT_TYPE.get(array_name)
