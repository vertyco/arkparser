"""
Game Object.

The core entity class for all objects in ARK save files.
Game objects represent creatures, items, structures, players, and other entities.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from .location import LocationData

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader
    from ..properties.base import Property


@dataclass
class GameObject:
    """
    A game object from an ARK save file.

    Game objects are the fundamental entities in ARK saves. They represent
    creatures, items, structures, players, and other game entities.

    Attributes:
        id: Object index/ID within the save file.
        guid: 16-byte GUID (ASA only, empty string for ASE).
        class_name: The UE4 class name (e.g., "Dodo_Character_BP_C").
        is_item: True if this is an item/blueprint/engram.
        names: List of ArkNames (usually 1 for actors, 2 for components).
        from_data_file: True if loaded from external data file.
        data_file_index: Index of the external data file.
        location: Position and rotation data (if has_location is True).
        properties_offset: Offset to property data in the save file.
        properties: List of parsed properties.
        extra_data: Additional data after properties (type depends on structGuid).
    """

    id: int = 0
    guid: str = ""
    class_name: str = ""
    is_item: bool = False
    names: list[str] = field(default_factory=list)
    from_data_file: bool = False
    data_file_index: int = 0
    location: LocationData | None = None
    properties_offset: int = 0
    properties: list[Property] = field(default_factory=list)
    extra_data: bytes | None = None

    # Parent/component relationships (set after loading)
    parent: GameObject | None = field(default=None, repr=False)
    components: dict[str, GameObject] = field(default_factory=dict, repr=False)

    @property
    def has_location(self) -> bool:
        """True if this object has location data."""
        return self.location is not None

    @property
    def primary_name(self) -> str | None:
        """The primary name of this object (first in names list)."""
        return self.names[0] if self.names else None

    @property
    def parent_names(self) -> list[str]:
        """Parent names (all names after the first)."""
        return self.names[1:] if len(self.names) > 1 else []

    @property
    def has_parent_names(self) -> bool:
        """True if this object has parent names (component)."""
        return len(self.names) > 1

    def get_property(self, name: str, index: int | None = None) -> Property | None:
        """
        Get a property by name and optional index.

        Args:
            name: Property name to find.
            index: Property index (for arrays with same name). If None, returns first match.

        Returns:
            The Property object, or None if not found.
        """
        for prop in self.properties:
            if prop.name == name:
                if index is None or prop.index == index:
                    return prop
        return None

    def get_property_value(self, name: str, default: t.Any = None, index: int | None = None) -> t.Any:
        """
        Get a property value by name.

        Args:
            name: Property name to find.
            default: Default value if property not found.
            index: Property index (for arrays with same name). If None, returns first match.

        Returns:
            The property value, or the default if not found.
        """
        prop = self.get_property(name, index)
        return prop.value if prop is not None else default

    def get_properties_by_name(self, name: str) -> list[Property]:
        """Get all properties with the given name (any index)."""
        return [p for p in self.properties if p.name == name]

    def has_property(self, name: str) -> bool:
        """Check if this object has a property with the given name."""
        return any(p.name == name for p in self.properties)

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, t.Any] = {
            "id": self.id,
            "class_name": self.class_name,
        }

        if self.guid:
            result["guid"] = self.guid
        if self.is_item:
            result["is_item"] = True
        if self.names:
            result["names"] = self.names
        if self.from_data_file:
            result["from_data_file"] = True
            result["data_file_index"] = self.data_file_index
        if self.location:
            result["location"] = self.location.to_dict()

        # Convert properties to dict
        props: dict[str, t.Any] = {}
        for prop in self.properties:
            if prop.name in props:
                existing = props[prop.name]
                if isinstance(existing, list):
                    existing.append(prop.value)
                else:
                    props[prop.name] = [existing, prop.value]
            else:
                props[prop.name] = prop.value
        if props:
            result["properties"] = props

        return result

    @classmethod
    def read_header(
        cls,
        reader: BinaryReader,
        obj_id: int,
        is_asa: bool = False,
    ) -> GameObject:
        """
        Read the object header (not properties).

        Properties are loaded separately via load_properties().

        Args:
            reader: Binary reader positioned at object header.
            obj_id: Object ID/index.
            is_asa: True for ASA format.

        Returns:
            GameObject with header data populated.
        """
        obj = cls(id=obj_id)

        # Read GUID (16 bytes) - always present, but all zeros in ASE
        guid = reader.read_guid()
        obj.guid = str(guid) if any(b != 0 for b in guid.bytes) else ""

        # Read class name
        obj.class_name = reader.read_string()

        # Is item flag (UInt32 bool)
        obj.is_item = reader.read_uint32() != 0

        # Read names
        name_count = reader.read_int32()
        obj.names = [reader.read_string() for _ in range(name_count)]

        # From data file flag
        obj.from_data_file = reader.read_uint32() != 0
        obj.data_file_index = reader.read_int32()

        # Location data
        has_location = reader.read_uint32() != 0
        if has_location:
            obj.location = LocationData.read(reader, is_asa)

        # Properties offset
        obj.properties_offset = reader.read_int32()

        # Unknown int (should be 0)
        _unknown = reader.read_int32()

        return obj

    def load_properties(
        self,
        reader: BinaryReader,
        properties_block_offset: int,
        is_asa: bool = False,
        next_object: GameObject | None = None,
        name_table: list[str] | None = None,
    ) -> None:
        """
        Load properties for this object.

        Args:
            reader: Binary reader.
            properties_block_offset: Base offset of the properties block.
            is_asa: True for ASA format.
            next_object: Next object (to determine property block end).
            name_table: Optional name table for world saves (version 6+).
        """
        from ..properties.registry import read_properties

        # Calculate absolute offset
        offset = properties_block_offset + self.properties_offset

        # Seek to properties
        reader.position = offset

        # Read properties
        self.properties = read_properties(reader, is_asa, name_table=name_table)

        # Any remaining data before next object is extra data
        if next_object is not None:
            next_offset = properties_block_offset + next_object.properties_offset
            remaining = next_offset - reader.position
            if remaining > 0:
                self.extra_data = reader.read_bytes(remaining)

    def add_component(self, component: GameObject) -> None:
        """Add a component to this object."""
        if component.primary_name:
            self.components[component.primary_name] = component
            component.parent = self


def read_object_list(
    reader: BinaryReader,
    is_asa: bool = False,
) -> list[GameObject]:
    """
    Read a list of game objects from the archive.

    This reads only the object headers. Properties must be loaded
    separately using load_properties().

    Args:
        reader: Binary reader positioned at object count.
        is_asa: True for ASA format.

    Returns:
        List of GameObject instances with headers populated.
    """
    count = reader.read_int32()
    objects: list[GameObject] = []

    for i in range(count):
        obj = GameObject.read_header(reader, i, is_asa)
        objects.append(obj)

    return objects
