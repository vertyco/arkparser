"""
Creature model classes - TamedCreature and WildCreature.

Wraps GameObject with intuitive attribute access for creature data.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from .stats import CreatureStats, Location


@dataclass
class Creature:
    """
    Base creature class with common attributes.

    This is the base class for both tamed and wild creatures.
    It wraps a GameObject and provides intuitive property access.

    Attributes:
        class_name: Blueprint class name (e.g., "Dodo_Character_BP_C").
        guid: Unique identifier (ASA only, ASE will be empty).
        is_female: True if the creature is female.
        is_baby: True if the creature is a baby.
        is_neutered: True if neutered/spayed.
        colors: List of 6 color region indices.
        base_level: Wild/base level of the creature.
        base_stats: Wild stat points (before taming).
        location: World position.
    """

    _game_object: t.Any = field(default=None, repr=False)
    _status_object: t.Any = field(default=None, repr=False)

    # Cached values
    _class_name: str | None = field(default=None, repr=False)
    _colors: list[int] | None = field(default=None, repr=False)
    _base_stats: CreatureStats | None = field(default=None, repr=False)

    @property
    def class_name(self) -> str:
        """Blueprint class name (e.g., 'Dodo_Character_BP_C')."""
        if self._class_name is None:
            self._class_name = self._game_object.class_name if self._game_object else ""
        return self._class_name or ""

    @property
    def guid(self) -> str:
        """Unique identifier (ASA only)."""
        return self._game_object.guid if self._game_object else ""

    @property
    def dino_id(self) -> int:
        """
        Unique dino ID (combination of DinoID1 and DinoID2).

        Returns:
            64-bit dino ID, or 0 if not available.
        """
        if not self._game_object:
            return 0
        id1 = self._game_object.get_property_value("DinoID1", default=0)
        id2 = self._game_object.get_property_value("DinoID2", default=0)
        if id1 and id2:
            return (int(id1) << 32) | (int(id2) & 0xFFFFFFFF)
        return 0

    @property
    def is_female(self) -> bool:
        """True if the creature is female."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("bIsFemale", default=False)

    @property
    def gender(self) -> str:
        """Gender as string ('Female' or 'Male')."""
        return "Female" if self.is_female else "Male"

    @property
    def is_baby(self) -> bool:
        """True if the creature is a baby."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("bIsBaby", default=False)

    @property
    def is_neutered(self) -> bool:
        """True if the creature is neutered/spayed."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("bNeutered", default=False)

    @property
    def colors(self) -> list[int]:
        """
        Color region indices (6 values).

        Returns:
            List of 6 color indices for regions 0-5.
        """
        if self._colors is None:
            self._colors = []
            if self._game_object:
                for i in range(6):
                    color = self._game_object.get_property_value("ColorSetIndices", index=i, default=0)
                    self._colors.append(int(color) if color else 0)
            else:
                self._colors = [0] * 6
        return self._colors

    @property
    def base_level(self) -> int:
        """Wild/base level (before any tamed levels)."""
        if self._status_object:
            return self._status_object.get_property_value("BaseCharacterLevel", default=1)
        return 1

    @property
    def base_stats(self) -> CreatureStats:
        """
        Wild stat points (points applied at spawn).

        These are the stat points the creature had before taming.
        """
        if self._base_stats is None:
            points = []
            if self._status_object:
                for i in range(12):
                    val = self._status_object.get_property_value("NumberOfLevelUpPointsApplied", index=i, default=0)
                    points.append(int(val) if val else 0)
            self._base_stats = CreatureStats.from_array(points)
        return self._base_stats

    @property
    def location(self) -> Location | None:
        """World position and rotation."""
        if self._game_object and self._game_object.location:
            loc = self._game_object.location
            return Location(
                x=loc.x,
                y=loc.y,
                z=loc.z,
                pitch=getattr(loc, "pitch", 0.0),
                yaw=getattr(loc, "yaw", 0.0),
                roll=getattr(loc, "roll", 0.0),
            )
        return None

    @property
    def wild_scale(self) -> float:
        """Wild random scale factor (size variation)."""
        if not self._game_object:
            return 1.0
        return self._game_object.get_property_value("WildRandomScale", default=1.0)

    @property
    def maturation(self) -> float:
        """
        Baby maturation progress (0.0 - 1.0).

        Only meaningful for babies. Returns 1.0 for adults.
        """
        if not self._game_object or not self.is_baby:
            return 1.0
        baby_age = self._game_object.get_property_value("BabyAge", default=1.0)
        return float(baby_age) if baby_age else 1.0

    @property
    def maturation_percent(self) -> str:
        """Baby maturation as a percentage string (e.g., '75' or '100')."""
        return str(int(self.maturation * 100))

    def get_property(self, name: str, index: int = 0, default: t.Any = None) -> t.Any:
        """
        Get a raw property value from the underlying game object.

        Args:
            name: Property name.
            index: Array index for repeated properties.
            default: Value to return if not found.

        Returns:
            The property value.
        """
        if self._game_object:
            return self._game_object.get_property_value(name, default=default, index=index)
        return default

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary matching C# ASV export format."""
        result: dict[str, t.Any] = {
            "id": self.dino_id,
            "creature": self.class_name,
            "sex": self.gender,
            "base": self.base_level,
            "colors": self.colors,
            "c0": self.colors[0] if len(self.colors) > 0 else 0,
            "c1": self.colors[1] if len(self.colors) > 1 else 0,
            "c2": self.colors[2] if len(self.colors) > 2 else 0,
            "c3": self.colors[3] if len(self.colors) > 3 else 0,
            "c4": self.colors[4] if len(self.colors) > 4 else 0,
            "c5": self.colors[5] if len(self.colors) > 5 else 0,
            "dinoid": str(self.dino_id),
            "base_stats": self.base_stats.to_dict(),
            # Flat stat fields matching C# wild export
            "hp": self.base_stats.health,
            "stam": self.base_stats.stamina,
            "melee": self.base_stats.melee,
            "weight": self.base_stats.weight,
            "speed": self.base_stats.speed,
            "food": self.base_stats.food,
            "oxy": self.base_stats.oxygen,
            "craft": self.base_stats.crafting,
        }
        if self.location:
            result["location"] = self.location.to_dict()
            result["ccc"] = self.location.ccc
            if self.location.latitude is not None:
                result["lat"] = self.location.latitude
            if self.location.longitude is not None:
                result["lon"] = self.location.longitude
        return result


