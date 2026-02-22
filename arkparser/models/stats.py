"""
Stats helper classes for creatures and players.

Provides named attribute access to the 12 ARK stat indices.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

if t.TYPE_CHECKING:
    from arkparser.common.map_config import MapConfig


@dataclass
class CreatureStats:
    """
    Creature stats with named attribute access.

    ARK uses 12 stat indices. This class provides friendly access:
    - Index 0: Health
    - Index 1: Stamina
    - Index 2: Torpidity
    - Index 3: Oxygen
    - Index 4: Food
    - Index 5: Water
    - Index 6: Temperature
    - Index 7: Weight
    - Index 8: Melee Damage
    - Index 9: Movement Speed
    - Index 10: Fortitude
    - Index 11: Crafting Skill

    Attributes:
        health: Health stat points.
        stamina: Stamina stat points.
        torpidity: Torpidity stat points.
        oxygen: Oxygen stat points.
        food: Food stat points.
        water: Water stat points.
        temperature: Temperature stat points.
        weight: Weight stat points.
        melee: Melee damage stat points.
        speed: Movement speed stat points.
        fortitude: Fortitude stat points.
        crafting: Crafting skill stat points.
    """

    health: int = 0
    stamina: int = 0
    torpidity: int = 0
    oxygen: int = 0
    food: int = 0
    water: int = 0
    temperature: int = 0
    weight: int = 0
    melee: int = 0
    speed: int = 0
    fortitude: int = 0
    crafting: int = 0

    @classmethod
    def from_array(cls, points: list[int] | None) -> CreatureStats:
        """
        Create from an array of stat points.

        Args:
            points: Array of 12 stat point values (can be None or shorter).

        Returns:
            CreatureStats instance with the stat values.
        """
        if points is None:
            return cls()

        pts = list(points) + [0] * (12 - len(points)) if len(points) < 12 else points

        return cls(
            health=pts[0],
            stamina=pts[1],
            torpidity=pts[2],
            oxygen=pts[3],
            food=pts[4],
            water=pts[5],
            temperature=pts[6],
            weight=pts[7],
            melee=pts[8],
            speed=pts[9],
            fortitude=pts[10],
            crafting=pts[11],
        )

    def to_array(self) -> list[int]:
        """Convert to array format."""
        return [
            self.health,
            self.stamina,
            self.torpidity,
            self.oxygen,
            self.food,
            self.water,
            self.temperature,
            self.weight,
            self.melee,
            self.speed,
            self.fortitude,
            self.crafting,
        ]

    @property
    def total(self) -> int:
        """Total stat points (excluding torpidity)."""
        return self.health + self.stamina + self.oxygen + self.food + self.water + self.weight + self.melee + self.speed

    def to_dict(self) -> dict[str, int]:
        """Convert to dictionary."""
        return {
            "health": self.health,
            "stamina": self.stamina,
            "torpidity": self.torpidity,
            "oxygen": self.oxygen,
            "food": self.food,
            "water": self.water,
            "temperature": self.temperature,
            "weight": self.weight,
            "melee": self.melee,
            "speed": self.speed,
            "fortitude": self.fortitude,
            "crafting": self.crafting,
        }


@dataclass
class Location:
    """
    3D position with optional rotation and GPS conversion.

    Attributes:
        x: X coordinate (UE world space).
        y: Y coordinate (UE world space).
        z: Z coordinate (UE world space).
        pitch: Pitch rotation.
        yaw: Yaw rotation.
        roll: Roll rotation.
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0
    _map_config: MapConfig | None = field(default=None, repr=False, compare=False)

    def with_map(self, map_config: MapConfig) -> Location:
        """
        Return a new Location with a map config attached for GPS conversion.

        Args:
            map_config: The map configuration to use.

        Returns:
            A new Location with GPS conversion enabled.
        """
        return Location(
            x=self.x,
            y=self.y,
            z=self.z,
            pitch=self.pitch,
            yaw=self.yaw,
            roll=self.roll,
            _map_config=map_config,
        )

    @property
    def latitude(self) -> float | None:
        """
        Latitude coordinate (requires map configuration).

        Set via ``with_map()`` or by passing map_config to the savegame parser.

        Formula: lat_shift + (y / lat_div)
        """
        if self._map_config is None:
            return None
        return self._map_config.ue_to_lat(self.y)

    @property
    def longitude(self) -> float | None:
        """
        Longitude coordinate (requires map configuration).

        Set via ``with_map()`` or by passing map_config to the savegame parser.

        Formula: lon_shift + (x / lon_div)
        """
        if self._map_config is None:
            return None
        return self._map_config.ue_to_lon(self.x)

    @property
    def ccc(self) -> str:
        """
        CCC string (cheat setplayerpos format).

        Returns:
            Space-separated "x y z" coordinate string.
        """
        return f"{self.x} {self.y} {self.z}"

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary."""
        result: dict[str, float] = {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "pitch": self.pitch,
            "yaw": self.yaw,
            "roll": self.roll,
        }
        if self.latitude is not None:
            result["lat"] = self.latitude
        if self.longitude is not None:
            result["lon"] = self.longitude
        return result
