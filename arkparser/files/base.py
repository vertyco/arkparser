"""
Base class for ARK save file formats.

All file types (Profile, Tribe, CloudInventory) share the same basic structure:
1. Version header (Int32)
2. Object list (Int32 count + GameObject headers)
3. Properties block (properties for each object)

This base class handles the common parsing logic.
"""

from __future__ import annotations

import typing as t
from abc import ABC
from dataclasses import dataclass, field
from pathlib import Path

from arkparser.common.binary_reader import BinaryReader
from arkparser.common.exceptions import ArkParseError
from arkparser.game_objects.container import GameObjectContainer
from arkparser.game_objects.game_object import GameObject


@dataclass
class ArkFile(ABC):
    """
    Abstract base class for ARK save file formats.

    All ARK save files share this structure:
    - Int32 version number
    - Int32 object count
    - Object headers (repeated object_count times)
    - Properties block (properties for each object)

    Subclasses define which version numbers are valid and which
    class name identifies the "main" object in the file.
    """

    version: int
    objects: list[GameObject] = field(default_factory=list)
    container: GameObjectContainer = field(default_factory=GameObjectContainer)
    is_asa: bool = False

    # Subclasses must define these
    VALID_VERSIONS: t.ClassVar[tuple[int, ...]] = ()
    MAIN_CLASS_NAME: t.ClassVar[str] = ""

    @property
    def main_object(self) -> GameObject | None:
        """
        Get the main object for this file type.

        For profiles, this is the PrimalPlayerData object.
        For tribes, this is the PrimalTribeData object.
        For cloud inventory, this is the ArkCloudInventoryData object.
        """
        for obj in self.objects:
            # ASA uses full path like "/Script/ShooterGame.ArkCloudInventoryData"
            # ASE uses just "ArkCloudInventoryData"
            if self.MAIN_CLASS_NAME in obj.class_name:
                return obj
        return None

    @classmethod
    def load(cls, source: str | Path | bytes) -> t.Self:
        """
        Load a file from path or bytes.

        Automatically detects ASE vs ASA format based on file structure.

        Args:
            source: File path (str or Path) or raw bytes

        Returns:
            Parsed file instance

        Raises:
            ArkParseError: If the file cannot be parsed
            FileNotFoundError: If the file path doesn't exist
        """
        if isinstance(source, bytes):
            reader = BinaryReader.from_bytes(source)
        else:
            path = Path(source)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {path}")
            reader = BinaryReader.from_file(path)

        return cls._parse(reader)

    @classmethod
    def _parse(cls, reader: BinaryReader) -> t.Self:
        """
        Parse the file from a binary reader.

        ASE File structure (profiles/tribes version 1, world saves version 5-6):
        1. Int32 version
        2. Int32 object_count
        3. (16 zero bytes padding for profiles/tribes)
        4. Object headers (object_count times)
        5. Properties for each object

        ASA File structure (profiles/tribes version 6, cloud inventory version 7+):
        For version 6 (profiles/tribes):
        1. Int32 version
        2. Int32 object_count
        3. No extra header - object headers with GUIDs follow immediately
        4. Object headers with embedded GUIDs
        5. Properties for each object

        For version 7+ (cloud inventory):
        1. Int32 version
        2. Int32 unknown1 (extra field)
        3. Int32 unknown2 (extra field)
        4. Int32 object_count
        5. Object headers with GUIDs
        6. Properties for each object
        """
        # Read version
        version = reader.read_int32()

        if cls.VALID_VERSIONS and version not in cls.VALID_VERSIONS:
            raise ArkParseError(f"Unsupported {cls.__name__} version {version}. Expected one of: {cls.VALID_VERSIONS}")

        # Detect ASE vs ASA
        is_asa = cls._detect_asa(reader, version)

        if is_asa and version >= 7:
            # Only cloud inventory (version 7+) has extra header fields before object count
            _unknown1 = reader.read_int32()
            _unknown2 = reader.read_int32()

        # Read object count
        object_count = reader.read_int32()

        if object_count < 0 or object_count > 1000000:
            raise ArkParseError(f"Invalid object count: {object_count}")

        # Read object headers
        objects: list[GameObject] = []
        for i in range(object_count):
            obj = cls._read_object_header(reader, obj_id=i, is_asa=is_asa, version=version)
            objects.append(obj)

        # For profile/tribe/obelisk files (version 1), propertiesOffset is absolute from file start
        # For world save files (version 5-7+), propertiesOffset is relative to a base offset in the header
        # Since we're parsing simple files here, we use absolute offsets (properties_block_offset = 0)
        properties_block_offset = 0

        # Load properties for each object
        # Properties are read in order, with each object's properties
        # starting at its propertiesOffset (absolute from file start for these file types)
        for i, obj in enumerate(objects):
            # Get next object for boundary checking (optional)
            next_obj = objects[i + 1] if i + 1 < len(objects) else None
            obj.load_properties(
                reader, properties_block_offset=properties_block_offset, is_asa=is_asa, next_object=next_obj
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
    def _read_object_header(cls, reader: BinaryReader, obj_id: int, is_asa: bool, version: int = 7) -> GameObject:
        """
        Read an object header in ASE or ASA format.

        ASE object header:
        - Class name (string)
        - Item1 flag (int32)
        - Item2 flag (int32)
        - Names (string array)
        - IsItem flag (int32, 0 or 1)
        - More fields...

        ASA object header:
        - GUID (16 bytes)
        - Class name (string)
        - Field1 (int32) - unknown purpose
        - names_count (int32) - number of name strings to read
        - Names array (names_count strings)
        - Padding (20 bytes): 12 zeros + Int32 properties_offset + 4 zeros
        """
        if is_asa:
            obj = GameObject(id=obj_id)

            # Read GUID
            guid = reader.read_guid()
            obj.guid = str(guid)

            # Class name
            obj.class_name = reader.read_string()

            # Unknown field and names count
            _field1 = reader.read_int32()
            names_count = reader.read_int32()

            # Read all names (first is typically instance name, rest are world context)
            names = []
            for _ in range(names_count):
                name = reader.read_string()
                names.append(name)
            obj.names = names

            # Read padding/metadata after names:
            # Layout: 12 zero bytes + int32 properties_offset + 4 zero bytes = 20 bytes
            # The stored properties_offset for v7 points to one byte before the actual
            # properties start. That byte is a 0x00 terminator in most single-object
            # files; in multi-object files, that byte is the first byte of the next
            # object's GUID (non-zero). Either way, actual properties = stored + 1 for v7.
            # For v6, the stored offset IS the exact properties start (no +1 needed).
            reader.skip(12)  # 12 padding zeros
            stored_props_offset = reader.read_int32()  # stored absolute file offset
            reader.skip(4)  # 4 trailing zeros
            # Consume the optional 0x00 terminator byte if present (most v7 single-obj files)
            if version >= 7 and reader.remaining > 0 and reader.peek_bytes(1)[0] == 0x00:
                reader.skip(1)

            obj.properties_offset = stored_props_offset + (1 if version >= 7 else 0)

            return obj
        else:
            return GameObject.read_header(reader, obj_id=obj_id, is_asa=False)

    @classmethod
    def _detect_asa(cls, reader: BinaryReader, version: int) -> bool:
        """
        Detect if this is an ASA format file.

        Detection heuristics:
        - Version 7+ is typically ASA (cloud inventory/obelisk)
        - Version 6 with non-zero GUID at offset 8 is ASA (profiles/tribes)
        - Version 6 with zeros at offset 8 is ASE

        File structure at this point (after reading version):
        - ASE: object_count (4) + zeros (16) + object headers
        - ASA: object_count (4) + GUID (16) + object headers

        The GUID check distinguishes ASE v6 world saves from ASA profiles.
        """
        # Version 7+ is always ASA
        if version >= 7:
            return True

        # Version 6 could be either ASE world save or ASA profile/tribe
        # Check for non-zero GUID at offset 8 (after version + object_count)
        if version == 6:
            # Save position after version read
            current_pos = reader.position
            # Skip object_count (4 bytes) to reach potential GUID position
            reader.skip(4)
            # Read 16 bytes that would be GUID in ASA or zeros in ASE
            guid_bytes = reader.read_bytes(16)
            # Restore position
            reader.position = current_pos
            # If any byte is non-zero, it's ASA (has a GUID)
            if any(b != 0 for b in guid_bytes):
                return True

        return False

    def get_property_value(self, name: str, default: t.Any = None, from_main: bool = True) -> t.Any:
        """
        Get a property value from the main object.

        Args:
            name: Property name to look up
            default: Default value if not found
            from_main: If True, get from main object. If False, search all objects.

        Returns:
            Property value or default
        """
        if from_main and self.main_object:
            return self.main_object.get_property_value(name, default)

        # Search all objects
        for obj in self.objects:
            value = obj.get_property_value(name)
            if value is not None:
                return value
        return default

    def to_dict(self) -> dict[str, t.Any]:
        """
        Convert to a dictionary representation.

        Returns:
            Dictionary with file data
        """
        return {
            "version": self.version,
            "is_asa": self.is_asa,
            "object_count": len(self.objects),
            "main_object": self.main_object.to_dict() if self.main_object else None,
            "objects": [obj.to_dict() for obj in self.objects],
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(version={self.version}, objects={len(self.objects)}, is_asa={self.is_asa})"
