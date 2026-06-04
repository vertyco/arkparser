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
import sys
import typing as t
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from ..common.binary_reader import BinaryReader, guid_str_le
from ..common.exceptions import ArkParseError, CorruptDataError
from ..common.normalization import normalize_indexed_data, normalize_indexed_list
from ..data_models import CryopodCreature
from ..game_objects.container import GameObjectContainer
from ..game_objects.game_object import MAX_OBJECT_COUNT, GameObject
from ..game_objects.location import LocationData
from ..properties.registry import read_properties, read_properties_partial

logger = logging.getLogger(__name__)

# ASE GUIDs are always all-zero; precomputed sentinel skips UUID construction.
_ZERO_GUID = b"\x00" * 16

# Upper bound on ASA name-table entries (largest observed real table ~4.6k).
# A count above this means the read is misaligned (a garbage int32 length),
# so we fail loudly instead of looping over ~billions of phantom entries.
_MAX_ASA_NAME_TABLE = 1_000_000

# Evictions between working-set trims on lazy saves. At ~1KB of property
# bytes per object this bounds the resident mmap-page window to a few
# hundred MB; saves smaller than one interval never trim (zero overhead).
_TRIM_INTERVAL_OBJECTS = 200_000


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

    # Retained ASE reader for lazy property loading. Set only when the save is
    # loaded with ``lazy_properties=True``; ``None`` on the default eager path.
    # Holds the file byte buffer open so :meth:`materialize_object` can seek to
    # any object's ``properties_offset`` and parse it on demand. The foundation
    # for the chunked single-pass export (see docs streaming-refactor design).
    _lazy_reader: BinaryReader | None = field(default=None, repr=False)

    # Retained ASA SQLite connection, the ASA counterpart of ``_lazy_reader``.
    # Set only when an ASA save is loaded with ``lazy_properties=True``;
    # :meth:`materialize_object` re-fetches an object's row blob by GUID and
    # parses its property block on demand, so blobs never accumulate on the
    # Python heap (SQLite's page cache bounds the resident file window).
    _lazy_conn: sqlite3.Connection | None = field(default=None, repr=False)

    # Raw 16-byte ``game`` row keys indexed by object id, captured during the
    # lazy ASA header pass. Saves a UUID string parse per materialization
    # (hundreds of thousands per export). Empty on eager and ASE paths.
    _asa_row_keys: list[bytes] = field(default_factory=list, repr=False)

    # Reused cursor for materialization fetches (cursor creation is ~20% of a
    # single-row SELECT's cost at this call volume).
    _lazy_cursor: sqlite3.Cursor | None = field(default=None, repr=False)

    # Eviction ring: every materialize_object() appends here so walk drivers
    # can release everything touched since the last drain with one
    # evict_materialized() call, without per-site bookkeeping. Empty on the
    # eager path. Eviction is always correctness-safe: a later access simply
    # re-materializes (idempotent), so drains may be sprinkled liberally.
    _lazy_materialized: list[GameObject] = field(default_factory=list, repr=False)

    # Objects evicted since the last working-set trim. Long lazy exports touch
    # every mmap page in the retained reader; without periodic trims those
    # clean file-backed pages pile up in the working set until peak RSS is
    # heap + whole file size. Counted here so small saves (under one trim
    # interval) never pay for a trim at all.
    _evicted_since_trim: int = field(default=0, repr=False)

    # Memoized creature list shared by the tamed/wild filters. Creature
    # classification walks (and on lazy saves, re-parses) the whole object
    # graph; without this cache get_tamed_creatures and get_wild_creatures
    # each ran that walk independently.
    _creatures_cache: list[GameObject] | None = field(default=None, repr=False)

    # Memoized (tamed, wild) split, partitioned from the TargetingTeam values
    # the fused classification pass captured (container._classified_teams).
    _creature_split_cache: tuple[list[GameObject], list[GameObject]] | None = field(
        default=None, repr=False
    )

    # Per-pod display summary (dino_id, creature, name) keyed by cryopod item
    # object id. Decoding a pod blob (zlib + full property parse) is one of
    # the most expensive operations in an export, and each pod is otherwise
    # decoded twice: once for its ASV_Tamed record and again when the
    # inventory holding it (cryofridge, pawn, vault) lists its contents.
    # The tamed pass populates this; inventory listings read it. ~150 bytes
    # per pod vs several KB for a retained full decode.
    _cryo_summaries: dict[int, tuple[int, str, str] | None] = field(
        default_factory=dict, repr=False
    )

    # Valid ASE save versions
    VALID_ASE_VERSIONS: t.ClassVar[tuple[int, ...]] = (5, 6, 7, 8, 9, 10, 11, 12)

    # ==================== public API ====================

    @classmethod
    def load(
        cls,
        source: str | Path | bytes,
        load_properties: bool = True,
        max_objects: int | None = None,
        lazy_properties: bool = False,
    ) -> WorldSave:
        """
        Load a world save from path or bytes.

        Automatically detects ASE (binary) vs ASA (SQLite) format.

        Args:
            source: File path (``str`` or ``Path``) or raw ``bytes``.
            load_properties: Whether to parse per-object properties.
            max_objects: Maximum number of objects to load (ASA only, useful for testing).
            lazy_properties: When ``True``, skip the eager per-object property
                pass; properties load on demand via :meth:`materialize_object`
                (and free via :meth:`GameObject.evict_properties`). ASE retains
                the file reader and seeks per object; ASA retains the SQLite
                connection and re-fetches each object's row blob by GUID.
                Default ``False`` keeps the eager behaviour.

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
            return cls._parse_ase(reader, load_properties, lazy_properties)

        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        # Peek at first 16 bytes to detect format
        with open(path, "rb") as fh:
            header = fh.read(16)

        local_tz = dt.datetime.now().astimezone().tzinfo
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=local_tz)

        if header.startswith(SQLITE_MAGIC):
            save = cls._parse_asa(path, load_properties, max_objects, lazy_properties)
        else:
            if lazy_properties:
                # The lazy reader stays alive for the whole export; an mmap
                # buffer keeps the file contents out of the Python heap and
                # lets the OS reclaim pages under pressure.
                reader = BinaryReader.from_file_mmap(path)
            else:
                reader = BinaryReader.from_file(path)
            save = cls._parse_ase(reader, load_properties, lazy_properties)
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
    def get_creatures(self) -> list[GameObject]:
        """Return all creature objects (tamed **and** wild)."""
        return self.container.get_creatures()

    def get_tamed_creatures(self) -> list[GameObject]:
        """Return tamed creatures."""
        return self._split_creatures()[0]

    def get_wild_creatures(self) -> list[GameObject]:
        """Return wild creatures."""
        return self._split_creatures()[1]

    def _split_creatures(self) -> tuple[list[GameObject], list[GameObject]]:
        """Classify creatures into ``(tamed, wild)`` in one materializing pass.

        Tame rule matches legacy ``GameObjectExtensions.IsTamed`` exactly: a
        creature is tamed iff ``TargetingTeam`` is a player team (``>= 50_000``;
        the breeding sentinel ``2_000_000_000`` falls above the threshold).
        Teams ``< 50_000`` (or a missing/non-numeric team) are wild / AI. Do not
        add marker-property fallbacks (``TamingTeamID`` / ``TamerString``): that
        mis-classified 14 wild creatures on TheIsland while catching 0 real
        tames. Cryopod-embedded tames are not world actors; they surface via
        :meth:`iter_cryopod_creatures`.

        Pre: ``self.objects`` parsed (headers at minimum). Post: split cached.
        The partition is pure dict lookups against the ``TargetingTeam`` values
        the fused classification pass captured (``container._classified_teams``)
        while each property block was resident, so it parses nothing; previously
        the tamed and wild filters each re-ran (and on lazy saves re-parsed) a
        full creature walk.
        """
        if self._creature_split_cache is not None:
            return self._creature_split_cache
        if self._creatures_cache is None:
            self._creatures_cache = self.get_creatures()
        # The fused classification pass (container._classify_world) captured
        # every creature's TargetingTeam while its property block was resident,
        # so this partition is pure dict lookups: no parsing, no draining. A
        # creature absent from the map had a missing/non-numeric team -> wild.
        teams = self.container._classified_teams
        tamed: list[GameObject] = []
        wild: list[GameObject] = []
        for obj in self._creatures_cache:
            team = teams.get(obj.id)
            if team is not None and team >= self._PLAYER_TEAM_THRESHOLD:
                tamed.append(obj)
            else:
                wild.append(obj)
        assert len(tamed) + len(wild) == len(self._creatures_cache), "split lost creatures"
        self._creature_split_cache = (tamed, wild)
        return self._creature_split_cache

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
    def _parse_ase(
        cls,
        reader: BinaryReader,
        load_properties: bool = True,
        lazy_properties: bool = False,
    ) -> WorldSave:
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

        if lazy_properties:
            # Defer property parsing: retain the reader so each object loads on
            # demand via materialize_object and frees via evict_properties.
            # Wiring _lazy_source makes property access auto-materialize via
            # GameObject._ensure_loaded, so every existing reader of these
            # objects (classifiers, record builders, resolvers) works unchanged.
            save._lazy_reader = reader
            for obj in save.objects:
                obj._lazy_source = save
        elif load_properties:
            save._read_ase_object_properties(reader)

        save.container = GameObjectContainer(objects=save.objects)
        # build_relationships reads only header names (not properties), so it is
        # safe under lazy loading and does not force materialization.
        save.container.build_relationships()

        return save

    def materialize_object(
        self, obj: GameObject, names: frozenset[str] | None = None
    ) -> None:
        """Lazy-load one object's properties (ASE reader seek / ASA row fetch).

        Pre: the save was loaded with ``lazy_properties=True``, so
        ``_lazy_reader`` (ASE) or ``_lazy_conn`` (ASA) is set and ``obj`` is
        one of ``self.objects``. Post: ``obj.properties`` is populated
        (idempotent: re-parses if called again, which is harmless and used by
        callers that evicted in between).

        ``names`` is a perf hint for ASA v14+ saves: decode only those
        property names and skip the rest (a verified byte-exact skip walk),
        leaving ``obj.properties`` holding just the requested subset. Callers
        must evict before anything else reads the object. Ignored on ASE and
        v13 (full parse, still correct).
        """
        if self.is_asa:
            self._materialize_asa_object(obj, names)
            self._lazy_materialized.append(obj)
            return
        assert self._lazy_reader is not None, "materialize_object requires lazy_properties=True"
        idx = obj.id
        next_obj = self.objects[idx + 1] if 0 <= idx and idx + 1 < len(self.objects) else None
        name_table = self.name_table if self.version > 5 and isinstance(self.name_table, list) else None
        try:
            obj.load_properties(
                self._lazy_reader,
                properties_block_offset=self._properties_block_offset,
                is_asa=False,
                next_object=next_obj,
                name_table=name_table,
            )
        except Exception as exc:  # noqa: BLE001 - mirror the eager pass
            # The eager pass (_read_ase_object_properties) swallows per-object
            # parse failures, records them, and keeps the partial properties.
            # Lazy materialization must behave identically or a corrupt object
            # would crash lazy exports that eager exports survive.
            # load_properties marks the object loaded before raising, so this
            # does not retry (and re-log) on every subsequent access.
            err = f"{obj.class_name or obj.id}: {exc}"
            if err not in self._parse_errors:
                self._parse_errors.append(err)
        self._lazy_materialized.append(obj)

    def _materialize_asa_object(
        self, obj: GameObject, names: frozenset[str] | None = None
    ) -> None:
        """Lazy-load one ASA object's properties from its SQLite row.

        Pre: the save was loaded with ``lazy_properties=True`` (ASA), so
        ``_lazy_conn`` is open and ``obj.guid`` is the row key in the ``game``
        table. Post: ``obj._props_loaded`` is True; ``obj.properties`` holds
        the parsed block, or stays empty on a parse failure (mirroring the
        eager pass, which records the error and keeps the object). With
        ``names`` set (v14+ only), the block is partially decoded via the
        verified skip walk; the caller owns evicting before other readers
        touch the object.
        """
        conn = self._lazy_conn
        assert conn is not None, "materialize_object requires lazy_properties=True"
        assert obj.guid, "ASA object missing its row GUID"
        keys = self._asa_row_keys
        key = keys[obj.id] if 0 <= obj.id < len(keys) else UUID(obj.guid).bytes_le
        cursor = self._lazy_cursor
        if cursor is None:
            cursor = conn.cursor()
            self._lazy_cursor = cursor
        row = cursor.execute("SELECT value FROM game WHERE key = ?", (key,)).fetchone()
        if row is None:
            # Mark loaded so a vanished row cannot retry on every access.
            obj._props_loaded = True
            err = f"Properties for {obj.class_name} ({obj.guid}): game row missing"
            if err not in self._parse_errors:
                self._parse_errors.append(err)
            return
        self._materialize_asa_from_blob(obj, row[0], names)

    def _materialize_asa_from_blob(
        self, obj: GameObject, blob: bytes, names: frozenset[str] | None
    ) -> None:
        """Parse one ASA object's property block from an in-hand row blob.

        Pre: ``blob`` is the object's ``game`` row value; ``obj`` headers are
        parsed (``properties_offset`` valid). Post: ``obj._props_loaded`` is
        True; properties hold the full block, the ``names`` subset (v14+), or
        stay empty on a parse failure (recorded, mirroring the eager pass).
        """
        # Mark loaded up front so a corrupt object cannot retry (and re-log)
        # on every subsequent property access.
        obj._props_loaded = True
        reader = BinaryReader(blob, save_version=self.version)
        reader.position = obj.properties_offset
        nt = self.name_table
        assert isinstance(nt, dict), "ASA name table must be a dict"
        try:
            if names is not None and self.version >= 14:
                obj.properties, _skipped = read_properties_partial(reader, nt, names)
                obj._partial_names = names
            else:
                obj.properties = read_properties(
                    reader,
                    is_asa=True,
                    name_table=nt,
                    worldsave_format=True,
                )
                obj._partial_names = None
            obj._prop_index = None
        except Exception as e:  # noqa: BLE001 - mirror the eager pass
            err = f"Properties for {obj.class_name} ({obj.guid}): {e}"
            if err not in self._parse_errors:
                self._parse_errors.append(err)

    def stream_materialize(
        self, objs: list[GameObject], names: frozenset[str] | None = None
    ) -> t.Iterator[GameObject]:
        """Materialize ``objs`` (ascending id order), yielding each in turn.

        On lazy ASA saves the row blobs come from ONE ordered table scan
        instead of one SELECT per object (a classification pass touches most
        of the table; per-row fetches cost ~12us each at that volume, the
        scan well under 1us per row). Rows are matched to objects by their
        stored row key, so load-time parse failures (which shift object ids
        off row ordinals) cannot misalign the stream. ASE lazy saves fall
        back to per-object reader seeks, which are already cheap.

        Pre: ``objs`` is an id-ascending subset of ``self.objects`` on a save
        loaded with ``lazy_properties=True``. Post: every yielded object is
        materialized (and ring-tracked for eviction); the caller drains.
        """
        assert all(a.id < b.id for a, b in zip(objs, objs[1:])), "objs must be id-ascending"
        if not self.is_asa or self._lazy_conn is None or not self._asa_row_keys:
            for obj in objs:
                self.materialize_object(obj, names)
                yield obj
            return
        keys = self._asa_row_keys
        j = 0
        n = len(objs)
        scan = self._lazy_conn.execute("SELECT key, value FROM game")
        for i, (key, blob) in enumerate(scan):
            assert i < MAX_OBJECT_COUNT, "game table scan exceeded bound"
            if j >= n:
                break
            obj = objs[j]
            if key == keys[obj.id]:
                self._materialize_asa_from_blob(obj, blob, names)
                self._lazy_materialized.append(obj)
                j += 1
                yield obj
        # Any leftovers (key drift, truncated scan) fall back to point fetches.
        for k in range(j, n):
            self.materialize_object(objs[k], names)
            yield objs[k]

    def evict_materialized(self) -> int:
        """Evict every object materialized since the last drain.

        Pre: lazy mode (ring only ever fills via materialize_object).
        Post: ring empty; each drained object's properties released. Returns
        the number of objects evicted (0 on the eager path). Walk drivers call
        this once per visited record to keep the resident set bounded.
        """
        drained = self._lazy_materialized
        assert isinstance(drained, list), "eviction ring missing"
        if not drained:
            return 0
        for obj in drained:
            obj.evict_properties()
        count = len(drained)
        drained.clear()
        assert not self._lazy_materialized, "eviction ring not drained"
        self._evicted_since_trim += count
        if self._evicted_since_trim >= _TRIM_INTERVAL_OBJECTS and self._lazy_reader is not None:
            # Drop clean mmap pages from the working set (~1KB of property
            # bytes per object means an interval bounds the mapped-page
            # window to a few hundred MB on the biggest saves).
            _ = self._lazy_reader.trim_working_set()  # False = bytes-backed, nothing to trim
            self._evicted_since_trim = 0
        return count

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
        # Interned entries make the per-header type/name comparisons and the
        # registry dict lookups pointer-fast (millions per save), and dedupe
        # the strings against the literals used throughout the parser.
        self.name_table = [sys.intern(reader.read_string()) for _ in range(count)]

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
        lazy_properties: bool = False,
    ) -> WorldSave:
        """Parse an ASA SQLite world save.

        ``lazy_properties=True`` parses only object headers from each row blob
        and retains the connection (``_lazy_conn``) so property blocks load on
        demand via :meth:`materialize_object`. The connection is kept open for
        the save's lifetime on success and closed on any load failure.
        """
        save = cls()
        save.is_asa = True
        save._parse_errors = []

        conn = None
        keep_open = False
        try:
            conn = sqlite3.connect(str(path))
            save._read_asa_header(conn)
            # Actor locations are positional enrichment, not load-critical. A
            # malformed/padded ActorTransforms blob must not abort the whole
            # save; record it and continue with object data only. (EndOfDataError
            # subclasses ArkParseError, so this catches both.)
            try:
                save._read_asa_actor_locations(conn)
            except ArkParseError as e:
                save._parse_errors.append(f"ActorTransforms: {e}")
            save._read_asa_game_objects(conn, load_properties, max_objects, lazy_properties)
            if lazy_properties:
                # Hold one read transaction for the connection's lifetime.
                # Without it every materialize SELECT opens and closes an
                # implicit transaction, which on Windows means a file lock
                # and unlock per fetch (~233us vs ~14us inside a held read
                # txn, measured). Lock exposure matches the eager path's
                # full-table streaming scan; this is read-only throughout.
                conn.execute("BEGIN")
                save._lazy_conn = conn
                keep_open = True
        except sqlite3.Error as e:
            raise ArkParseError(f"SQLite error reading ASA world save: {e}")
        finally:
            if conn is not None and not keep_open:
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
            # Interned for the same pointer-fast comparisons as the ASE table.
            nt[idx] = sys.intern(raw.rsplit(".", 1)[-1] if "." in raw else raw)
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

            guid_str = guid_str_le(guid_bytes)
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
        lazy: bool = False,
    ) -> None:
        """Read all game objects from the ``game`` table."""
        query = "SELECT key, value FROM game"
        if max_objects is not None:
            query += f" LIMIT {max_objects}"

        cursor = conn.execute(query)
        self.objects = []
        obj_id = 0

        for key_bytes, value_bytes in cursor:
            guid_str = guid_str_le(key_bytes)
            try:
                obj = self._parse_asa_game_object(guid_str, value_bytes, obj_id, load_properties, lazy)
                if guid_str in self.actor_locations:
                    obj.location = self.actor_locations[guid_str]
                self.objects.append(obj)
                if lazy:
                    # Keep the raw row key so materialization skips the
                    # guid-string -> bytes round trip (one UUID parse per
                    # fetch, hundreds of thousands per export).
                    self._asa_row_keys.append(key_bytes)
                obj_id += 1
            except Exception as e:
                self._parse_errors.append(f"GUID {guid_str}: {e}")

    def _parse_asa_game_object(
        self,
        guid_str: str,
        blob: bytes,
        obj_id: int,
        load_properties: bool = True,
        lazy: bool = False,
    ) -> GameObject:
        """Parse a single ASA game object from its binary blob.

        ``lazy=True`` stops after the header: the blob is dropped and
        ``_lazy_source`` is wired so the first property access re-fetches the
        row and parses the block on demand (see :meth:`materialize_object`).
        Truncated blobs (the early returns below) never had a property block,
        so they stay eager-empty and are never wired for materialization.
        """
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

        if lazy:
            # Defer the property block: drop this blob entirely and let the
            # first property access re-fetch the row via materialize_object.
            obj._lazy_source = self
            return obj

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
