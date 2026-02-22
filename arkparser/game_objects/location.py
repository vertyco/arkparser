"""
Location Data.

Position and rotation data for game objects.
ASE uses floats (4 bytes each), ASA uses doubles (8 bytes each).
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader


@dataclass
class LocationData:
    """
    Position and rotation data for a game object.

    Contains 6 values: x, y, z position and pitch, yaw, roll rotation.
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0

    @property
    def position(self) -> tuple[float, float, float]:
        """Get position as (x, y, z) tuple."""
        return (self.x, self.y, self.z)

    @property
    def rotation(self) -> tuple[float, float, float]:
        """Get rotation as (pitch, yaw, roll) tuple."""
        return (self.pitch, self.yaw, self.roll)

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary."""
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "pitch": self.pitch,
            "yaw": self.yaw,
            "roll": self.roll,
        }

    @classmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False) -> LocationData:
        """
        Read location data from the archive.

        Args:
            reader: Binary reader positioned at location data.
            is_asa: True for ASA format (doubles), False for ASE (floats).

        Returns:
            LocationData instance.
        """
        if is_asa:
            return cls(
                x=reader.read_double(),
                y=reader.read_double(),
                z=reader.read_double(),
                pitch=reader.read_double(),
                yaw=reader.read_double(),
                roll=reader.read_double(),
            )
        else:
            return cls(
                x=reader.read_float(),
                y=reader.read_float(),
                z=reader.read_float(),
                pitch=reader.read_float(),
                yaw=reader.read_float(),
                roll=reader.read_float(),
            )

    @classmethod
    def size(cls, is_asa: bool = False) -> int:
        """Get the byte size of location data."""
        return 48 if is_asa else 24  # 6 doubles vs 6 floats
