"""
Structure model class - Map structures (buildings, rafts, etc.).

Wraps GameObject with intuitive attribute access for structure data.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from .stats import Location


@dataclass
class Structure:
    """
    A placed structure (building piece, crafting station, etc.).

    Wraps a GameObject representing a structure with intuitive property access.

    Attributes:
        class_name: Blueprint class name.
        owner_tribe_id: ID of the owning tribe.
        owner_tribe_name: Name of the owning tribe.
        location: World position.
        health: Current health.
        max_health: Maximum health.

    Example:
        >>> for structure in save.structures:
        ...     print(f"{structure.class_name} - {structure.owner_tribe_name}")
    """

    _game_object: t.Any = field(default=None, repr=False)

    @classmethod
    def from_game_object(cls, game_object: t.Any) -> Structure:
        """
        Create a Structure from a GameObject.

        Args:
            game_object: The structure's game object.

        Returns:
            A Structure instance.
        """
        return cls(_game_object=game_object)

    @property
    def class_name(self) -> str:
        """Blueprint class name."""
        return self._game_object.class_name if self._game_object else ""

    @property
    def guid(self) -> str:
        """Unique identifier (ASA only)."""
        return self._game_object.guid if self._game_object else ""

    @property
    def owner_tribe_id(self) -> int:
        """ID of the owning tribe."""
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("TargetingTeam", default=0)
        return int(val) if val else 0

    @property
    def owner_tribe_name(self) -> str:
        """Name of the owning tribe."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("OwnerName", default="") or ""

    @property
    def owner_name(self) -> str:
        """Name of the owner (player who placed it)."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("OwnerName", default="") or ""

    @property
    def health(self) -> float:
        """Current health."""
        if not self._game_object:
            return 0.0
        val = self._game_object.get_property_value("Health", default=0.0)
        return float(val) if val else 0.0

    @property
    def max_health(self) -> float:
        """Maximum health."""
        if not self._game_object:
            return 0.0
        val = self._game_object.get_property_value("MaxHealth", default=0.0)
        return float(val) if val else 0.0

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
    def is_powered(self) -> bool:
        """True if the structure is powered (for electrical structures)."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("bIsPowered", default=False)

    @property
    def is_locked(self) -> bool:
        """True if the structure is locked (for doors, containers)."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("bIsLocked", default=False)

    @property
    def decay_time(self) -> float:
        """Time until decay (in seconds)."""
        if not self._game_object:
            return 0.0
        val = self._game_object.get_property_value("LastInAllyRangeTime", default=0.0)
        return float(val) if val else 0.0

    @property
    def custom_name(self) -> str:
        """Custom name given to the structure (if renamed)."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("StructureName", default="") or ""

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
        """Convert to dictionary matching C# ASV_Structures export format."""
        result: dict[str, t.Any] = {
            "tribeid": self.owner_tribe_id,
            "tribe": self.owner_tribe_name,
            "struct": self.class_name,
            "name": self.custom_name,
        }
        if self.location:
            result["location"] = self.location.to_dict()
            result["ccc"] = self.location.ccc
            if self.location.latitude is not None:
                result["lat"] = self.location.latitude
            if self.location.longitude is not None:
                result["lon"] = self.location.longitude
        return result

    def __repr__(self) -> str:
        return f"Structure({self.class_name!r})"
