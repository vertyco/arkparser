"""
Byte Property Type.

ByteProperty is special because it can represent either:
1. A raw byte value (UInt8)
2. An enum value (string name from an enum type)

The enum name is stored after the index, before the value.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from ..common.exceptions import ArkParseError
from .base import Property, PropertyHeader, read_name

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader


@dataclass(slots=True)
class ByteProperty(Property):
    """
    Byte property - can be either a raw byte or an enum value.

    Format after header:
        - String enum_name (e.g., "None" for raw byte, or enum type name)
        - ASA: 1 unknown byte
        - If enum_name == "None": UInt8 value
        - Else: String enum_value (the actual enum constant name)
    """

    name: str
    index: int = 0
    enum_name: str = "None"  # "None" means raw byte, otherwise enum type name
    _byte_value: int | None = None  # Raw byte value (if enum_name == "None")
    _enum_value: str | None = None  # Enum constant name (if enum_name != "None")

    @property
    def type_name(self) -> str:
        return "ByteProperty"

    @property
    def value(self) -> int | str:
        """Returns byte value (int) or enum value (str)."""
        if self._byte_value is not None:
            return self._byte_value
        return self._enum_value or ""

    @property
    def is_enum(self) -> bool:
        """True if this is an enum value, False if raw byte."""
        return self.enum_name != "None"

    @property
    def byte_value(self) -> int | None:
        """The raw byte value, or None if this is an enum."""
        return self._byte_value

    @property
    def enum_value(self) -> str | None:
        """The enum constant name, or None if this is a raw byte."""
        return self._enum_value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> ByteProperty:
        """
        Read a ByteProperty from the archive.

        WorldSave format: 8 zeros + length + array_index + byte_value
        (Note: In WorldSave format, ByteProperty is always a raw byte)

        ASE format:
        - enum_name (name) - "None" for raw byte, or enum type name
        - If enum_name == "None": UInt8 value
        - Else: enum_value (name) - the enum constant

        ASA format (string-based files like cloud inventory):
        Header: name, type, data_size, index

        For raw byte (data_size=0, index=1):
        - enum_name (1 byte null = empty string)
        - extra_byte (1)
        - byte_value (1)

        For raw byte (index=1 in header):
        - extra_byte (1)
        - If extra_byte & 0x01: array_index (int32)
        - byte_value (1)

        For enum (index > 1 = enum_name_length):
        - enum_name string (using header.index as length, null-terminated)
        - extra1 (int32)
        - blueprint_path (string)
        - zeros (int32)
        - data_size (int32)
        - extra_byte (1)
        - If extra_byte & 0x01: array_index (int32)
        - enum_value (string)
        """
        if worldsave_format:
            # ASA v13 ByteProperty body layout (per AsaSavegameToolkit):
            #   dataSize(4) + position(4) + byteType_ref(8) + positionByte(1) +
            #   value_byte(1) [raw] or value_name_ref(8) [enum]
            # The v14+ marker-based layout below is incompatible with v13 and
            # over-reads ~40 bytes when applied to v13 byte enums like
            # ColorSetIndices, causing cascading desync.
            if reader.save_version == 13:
                if not (name_table and isinstance(name_table, dict)):
                    raise ValueError("v13 ByteProperty requires a name table")
                _data_size = reader.read_int32()
                _position_int = reader.read_int32()
                byte_type_id = reader.read_int32()
                _byte_type_inst = reader.read_int32()
                byte_type = name_table.get(byte_type_id, f"__UNKNOWN_{byte_type_id}__")
                _position_byte = reader.read_uint8()
                if byte_type == "None":
                    byte_value = reader.read_uint8()
                    return cls(
                        name=header.name,
                        index=header.index,
                        enum_name="None",
                        _byte_value=byte_value,
                    )
                enum_value_id = reader.read_int32()
                enum_value_inst = reader.read_int32()
                enum_value = name_table.get(enum_value_id, f"__UNKNOWN_{enum_value_id}__")
                if enum_value_inst > 0:
                    enum_value = f"{enum_value}_{enum_value_inst - 1}"
                return cls(
                    name=header.name,
                    index=header.index,
                    enum_name=byte_type,
                    _enum_value=enum_value,
                )

            # WorldSave ByteProperty has two formats, determined by the first int32
            # after the 16-byte common header:
            #
            # Raw byte (marker == 0):
            #   marker(4) + data_size(4) + flag(1) + value(1) = 10 bytes
            #
            # Enum (marker == 1):
            #   marker(4) + enum_type_name(8) + marker2(4) + blueprint_name(8)
            #   + zeros(4) + data_size(4) + flag(1) + enum_value_name(8) = 41 bytes
            marker = reader.read_int32()

            if marker == 0:
                # Raw byte format (same as simple prefix)
                _data_size = reader.read_int32()
                flag = reader.read_uint8()
                # Simple prefix: if flag bit 0 is set, read array_index
                array_index = header.index
                if flag & 0x01:
                    array_index = reader.read_int32()
                byte_value = reader.read_uint8()
                return cls(
                    name=header.name,
                    index=array_index,
                    enum_name="None",
                    _byte_value=byte_value,
                )
            else:
                # Enum format (marker == 1): sub-header + enum value
                if not (name_table and isinstance(name_table, dict)):
                    raise ValueError("ByteProperty enum format requires a name table")

                enum_type_id = reader.read_int32()
                _enum_type_inst = reader.read_int32()
                enum_type_name = name_table.get(enum_type_id, f"__UNKNOWN_{enum_type_id}__")

                _marker2 = reader.read_int32()  # Usually 1
                _blueprint_id = reader.read_int32()
                _blueprint_inst = reader.read_int32()
                _zeros = reader.read_int32()
                _data_size = reader.read_int32()
                _flag = reader.read_uint8()

                enum_value_id = reader.read_int32()
                enum_value_inst = reader.read_int32()
                enum_value = name_table.get(enum_value_id, f"__UNKNOWN_{enum_value_id}__")
                if enum_value_inst > 0:
                    enum_value = f"{enum_value}_{enum_value_inst - 1}"

                return cls(
                    name=header.name,
                    index=header.index,
                    enum_name=enum_type_name,
                    _enum_value=enum_value,
                )
        elif is_asa:
            # For ASA, header.position (the second int32 from the file header,
            # NOT an array index) discriminates the layout:
            # - position == 1: raw byte (no enum_name)
            # - position > 1: enum type name length (null-terminated string)
            enum_name_len = header.position

            if enum_name_len == 1:
                # Raw byte value - no enum_name at all
                # Format: extra_byte + optional array_index + byte_value
                extra_byte = reader.read_uint8()
                array_index = 0
                if extra_byte & 0x01:
                    array_index = reader.read_int32()
                byte_value = reader.read_uint8()
                return cls(
                    name=header.name,
                    index=array_index,
                    enum_name="None",
                    _byte_value=byte_value,
                )
            else:
                # Enum value - has enum_name string followed by more data
                enum_name_bytes = reader.read_bytes(enum_name_len)
                enum_name = enum_name_bytes[:-1].decode("latin-1")

                # extra1 (int32)
                _extra1 = reader.read_int32()
                # blueprint_path (string)
                _blueprint_path = reader.read_string()
                # zeros (int32)
                _zeros = reader.read_int32()
                # data_size (int32)
                _data_size = reader.read_int32()
                # extra_byte (1)
                extra_byte = reader.read_uint8()
                array_index = 0
                if extra_byte & 0x01:
                    array_index = reader.read_int32()
                # enum_value (string)
                enum_value = reader.read_string()
                return cls(
                    name=header.name,
                    index=array_index,
                    enum_name=enum_name,
                    _enum_value=enum_value,
                )
        else:
            # ASE format with enum_name (uses name table if present)
            enum_name = read_name(reader, name_table)

            if enum_name == "None":
                # Raw byte value
                byte_value = reader.read_uint8()
                return cls(
                    name=header.name,
                    index=header.index,
                    enum_name=enum_name,
                    _byte_value=byte_value,
                )
            else:
                # Enum value - read the enum constant name (also uses name table)
                enum_value = read_name(reader, name_table)
                return cls(
                    name=header.name,
                    index=header.index,
                    enum_name=enum_name,
                    _enum_value=enum_value,
                )


class EnumProperty(ByteProperty):
    """Unreal scoped-enum property, e.g. a Dragon Horn's ``LinkState``.

    Unreal emits ByteProperty for the legacy ``TEnumAsByte`` and EnumProperty for
    an ``enum class``. The body is an enum-form ByteProperty's plus a nested tag
    naming the underlying storage type, so it needs its own reader.

    Kept a distinct type rather than a registry alias because ``type_name`` is
    load-bearing: GameObject forces ByteProperty groups to keep indexed dict form
    for stat arrays, while a scoped enum is scalar and should collapse to a bare
    value. ``__slots__ = ()`` keeps this free per instance.
    """

    __slots__ = ()

    @property
    def type_name(self) -> str:
        return "EnumProperty"

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,  # noqa: ARG003 - unused; ASA enums are string-based
        worldsave_format: bool = False,
    ) -> EnumProperty:
        """Read an EnumProperty body (ASA string-based files only).

        Layout, verified byte-exactly against live ASA profiles::

            enum_type_name  (header.position bytes, null-terminated)
            extra1          (int32, observed 1)
            blueprint_path  (string, e.g. "/Script/ShooterGame")
            zeros           (int32)
            underlying_type (string, e.g. "ByteProperty")   <- absent on ByteProperty
            zeros2          (int32)                          <- absent on ByteProperty
            data_size       (int32, counts the enum_value field)
            flag            (uint8, bit 0 -> an array index follows)
            enum_value      (string, e.g. "EDragonHornLinkState::Live")

        Preconditions: ``header.position`` is the enum type name's length, which
        is always > 1 because a scoped enum always names its type.
        Postconditions: reader sits on the next property header.
        Failure modes: raises ArkParseError on the ASE and worldsave paths, whose
        layouts are unverified - EnumProperty appears in no ASE fixture and in no
        ASA worldsave name table, so guessing a layout there would risk silently
        desyncing the stream instead of failing loudly.
        """
        if worldsave_format or not is_asa:
            raise ArkParseError(
                f"EnumProperty {header.name!r} in an "
                f"{'ASA worldsave' if worldsave_format else 'ASE'} stream: layout unverified. "
                "Capture the save and confirm the byte layout before enabling this path."
            )
        assert header.position > 1, f"EnumProperty {header.name!r} must name its enum type"

        enum_name = reader.read_bytes(header.position)[:-1].decode("latin-1")
        _extra1 = reader.read_int32()
        _blueprint_path = reader.read_string()
        _zeros = reader.read_int32()
        _underlying_type = reader.read_string()
        _zeros2 = reader.read_int32()
        _data_size = reader.read_int32()
        flag = reader.read_uint8()
        array_index = reader.read_int32() if flag & 0x01 else 0
        enum_value = reader.read_string()

        assert enum_value, f"EnumProperty {header.name!r} produced an empty value"
        return cls(
            name=header.name,
            index=array_index,
            enum_name=enum_name,
            _enum_value=enum_value,
        )
