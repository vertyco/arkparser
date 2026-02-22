"""
Character model class - Player characters in world saves.

Wraps GameObject with intuitive attribute access for character data.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from .stats import CreatureStats, Location


@dataclass
class Character:
    """
    A player character in a world save.

    Wraps a GameObject representing a player character with intuitive property access.
    This differs from Player (profile data) - Character is the in-world entity.

    Attributes:
        class_name: Blueprint class name.
        player_name: Character name.
        tribe_id: ID of the player's tribe.
        tribe_name: Name of the player's tribe.
        level: Character level.
        location: World position.

    Example:
        >>> for character in save.characters:
        ...     print(f"{character.player_name} - Level {character.level}")
    """

    _game_object: t.Any = field(default=None, repr=False)
    _status_object: t.Any = field(default=None, repr=False)

    # Cached values
    _stats: CreatureStats | None = field(default=None, repr=False)

    @classmethod
    def from_game_object(
        cls,
        game_object: t.Any,
        status_object: t.Any = None,
    ) -> Character:
        """
        Create a Character from a GameObject.

        Args:
            game_object: The character's main game object.
            status_object: The character's status component (for stats).

        Returns:
            A Character instance.
        """
        return cls(_game_object=game_object, _status_object=status_object)

    @property
    def class_name(self) -> str:
        """Blueprint class name."""
        return self._game_object.class_name if self._game_object else ""

    @property
    def guid(self) -> str:
        """Unique identifier (ASA only)."""
        return self._game_object.guid if self._game_object else ""

    @property
    def player_id(self) -> int:
        """Unique player ID."""
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("LinkedPlayerDataID", default=0)
        if not val:
            val = self._game_object.get_property_value("PlayerDataID", default=0)
        return int(val) if val else 0

    @property
    def player_name(self) -> str:
        """Character name."""
        if not self._game_object:
            return ""
        name = self._game_object.get_property_value("PlayerName", default="")
        if not name:
            name = self._game_object.get_property_value("LinkedPlayerName", default="")
        return name or ""

    @property
    def steam_name(self) -> str:
        """Steam/platform username."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("PlatformProfileName", default="") or ""

    @property
    def tribe_id(self) -> int:
        """Tribe ID the character belongs to."""
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("TargetingTeam", default=0)
        if not val:
            val = self._game_object.get_property_value("TribeID", default=0)
        return int(val) if val else 0

    @property
    def tribe_name(self) -> str:
        """Name of the character's tribe."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("TribeName", default="") or ""

    @property
    def is_female(self) -> bool:
        """True if the character is female."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("bIsFemale", default=False)

    @property
    def gender(self) -> str:
        """Gender as string ('Female' or 'Male')."""
        return "Female" if self.is_female else "Male"

    @property
    def base_level(self) -> int:
        """Base character level."""
        if self._status_object:
            return self._status_object.get_property_value("BaseCharacterLevel", default=1)
        return 1

    @property
    def extra_level(self) -> int:
        """Extra levels (ascension levels, etc.)."""
        if self._status_object:
            val = self._status_object.get_property_value("ExtraCharacterLevel", default=0)
            return int(val) if val else 0
        return 0

    @property
    def level(self) -> int:
        """Total character level."""
        return self.base_level + self.extra_level

    @property
    def experience(self) -> float:
        """Current experience points."""
        if self._status_object:
            val = self._status_object.get_property_value("ExperiencePoints", default=0.0)
            return float(val) if val else 0.0
        return 0.0

    @property
    def stats(self) -> CreatureStats:
        """
        Character stat points.

        Uses the same 12-stat system as creatures.
        """
        if self._stats is None:
            points = []
            if self._status_object:
                for i in range(12):
                    val = self._status_object.get_property_value("NumberOfLevelUpPointsApplied", index=i, default=0)
                    points.append(int(val) if val else 0)
            self._stats = CreatureStats.from_array(points)
        return self._stats

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
    def is_sleeping(self) -> bool:
        """True if the character is sleeping (logged out)."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("bIsSleeping", default=False)

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
        """Convert to dictionary."""
        result: dict[str, t.Any] = {
            "player_id": self.player_id,
            "player_name": self.player_name,
            "gender": self.gender,
            "level": self.level,
            "experience": self.experience,
            "stats": self.stats.to_dict(),
            "tribe_id": self.tribe_id,
            "tribe_name": self.tribe_name,
        }
        if self.steam_name:
            result["steam_name"] = self.steam_name
        if self.location:
            result["location"] = self.location.to_dict()
        return result

    def __repr__(self) -> str:
        return f"Character({self.player_name!r}, level={self.level})"
