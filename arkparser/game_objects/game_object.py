"""
Game Object.

The core entity class for all objects in ARK save files.
Game objects represent creatures, items, structures, players, and other entities.
"""

from __future__ import annotations

import logging
import re
import typing as t
from collections import defaultdict
from dataclasses import dataclass, field

from ..common.exceptions import CorruptDataError
from ..properties.registry import read_properties, read_property
from .location import LocationData

logger = logging.getLogger(__name__)

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader
    from ..properties.base import Property

# Upper sanity bound for the ASE object-table count. Legitimate maps top out
# in the low millions; a misaligned header decodes a garbage count (commonly a
# negative int32 read as a ~4-billion uint), so anything past this is corruption.
MAX_OBJECT_COUNT = 100_000_000


@dataclass(slots=True)
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

    # Lazy property index: name -> Property (single-index, the common case) OR
    # name -> {index: Property} (only when a name carries >1 distinct index).
    # Storing the bare Property for single-index names avoids allocating one
    # inner dict per (object, name): on a 300k-object save that was ~5.4M dicts
    # / ~600 MB of pure index overhead built during export. Built on first
    # lookup, invalidated by setting to None when properties is mutated.
    _prop_index: dict[str, "Property | dict[int, Property]"] | None = field(
        default=None, repr=False, compare=False
    )

    # Lazy-loading hooks (saves loaded with lazy_properties=True). When
    # _lazy_source is set (the owning WorldSave), property access auto-loads the
    # deferred property block via _ensure_loaded(); evict_properties() releases
    # it again. All stay at their defaults on the eager path, where
    # _ensure_loaded() is a no-op.
    #
    # _partial_names: non-None only while the object holds a partial decode
    # (ASA v14+ materialize_object(names=...)): the set of names that were
    # requested. Getter lookups for names OUTSIDE the set transparently
    # re-materialize the full block first, so a partial decode is a pure perf
    # hint and can never change what a consumer reads.
    _lazy_source: t.Any = field(default=None, repr=False, compare=False)
    _props_loaded: bool = field(default=False, repr=False, compare=False)
    _partial_names: frozenset[str] | None = field(default=None, repr=False, compare=False)

    def _ensure_loaded(self) -> None:
        """Materialize deferred properties (lazy saves); no-op otherwise.

        Pre: if ``_lazy_source`` is set it is the owning WorldSave (exposes
        ``materialize_object``). Post: ``_props_loaded`` is True on the lazy
        path; eager objects are untouched.
        """
        if self._lazy_source is not None and not self._props_loaded:
            self._lazy_source.materialize_object(self)
            assert self._props_loaded, "materialize_object did not mark object loaded"

    def _ensure_name(self, name: str) -> None:
        """Upgrade a partial decode to the full block when ``name`` is outside it.

        Pre: ``name`` is the property about to be looked up. Post: if the
        resident decode was partial and did not cover ``name``, the full block
        is re-materialized (and the property index invalidated) before the
        lookup proceeds; otherwise no-op.
        """
        pn = self._partial_names
        if pn is not None and name not in pn and self._lazy_source is not None:
            self._partial_names = None
            self._lazy_source.materialize_object(self)
            assert self._props_loaded, "full re-materialization failed"

    def _ensure_full(self) -> None:
        """Upgrade a partial decode to the full block unconditionally.

        Raw ``properties`` iterators (serialization, prop-index dumps) call
        this so they never observe a whitelist subset.
        """
        if self._partial_names is not None and self._lazy_source is not None:
            self._partial_names = None
            self._lazy_source.materialize_object(self)
            assert self._props_loaded, "full re-materialization failed"

    def _build_prop_index(self) -> dict[str, "Property | dict[int, Property]"]:
        # First-writer wins, matching legacy C# GetPropertyValue
        # (IPropertyContainer.cs:45) which returns the first (name, index)
        # match. _serialize_properties keeps all occurrences in the additive
        # `properties` dict; lookups intentionally mirror legacy here. Do not
        # switch to last-wins.
        self._ensure_loaded()
        idx: dict[str, "Property | dict[int, Property]"] = {}
        for prop in self.properties:
            existing = idx.get(prop.name)
            if existing is None:
                idx[prop.name] = prop  # common case: store the bare Property
            elif isinstance(existing, dict):
                existing.setdefault(prop.index, prop)
            elif existing.index != prop.index:
                # Second distinct index for this name: promote to a dict.
                # `existing` first preserves first-writer iteration order.
                idx[prop.name] = {existing.index: existing, prop.index: prop}
            # else: duplicate (name, index) -> keep first-writer `existing`.
        self._prop_index = idx
        return idx

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
        """Get a property by name and optional index (None = first by insertion)."""
        self._ensure_name(name)
        idx = self._prop_index if self._prop_index is not None else self._build_prop_index()
        bucket = idx.get(name)
        if bucket is None:
            return None
        if isinstance(bucket, dict):
            if index is None:
                return next(iter(bucket.values()))
            return bucket.get(index)
        # Single-index bucket: the bare Property.
        if index is None or bucket.index == index:
            return bucket
        return None

    def get_property_value(self, name: str, default: t.Any = None, index: int | None = None) -> t.Any:
        """Get a property value by name (returns default if missing)."""
        prop = self.get_property(name, index)
        return prop.value if prop is not None else default

    def get_properties_by_name(self, name: str) -> list[Property]:
        """Get all properties with the given name (any index)."""
        self._ensure_name(name)
        idx = self._prop_index if self._prop_index is not None else self._build_prop_index()
        bucket = idx.get(name)
        if bucket is None:
            return []
        if isinstance(bucket, dict):
            return list(bucket.values())
        return [bucket]

    def has_property(self, name: str) -> bool:
        """Check if this object has a property with the given name."""
        self._ensure_name(name)
        idx = self._prop_index if self._prop_index is not None else self._build_prop_index()
        return name in idx

    # Normalized component key names: maps UE4 dynamic blueprint names
    # (e.g. DinoCharacterStatus_BP_Rex_C1) to stable consumer-friendly keys.
    _COMPONENT_PATTERNS: t.ClassVar[tuple[tuple[str, str], ...]] = (
        ("CharacterStatus", "status"),
        ("Inventory", "inventory"),
        ("Painting", "painting"),
    )

    @staticmethod
    def _normalize_component_name(name: str) -> str:
        """Map a dynamic UE4 component name to a stable key.

        Falls back to the original name for unrecognized components.
        """
        for pattern, key in GameObject._COMPONENT_PATTERNS:
            if pattern in name:
                return key
        return name

    _UUID_RE = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        re.IGNORECASE,
    )

    @staticmethod
    def _is_object_ref(prop: Property) -> bool:
        """True if this property is an internal object-index reference.

        ``ObjectProperty`` can hold either:
        - An integer object-index (ASE internal plumbing) → filtered
        - A GUID string (ASA internal plumbing) → filtered
        - A blueprint/name path string (meaningful to consumers) → kept

        ``ArrayProperty`` whose ``array_type`` is ``ObjectProperty`` is also
        treated as internal when every element is an ``("id", <int>)`` tuple.
        """
        if prop.type_name == "ObjectProperty":
            val = prop.value
            if isinstance(val, int):
                return True
            if isinstance(val, str) and GameObject._UUID_RE.match(val):
                return True
            return False
        if prop.type_name == "ArrayProperty" and getattr(prop, "array_type", "") == "ObjectProperty":
            # all() over an empty list is True; require a non-empty value so an
            # empty object-ref array is serialized rather than silently dropped.
            return bool(prop.value) and all(
                isinstance(v, (tuple, list)) and len(v) == 2 and v[0] == "id"
                for v in prop.value
            )
        return False

    @staticmethod
    def _clean_value(val: t.Any) -> t.Any:
        """Strip internal metadata (``_struct_type``) from serialized values."""
        if isinstance(val, dict):
            return {k: GameObject._clean_value(v) for k, v in val.items() if k != "_struct_type"}
        if isinstance(val, list):
            return [GameObject._clean_value(v) for v in val]
        return val

    def _serialize_properties(self) -> dict[str, t.Any]:
        """Serialize this object's properties to a flat dict.

        Skips ``ObjectProperty`` and ``ArrayProperty[ObjectProperty]`` values
        because they are internal save-file references (indices into the
        object table).  The data they point to is already surfaced under
        ``components`` where applicable.

        Also strips internal metadata keys like ``_struct_type`` from nested
        struct dicts.

        Single non-indexed properties become bare values.
        Multiple or indexed properties become ``{index: value}`` dicts.
        ByteProperty always uses dict form because it is commonly used for
        indexed stat arrays where only a single entry at index 0 may be
        populated; collapsing it would change the data shape.
        """
        self._ensure_loaded()
        self._ensure_full()
        grouped: dict[str, list[Property]] = defaultdict(list)
        for prop in self.properties:
            if not self._is_object_ref(prop):
                grouped[prop.name].append(prop)

        clean = self._clean_value

        def _should_collapse(props: list[Property]) -> bool:
            """True if a property group should collapse to a bare value."""
            if len(props) != 1:
                return False
            # ByteProperty is used for indexed stat arrays that may have only
            # one populated entry; always keep dict form for shape consistency.
            if props[0].type_name == "ByteProperty":
                return False
            return True

        return {
            name: clean(prop_list[0].value if _should_collapse(prop_list) else {p.index: p.value for p in prop_list})
            for name, prop_list in grouped.items()
        }

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, t.Any] = {
            "class_name": self.class_name,
        }

        if self.names:
            result["names"] = self.names
        if self.location:
            result["location"] = self.location.to_dict()

        props = self._serialize_properties()
        if props:
            result["properties"] = props

        if self.components:
            result["components"] = {
                name: comp._serialize_properties()
                for name, comp in self.components.items()
            }

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
        # Calculate absolute offset
        offset = properties_block_offset + self.properties_offset

        # Seek to properties
        reader.position = offset

        # Read properties. Some ASE objects contain trailing opaque extra data
        # after a run of normal properties; preserve successfully parsed
        # properties and store the remainder as `extra_data`.
        if is_asa:
            self.properties = read_properties(reader, is_asa, name_table=name_table)
        else:
            properties: list[Property] = []
            try:
                while True:
                    prop = read_property(reader, is_asa, name_table=name_table)
                    if prop is None:
                        break
                    properties.append(prop)
            except Exception as exc:
                self.properties = properties
                self._props_loaded = True
                if next_object is None:
                    raise
                logger.debug(
                    "property parse stopped early for %s after %d properties, "
                    "remainder kept as extra_data: %s",
                    self.class_name,
                    len(properties),
                    exc,
                )

                next_offset = properties_block_offset + next_object.properties_offset
                remaining = next_offset - reader.position
                if remaining > 0:
                    self.extra_data = reader.read_bytes(remaining)
                return

            self.properties = properties

        self._prop_index = None
        self._props_loaded = True

        # Any remaining data before next object is extra data
        if next_object is not None:
            next_offset = properties_block_offset + next_object.properties_offset
            remaining = next_offset - reader.position
            if remaining > 0:
                self.extra_data = reader.read_bytes(remaining)

    def evict_properties(self) -> None:
        """Release parsed properties to reclaim RAM.

        Pre: ``self`` is a normal GameObject (properties may or may not be
        loaded). Post: ``properties`` / ``extra_data`` / ``_prop_index`` are
        cleared; the object can be re-populated via
        ``WorldSave.materialize_object``. Header fields (id, names, class_name,
        location, properties_offset) are untouched, so the object stays
        classifiable and re-loadable. Idempotent.
        """
        assert isinstance(self.properties, list), "properties must be a list"
        self.properties = []
        self.extra_data = None
        self._prop_index = None
        self._props_loaded = False
        self._partial_names = None
        assert self._prop_index is None, "prop index not cleared"

    def add_component(self, component: GameObject) -> None:
        """Add a component to this object under its normalized key."""
        if component.primary_name:
            key = self._normalize_component_name(component.primary_name)
            self.components[key] = component
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
    count = reader.read_uint32()
    if count > MAX_OBJECT_COUNT:
        raise CorruptDataError(
            f"object count {count} exceeds maximum {MAX_OBJECT_COUNT} "
            "(likely a misaligned object table header)"
        )
    objects: list[GameObject] = []

    for i in range(count):
        obj = GameObject.read_header(reader, i, is_asa)
        objects.append(obj)

    return objects
