"""
World Save parser for .ark map save files.

WorldSave files contain the complete state of an ARK map including:
- All creatures (wild, tamed, hibernating)
- All structures
- All items dropped in the world
- Player and tribe data (in later versions)
- Hibernation data

This is the most complex file type, containing all game objects.

Supports both formats transparently via ``WorldSave.load()``:

ASE World Saves:
    Binary files with version 5-12, using the traditional ARK binary format.

ASA World Saves:
    SQLite databases with tables: game (objects), custom (header/locations/tribes/profiles).
    The key is a 16-byte GUID, the value is a binary blob.
"""

from __future__ import annotations

import logging
import sqlite3
import typing as t
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from ..common.binary_reader import BinaryReader
from ..common.exceptions import ArkParseError
from ..game_objects.container import GameObjectContainer
from ..game_objects.game_object import GameObject
from ..game_objects.location import LocationData
from ..properties.registry import read_properties

logger = logging.getLogger(__name__)


@dataclass
class EmbeddedData:
    """
    Embedded data structure for single-player saves.

    Embedded data is used to store additional map data in single-player
    saves. In server saves, this is typically empty.

    Attributes:
        path: The file path/identifier for this embedded data.
        data: 3D array of byte blobs organized as [parts][blobs][bytes].
    """

    path: str = ""
    data: list[list[bytes]] = field(default_factory=list)

    @classmethod
    def read(cls, reader: BinaryReader) -> EmbeddedData:
        """Read embedded data from binary."""
        path = reader.read_string()

        part_count = reader.read_int32()
        data: list[list[bytes]] = []

        for _ in range(part_count):
            blob_count = reader.read_int32()
            part_data: list[bytes] = []

            for _ in range(blob_count):
                blob_size = reader.read_int32() * 4  # Size is in 32-bit units
                blob_bytes = reader.read_bytes(blob_size)
                part_data.append(blob_bytes)

            data.append(part_data)

        return cls(path=path, data=data)

    @classmethod
    def skip(cls, reader: BinaryReader) -> None:
        """Skip embedded data without parsing."""
        reader.read_string()  # Skip path

        part_count = reader.read_int32()
        for _ in range(part_count):
            blob_count = reader.read_int32()
            for _ in range(blob_count):
                blob_size = reader.read_int32() * 4
                reader.skip(blob_size)


