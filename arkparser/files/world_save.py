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

import datetime as dt
import logging
import sqlite3
import typing as t
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from ..common.binary_reader import BinaryReader
from ..common.exceptions import ArkParseError, CorruptDataError
from ..common.normalization import normalize_indexed_data, normalize_indexed_list
from ..data_models import CryopodCreature
from ..game_objects.container import GameObjectContainer
from ..game_objects.game_object import MAX_OBJECT_COUNT, GameObject
from ..game_objects.location import LocationData
from ..properties.registry import read_properties

logger = logging.getLogger(__name__)

# ASE GUIDs are always all-zero; precomputed sentinel skips UUID construction.
_ZERO_GUID = b"\x00" * 16

# Upper bound on ASA name-table entries (largest observed real table ~4.6k).
# A count above this means the read is misaligned (a garbage int32 length),
# so we fail loudly instead of looping over ~billions of phantom entries.
_MAX_ASA_NAME_TABLE = 1_000_000


def _checked_count(reader: BinaryReader, label: str, maximum: int = MAX_OBJECT_COUNT) -> int:
    """Read a length-prefix int32 and reject corrupt/implausible values.

    Power-of-10 rule 2 (fixed loop bounds): every count that drives a read
    loop must be provably bounded. A negative or absurd count means a
    misaligned/corrupt header; raise ``CorruptDataError`` (NOT ``assert`` -
    asserts vanish under ``python -O``) rather than looping over billions of
    phantom entries (OOM/hang).
    """
    if reader.remaining < 4:
        raise CorruptDataError(f"{label}: truncated before count int32")
    count = reader.read_int32()
    if not 0 <= count <= maximum:
        raise CorruptDataError(f"{label}: implausible count {count} (corrupt/misaligned read)")
    return count


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

    Call :meth:`load` with any ``.ark`` file; the format is auto-detected:

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
        container: Relationship-aware object container (ASE only; ``None`` for ASA).
        actor_locations: GUID → location mapping (ASA only; empty dict for ASE).
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
    # Wall-clock mtime of the source .ark file (None when loaded from bytes).
    # Used to convert in-game ``OriginalCreationTime`` to real timestamps,
    # matching the legacy ContentContainer.GetApproxDateTimeOf formula:
    # real = file_mtime + (object_time - game_time).
    file_mtime: dt.datetime | None = None

    # ASE-specific
    embedded_data: list[EmbeddedData] = field(default_factory=list)
    data_files_object_map: dict[int, list[list[str]]] = field(default_factory=dict)
    container: GameObjectContainer = field(default_factory=GameObjectContainer)

    # ASA-specific
    actor_locations: dict[str, LocationData] = field(default_factory=dict)

    # Caller-assembled sidecars (NOT parsed from the .ark): the orchestrator
    # globs the map dir for *.arkprofile / *.arktribe and assigns these before
    # calling export_all, which reads them to enrich player/tribe records.
    # Default to empty lists so export still runs when no sidecars are loaded.
    profiles: list[t.Any] = field(default_factory=list)
    tribes: list[t.Any] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Internal state
    # ------------------------------------------------------------------
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

        local_tz = dt.datetime.now().astimezone().tzinfo
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=local_tz)

        if header.startswith(SQLITE_MAGIC):
            save = cls._parse_asa(path, load_properties, max_objects)
        else:
            reader = BinaryReader.from_file(path)
            save = cls._parse_ase(reader, load_properties)
        save.file_mtime = mtime
        return save

    # ------------------------------------------------------------------
    # Convenience queries
    # ------------------------------------------------------------------

    def get_object_by_guid(self, guid: str) -> GameObject | None:
        """Get an object by its GUID string."""
        return self.container.get_by_guid(guid)

    def get_actor_location(self, guid: str) -> LocationData | None:
        """Get the location of an actor by GUID (ASA saves only)."""
        return self.actor_locations.get(guid)

    def get_objects_by_class(self, class_name: str) -> list[GameObject]:
        """Return all objects whose ``class_name`` contains *class_name*."""
        return self.container.find_by_class_pattern(class_name)

    # TargetingTeam threshold: the C# reference (TeamType.cs) uses 50_000 as the
    # boundary between non-player (wild/AI) and player-owned teams.
    _PLAYER_TEAM_THRESHOLD: t.ClassVar[int] = 50_000
    # Unclaimed babies use 2_000_000_000 as a sentinel; still tamed.
    _BREEDING_SENTINEL: t.ClassVar[int] = 2_000_000_000

    # Property names that indicate a creature was tamed by a player. Cryo'd
    # creatures often have their TargetingTeam stripped to 0 while keeping
    # these markers, so we check them as a fallback after the team-id rule.
    _TAMED_MARKER_PROPERTIES: t.ClassVar[tuple[str, ...]] = (
        "TamerString",
        "TamedName",
        "TamedAtTime",
        "TribeName",
        "TamedOnServerName",
        "UploadedFromServerName",
        "ImprinterName",
        "ImprinterPlayerDataID",
        "TamingTeamID",
    )

    def _is_tamed_creature(self, obj: GameObject) -> bool:
        """Return ``True`` if a creature is player-owned.

        Two paths:
        - Primary (C# parity, GameObjectExtensions.IsTamed): targeting_team
          ``>= 50_000``. The breeding sentinel (``2_000_000_000``) is also
          considered tamed because it falls above the threshold.
        - Fallback for cryo'd creatures: ARK strips ``TargetingTeam`` on
          cryopod'd dinos but retains ``TamerString``/``TamedName``/
          ``TamingTeamID``/etc. Without this fallback we lose every cryo'd
          tame on the map. (Restored from the pre-0.1.x parser behavior;
          dropping it caused a ~2k-tame regression on live PvE servers.)
        """
        targeting_team = obj.get_property_value("TargetingTeam")
        if isinstance(targeting_team, (int, float)):
            if int(targeting_team) >= self._PLAYER_TEAM_THRESHOLD:
                return True
        return any(
            obj.get_property_value(prop_name) not in (None, "", 0, 0.0, False)
            for prop_name in self._TAMED_MARKER_PROPERTIES
        )

    def get_creatures(self) -> list[GameObject]:
        """Return all creature objects (tamed **and** wild)."""
        return self.container.get_creatures()

    def get_tamed_creatures(self) -> list[GameObject]:
        """Return tamed creatures."""
        return [obj for obj in self.get_creatures() if self._is_tamed_creature(obj)]

    def get_wild_creatures(self) -> list[GameObject]:
        """Return wild creatures."""
        return [obj for obj in self.get_creatures() if not self._is_tamed_creature(obj)]

    def get_structures(self) -> list[GameObject]:
        """Return tribe-owned placed structures."""
        return self.container.get_structures()

    def get_player_pawns(self) -> list[GameObject]:
        """Return player character objects currently on the map."""
        return self.container.get_player_pawns()

    def get_items(self) -> list[GameObject]:
        """Return objects with ``is_item`` set."""
        return self.container.get_items()

    def get_terminals(self) -> list[GameObject]:
        """Return map-placed terminal objects."""
        return self.container.get_terminals()

    def get_supply_drops(self) -> list[GameObject]:
        """Return active supply-drop / loot-crate objects on the map."""
        return self.container.get_supply_drops()

    def get_artifact_crates(self) -> list[GameObject]:
        """Return artifact-crate spawn objects."""
        return self.container.get_artifact_crates()

    def get_map_resources(self) -> list[GameObject]:
        """Return engine-placed resource / vein / node objects."""
        return self.container.get_map_resources()

    def get_nests(self) -> list[GameObject]:
        """Return creature nest objects (wyvern, drake, etc.)."""
        return self.container.get_nests()

    # Class-name fragments that indicate a creature-storage item. Mirrors
    # data_models.UploadedItem.is_cryopod (which matches against blueprint
    # paths); the in-world version matches against the GameObject's
    # ``class_name`` directly.
    _CRYOPOD_PATTERNS: t.ClassVar[tuple[str, ...]] = (
        "Cryopod", "SoulTrap", "Vivarium", "DinoBall",
    )

    def iter_cryopod_creatures(self) -> t.Iterator[tuple[GameObject, CryopodCreature]]:
        """Yield ``(item_obj, CryopodCreature)`` for every *filled* cryopod
        item in the save.

        Why this is needed: when a creature is cryopodded, ARK removes the
        actor from the world and embeds a serialized snapshot of it into the
        cryopod item's ``CustomItemDatas``. Standard creature iteration
        (``get_tamed_creatures``) therefore misses everything in cryo,
        which on busy PvE servers is the majority of a tribe's roster
        (e.g. 2,158 of 2,518 on-map tames on the live SE PvE reference).
        Iterating cryopods here brings them back into view.

        Empty cryopods (no embedded dino) are silently skipped; parsing
        returns ``None`` for them.

        Yields ``(GameObject, CryopodCreature)`` pairs so the caller can
        recover the cryopod's owning structure / location if needed.
        """
        for obj in self.container.objects:
            cn = obj.class_name or ""
            if not any(p in cn for p in self._CRYOPOD_PATTERNS):
                continue
            # In-world cryopod items store their CustomItemDatas directly on
            # the item's properties (cloud-inventory cryopods wrap them in
            # ``ArkTributeItem``, but those are handled by
            # ``UploadedItem.cryopod_creature``).
            custom_datas_raw = obj.get_property_value("CustomItemDatas")
            if custom_datas_raw is None:
                continue
            custom_datas = normalize_indexed_list(custom_datas_raw)
            cryo = None
            for entry in custom_datas:
                if not isinstance(entry, dict):
                    continue
                if entry.get("CustomDataName") != "Dino":
                    continue
                # Byte-blob path (most ASE saves)
                cryo_bytes_wrapper = normalize_indexed_data(
                    entry.get("CustomDataBytes", {})
                )
                byte_arrays: list[t.Any] = []
                if isinstance(cryo_bytes_wrapper, dict):
                    byte_arrays = normalize_indexed_list(
                        cryo_bytes_wrapper.get("ByteArrays")
                    )
                if byte_arrays and isinstance(byte_arrays[0], dict) and "Bytes" in byte_arrays[0]:
                    cryo = CryopodCreature.from_cryopod_bytes(byte_arrays[0]["Bytes"])
                    if cryo is not None:
                        # Supplement with CustomDataStrings/Names when present
                        # (species + color names live there, not in the blob).
                        strings = normalize_indexed_list(entry.get("CustomDataStrings"))
                        if len(strings) > 9 and strings[9]:
                            cryo.species = strings[9]
                        color_names = normalize_indexed_list(entry.get("CustomDataNames"))
                        if color_names:
                            cryo.color_names = [str(n) for n in color_names]
                        break
                # ASA / fallback path (no byte blob, just strings + floats)
                if entry.get("CustomDataStrings"):
                    cryo = CryopodCreature.from_asa_cryopod_data(entry)
                    if cryo is not None:
                        break
            if cryo is not None:
                yield obj, cryo

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

        count = _checked_count(reader, "ASE name table")
        self.name_table = [reader.read_string() for _ in range(count)]

        reader.position = saved

    def _read_ase_data_files(self, reader: BinaryReader) -> None:
        count = _checked_count(reader, "ASE data files")
        self.data_files = [reader.read_string() for _ in range(count)]

    def _read_ase_embedded_data(self, reader: BinaryReader) -> None:
        count = _checked_count(reader, "ASE embedded data")
        self.embedded_data = [EmbeddedData.read(reader) for _ in range(count)]

    def _read_ase_data_files_object_map(self, reader: BinaryReader) -> None:
        count = _checked_count(reader, "ASE data-files object map")
        self.data_files_object_map = {}
        for _ in range(count):
            level = reader.read_int32()
            name_count = _checked_count(reader, "ASE data-files object names")
            names = [reader.read_string() for _ in range(name_count)]
            self.data_files_object_map.setdefault(level, []).append(names)

    def _read_ase_name_from_table(self, reader: BinaryReader) -> str:
        """Read a name-table reference (index + instance)."""
        index, instance = reader.read_int32_pair()
        internal = index - 1
        nt = self.name_table
        if isinstance(nt, list) and 0 <= internal < len(nt):
            name = nt[internal]
        else:
            name = f"__INVALID_NAME_INDEX_{index}__"
        return f"{name}_{instance - 1}" if instance > 0 else name

    def _read_ase_object_header(self, reader: BinaryReader, obj_id: int) -> GameObject:
        """Read a single ASE object header."""
        obj = GameObject(id=obj_id)

        # ASE zero-GUID fast path: skip UUID construction for the common case
        # where every byte is zero. Saves ~65k UUID() calls per save.
        guid_bytes = reader.read_bytes(16)
        if guid_bytes == _ZERO_GUID:
            obj.guid = ""
        else:
            obj.guid = str(UUID(bytes_le=guid_bytes))

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
        count = _checked_count(reader, "ASE objects")
        self.objects = [self._read_ase_object_header(reader, i) for i in range(count)]

    def _read_ase_object_properties(self, reader: BinaryReader) -> None:
        """Load properties for every ASE object."""
        name_table = self.name_table if self.version > 5 and isinstance(self.name_table, list) else None

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
            except Exception as exc:
                logger.debug(
                    "Failed to load properties for object %s",
                    obj.class_name,
                    exc_info=True,
                )
                self._parse_errors.append(f"{obj.class_name or obj.id}: {exc}")

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

        conn = None
        try:
            conn = sqlite3.connect(str(path))
            save._read_asa_header(conn)
            # Actor locations are positional enrichment, not load-critical. A
            # malformed/padded ActorTransforms blob must not abort the whole
            # save — record it and continue with object data only. (EndOfDataError
            # subclasses ArkParseError, so this catches both.)
            try:
                save._read_asa_actor_locations(conn)
            except ArkParseError as e:
                save._parse_errors.append(f"ActorTransforms: {e}")
            save._read_asa_game_objects(conn, load_properties, max_objects)
        except sqlite3.Error as e:
            raise ArkParseError(f"SQLite error reading ASA world save: {e}")
        finally:
            if conn is not None:
                conn.close()

        save.container = GameObjectContainer(objects=save.objects)
        save.container.build_relationships()

        return save

    def _read_asa_header(self, conn: sqlite3.Connection) -> None:
        """Parse the ``SaveHeader`` blob."""
        cursor = conn.execute("SELECT value FROM custom WHERE key = 'SaveHeader'")
        row = cursor.fetchone()
        if row is None:
            raise ArkParseError("SaveHeader not found in ASA world save")

        reader = BinaryReader.from_bytes(row[0])

        self.version = reader.read_int16()
        legacy_offset = reader.read_int32()
        # v14+ adds two int32 fields (unk1, name_table_offset) between
        # legacy_offset and game_time; v13 saves jump straight to game_time.
        # Without this version gate we mis-align the read by 8 bytes and the
        # data_files loop walks into garbage.
        name_table_offset = legacy_offset  # v13: table follows the parts section
        if self.version >= 14:
            _unknown1 = reader.read_int32()
            name_table_offset = reader.read_int32()  # absolute offset of name table
        self.game_time = reader.read_double()
        _unknown2 = reader.read_int32()

        # Data files (immediately follow the header; populate self.data_files).
        count = _checked_count(reader, "ASA data files")
        self.data_files = []
        for _ in range(count):
            self.data_files.append(reader.read_string())
            _term = reader.read_int32()  # per-entry terminator, always -1

        # Name table (dict keyed by FName hash for ASA).
        #
        # v14+: the engine stores the table at an explicit absolute offset
        # (name_table_offset = the 2nd int32 after legacy_offset). The bytes
        # between the data-files section and that offset are NOT a fixed pad
        # pair on every map - on busy/modded saves (measured: Ragnarok +26 B,
        # Scorched Earth +31 B past where a sequential read lands) the table
        # would be read truncated, leaving ~half the class refs resolving to
        # __UNKNOWN_CLASS_<hash>__. Seek to the offset like the C# reference
        # (AsaSavegame.readNametable: ``archive.Position = nameTableOffset``).
        # Where the gap is zero (TheIsland, Aberration, Extinction) the seek is
        # a no-op; where it drifts it recovers every leaked class name.
        if self.version >= 14:
            # Explicit raise (not assert) so the bound survives ``python -O``.
            if not 0 <= name_table_offset <= reader.size:
                raise CorruptDataError(
                    f"ASA name-table offset {name_table_offset} out of range "
                    f"(blob size {reader.size})"
                )
            reader.position = name_table_offset
            self.name_table = self._read_asa_name_table(reader)
        else:
            # v13: no explicit offset field. Retain the historical sequential
            # read (two pad int32s, then the table) - there is no live v13
            # fixture to validate a seek against. The idx==1 sentinel consumes
            # the 4-byte trailer on user-placed-actor entries.
            reader.read_int32()  # pad1
            reader.read_int32()  # pad2
            self.name_table = self._read_asa_name_table(reader, sentinel=True)

    def _read_asa_name_table(
        self, reader: BinaryReader, sentinel: bool = False
    ) -> dict[int, str]:
        """Read an ASA name table (FName-hash -> class string) at ``reader``'s position.

        Preconditions: ``reader`` is positioned at the table's int32 entry
        count. Postconditions: returns ``{hash: trimmed_class_string}`` (the
        substring after the last ``.``) and advances the reader past the table.
        ``sentinel`` consumes the extra 4-byte trailer following
        user-placed-actor entries (``idx == 1``) on the v13 sequential path; it
        is unused on the v14 seek path.
        """
        name_count = _checked_count(reader, "ASA name table", _MAX_ASA_NAME_TABLE)
        nt: dict[int, str] = {}
        for _ in range(name_count):
            idx = reader.read_int32()
            raw = reader.read_string()
            nt[idx] = raw.rsplit(".", 1)[-1] if "." in raw else raw
            if sentinel and idx == 1:
                # User-placed-actor sentinel: skip the trailing 4-byte tag.
                reader.skip(4)
        return nt

    def _read_asa_actor_locations(self, conn: sqlite3.Connection) -> None:
        """Parse the ``ActorTransforms`` blob."""
        cursor = conn.execute("SELECT value FROM custom WHERE key = 'ActorTransforms'")
        row = cursor.fetchone()
        if row is None:
            return

        reader = BinaryReader.from_bytes(row[0])
        self.actor_locations = {}

        # Each record is exactly 72 bytes: 16 (GUID) + 6*8 (xyz + pitch/yaw/roll)
        # + 8 (pad). Guard on the full record size so a non-72-aligned tail can't
        # underflow mid-record and raise instead of stopping cleanly.
        while reader.remaining >= 72:
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
        obj_id = 0

        for key_bytes, value_bytes in cursor:
            guid_str = str(UUID(bytes_le=key_bytes))
            try:
                obj = self._parse_asa_game_object(guid_str, value_bytes, obj_id, load_properties)
                if guid_str in self.actor_locations:
                    obj.location = self.actor_locations[guid_str]
                self.objects.append(obj)
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
        reader = BinaryReader(blob, save_version=self.version)
        obj = GameObject(id=obj_id, guid=guid_str)
        nt = self.name_table
        assert isinstance(nt, dict)

        # Object layout per AsaSavegameToolkit (legacy C# reference):
        #   ClassName (name-ref = int32 id + int32 instance)
        #   IsItem (int32 bool)
        #   NameCount (int32)
        #   Names: ReadString() each (v>=13)
        #   DataFileIndex (int32)
        #   Trailer skip: 1 byte (v13) / 2 bytes (v14+)
        class_idx = reader.read_int32()
        obj.class_name = nt.get(class_idx, f"__UNKNOWN_CLASS_{class_idx}__")
        _class_inst = reader.read_int32()
        obj.is_item = reader.read_int32() != 0

        name_count = reader.read_int32()
        obj.names = [reader.read_string() for _ in range(name_count)]

        if reader.remaining < 4:
            obj.properties_offset = reader.position
            return obj
        obj.data_file_index = reader.read_int32()

        trailer = 2 if self.version >= 14 else 1
        if reader.remaining < trailer:
            obj.properties_offset = reader.position
            return obj
        reader.skip(trailer)
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
