"""
Property-Based Struct.

This struct type contains a list of properties rather than a fixed binary format.
It's used for complex game objects and custom data structures.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from .base import Struct

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader
    from ..properties.base import Property


@dataclass
class StructPropertyList(Struct):
    """
    A struct that contains a list of properties.

    This is the fallback for any struct type that isn't a known native type.
    The properties are read until a "None" terminator is encountered.
    """

    _struct_type: str = "PropertyList"
    properties: list[Property] = field(default_factory=list)

    @property
    def struct_type(self) -> str:
        return self._struct_type

    @property
    def is_native(self) -> bool:
        return False

    def to_dict(self) -> dict[str, t.Any]:
        """Convert properties to a dictionary."""
        result: dict[str, t.Any] = {}
        for prop in self.properties:
            if prop.name in result:
                # Handle duplicate property names (array-like)
                existing = result[prop.name]
                if isinstance(existing, list):
                    existing.append(prop.value)
                else:
                    result[prop.name] = [existing, prop.value]
            else:
                result[prop.name] = prop.value
        return result

    def get_property(self, name: str, index: int = 0) -> Property | None:
        """Get a property by name and optional index."""
        for prop in self.properties:
            if prop.name == name and prop.index == index:
                return prop
        return None

    def get_value(self, name: str, default: t.Any = None, index: int = 0) -> t.Any:
        """Get a property value by name."""
        prop = self.get_property(name, index)
        return prop.value if prop else default

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        is_asa: bool = False,
        struct_type: str = "PropertyList",
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> StructPropertyList:
        """
        Read a property-based struct from the archive.

        Note: This imports the registry at runtime to avoid circular imports.

        Args:
            reader: The binary reader.
            is_asa: True for ASA format.
            struct_type: The struct type name.
            name_table: Optional name table for world saves (version 6+).
            worldsave_format: True for ASA WorldSave SQLite object format.
        """
        # Import here to avoid circular dependency
        from ..properties.registry import read_properties

        # Note: For ASA, the extra_byte that precedes struct data is read by the
        # calling code (StructProperty.read or ArrayProperty.read), not here.
        # We just read the properties directly.

        properties = read_properties(
            reader,
            is_asa,
            name_table=name_table,
            worldsave_format=worldsave_format,
        )
        return cls(_struct_type=struct_type, properties=properties)