@dataclass
class TamedCreature(Creature):
    """
    A tamed creature with full attribute access.

    Extends Creature with taming-specific attributes like name,
    tribe, imprint quality, tamed stats, and mutations.

    Example:
        >>> creature = TamedCreature.from_game_object(obj, status_obj)
        >>> print(f"{creature.name} - Level {creature.level}")
        >>> print(f"Imprint: {creature.imprint_quality:.1%}")
        >>> print(f"HP: {creature.base_stats.health} + {creature.tamed_stats.health}")

    Attributes:
        name: Tamed name given by player.
        tribe_name: Name of the owning tribe.
        tamer_name: Name of the player who tamed it.
        level: Total level (base + extra).
        imprint_quality: Imprint percentage (0.0 - 1.0).
        imprinter_name: Name of the player who imprinted.
        tamed_stats: Tamed stat points (added after taming).
        is_clone: True if this is a cloned creature.
        is_cryo: True if stored in a cryopod.
        mutations_female: Number of mutations from female line.
        mutations_male: Number of mutations from male line.
    """

    # Cached values
    _tamed_stats: CreatureStats | None = field(default=None, repr=False)
    _mutated_stats: CreatureStats | None = field(default=None, repr=False)

    @classmethod
    def from_game_object(
        cls,
        game_object: t.Any,
        status_object: t.Any = None,
    ) -> TamedCreature:
        """
        Create a TamedCreature from a GameObject.

        Args:
            game_object: The creature's main game object.
            status_object: The creature's status component (for stats).

        Returns:
            A TamedCreature instance.
        """
        return cls(_game_object=game_object, _status_object=status_object)

    @property
    def name(self) -> str:
        """Tamed name given by player."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("TamedName", default="") or ""

    @property
    def tribe_name(self) -> str:
        """Name of the owning tribe."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("TribeName", default="") or ""

    @property
    def tamer_name(self) -> str:
        """Name of the player who tamed this creature."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("TamerString", default="") or ""

    @property
    def extra_level(self) -> int:
        """Extra levels gained after taming."""
        if self._status_object:
            val = self._status_object.get_property_value("ExtraCharacterLevel", default=0)
            return int(val) if val else 0
        return 0

    @property
    def level(self) -> int:
        """Total level (base level + extra levels)."""
        return self.base_level + self.extra_level

    @property
    def imprint_quality(self) -> float:
        """
        Imprint percentage (0.0 to 1.0).

        A value of 1.0 means 100% imprinted.
        """
        if self._status_object:
            val = self._status_object.get_property_value("DinoImprintingQuality", default=0.0)
            return float(val) if val else 0.0
        return 0.0

    @property
    def imprinter_name(self) -> str:
        """Name of the player who imprinted this creature."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("ImprinterName", default="") or ""

    @property
    def imprinter_id(self) -> int:
        """Player ID of the imprinter."""
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("ImprinterPlayerDataID", default=0)
        return int(val) if val else 0

    @property
    def tamed_stats(self) -> CreatureStats:
        """
        Tamed stat points (points added after taming).

        These are the stat points allocated by the player.
        """
        if self._tamed_stats is None:
            points = []
            if self._status_object:
                for i in range(12):
                    val = self._status_object.get_property_value(
                        "NumberOfLevelUpPointsAppliedTamed", index=i, default=0
                    )
                    points.append(int(val) if val else 0)
            self._tamed_stats = CreatureStats.from_array(points)
        return self._tamed_stats

    @property
    def mutated_stats(self) -> CreatureStats:
        """
        Mutated stat points (NumberOfMutationsAppliedTamed).

        These are the stat points gained through mutations.
        """
        if self._mutated_stats is None:
            points = []
            if self._status_object:
                for i in range(12):
                    val = self._status_object.get_property_value("NumberOfMutationsAppliedTamed", index=i, default=0)
                    points.append(int(val) if val else 0)
            self._mutated_stats = CreatureStats.from_array(points)
        return self._mutated_stats

    @property
    def experience(self) -> float:
        """Current experience points."""
        if self._status_object:
            val = self._status_object.get_property_value("ExperiencePoints", default=0.0)
            return float(val) if val else 0.0
        return 0.0

    @property
    def is_clone(self) -> bool:
        """True if this creature was cloned."""
        if not self._game_object:
            return False
        is_clone = self._game_object.get_property_value("bIsClone", default=False)
        if is_clone:
            return True
        return self._game_object.get_property_value("bIsCloneDino", default=False)

    @property
    def is_cryo(self) -> bool:
        """True if this creature is stored in a cryopod."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("IsInCryo", default=False)

    @property
    def is_wandering(self) -> bool:
        """True if wandering is enabled."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("bEnableTamedWandering", default=False)

    @property
    def is_mating(self) -> bool:
        """True if mating is enabled."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("bEnableTamedMating", default=False)

    @property
    def mutations_female(self) -> int:
        """Number of mutations from the female line."""
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("RandomMutationsFemale", default=0)
        return int(val) if val else 0

    @property
    def mutations_male(self) -> int:
        """Number of mutations from the male line."""
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("RandomMutationsMale", default=0)
        return int(val) if val else 0

    @property
    def total_mutations(self) -> int:
        """Total mutations (female + male)."""
        return self.mutations_female + self.mutations_male

    @property
    def targeting_team(self) -> int:
        """Targeting team ID (tribe ID)."""
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("TargetingTeam", default=0)
        return int(val) if val else 0

    @property
    def tamed_server(self) -> str:
        """Server name where the creature was tamed."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("TamedOnServerName", default="") or ""

    @property
    def uploaded_server(self) -> str:
        """Server name from which the creature was uploaded."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("UploadedFromServerName", default="") or ""

    @property
    def father_id(self) -> int | None:
        """
        Father's dino ID, if bred.

        Parses DinoAncestors struct array to extract the father's
        combined DinoID1/DinoID2 values.
        """
        ancestors = self._get_ancestors("DinoAncestors")
        if ancestors:
            return self._extract_dino_id(ancestors[0])
        return None

    @property
    def mother_id(self) -> int | None:
        """
        Mother's dino ID, if bred.

        Parses DinoAncestorsMale struct array to extract the mother's
        combined DinoID1/DinoID2 values.
        """
        ancestors = self._get_ancestors("DinoAncestorsMale")
        if ancestors:
            return self._extract_dino_id(ancestors[0])
        return None

    @property
    def father_name(self) -> str:
        """Father's name, if bred."""
        ancestors = self._get_ancestors("DinoAncestors")
        if ancestors:
            return self._extract_ancestor_name(ancestors[0])
        return ""

    @property
    def mother_name(self) -> str:
        """Mother's name, if bred."""
        ancestors = self._get_ancestors("DinoAncestorsMale")
        if ancestors:
            return self._extract_ancestor_name(ancestors[0])
        return ""

    def _get_ancestors(self, prop_name: str) -> list[t.Any]:
        """Get ancestor list from a DinoAncestors property."""
        if not self._game_object:
            return []
        val = self._game_object.get_property_value(prop_name, default=None)
        if isinstance(val, list) and val:
            return val
        return []

    def _extract_dino_id(self, ancestor: t.Any) -> int | None:
        """Extract dino ID from an ancestor struct/dict."""
        if isinstance(ancestor, dict):
            id1 = ancestor.get("DinoID1", 0)
            id2 = ancestor.get("DinoID2", 0)
            if id1 or id2:
                return (int(id1) << 32) | (int(id2) & 0xFFFFFFFF)
        return None

    def _extract_ancestor_name(self, ancestor: t.Any) -> str:
        """Extract name from an ancestor struct/dict."""
        if isinstance(ancestor, dict):
            name = ancestor.get("DinoName", "") or ancestor.get("MaleName", "")
            return str(name) if name else ""
        return ""

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary matching C# ASV_Tamed export format."""
        result = super().to_dict()
        result.update(
            {
                "name": self.name,
                "tribeid": self.targeting_team,
                "tribe": self.tribe_name or None,
                "tamer": self.tamer_name,
                "imprinter": self.imprinter_name,
                "imprint": self.imprint_quality,
                "lvl": self.level,
                "extra_level": self.extra_level,
                "tamed_stats": self.tamed_stats.to_dict(),
                # Flat tamed stat fields matching C# export
                "hp-w": self.base_stats.health,
                "stam-w": self.base_stats.stamina,
                "melee-w": self.base_stats.melee,
                "weight-w": self.base_stats.weight,
                "speed-w": self.base_stats.speed,
                "food-w": self.base_stats.food,
                "oxy-w": self.base_stats.oxygen,
                "craft-w": self.base_stats.crafting,
                "hp-m": self.mutated_stats.health,
                "stam-m": self.mutated_stats.stamina,
                "melee-m": self.mutated_stats.melee,
                "weight-m": self.mutated_stats.weight,
                "speed-m": self.mutated_stats.speed,
                "food-m": self.mutated_stats.food,
                "oxy-m": self.mutated_stats.oxygen,
                "craft-m": self.mutated_stats.crafting,
                "hp-t": self.tamed_stats.health,
                "stam-t": self.tamed_stats.stamina,
                "melee-t": self.tamed_stats.melee,
                "weight-t": self.tamed_stats.weight,
                "speed-t": self.tamed_stats.speed,
                "food-t": self.tamed_stats.food,
                "oxy-t": self.tamed_stats.oxygen,
                "craft-t": self.tamed_stats.crafting,
                "mut-f": self.mutations_female,
                "mut-m": self.mutations_male,
                "cryo": self.is_cryo,
                "isMating": self.is_mating,
                "isNeutered": self.is_neutered,
                "isClone": self.is_clone,
                "tamedServer": self.tamed_server,
                "uploadedServer": self.uploaded_server,
                "maturation": self.maturation_percent,
                "experience": self.experience,
            }
        )
        return result

    def __repr__(self) -> str:
        name = self.name or self.class_name
        return f"TamedCreature({name!r}, level={self.level}, gender={self.gender!r})"


