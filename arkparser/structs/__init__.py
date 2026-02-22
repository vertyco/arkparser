"""
ARK Struct System.

This module provides struct types for structured data within properties.

Structs come in two forms:
1. Native structs: Fixed binary format (Vector, Color, etc.)
2. Property-based structs: List of properties terminated by "None"

Usage:
    from arkparser.structs import read_struct, Vector, Color

    # Read a struct by type name
    struct = read_struct(reader, "Vector", is_asa=False)

    # Access struct data
    if isinstance(struct, Vector):
        print(f"Position: ({struct.x}, {struct.y}, {struct.z})")
"""

from .base import NativeStruct, Struct
from .colors import Color, LinearColor
from .misc import CustomItemDataRef, Guid, UniqueNetIdRepl
from .property_list import StructPropertyList
from .registry import (
    ARRAY_NAME_TO_STRUCT_TYPE,
    STRUCT_REGISTRY,
    get_array_struct_type,
    is_native_struct,
    read_struct,
)
from .vectors import IntPoint, IntVector, Quat, Rotator, Vector, Vector2D

__all__ = [
    # Base
    "Struct",
    "NativeStruct",
    # Vectors
    "Vector",
    "Vector2D",
    "Rotator",
    "Quat",
    "IntPoint",
    "IntVector",
    # Colors
    "Color",
    "LinearColor",
    # Misc
    "UniqueNetIdRepl",
    "Guid",
    "CustomItemDataRef",
    # Property-based
    "StructPropertyList",
    # Registry
    "STRUCT_REGISTRY",
    "ARRAY_NAME_TO_STRUCT_TYPE",
    "read_struct",
    "is_native_struct",
    "get_array_struct_type",
]
