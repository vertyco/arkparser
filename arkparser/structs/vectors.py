"""
Vector and Rotation Structs.

Geometric structs used for positions, rotations, and quaternions.
Note: ASE uses Float (4 bytes), ASA uses Double (8 bytes) for vectors.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from .base import NativeStruct

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader


@dataclass
class Vector(NativeStruct):
    """
    3D Vector (x, y, z).

    ASE: 3 x Float (12 bytes)
    ASA: 3 x Double (24 bytes)
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    @property
    def struct_type(self) -> str:
        return "Vector"

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}

    @classmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False, **kwargs: t.Any) -> Vector:
        """Read a Vector from the archive."""
        if is_asa:
            return cls(
                x=reader.read_double(),
                y=reader.read_double(),
                z=reader.read_double(),
            )
        else:
            return cls(
                x=reader.read_float(),
                y=reader.read_float(),
                z=reader.read_float(),
            )


@dataclass
class Vector2D(NativeStruct):
    """
    2D Vector (x, y).

    ASE: 2 x Float (8 bytes)
    ASA: 2 x Double (16 bytes)
    """

    x: float = 0.0
    y: float = 0.0

    @property
    def struct_type(self) -> str:
        return "Vector2D"

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}

    @classmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False, **kwargs: t.Any) -> Vector2D:
        """Read a Vector2D from the archive."""
        if is_asa:
            return cls(
                x=reader.read_double(),
                y=reader.read_double(),
            )
        else:
            return cls(
                x=reader.read_float(),
                y=reader.read_float(),
            )


@dataclass
class Rotator(NativeStruct):
    """
    Rotation angles (pitch, yaw, roll).

    ASE: 3 x Float (12 bytes)
    ASA: 3 x Double (24 bytes)
    """

    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0

    @property
    def struct_type(self) -> str:
        return "Rotator"

    def to_dict(self) -> dict[str, float]:
        return {"pitch": self.pitch, "yaw": self.yaw, "roll": self.roll}

    @classmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False, **kwargs: t.Any) -> Rotator:
        """Read a Rotator from the archive."""
        if is_asa:
            return cls(
                pitch=reader.read_double(),
                yaw=reader.read_double(),
                roll=reader.read_double(),
            )
        else:
            return cls(
                pitch=reader.read_float(),
                yaw=reader.read_float(),
                roll=reader.read_float(),
            )


@dataclass
class Quat(NativeStruct):
    """
    Quaternion rotation (x, y, z, w).

    ASE: 4 x Float (16 bytes)
    ASA: 4 x Float (16 bytes) for non-worldsave, 4 x Double (32 bytes) for worldsave
    """

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 0.0

    @property
    def struct_type(self) -> str:
        return "Quat"

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z, "w": self.w}

    @classmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False, worldsave_format: bool = False, **kwargs: t.Any) -> Quat:
        """Read a Quat from the archive."""
        if worldsave_format:
            # WorldSave uses doubles for quaternions
            return cls(
                x=reader.read_double(),
                y=reader.read_double(),
                z=reader.read_double(),
                w=reader.read_double(),
            )
        else:
            return cls(
                x=reader.read_float(),
                y=reader.read_float(),
                z=reader.read_float(),
                w=reader.read_float(),
            )


@dataclass
class IntPoint(NativeStruct):
    """
    2D Integer point (x, y).

    Always 2 x Int32 (8 bytes).
    """

    x: int = 0
    y: int = 0

    @property
    def struct_type(self) -> str:
        return "IntPoint"

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y}

    @classmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False, **kwargs: t.Any) -> IntPoint:
        """Read an IntPoint from the archive."""
        return cls(
            x=reader.read_int32(),
            y=reader.read_int32(),
        )


@dataclass
class IntVector(NativeStruct):
    """
    3D Integer vector (x, y, z).

    Always 3 x Int32 (12 bytes).
    """

    x: int = 0
    y: int = 0
    z: int = 0

    @property
    def struct_type(self) -> str:
        return "IntVector"

    def to_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "z": self.z}

    @classmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False, **kwargs: t.Any) -> IntVector:
        """Read an IntVector from the archive."""
        return cls(
            x=reader.read_int32(),
            y=reader.read_int32(),
            z=reader.read_int32(),
        )
