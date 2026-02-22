"""
Miscellaneous Native Structs.

Various native structs that don't fit into other categories.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from .base import NativeStruct

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader


@dataclass
class UniqueNetIdRepl(NativeStruct):
    """
    Unique Network ID for player identification.

    Used for Steam IDs and other platform identifiers.

    ASE Format:
        - Int32 unknown
        - String net_id (e.g., "2533274977850953" for Xbox)

    ASA Format:
        - Byte unknown
        - String value_type (platform, e.g., "RedpointEOS")
        - Byte length
        - Bytes value (raw ID bytes, converted to hex string)
    """

    unknown: int = 0
    net_id: str = ""
    value_type: str = ""  # ASA only: platform type like "RedpointEOS"

    @property
    def struct_type(self) -> str:
        return "UniqueNetIdRepl"

    def to_dict(self) -> dict[str, t.Any]:
        result = {"unknown": self.unknown, "net_id": self.net_id}
        if self.value_type:
            result["value_type"] = self.value_type
        return result

    @property
    def steam_id(self) -> str | None:
        """Extract Steam ID if this is a Steam network ID."""
        if self.net_id.startswith("steam:"):
            return self.net_id[6:]
        return self.net_id if self.net_id else None

    @classmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False, **kwargs: t.Any) -> UniqueNetIdRepl:
        """Read a UniqueNetIdRepl from the archive."""
        if is_asa:
            # ASA format: byte unknown + string value_type + byte length + bytes value
            unknown = reader.read_uint8()
            value_type = reader.read_string()
            length = reader.read_uint8()
            value_bytes = reader.read_bytes(length)
            net_id = value_bytes.hex()
            return cls(unknown=unknown, net_id=net_id, value_type=value_type)
        else:
            # ASE format: int32 unknown + string net_id
            unknown = reader.read_int32()
            net_id = reader.read_string()
            return cls(unknown=unknown, net_id=net_id)


@dataclass
class Guid(NativeStruct):
    """
    GUID/UUID structure.

    16-byte globally unique identifier.
    """

    value: str = ""  # Stored as hex string

    @property
    def struct_type(self) -> str:
        return "Guid"

    def to_dict(self) -> dict[str, str]:
        return {"guid": self.value}

    @classmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False, **kwargs: t.Any) -> Guid:
        """Read a Guid from the archive."""
        guid_value = reader.read_guid()
        return cls(value=str(guid_value))


@dataclass
class CustomItemDataRef(NativeStruct):
    """
    Reference to custom item data.

    Used for storing references to item-specific custom data.
    Format: 4 x Int32 values (16 bytes)
    """

    value1: int = 0
    value2: int = 0
    value3: int = 0
    value4: int = 0

    @property
    def struct_type(self) -> str:
        return "CustomItemDataRef"

    def to_dict(self) -> dict[str, int]:
        return {
            "value1": self.value1,
            "value2": self.value2,
            "value3": self.value3,
            "value4": self.value4,
        }

    @classmethod
    def read(cls, reader: BinaryReader, is_asa: bool = False, **kwargs: t.Any) -> CustomItemDataRef:
        """Read a CustomItemDataRef from the archive."""
        return cls(
            value1=reader.read_int32(),
            value2=reader.read_int32(),
            value3=reader.read_int32(),
            value4=reader.read_int32(),
        )
