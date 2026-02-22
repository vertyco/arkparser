"""
Player model class - ARK player/profile data.

Wraps profile data with intuitive attribute access.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from .stats import CreatureStats, Location


@dataclass
class Player:
    """
    An ARK player character.

    Wraps profile and character data with intuitive property access.

    Attributes:
        name: Player character name.
        level: Character level.
        experience: Experience points.
        tribe_id: Tribe ID the player belongs to.
        tribe_name: Name of the player's tribe.
        stats: Player stat points.

    Example:
        >>> player = Player.from_game_object(obj, status_obj)
        >>> print(f"{player.name} - Level {player.level}")
        >>> print(f"Health: {player.stats.health}")
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
    ) -> Player:
        """
        Create a Player from a GameObject.

        Args:
            game_object: The player's main game object.
            status_object: The player's status component (for stats).

        Returns:
            A Player instance.
        """
        return cls(_game_object=game_object, _status_object=status_object)

    @property
    def guid(self) -> str:
        """Unique identifier (ASA only)."""
        return self._game_object.guid if self._game_object else ""

    @property
    def player_id(self) -> int:
        """Player data ID (unique per player)."""
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("PlayerDataID", default=0)
        return int(val) if val else 0

    @property
    def name(self) -> str:
        """Player character name."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("PlayerName", default="") or ""

    @property
    def steam_name(self) -> str:
        """Steam/platform username."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("PlatformProfileName", default="") or ""

    @property
    def tribe_id(self) -> int:
        """Tribe ID the player belongs to."""
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("TribeID", default=0)
        return int(val) if val else 0

    @property
    def tribe_name(self) -> str:
        """Name of the player's tribe."""
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
        Player stat points.

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
    def engram_points(self) -> int:
        """Total engram points available."""
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("TotalEngramPoints", default=0)
        return int(val) if val else 0

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
    def last_server(self) -> str:
        """Last server the player was on."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("LastServerSavedOn", default="") or ""

    @property
    def steam_id(self) -> str:
        """Steam/platform unique ID (from UniqueID or file)."""
        if not self._game_object:
            return ""
        val = self._game_object.get_property_value("UniqueID", default="")
        if val:
            return str(val)
        return ""

    @property
    def data_file(self) -> str:
        """Profile data file name (e.g., '2535445137750472.arkprofile')."""
        sid = self.steam_id
        if sid:
            return f"{sid}.arkprofile"
        pid = self.player_id
        if pid:
            return f"{pid}.arkprofile"
        return ""

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
        """Convert to dictionary matching C# ASV_Players export format."""
        result: dict[str, t.Any] = {
            "playerid": self.player_id,
            "steam": self.steam_name,
            "name": self.name,
            "tribeid": self.tribe_id,
            "tribe": self.tribe_name,
            "sex": self.gender,
            "lvl": self.level,
            # Flat stat fields matching C# export
            "hp": self.stats.health,
            "stam": self.stats.stamina,
            "melee": self.stats.melee,
            "weight": self.stats.weight,
            "speed": self.stats.speed,
            "food": self.stats.food,
            "water": self.stats.water,
            "oxy": self.stats.oxygen,
            "craft": self.stats.crafting,
            "fort": self.stats.fortitude,
            "stats": self.stats.to_dict(),
            "engram_points": self.engram_points,
        }
        if self.steam_id:
            result["steamid"] = self.steam_id
        if self.data_file:
            result["dataFile"] = self.data_file
        if self.location:
            result["location"] = self.location.to_dict()
            result["ccc"] = self.location.ccc
            if self.location.latitude is not None:
                result["lat"] = self.location.latitude
            if self.location.longitude is not None:
                result["lon"] = self.location.longitude
        return result

    def __repr__(self) -> str:
        return f"Player({self.name!r}, level={self.level})"
