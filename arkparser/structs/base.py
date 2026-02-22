"""
Struct Base Classes.

Structs in ARK save files come in two forms:
1. Native structs: Fixed binary format, known by struct type name
2. Property-based structs: List of properties terminated by "None"

This module provides the abstract base class and common types.
"""

from __future__ import annotations

import typing as t
from abc import ABC, abstractmethod
from dataclasses import dataclass

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader


class Struct(ABC):
    """
    Abstract base class for all struct types.

    Structs are typed data containers used within StructProperty values.
    """

    @property
    @abstractmethod
    def struct_type(self) -> str:
        """The struct type name (e.g., 'Vector', 'Color')."""
        ...

    @property
    @abstractmethod
    def is_native(self) -> bool:
        """True if this is a native (fixed format) struct."""
        ...

    @abstractmethod
    def to_dict(self) -> dict[str, t.Any]:
        """Convert the struct to a dictionary for serialization."""
        ...

    @classmethod
    @abstractmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False, **kwargs: t.Any) -> Struct:
        """Read the struct from binary data."""
        ...


@dataclass
class NativeStruct(Struct):
    """
    Base class for native structs with fixed binary formats.

    Native structs have a known, fixed structure that doesn't use the
    property system. Examples: Vector, Rotator, Color, etc.
    """

    @property
    def is_native(self) -> bool:
        return True
