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

    def get_creatures(self) -> list[GameObject]:
        """Get all creature objects (tamed and wild)."""
        return [obj for obj in self.objects if "_Character_BP" in obj.class_name or "DinoCharacter" in obj.class_name]

    def get_items(self) -> list[GameObject]:
        """Get all item objects."""
        return [obj for obj in self.objects if obj.is_item]

    def get_structures(self) -> list[GameObject]:
        """Get all tribe-owned placed structures."""
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
