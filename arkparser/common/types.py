"""
Core ARK Types.

This module defines the fundamental types used throughout ARK save files:
- ArkName: Unreal Engine's FName type (name + instance index)
- ObjectReference: References to other game objects

These types mirror Unreal Engine 4's serialization format.
"""

from __future__ import annotations

import re
import typing as t
from dataclasses import dataclass

# =============================================================================
# Constants
# =============================================================================

# The "None" name is used as a terminator in property lists
NAME_NONE = "None"


# =============================================================================
# ArkName (FName)
# =============================================================================

# Pattern to extract instance index from name strings like "MyName_5"
_NAME_INDEX_PATTERN = re.compile(r"^(.+)_(\d+)$")


@dataclass(frozen=True, slots=True)
class ArkName:
    """
    Unreal Engine FName type.

    FNames consist of a base name and an instance index. They're used
    extensively for property names, class names, and identifiers.

    Format in files:
        - Without name table: String with optional "_N" suffix
        - With name table: Int32 index + Int32 instance

    Instance numbering:
        - Instance 0 = no suffix (or first occurrence)
        - Instance 1 = "_0" suffix
        - Instance 2 = "_1" suffix
        - etc.

    Examples:
        >>> ArkName.from_string("Health")
        ArkName(name='Health', instance=0)

        >>> ArkName.from_string("MyDino_5")
        ArkName(name='MyDino', instance=6)  # instance = parsed + 1

        >>> str(ArkName("MyDino", 6))
        'MyDino_5'

    Attributes:
        name: The base name string.
        instance: The instance index (0 = no suffix).
    """

    name: str
    instance: int = 0

    def __str__(self) -> str:
        """Convert to string representation."""
        if self.instance == 0:
            return self.name
        return f"{self.name}_{self.instance - 1}"

    def __repr__(self) -> str:
        """Detailed representation for debugging."""
        if self.instance == 0:
            return f"ArkName({self.name!r})"
        return f"ArkName({self.name!r}, instance={self.instance})"

    def __eq__(self, other: object) -> bool:
        """Check equality with another ArkName."""
        if isinstance(other, ArkName):
            return self.name == other.name and self.instance == other.instance
        return NotImplemented

    def __hash__(self) -> int:
        """Hash for use in dicts/sets."""
        return hash((self.name, self.instance))

    @property
    def is_none(self) -> bool:
        """Check if this is the 'None' terminator name."""
        return self.name == NAME_NONE and self.instance == 0

    @classmethod
    def from_string(cls, value: str) -> ArkName:
        """
        Parse an ArkName from a string.

        Handles the "_N" suffix convention:
        - "Health" -> ArkName("Health", 0)
        - "MyDino_0" -> ArkName("MyDino", 1)
        - "Item_5" -> ArkName("Item", 6)

        Args:
            value: The string to parse.

        Returns:
            An ArkName instance.
        """
        if not value:
            return cls("", 0)

        match = _NAME_INDEX_PATTERN.match(value)
        if match:
            name = match.group(1)
            index = int(match.group(2))
            return cls(name, index + 1)

        return cls(value, 0)

    @classmethod
    def from_parts(cls, name: str, instance: int) -> ArkName:
        """
        Create an ArkName from separate name and instance.

        Used when reading from a name table where name and instance
        are stored separately.

        Args:
            name: The base name.
            instance: The instance index.

        Returns:
            An ArkName instance.
        """
        return cls(name, instance)

    @classmethod
    def none(cls) -> ArkName:
        """Return the 'None' terminator name."""
        return cls(NAME_NONE, 0)


# =============================================================================
# ObjectReference
# =============================================================================


@dataclass(frozen=True, slots=True)
class ObjectReference:
    """
    Reference to another game object.

    Objects in ARK save files can reference each other. The format differs
    between ASE and ASA:

    ASE format:
        - Int32 type (0 = index, 1 = name)
        - If type 0: Int32 object index
        - If type 1: ArkName

    ASA format:
        - Int16 isName flag
        - If isName = 0: 16-byte GUID
        - If isName = 1: ArkName

    Attributes:
        object_id: The object index (ASE) or None.
        object_guid: The object GUID as hex string (ASA) or None.
        object_name: The object name (when referencing by name) or None.
        is_null: True if this is a null reference.
    """

    object_id: int | None = None
    object_guid: str | None = None
    object_name: ArkName | None = None

    @property
    def is_null(self) -> bool:
        """Check if this is a null/empty reference."""
        return self.object_id is None and self.object_guid is None and self.object_name is None

    @property
    def is_id_reference(self) -> bool:
        """Check if this references by ID (ASE style)."""
        return self.object_id is not None

    @property
    def is_guid_reference(self) -> bool:
        """Check if this references by GUID (ASA style)."""
        return self.object_guid is not None

    @property
    def is_name_reference(self) -> bool:
        """Check if this references by name."""
        return self.object_name is not None

    @classmethod
    def null(cls) -> ObjectReference:
        """Create a null reference."""
        return cls()

    @classmethod
    def from_id(cls, object_id: int) -> ObjectReference:
        """Create a reference from an object ID (ASE)."""
        return cls(object_id=object_id)

    @classmethod
    def from_guid(cls, guid: str) -> ObjectReference:
        """Create a reference from a GUID string (ASA)."""
        return cls(object_guid=guid)

    @classmethod
    def from_name(cls, name: ArkName) -> ObjectReference:
        """Create a reference from an object name."""
        return cls(object_name=name)

    def __str__(self) -> str:
        """String representation."""
        if self.is_null:
            return "ObjectReference(null)"
        if self.object_id is not None:
            return f"ObjectReference(id={self.object_id})"
        if self.object_guid is not None:
            return f"ObjectReference(guid={self.object_guid})"
        if self.object_name is not None:
            return f"ObjectReference(name={self.object_name})"
        return "ObjectReference()"


# =============================================================================
# Type Aliases
# =============================================================================

# For type hints in generic contexts
PropertyValue = t.Union[
    int,
    float,
    bool,
    str,
    bytes,
    ArkName,
    ObjectReference,
    list[t.Any],
    dict[str, t.Any],
    None,
]
