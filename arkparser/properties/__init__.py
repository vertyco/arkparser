"""
ARK Property System.

This module provides the property parsing system for ARK save files.
Properties are the core data storage mechanism for game objects.

Usage:
    from arkparser.properties import read_properties, read_properties_as_dict

    # Read properties from binary data
    properties = read_properties(reader, is_asa=False)

    # Or as a dictionary for easier access
    props_dict = read_properties_as_dict(reader, is_asa=False)
    health = get_property_value(props_dict, "Health", default=100.0)
"""

from .base import Property, PropertyHeader, read_property_header
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
from .registry import (
    PROPERTY_REGISTRY,
    get_property_value,
    read_properties,
    read_properties_as_dict,
    read_property,
)

__all__ = [
    # Base
    "Property",
    "PropertyHeader",
    "read_property_header",
    # Primitives
    "Int8Property",
    "Int16Property",
    "IntProperty",
    "Int64Property",
    "UInt16Property",
    "UInt32Property",
    "UInt64Property",
    "FloatProperty",
    "DoubleProperty",
    "BoolProperty",
    "StrProperty",
    "NameProperty",
    "ObjectProperty",
    "SoftObjectProperty",
    # Byte
    "ByteProperty",
    # Compound
    "ArrayProperty",
    "StructProperty",
    "MapProperty",
    # Registry
    "PROPERTY_REGISTRY",
    "read_property",
    "read_properties",
    "read_properties_as_dict",
    "get_property_value",
]
