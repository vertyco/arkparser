"""
Cloud inventory parser for obelisk/ARK data files.

Cloud inventory files contain uploaded data including:
- Uploaded creatures (dinos)
- Uploaded items (including cryopods with dinos inside)
- Uploaded characters
- Transfer timers

These files have no extension and are typically found in obelisk directories.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from arkparser.common.binary_reader import BinaryReader
from arkparser.common.exceptions import ArkParseError
from arkparser.data_models import UploadedCreature, UploadedItem
from arkparser.game_objects.container import GameObjectContainer
from arkparser.game_objects.game_object import GameObject

from .base import ArkFile


@dataclass
class CloudInventory(ArkFile):
    """
    Parser for obelisk/cloud inventory data files.

    The main object has class name "ArkCloudInventoryData".

    Supports both ASE (versions 1-6) and ASA (version 7+) formats.

    Example usage:
        >>> inv = CloudInventory.load("examples/ase/obelisk/2533274922942310")
        >>> print(f"Creatures: {len(inv.uploaded_creatures)}")
        >>> for creature in inv.uploaded_creatures:
        ...     print(f"  {creature.name} ({creature.species}) Lvl {creature.level}")
        >>> for item in inv.uploaded_items:
        ...     print(f"  {item.display_name} ({item.quality_name})")
    """

    VALID_VERSIONS: t.ClassVar[tuple[int, ...]] = (1, 2, 3, 4, 5, 6, 7)
    MAIN_CLASS_NAME: t.ClassVar[str] = "ArkCloudInventoryData"

    @classmethod
    def _parse(cls, reader: BinaryReader) -> t.Self:
        """
        Parse the cloud inventory file.

        ASE format:
        - Int32 version
        - Int32 object_count
        - Object headers (ASE format)
        - Properties

        ASA v7 format:
        - Int32 version (7)
        - Int32 unknown1 (extra field, v7+ only)
        - Int32 unknown2 (extra field, v7+ only)
        - Int32 object_count
        - Object headers (ASA format with GUIDs)
        - Properties

        ASA v6 format (solo-cluster / cross-ARK transfer files):
        - Int32 version (6)
        - Int32 object_count
        - Object headers (ASA format with GUIDs — no extra header fields)
        - Properties
        """
        # Read version
        version = reader.read_int32()

        if cls.VALID_VERSIONS and version not in cls.VALID_VERSIONS:
            raise ArkParseError(f"Unsupported {cls.__name__} version {version}. Expected one of: {cls.VALID_VERSIONS}")

        # Detect ASE vs ASA
        is_asa = cls._detect_asa(reader, version)

        if is_asa and version >= 7:
            # v7+ ASA has two extra header fields before object_count
            _unknown1 = reader.read_int32()
            _unknown2 = reader.read_int32()

        # Read object count
        object_count = reader.read_int32()

        if object_count < 0 or object_count > 1000000:
            raise ArkParseError(f"Invalid object count: {object_count}")

        # Read object headers
        objects: list[GameObject] = []
        for i in range(object_count):
            if is_asa:
                obj = cls._read_asa_object_header(reader, obj_id=i, version=version)
            else:
                obj = GameObject.read_header(reader, obj_id=i, is_asa=False)
            objects.append(obj)

        # Load properties for each object.
        # Version 6 ASA (cross-ARK / solecluster) uses ASA-style object headers
        # but ASE-style (is_asa=False) properties. Only v7+ uses ASA properties.
        properties_is_asa = version >= 7
        properties_block_offset = 0
        for i, obj in enumerate(objects):
            next_obj = objects[i + 1] if i + 1 < len(objects) else None
            obj.load_properties(
                reader,
                properties_block_offset=properties_block_offset,
                is_asa=properties_is_asa,
                next_object=next_obj,
            )

        # Build container with lookups
        container = GameObjectContainer(objects=objects)
        container.build_relationships()

        return cls(
            version=version,
            objects=objects,
            container=container,
            is_asa=is_asa,
        )

    @classmethod
    def _read_asa_object_header(cls, reader: BinaryReader, obj_id: int, version: int = 7) -> GameObject:
        """
        Read an ASA object header.

        ASA obelisk object header format:
        - GUID (16 bytes)
        - Class name (string)
        - Field1 (int32)
        - Field2 (int32)
        - Instance name (string)
        - Padding (21 bytes for v7+, 20 bytes for v6)

        Version 6 (cross-ARK / solecluster files) uses a slightly older format
        with one fewer padding byte before the properties block.
        """
        obj = GameObject(id=obj_id)

        # Read GUID
        guid = reader.read_guid()
        obj.guid = str(guid)

        # Class name
        obj.class_name = reader.read_string()

        # Fields (not sure what these represent)
        _field1 = reader.read_int32()
        _field2 = reader.read_int32()

        # Instance name
        instance_name = reader.read_string()
        obj.names = [instance_name] if instance_name else []

        # v7+ uses 21 bytes of padding; v6 (cross-ARK / solecluster) uses 20
        padding_size = 21 if version >= 7 else 20
        reader.skip(padding_size)

        # Properties offset will be set by sequential reading
        obj.properties_offset = reader.position

        return obj

    # =========================================================================
    # Data Extraction - Primary API
    # =========================================================================

    @property
    def uploaded_creatures(self) -> list[UploadedCreature]:
        """
        Get all uploaded creatures as structured data.

        Returns:
            List of UploadedCreature objects with typed fields.
        """
        my_ark_data = self.get_property_value("MyArkData")
        if not my_ark_data:
            return []

        dino_data_list = my_ark_data.get("ArkTamedDinosData", [])
        return [UploadedCreature.from_ark_data(d) for d in dino_data_list]

    @property
    def uploaded_items(self) -> list[UploadedItem]:
        """
        Get all uploaded items as structured data.

        Returns:
            List of UploadedItem objects with typed fields.
        """
        my_ark_data = self.get_property_value("MyArkData")
        if not my_ark_data:
            return []

        item_data_list = my_ark_data.get("ArkItems", [])
        return [UploadedItem.from_ark_data(d) for d in item_data_list]

    # =========================================================================
    # Convenience Properties
    # =========================================================================

    @property
    def creature_count(self) -> int:
        """Get number of uploaded creatures."""
        return len(self.uploaded_creatures)

    @property
    def item_count(self) -> int:
        """Get number of uploaded items."""
        return len(self.uploaded_items)

    # =========================================================================
    # Legacy API (for backward compatibility)
    # =========================================================================

    @property
    def creatures(self) -> list[GameObject]:
        """
        Get creatures as raw GameObjects.

        Note: Use `uploaded_creatures` for structured data access.
        """
        return self.container.get_creatures()

    @property
    def items(self) -> list[GameObject]:
        """
        Get items as raw GameObjects.

        Note: Use `uploaded_items` for structured data access.
        """
        result = []
        for obj in self.objects:
            class_name = obj.class_name or ""
            if "PrimalItem" in class_name or "Item" in class_name:
                result.append(obj)
        return result

    @property
    def characters(self) -> list[GameObject]:
        """
        Get all uploaded player characters.

        Characters are identified by having PlayerPawnTest class name.
        """
        result = []
        for obj in self.objects:
            class_name = obj.class_name or ""
            if "PlayerPawnTest" in class_name:
                result.append(obj)
        return result

    @property
    def character_count(self) -> int:
        """Get number of uploaded characters."""
        return len(self.characters)

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary with cloud inventory-specific fields."""
        base_dict = super().to_dict()
        base_dict.update(
            {
                "creature_count": self.creature_count,
                "item_count": self.item_count,
                "character_count": self.character_count,
                "uploaded_creatures": [c.to_dict() for c in self.uploaded_creatures],
                "uploaded_items": [i.to_dict() for i in self.uploaded_items],
            }
        )
        return base_dict
