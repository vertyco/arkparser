"""
Color Structs.

Color-related native structs for storing RGBA color values.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from .base import NativeStruct

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader


@dataclass
class Color(NativeStruct):
    """
    BGRA Color (8-bit per channel).

    Format: b, g, r, a as UInt8 (4 bytes total).
    Note: Byte order is BGRA, not RGBA!
    """

    b: int = 0
    g: int = 0
    r: int = 0
    a: int = 255

    @property
    def struct_type(self) -> str:
        return "Color"

    def to_dict(self) -> dict[str, int]:
        return {"r": self.r, "g": self.g, "b": self.b, "a": self.a}

    @property
    def rgba(self) -> tuple[int, int, int, int]:
        """Get color as (r, g, b, a) tuple."""
        return (self.r, self.g, self.b, self.a)

    @property
    def hex(self) -> str:
        """Get color as hex string (#RRGGBB or #RRGGBBAA)."""
        if self.a == 255:
            return f"#{self.r:02x}{self.g:02x}{self.b:02x}"
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}{self.a:02x}"

    @classmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False, **kwargs: t.Any) -> Color:
        """Read a Color from the archive."""
        return cls(
            b=reader.read_uint8(),
            g=reader.read_uint8(),
            r=reader.read_uint8(),
            a=reader.read_uint8(),
        )


@dataclass
class LinearColor(NativeStruct):
    """
    Linear RGBA Color (32-bit float per channel).

    Format: r, g, b, a as Float (16 bytes total).
    Values are typically in range [0.0, 1.0] but can exceed for HDR.
    """

    r: float = 0.0
    g: float = 0.0
    b: float = 0.0
    a: float = 1.0

    @property
    def struct_type(self) -> str:
        return "LinearColor"

    def to_dict(self) -> dict[str, float]:
        return {"r": self.r, "g": self.g, "b": self.b, "a": self.a}

    def to_color(self) -> Color:
        """Convert to 8-bit Color (clamped to 0-255)."""
        return Color(
            r=max(0, min(255, int(self.r * 255))),
            g=max(0, min(255, int(self.g * 255))),
            b=max(0, min(255, int(self.b * 255))),
            a=max(0, min(255, int(self.a * 255))),
        )

    @classmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False, **kwargs: t.Any) -> LinearColor:
        """Read a LinearColor from the archive.

        Args:
            reader: Binary reader positioned at the struct data.
            is_asa: True for ASA format.

        Note: For ASA indexed struct properties, the array index prefix is
        already handled by the struct registry before this method is called.
        """
        return cls(
            r=reader.read_float(),
            g=reader.read_float(),
            b=reader.read_float(),
            a=reader.read_float(),
        )