@dataclass
class WildCreature(Creature):
    """
    A wild (untamed) creature.

    Wild creatures have simpler attributes than tamed ones.

    Attributes:
        level: Same as base_level for wild creatures.
    """

    @classmethod
    def from_game_object(
        cls,
        game_object: t.Any,
        status_object: t.Any = None,
    ) -> WildCreature:
        """
        Create a WildCreature from a GameObject.

        Args:
            game_object: The creature's main game object.
            status_object: The creature's status component (for stats).

        Returns:
            A WildCreature instance.
        """
        return cls(_game_object=game_object, _status_object=status_object)

    @property
    def level(self) -> int:
        """Creature level (same as base level for wild)."""
        return self.base_level

    @property
    def tameable(self) -> bool:
        """
        Whether this creature can be tamed.

        Checks for the RequiredTameAffinity property — if present and > 0,
        the creature is tameable.
        """
        if not self._game_object:
            return False
        val = self._game_object.get_property_value("RequiredTameAffinity", default=None)
        if val is not None:
            return float(val) > 0
        if self._status_object:
            val = self._status_object.get_property_value("RequiredTameAffinity", default=None)
            if val is not None:
                return float(val) > 0
        return False

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary matching C# ASV_Wild export format."""
        result = super().to_dict()
        result["lvl"] = self.level
        result["tameable"] = self.tameable
        return result

    def __repr__(self) -> str:
        return f"WildCreature({self.class_name!r}, level={self.level}, gender={self.gender!r})"
