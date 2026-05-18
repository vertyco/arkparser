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

    def get_creatures(self) -> list[GameObject]:
        """Get all creature objects (tamed and wild)."""
        return [obj for obj in self.objects if self._is_creature_object(obj)]

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

    # Class-name fragments that always disqualify an object from being treated
    # as a structure — even if it carries TargetingTeam. Used by the
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

        2. C# IsStructure parity — accept if ``OwnerName`` or
           ``bHasResetDecayTime`` is set, or if the class name is in the
           known special list (vehicles, CherufeNest_C).

        3. Tribe-owned fallback — accept if ``TargetingTeam`` is set, the
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

        # Tier 3: tribe-owned fallback (flex pipes / wires)
        if obj.get_property_value("TargetingTeam") is None:
            return False
        if obj.get_property_value("DinoID1") is not None:
            return False
        if any(pat in cn for pat in self._NON_STRUCTURE_PATTERNS):
            return False
        return True

    def get_structures(self) -> list[GameObject]:
        """Get all placed structures.

        ASE saves include the same actor in both the main level and sub-levels,
        producing duplicate entries with identical Names[0]. Deduplicating by
        primary_name matches the C# ASVPack reference (ContentContainer.cs:1049):
            .GroupBy(x => x.Names[0]).Select(s => s.First())
        """
        seen_names: set[str] = set()
        results: list[GameObject] = []
        for obj in self.objects:
            if not self._is_structure(obj):
                continue
            name = obj.primary_name
            if name is not None:
                if name in seen_names:
                    continue
                seen_names.add(name)
            results.append(obj)
        return results

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