@dataclass
class WorldSave:
    """
    Unified parser for ``.ark`` world save files (ASE binary **and** ASA SQLite).

    Call :meth:`load` with any ``.ark`` file — the format is auto‑detected:

    * **ASE** (versions 5‑12): traditional binary format.
    * **ASA** (SQLite): tables ``game`` (objects) and ``custom``
      (header / locations / tribes / profiles).

    Attributes:
        version: Save format version.
        game_time: In-game time in seconds.
        save_count: Number of times the map has been saved (ASE v9+ only).
        data_files: References to external data files.
        embedded_data: Embedded map data (single-player saves, ASE only).
        data_files_object_map: Maps data-file indices to object names (ASE only).
        name_table: Deduplicated name strings used during parsing.
        objects: All parsed game objects (always a flat list).
        container: Relationship-aware object container (ASE only — ``None`` for ASA).
        actor_locations: GUID → location mapping (ASA only — empty dict for ASE).
        is_asa: Whether this save was loaded from an ASA SQLite file.

    Example::

        >>> from arkparser import WorldSave
        >>> save = WorldSave.load("path/to/TheIsland.ark")   # ASE binary
        >>> save = WorldSave.load("path/to/Extinction_WP.ark")  # ASA SQLite
        >>> print(save.object_count, save.is_asa)
    """

    # ------------------------------------------------------------------
    # Public fields (both formats)
    # ------------------------------------------------------------------
    version: int = 0
    game_time: float = 0.0
    save_count: int = 0
    data_files: list[str] = field(default_factory=list)
    name_table: list[str] | dict[int, str] = field(default_factory=list)
    objects: list[GameObject] = field(default_factory=list)
    is_asa: bool = False

    # ASE-specific
    embedded_data: list[EmbeddedData] = field(default_factory=list)
    data_files_object_map: dict[int, list[list[str]]] = field(default_factory=dict)
    container: GameObjectContainer | None = None

    # ASA-specific
    actor_locations: dict[str, LocationData] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Internal state
    # ------------------------------------------------------------------
    _objects_by_guid: dict[str, GameObject] = field(default_factory=dict, repr=False)
    _parse_errors: list[str] = field(default_factory=list, repr=False)

    # ASE header offsets
    _name_table_offset: int = field(default=0, repr=False)
    _properties_block_offset: int = field(default=0, repr=False)
    _hibernation_offset: int = field(default=0, repr=False)

    # Valid ASE save versions
    VALID_ASE_VERSIONS: t.ClassVar[tuple[int, ...]] = (5, 6, 7, 8, 9, 10, 11, 12)

    # ==================== public API ====================

    @classmethod
    def load(
        cls,
        source: str | Path | bytes,
        load_properties: bool = True,
        max_objects: int | None = None,
    ) -> WorldSave:
        """
        Load a world save from path or bytes.

        Automatically detects ASE (binary) vs ASA (SQLite) format.

        Args:
            source: File path (``str`` or ``Path``) or raw ``bytes``.
            load_properties: Whether to parse per-object properties.
            max_objects: Maximum number of objects to load (ASA only, useful for testing).

        Returns:
            A fully-parsed :class:`WorldSave` instance.

        Raises:
            ArkParseError: If the file cannot be parsed.
            FileNotFoundError: If the file path does not exist.
        """
        SQLITE_MAGIC = b"SQLite format 3\x00"

        if isinstance(source, bytes):
            if source.startswith(SQLITE_MAGIC):
                raise ArkParseError("ASA world saves from raw bytes are not supported. Pass a file path instead.")
            reader = BinaryReader.from_bytes(source)
            return cls._parse_ase(reader, load_properties)

        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        # Peek at first 16 bytes to detect format
        with open(path, "rb") as fh:
            header = fh.read(16)

        if header.startswith(SQLITE_MAGIC):
            return cls._parse_asa(path, load_properties, max_objects)

        reader = BinaryReader.from_file(path)
        return cls._parse_ase(reader, load_properties)

    # ------------------------------------------------------------------
    # Convenience queries
    # ------------------------------------------------------------------

    def get_object_by_guid(self, guid: str) -> GameObject | None:
        """Get an object by its GUID string (efficient for ASA saves)."""
        return self._objects_by_guid.get(guid)

    def get_actor_location(self, guid: str) -> LocationData | None:
        """Get the location of an actor by GUID (ASA saves only)."""
        return self.actor_locations.get(guid)

    def get_objects_by_class(self, class_name: str) -> list[GameObject]:
        """Return all objects whose ``class_name`` contains *class_name*."""
        return [obj for obj in self.objects if class_name in obj.class_name]

    # Class-name patterns that are never structures even though they may
    # carry ``TargetingTeam``.  Checked via ``any(pat in cn for pat ...)``.
    _NON_STRUCTURE_PATTERNS: t.ClassVar[tuple[str, ...]] = (
        "_Character_BP",   # Creatures / tamed dinos
        "DinoCharacter",   # Creature variants
        "PlayerPawn",      # Player avatars on the map
        "Buff_",           # Active buffs
        "PrimalBuff",      # Persistent buff data
        "Weap",            # Held weapons
        "StatusComponent",  # Character/dino status components
        "Inventory",       # Inventory components
        "DroppedItem",     # Dropped items
        "DeathItemCache",  # Death caches
        "NPCZone",        # NPC spawn zones
        "DinoDropInventory",  # Dino death drops
    )

    def get_creatures(self) -> list[GameObject]:
        """Return all creature objects (tamed **and** wild)."""
        return [
            obj
            for obj in self.objects
            if "_Character_BP" in obj.class_name or "DinoCharacter" in obj.class_name
        ]

    def get_tamed_creatures(self) -> list[GameObject]:
        """Return tamed creatures (have ``TamingTeamID`` property)."""
        return [
            obj
            for obj in self.get_creatures()
            if obj.get_property_value("TamingTeamID") is not None
        ]

    def get_wild_creatures(self) -> list[GameObject]:
        """Return wild creatures (no ``TamingTeamID`` property)."""
        return [
            obj
            for obj in self.get_creatures()
            if obj.get_property_value("TamingTeamID") is None
        ]

    def get_structures(self) -> list[GameObject]:
        """Return tribe-owned placed structures.

        Uses property-based classification:
        1. Must have ``TargetingTeam`` (placed by a player/tribe).
        2. Must not have ``DinoID1`` (that would be a creature).
        3. Must not match any non-structure class-name pattern (players,
           buffs, weapons, status components, etc.).
        """
        results: list[GameObject] = []
        for obj in self.objects:
            cn = obj.class_name
            if obj.get_property_value("TargetingTeam") is None:
                continue
            if obj.get_property_value("DinoID1") is not None:
                continue
            if any(pat in cn for pat in self._NON_STRUCTURE_PATTERNS):
                continue
            results.append(obj)
        return results

    def get_player_pawns(self) -> list[GameObject]:
        """Return player character objects currently on the map.

        These are the in-world player avatars (``PlayerPawnTest_*``). Each
        carries ``PlayerName``, ``LinkedPlayerDataID``, ``TribeName``,
        ``TargetingTeam``, a location, and component references for stats
        and inventory.
        """
        return [obj for obj in self.objects if "PlayerPawn" in obj.class_name]

    def get_items(self) -> list[GameObject]:
        """Return objects with ``is_item`` set."""
        return [obj for obj in self.objects if obj.is_item]

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def object_count(self) -> int:
        """Total number of parsed objects."""
        return len(self.objects)

    @property
    def location_count(self) -> int:
        """Total number of actor locations (ASA only)."""
        return len(self.actor_locations)

    @property
    def parse_error_count(self) -> int:
        """Number of parsing errors encountered."""
        return len(self._parse_errors)

    @property
    def parse_errors(self) -> list[str]:
        """Parsing error messages (read-only copy)."""
        return list(self._parse_errors)

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to a dictionary representation (metadata only)."""
        d: dict[str, t.Any] = {
            "version": self.version,
            "game_time": self.game_time,
            "is_asa": self.is_asa,
            "data_files": self.data_files,
            "data_files_count": len(self.data_files),
            "object_count": self.object_count,
            "parse_errors": self.parse_error_count,
        }
        if self.is_asa:
            d["name_table_count"] = len(self.name_table)
            d["location_count"] = self.location_count
        else:
            d["save_count"] = self.save_count
            d["embedded_data_count"] = len(self.embedded_data)
            d["name_table_count"] = len(self.name_table)
        return d

    def __repr__(self) -> str:
        tag = "ASA" if self.is_asa else "ASE"
        return (
            f"WorldSave({tag}, version={self.version}, "
            f"game_time={self.game_time:.1f}s, "
            f"objects={self.object_count}, "
            f"errors={self.parse_error_count})"
        )

    # ==================================================================
    # ASE parsing (binary)
    # ==================================================================

    @classmethod
    def _parse_ase(cls, reader: BinaryReader, load_properties: bool = True) -> WorldSave:
        """
        Parse an ASE binary world save.

        Order:
        1. Header (version, offsets, game_time)
        2. Name table (v6+, at nameTableOffset)
        3. Data files list
        4. Embedded data
        5. Data files object map
        6. Object headers
        7. Object properties
        """
        save = cls()
        save.is_asa = False
        save._parse_errors = []

        save._read_ase_header(reader)

        if save.version > 5 and save._name_table_offset > 0:
            save._read_ase_name_table(reader)

        save._read_ase_data_files(reader)
        save._read_ase_embedded_data(reader)
        save._read_ase_data_files_object_map(reader)
        save._read_ase_objects(reader)

        if load_properties:
            save._read_ase_object_properties(reader)

        save.container = GameObjectContainer(objects=save.objects)
        save.container.build_relationships()

        return save

    def _read_ase_header(self, reader: BinaryReader) -> None:
        """Read the ASE binary header (varies by version)."""
        self.version = reader.read_int16()

        if self.version not in self.VALID_ASE_VERSIONS:
            raise ArkParseError(
                f"Unsupported WorldSave version {self.version}. Expected one of: {self.VALID_ASE_VERSIONS}"
            )

        # Version 11+ has stored-data offsets
        if self.version > 10:
            for _ in range(4):
                _offset = reader.read_int64()
                _size = reader.read_int64()

        # Version 7+ has hibernation offset
        if self.version > 6:
            self._hibernation_offset = reader.read_int32()
            _should_be_zero = reader.read_int32()

        # Version 6+ has name-table / properties-block offsets
        if self.version > 5:
            self._name_table_offset = reader.read_int32()
            self._properties_block_offset = reader.read_int32()

        self.game_time = reader.read_float()

        if self.version > 8:
            self.save_count = reader.read_int32()

    def _read_ase_name_table(self, reader: BinaryReader) -> None:
        """Jump to *nameTableOffset* and read the name table."""
        if self._name_table_offset == 0:
            return

        saved = reader.position
        reader.position = self._name_table_offset

        count = reader.read_int32()
        self.name_table = [reader.read_string() for _ in range(count)]

        reader.position = saved

    def _read_ase_data_files(self, reader: BinaryReader) -> None:
        count = reader.read_int32()
        self.data_files = [reader.read_string() for _ in range(count)]

    def _read_ase_embedded_data(self, reader: BinaryReader) -> None:
        count = reader.read_int32()
        self.embedded_data = [EmbeddedData.read(reader) for _ in range(count)]

    def _read_ase_data_files_object_map(self, reader: BinaryReader) -> None:
        count = reader.read_int32()
        self.data_files_object_map = {}
        for _ in range(count):
            level = reader.read_int32()
            name_count = reader.read_int32()
            names = [reader.read_string() for _ in range(name_count)]
            self.data_files_object_map.setdefault(level, []).append(names)

    def _read_ase_name_from_table(self, reader: BinaryReader) -> str:
        """Read a name-table reference (index + instance)."""
        index = reader.read_int32()
        internal = index - 1
        nt = self.name_table
        if isinstance(nt, list) and 0 <= internal < len(nt):
            name = nt[internal]
        else:
            name = f"__INVALID_NAME_INDEX_{index}__"
        instance = reader.read_int32()
        return f"{name}_{instance - 1}" if instance > 0 else name

    def _read_ase_object_header(self, reader: BinaryReader, obj_id: int) -> GameObject:
        """Read a single ASE object header."""
        obj = GameObject(id=obj_id)

        guid = reader.read_guid()
        obj.guid = str(guid) if any(b != 0 for b in guid.bytes) else ""

        if self.version > 5 and isinstance(self.name_table, list) and self.name_table:
            obj.class_name = self._read_ase_name_from_table(reader)
        else:
            obj.class_name = reader.read_string()

        obj.is_item = reader.read_uint32() != 0

        name_count = reader.read_int32()
        obj.names = []
        for _ in range(name_count):
            if self.version > 5 and isinstance(self.name_table, list) and self.name_table:
                obj.names.append(self._read_ase_name_from_table(reader))
            else:
                obj.names.append(reader.read_string())

        obj.from_data_file = reader.read_uint32() != 0
        obj.data_file_index = reader.read_int32()

        has_location = reader.read_uint32() != 0
        if has_location:
            obj.location = LocationData.read(reader, False)

        obj.properties_offset = reader.read_int32()
        _unknown = reader.read_int32()

        return obj

    def _read_ase_objects(self, reader: BinaryReader) -> None:
        count = reader.read_int32()
        self.objects = [self._read_ase_object_header(reader, i) for i in range(count)]

    def _read_ase_object_properties(self, reader: BinaryReader) -> None:
        """Load properties for every ASE object."""
        name_table = self.name_table if self.version > 5 and isinstance(self.name_table, list) else None
        failures = 0

        for i, obj in enumerate(self.objects):
            next_obj = self.objects[i + 1] if i + 1 < len(self.objects) else None
            try:
                obj.load_properties(
                    reader,
                    properties_block_offset=self._properties_block_offset,
                    is_asa=False,
                    next_object=next_obj,
                    name_table=name_table,
                )
            except Exception:
                logger.debug(
                    "Failed to load properties for object %s",
                    obj.class_name,
                    exc_info=True,
                )
                failures += 1

    # ==================================================================
    # ASA parsing (SQLite)
    # ==================================================================

    @classmethod
    def _parse_asa(
        cls,
        path: Path,
        load_properties: bool = True,
        max_objects: int | None = None,
    ) -> WorldSave:
        """Parse an ASA SQLite world save."""
        save = cls()
        save.is_asa = True
        save._parse_errors = []

        try:
            conn = sqlite3.connect(str(path))
            save._read_asa_header(conn)
            save._read_asa_actor_locations(conn)
            save._read_asa_game_objects(conn, load_properties, max_objects)
            conn.close()
        except sqlite3.Error as e:
            raise ArkParseError(f"SQLite error reading ASA world save: {e}")

        return save

    def _read_asa_header(self, conn: sqlite3.Connection) -> None:
        """Parse the ``SaveHeader`` blob."""
        cursor = conn.execute("SELECT value FROM custom WHERE key = 'SaveHeader'")
        row = cursor.fetchone()
        if row is None:
            raise ArkParseError("SaveHeader not found in ASA world save")

        reader = BinaryReader.from_bytes(row[0])

        self.version = reader.read_int16()
        _legacy_offset = reader.read_int32()
        _unknown1 = reader.read_int32()
        _actual_offset = reader.read_int32()
        self.game_time = reader.read_double()
        _unknown2 = reader.read_int32()

        # Data files
        count = reader.read_int32()
        self.data_files = []
        for _ in range(count):
            self.data_files.append(reader.read_string())
            _term = reader.read_int32()

        _pad1 = reader.read_int32()
        _pad2 = reader.read_int32()

        # Name table (dict keyed by hash for ASA)
        name_count = reader.read_int32()
        nt: dict[int, str] = {}
        for _ in range(name_count):
            idx = reader.read_int32()
            raw = reader.read_string()
            nt[idx] = raw.rsplit(".", 1)[-1] if "." in raw else raw
        self.name_table = nt

    def _read_asa_actor_locations(self, conn: sqlite3.Connection) -> None:
        """Parse the ``ActorTransforms`` blob."""
        cursor = conn.execute("SELECT value FROM custom WHERE key = 'ActorTransforms'")
        row = cursor.fetchone()
        if row is None:
            return

        reader = BinaryReader.from_bytes(row[0])
        self.actor_locations = {}

        while reader.remaining >= 16:
            guid_bytes = reader.read_bytes(16)
            if all(b == 0 for b in guid_bytes):
                break

            guid_str = str(UUID(bytes_le=guid_bytes))
            x, y, z = reader.read_double(), reader.read_double(), reader.read_double()
            pitch, yaw, roll = reader.read_double(), reader.read_double(), reader.read_double()
            reader.skip(8)

            self.actor_locations[guid_str] = LocationData(
                x=x,
                y=y,
                z=z,
                pitch=pitch,
                yaw=yaw,
                roll=roll,
            )

    def _read_asa_game_objects(
        self,
        conn: sqlite3.Connection,
        load_properties: bool = True,
        max_objects: int | None = None,
    ) -> None:
        """Read all game objects from the ``game`` table."""
        query = "SELECT key, value FROM game"
        if max_objects is not None:
            query += f" LIMIT {max_objects}"

        cursor = conn.execute(query)
        self.objects = []
        self._objects_by_guid = {}
        obj_id = 0

        for key_bytes, value_bytes in cursor:
            guid_str = str(UUID(bytes_le=key_bytes))
            try:
                obj = self._parse_asa_game_object(guid_str, value_bytes, obj_id, load_properties)
                if guid_str in self.actor_locations:
                    obj.location = self.actor_locations[guid_str]
                self.objects.append(obj)
                self._objects_by_guid[guid_str] = obj
                obj_id += 1
            except Exception as e:
                self._parse_errors.append(f"GUID {guid_str}: {e}")

    def _parse_asa_game_object(
        self,
        guid_str: str,
        blob: bytes,
        obj_id: int,
        load_properties: bool = True,
    ) -> GameObject:
        """Parse a single ASA game object from its binary blob."""
        reader = BinaryReader.from_bytes(blob)
        obj = GameObject(id=obj_id, guid=guid_str)
        nt = self.name_table
        assert isinstance(nt, dict)

        # Class name from name-table index
        class_idx = reader.read_int32()
        obj.class_name = nt.get(class_idx, f"__UNKNOWN_CLASS_{class_idx}__")
        _class_inst = reader.read_int32()
        _zeros = reader.read_int32()

        # Inline names
        name_count = reader.read_int32()
        obj.names = [reader.read_string() for _ in range(name_count)]
        _end_marker = reader.read_int32()

        # Object type flag
        if reader.remaining < 2:
            obj.is_item = False
            obj.properties_offset = reader.position
            return obj

        obj.is_item = reader.read_uint16() == 1
        obj.properties_offset = reader.position

        if load_properties:
            try:
                obj.properties = read_properties(
                    reader,
                    is_asa=True,
                    name_table=nt,
                    worldsave_format=True,
                )
            except Exception as e:
                self._parse_errors.append(f"Properties for {obj.class_name} ({guid_str}): {e}")

        return obj

    def _read_asa_name_from_table(self, reader: BinaryReader) -> str:
        """Read a name-table reference in ASA format."""
        index = reader.read_int32()
        nt = self.name_table
        assert isinstance(nt, dict)
        name = nt.get(index, f"__UNKNOWN_NAME_{index}__")
        instance = reader.read_int32()
        return f"{name}_{instance - 1}" if instance > 0 else name
