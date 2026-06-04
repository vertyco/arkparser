"""
Game Object Container.

A container for game objects that provides lookup and relationship management.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from .game_object import GameObject

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader

# Every property name the fused classification walk reads: the
# _is_creature_object / _is_structure probes plus the _classified_teams and
# _inv_actor_info scalar captures. Passed to materialize_object as a partial-
# decode hint on ASA v14+ lazy saves; if a future edit adds a probe, its name
# MUST be added here or lazy classification silently reads None (the golden
# suite catches the resulting export drift).
_CLASSIFY_PROPERTY_NAMES: frozenset[str] = frozenset({
    "bServerInitializedDino",
    "IsInCryo",
    "OwnerName",
    "bHasResetDecayTime",
    "TargetingTeam",
    "DinoID1",
    "MyInventoryComponent",
    "TribeName",
    "TamerString",
})


@dataclass
class GameObjectContainer:
    """
    Container for a collection of game objects.

    Provides methods for looking up objects by ID, class name, or name,
    and manages parent/component relationships.
    """

    objects: list[GameObject] = field(default_factory=list)

    # Lookup caches (built on demand)
    _by_guid: dict[str, GameObject] = field(default_factory=dict, repr=False)
    _by_class: dict[str, list[GameObject]] = field(default_factory=dict, repr=False)
    _by_name: dict[str, GameObject] = field(default_factory=dict, repr=False)

    def __len__(self) -> int:
        return len(self.objects)

    def __iter__(self) -> t.Iterator[GameObject]:
        return iter(self.objects)

    def __getitem__(self, index: int) -> GameObject:
        return self.objects[index]

    def add(self, obj: GameObject) -> None:
        """Add an object to the container."""
        self.objects.append(obj)
        self._invalidate_caches()

    def _invalidate_caches(self) -> None:
        """Clear lookup caches."""
        self._by_guid.clear()
        self._by_class.clear()
        self._by_name.clear()
        self._classify_cache = None

    def _build_caches(self) -> None:
        """Build lookup caches if empty."""
        if not self._by_guid and self.objects:
            for obj in self.objects:
                if obj.guid:
                    self._by_guid[obj.guid] = obj
                if obj.class_name:
                    if obj.class_name not in self._by_class:
                        self._by_class[obj.class_name] = []
                    self._by_class[obj.class_name].append(obj)
                if obj.primary_name:
                    self._by_name[obj.primary_name] = obj

    def get_by_id(self, obj_id: int) -> GameObject | None:
        """Get object by ID."""
        if 0 <= obj_id < len(self.objects):
            return self.objects[obj_id]
        return None

    def get_by_guid(self, guid: str) -> GameObject | None:
        """Get object by GUID."""
        self._build_caches()
        return self._by_guid.get(guid)

    def get_by_name(self, name: str) -> GameObject | None:
        """Get object by primary name."""
        self._build_caches()
        return self._by_name.get(name)

    def get_by_class(self, class_name: str) -> list[GameObject]:
        """Get all objects with the given class name."""
        self._build_caches()
        return self._by_class.get(class_name, [])

    def find_by_class_pattern(self, pattern: str) -> list[GameObject]:
        """Find objects whose class name contains the pattern."""
        return [obj for obj in self.objects if pattern in obj.class_name]

    def build_relationships(self) -> None:
        """
        Build parent/component relationships between objects.

        Components have multiple names - the last name references the parent.
        """
        self._build_caches()

        for obj in self.objects:
            if obj.has_parent_names:
                # This is a component - find its parent
                parent_name = obj.names[-1]  # Last name is parent reference
                parent = self.get_by_name(parent_name)
                if parent:
                    parent.add_component(obj)

    # Class name patterns that are never structures
    _NON_STRUCTURE_PATTERNS: t.ClassVar[tuple[str, ...]] = (
        "_Character_BP",
        "DinoCharacter",
        "PlayerPawn",
        "Buff_",
        "PrimalBuff",
        "Weap",
        "StatusComponent",
        "Inventory",
        "DroppedItem",
        "DeathItemCache",
        "NPCZone",
        "DinoDropInventory",
    )

    # Vehicles that carry DinoID1/bServerInitializedDino but are not creatures.
    # Source: C# GameObjectExtensions.IsCreature (SavegameToolkitAdditions).
    _VEHICLE_CLASS_NAMES: t.ClassVar[frozenset[str]] = frozenset({
        "MotorRaft_BP_C",
        "Raft_BP_C",
        "TekHoverSkiff_Character_BP_C",
        "CogRaft_BP_C",
        "DingyRaft_BP_C",
        "LongshipRaft_BP_C",
        "SRaft_BP_C",
    })

    def _is_creature_object(self, obj: GameObject) -> bool:
        """Return ``True`` for top-level creature actors only.

        Primary check mirrors C# GameObjectExtensions.IsCreature: presence of
        ``bServerInitializedDino`` AND not a vehicle.  Falls back to class name
        patterns for unit tests and edge cases where properties are absent.
        """
        if obj.is_item:
            return False
        if obj.class_name in self._VEHICLE_CLASS_NAMES:
            return False
        if obj.get_property_value("bServerInitializedDino") is not None:
            return True
        # Class-name fallback for minimal test objects or pre-property-load pass.
        cn = obj.class_name
        is_character = "_Character_" in cn or "DinoCharacter" in cn
        return is_character and "StatusComponent" not in cn and "Inventory" not in cn

    # Memoized (creatures, structures) pair from the fused classification
    # pass. Both lists previously required their own full-graph walk, and on
    # lazy saves each walk is a full property re-parse.
    _classify_cache: tuple[list[GameObject], list[GameObject]] | None = field(
        default=None, repr=False
    )

    # Scalars captured while each object is materialized during the fused
    # classification pass, so later consumers never re-parse property blocks
    # just to re-read them on lazy saves:
    # - _classified_teams: obj.id -> TargetingTeam for creatures + structures
    #   (tamed/wild split, tribe tame/structure counts).
    # - _inv_actor_info: obj.id -> (MyInventoryComponent ref, TargetingTeam,
    #   TribeName, OwnerName) for every non-item actor carrying an inventory
    #   ref (the item-owner lookup used for cryopod tribe backfill).
    _classified_teams: dict[int, int] = field(default_factory=dict, repr=False)
    _inv_actor_info: dict[int, tuple[t.Any, t.Any, t.Any, t.Any]] = field(
        default_factory=dict, repr=False
    )
    # obj.id -> (OwnerName, TamerString, TribeName) for every classified
    # creature/structure, captured while the block is resident so the tribe
    # synthesis walks (_distinct_team_names) never re-parse property blocks
    # just to read three strings on lazy saves.
    _classified_names: dict[int, tuple[t.Any, t.Any, t.Any]] = field(
        default_factory=dict, repr=False
    )

    def get_creatures(self) -> list[GameObject]:
        """Get all creature objects (tamed and wild)."""
        return self._classify_world()[0]

    def _classify_world(self) -> tuple[list[GameObject], list[GameObject]]:
        """Classify every object into creatures / structures in ONE pass.

        Pre: ``self.objects`` populated (headers at minimum). Post: result
        cached; identical to running the old independent ``get_creatures`` and
        ``get_structures`` walks (a creature never classifies as a structure:
        vehicles are excluded by ``_is_creature_object`` and accepted by
        ``_is_structure``, every other creature is rejected by its ``DinoID1``
        / ``_Character_BP`` checks, so the ``elif`` is exact).

        Classification reads properties, which auto-materializes lazy objects;
        drain after each object so a lazy save never holds the whole graph just
        to classify it, and probe each object's property block once instead of
        once per category walk. Eager objects have no ``_lazy_source`` and skip
        the drain entirely.

        Structure dedup matches the C# ASVPack reference
        (ContentContainer.cs:1049): ASE saves include the same actor in main
        and sub-levels, so duplicates are dropped by ``Names[0]``.
        """
        if self._classify_cache is not None:
            return self._classify_cache
        creatures: list[GameObject] = []
        structures: list[GameObject] = []
        seen_names: set[str] = set()
        # Pre-filter on header data alone: items and status/inventory
        # components never classify as creature or structure, so skip them
        # before any property probe (which on lazy saves would materialize
        # ~2/3 of the object graph just to classify it). The component
        # patterns are deliberately tighter than the bare "Inventory" used by
        # _NON_STRUCTURE_PATTERNS: every real component class is
        # *StatusComponent* / PrimalInventory* / *InventoryComponent*
        # (surveyed across ASE+ASA saves), while a bare substring also caught
        # modded structures like StructureBP_InventoryCars_C that legacy
        # admits via OwnerName.
        candidates: list[GameObject] = []
        for obj in self.objects:
            cn = obj.class_name
            if (
                obj.is_item
                or "StatusComponent" in cn
                or "PrimalInventory" in cn
                or "InventoryComponent" in cn
            ):
                continue
            candidates.append(obj)
        # Partial materialization: every property this walk (and its scalar
        # captures below) reads is in _CLASSIFY_PROPERTY_NAMES, so ASA v14+
        # lazy saves decode just those and skip the rest of each block (a
        # verified byte-exact skip walk), with the row blobs streamed from
        # one ordered table scan instead of a SELECT per object. ASE / v13
        # parse fully per object; the drain below evicts either way, so
        # nothing downstream ever sees a partial object. Eager saves iterate
        # the candidates directly.
        src0 = candidates[0]._lazy_source if candidates else None
        if src0 is not None:
            walk: t.Iterable[GameObject] = src0.stream_materialize(
                candidates, _CLASSIFY_PROPERTY_NAMES
            )
        else:
            walk = candidates
        for obj in walk:
            src = obj._lazy_source
            is_creature = self._is_creature_object(obj)
            is_structure = False if is_creature else self._is_structure(obj)
            # Capture the scalars later walks need while the property block is
            # resident (re-reading them after the drain would re-parse it).
            if is_creature or is_structure:
                team = obj.get_property_value("TargetingTeam")
                if isinstance(team, (int, float)):
                    self._classified_teams[obj.id] = int(team)
                self._classified_names[obj.id] = (
                    obj.get_property_value("OwnerName"),
                    obj.get_property_value("TamerString"),
                    obj.get_property_value("TribeName"),
                )
            # Pre-filter above already excluded items and status/inventory
            # components, so every survivor is an inventory-owner candidate.
            inv_ref = obj.get_property_value("MyInventoryComponent")
            if inv_ref is not None:
                self._inv_actor_info[obj.id] = (
                    inv_ref,
                    obj.get_property_value("TargetingTeam"),
                    obj.get_property_value("TribeName"),
                    obj.get_property_value("OwnerName"),
                )
            if src is not None:
                src.evict_materialized()
            if is_creature:
                creatures.append(obj)
            elif is_structure:
                name = obj.primary_name
                if name is not None:
                    if name in seen_names:
                        continue
                    seen_names.add(name)
                structures.append(obj)
        self._classify_cache = (creatures, structures)
        return self._classify_cache

    def get_items(self) -> list[GameObject]:
        """Get all item objects."""
        return [obj for obj in self.objects if obj.is_item]

    # Class-name substrings for environmental map elements that should NOT
    # appear in get_structures() (they go through get_terminals/get_nests/etc).
    _MAP_ELEMENT_PATTERNS: t.ClassVar[tuple[str, ...]] = (
        "TributeTerminal",
        "CityTerminal",
        "ArtifactCrate",
        "OilVein",
        "WaterVein",
        "GasVein",
        "ChargeNode",
        "ElementVein",
        "BeaverDam",
        "Nest",
    )

    # Class-name fragments matching placed objects that carry NO properties
    # at all (no OwnerName, no TargetingTeam, no bHasResetDecayTime, just a
    # class name + location).  ARK persists flex pipe / flex wire segments
    # this way (they're graphical connectors between intake/outlet endpoints,
    # which DO carry properties).  Tier 3a of _is_structure matches against
    # this list so the segments still count toward the structure list,
    # mirroring v2 ASVPack behaviour.
    _PROPERTY_LESS_STRUCTURE_PATTERNS: t.ClassVar[tuple[str, ...]] = (
        "BP_PipeFlex_",   # BP_PipeFlex_Metal_C, BP_PipeFlex_Stone_C, ...
        "BP_Wire_Flex_",  # BP_Wire_Flex_C, BP_Wire_Flex_Tek_C, ...
    )

    # Class-name fragments that always disqualify an object from being treated
    # as a structure, even if it carries TargetingTeam. Used by the
    # tribe-owned fallback below to catch flex pipes/wires (which lack
    # OwnerName/bHasResetDecayTime) without sweeping in creatures, items,
    # buffs, etc.
    _NON_STRUCTURE_PATTERNS: t.ClassVar[tuple[str, ...]] = (
        "_Character_BP",
        "DinoCharacter",
        "PlayerPawn",
        "Buff_",
        "PrimalBuff",
        "Weap",
        "StatusComponent",
        "Inventory",
        "DroppedItem",
        "DeathItemCache",
        "NPCZone",
        "DinoDropInventory",
    )

    def _is_structure(self, obj: GameObject) -> bool:
        """Return ``True`` if the object is a placed structure.

        Three-tier rule (in order, first match wins):

        1. Hard exclusions: loadout dummies, death item caches, cryo-pinned
           objects, and environmental map elements (which surface separately
           via ``get_terminals`` / ``get_nests`` / ``get_map_resources``).

        2. C# IsStructure parity: accept if ``OwnerName`` or
           ``bHasResetDecayTime`` is set, or if the class name is in the
           known special list (vehicles, CherufeNest_C).

        3. Tribe-owned fallback: accept if ``TargetingTeam`` is set, the
           object isn't a creature (no ``DinoID1``) and the class name
           doesn't match any ``_NON_STRUCTURE_PATTERNS``. This recovers
           flex pipes / wires (``BP_PipeFlex_*``, ``BP_Wire_Flex_C``) and
           similar connector segments that don't carry OwnerName but are
           clearly part of a tribe's build. Without this fallback v3 was
           dropping ~675 of these per busy PvE map vs the v2 reference.
        """
        cn = obj.class_name
        # Tier 1: hard exclusions
        if cn == "Structure_LoadoutDummy_Hotbar_C":
            return False
        if cn.startswith("DeathItemCache_"):
            return False
        if obj.get_property_value("IsInCryo"):
            return False
        if cn != "CherufeNest_C" and any(p in cn for p in self._MAP_ELEMENT_PATTERNS):
            return False

        # Tier 2: C# IsStructure parity
        if obj.get_property_value("OwnerName") is not None:
            return True
        if obj.get_property_value("bHasResetDecayTime") is not None:
            return True
        if cn == "CherufeNest_C" or cn in self._VEHICLE_CLASS_NAMES:
            return True

        # Tier 3a: property-less placed segments (flex pipes / flex wires).
        # These exist as actor GameObjects with a real location but NO
        # properties at all. ARK persists them as graphical connectors
        # between intake/outlet endpoints. The C# IsStructure rule misses
        # them; v2 ASVPack captures them anyway. Class-name match against
        # ``_PROPERTY_LESS_STRUCTURE_PATTERNS`` recovers them without
        # sweeping in anything property-bearing.
        if not getattr(obj, "is_item", False) and any(
            p in cn for p in self._PROPERTY_LESS_STRUCTURE_PATTERNS
        ):
            return True

        # Tier 3b: tribe-owned fallback for property-bearing structures the
        # canonical C# rule missed (decoration items, etc.).
        if obj.get_property_value("TargetingTeam") is None:
            return False
        if obj.get_property_value("DinoID1") is not None:
            return False
        if any(pat in cn for pat in self._NON_STRUCTURE_PATTERNS):
            return False
        return True

    def get_structures(self) -> list[GameObject]:
        """Get all placed structures (deduped by ``Names[0]``, see _classify_world)."""
        return self._classify_world()[1]

    def get_player_pawns(self) -> list[GameObject]:
        """Get player character objects on the map."""
        return [obj for obj in self.objects if "PlayerPawn" in obj.class_name]

    def get_terminals(self) -> list[GameObject]:
        """Get map-placed terminal objects (tribute terminals, city terminals).

        Inventory components and item sub-objects are excluded.
        """
        return [
            obj
            for obj in self.objects
            if ("TributeTerminal" in obj.class_name or "CityTerminal" in obj.class_name)
            and not obj.is_item
            and "Inventory" not in obj.class_name
            and "PrimalItem" not in obj.class_name
        ]

    def get_supply_drops(self) -> list[GameObject]:
        """Get active supply-drop / loot-crate objects on the map.

        Inventory components are excluded.
        """
        _SUPPLY_PATTERNS = ("SupplyCrate", "OrbitalSupply", "SupplyDrop")
        return [
            obj
            for obj in self.objects
            if any(p in obj.class_name for p in _SUPPLY_PATTERNS)
            and "Inventory" not in obj.class_name
            and not obj.is_item
        ]

    def get_artifact_crates(self) -> list[GameObject]:
        """Get artifact-crate spawn objects. Inventory components are excluded."""
        return [
            obj
            for obj in self.objects
            if "ArtifactCrate" in obj.class_name and "Inventory" not in obj.class_name and not obj.is_item
        ]

    def get_map_resources(self) -> list[GameObject]:
        """Get engine-placed resource / vein / node objects.

        Covers oil veins, water veins, gas veins, charge nodes, element
        veins, and beaver dams.  Inventory components are excluded.
        """
        _RESOURCE_PATTERNS = (
            "OilVein",
            "WaterVein",
            "GasVein",
            "ChargeNode",
            "ElementVein",
            "BeaverDam",
        )
        return [
            obj
            for obj in self.objects
            if any(p in obj.class_name for p in _RESOURCE_PATTERNS)
            and "Inventory" not in obj.class_name
            and not obj.is_item
        ]

    def get_nests(self) -> list[GameObject]:
        """Get creature nest objects (wyvern, drake, etc.). Inventory excluded."""
        return [
            obj
            for obj in self.objects
            if "Nest" in obj.class_name
            and "Inventory" not in obj.class_name
            and not obj.is_item
        ]

    def get_players(self) -> list[GameObject]:
        """Get all player data objects."""
        return self.get_by_class("PrimalPlayerData") + self.find_by_class_pattern("PlayerPawnTest")

    def load_all_properties(
        self,
        reader: BinaryReader,
        properties_block_offset: int,
        is_asa: bool = False,
    ) -> None:
        """
        Load properties for all objects.

        Args:
            reader: Binary reader.
            properties_block_offset: Base offset of properties block.
            is_asa: True for ASA format.
        """
        for i, obj in enumerate(self.objects):
            next_obj = self.objects[i + 1] if i + 1 < len(self.objects) else None
            obj.load_properties(reader, properties_block_offset, is_asa, next_obj)

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary for serialization."""
        return {
            "count": len(self.objects),
            "objects": [obj.to_dict() for obj in self.objects],
        }
