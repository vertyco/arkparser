"""
Primitive Property Types.

These are the simple, single-value property types used in ARK save files.
Each reads a single value of a specific type.

Property Types:
    - Numeric: Int8, Int16, Int32, Int64, UInt16, UInt32, UInt64, Float, Double
    - Boolean: Bool (special - value in header, not data section)
    - String: Str (length-prefixed string)
    - Name: Name (UE4 FName - string with instance index)
    - Reference: Object (reference to another game object)
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from .base import Property, PropertyHeader, read_name

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader

    pass


def _read_worldsave_simple_prefix(reader: BinaryReader) -> tuple[int, int, int]:
    """
    Read the WorldSave prefix for simple (non-compound) property values.

    In WorldSave format for simple properties, after the common header
    (NameID + NameInstance + TypeID + TypeInstance), the format is:
        - 4 zeros (4 bytes): Padding (type_instance already read by header)
        - Length (4 bytes): Size of property data
        - Flag (1 byte): If bit 0 is set, an array index follows
        - Array Index (4 bytes): Only present if flag & 0x01

    Note: For BoolProperty, flag byte bit 4 is the bool value,
    but the array index logic still applies if bit 0 is set.

    Args:
        reader: The binary reader.

    Returns:
        Tuple of (data_size, flag_byte, array_index).
        For BoolProperty, the bool value should be derived from flag & 0x10.
    """
    _padding = reader.read_int32()  # Only 4 zeros (type_instance already read by header)
    data_size = reader.read_int32()
    flag = reader.read_uint8()

    array_index = 0
    if flag & 0x01:
        array_index = reader.read_int32()

    return data_size, flag, array_index


# =============================================================================
# Numeric Properties
# =============================================================================


@dataclass
class Int8Property(Property):
    """Signed 8-bit integer property."""

    name: str
    index: int = 0
    _value: int = 0

    @property
    def type_name(self) -> str:
        return "Int8Property"

    @property
    def value(self) -> int:
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> Int8Property:
        """Read an Int8Property from the archive."""
        index = header.index
        if worldsave_format:
            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
        elif is_asa:
            extra_byte = reader.read_uint8()
            if extra_byte & 0x01:
                index = reader.read_int32()
        value = reader.read_int8()
        return cls(name=header.name, index=index, _value=value)


@dataclass
class Int16Property(Property):
    """Signed 16-bit integer property."""

    name: str
    index: int = 0
    _value: int = 0

    @property
    def type_name(self) -> str:
        return "Int16Property"

    @property
    def value(self) -> int:
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> Int16Property:
        """Read an Int16Property from the archive."""
        index = header.index
        if worldsave_format:
            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
        elif is_asa:
            extra_byte = reader.read_uint8()
            if extra_byte & 0x01:
                index = reader.read_int32()
        value = reader.read_int16()
        return cls(name=header.name, index=index, _value=value)


@dataclass
class IntProperty(Property):
    """Signed 32-bit integer property (most common integer type)."""

    name: str
    index: int = 0
    _value: int = 0

    @property
    def type_name(self) -> str:
        return "IntProperty"

    @property
    def value(self) -> int:
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> IntProperty:
        """Read an IntProperty from the archive."""
        index = header.index
        if worldsave_format:
            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
        elif is_asa:
            extra_byte = reader.read_uint8()
            if extra_byte & 0x01:
                index = reader.read_int32()
        value = reader.read_int32()
        return cls(name=header.name, index=index, _value=value)


@dataclass
class Int64Property(Property):
    """Signed 64-bit integer property."""

    name: str
    index: int = 0
    _value: int = 0

    @property
    def type_name(self) -> str:
        return "Int64Property"

    @property
    def value(self) -> int:
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> Int64Property:
        """Read an Int64Property from the archive."""
        index = header.index
        if worldsave_format:
            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
        elif is_asa:
            extra_byte = reader.read_uint8()
            if extra_byte & 0x01:
                index = reader.read_int32()
        value = reader.read_int64()
        return cls(name=header.name, index=index, _value=value)


@dataclass
class UInt16Property(Property):
    """Unsigned 16-bit integer property."""

    name: str
    index: int = 0
    _value: int = 0

    @property
    def type_name(self) -> str:
        return "UInt16Property"

    @property
    def value(self) -> int:
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> UInt16Property:
        """Read a UInt16Property from the archive."""
        index = header.index
        if worldsave_format:
            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
        elif is_asa:
            extra_byte = reader.read_uint8()
            if extra_byte & 0x01:
                index = reader.read_int32()
        value = reader.read_uint16()
        return cls(name=header.name, index=index, _value=value)


@dataclass
class UInt32Property(Property):
    """Unsigned 32-bit integer property."""

    name: str
    index: int = 0
    _value: int = 0

    @property
    def type_name(self) -> str:
        return "UInt32Property"

    @property
    def value(self) -> int:
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> UInt32Property:
        """Read a UInt32Property from the archive."""
        index = header.index
        if worldsave_format:
            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
        elif is_asa:
            extra_byte = reader.read_uint8()
            if extra_byte & 0x01:
                index = reader.read_int32()
        value = reader.read_uint32()
        return cls(name=header.name, index=index, _value=value)


@dataclass
class UInt64Property(Property):
    """Unsigned 64-bit integer property."""

    name: str
    index: int = 0
    _value: int = 0

    @property
    def type_name(self) -> str:
        return "UInt64Property"

    @property
    def value(self) -> int:
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> UInt64Property:
        """Read a UInt64Property from the archive."""
        index = header.index
        if worldsave_format:
            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
        elif is_asa:
            extra_byte = reader.read_uint8()
            if extra_byte & 0x01:
                index = reader.read_int32()
        value = reader.read_uint64()
        return cls(name=header.name, index=index, _value=value)


@dataclass
class FloatProperty(Property):
    """32-bit floating point property."""

    name: str
    index: int = 0
    _value: float = 0.0

    @property
    def type_name(self) -> str:
        return "FloatProperty"

    @property
    def value(self) -> float:
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> FloatProperty:
        """Read a FloatProperty from the archive."""
        index = header.index
        if worldsave_format:
            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
        elif is_asa:
            extra_byte = reader.read_uint8()
            if extra_byte & 0x01:
                index = reader.read_int32()
        value = reader.read_float()
        return cls(name=header.name, index=index, _value=value)


@dataclass
class DoubleProperty(Property):
    """64-bit floating point property."""

    name: str
    index: int = 0
    _value: float = 0.0

    @property
    def type_name(self) -> str:
        return "DoubleProperty"

    @property
    def value(self) -> float:
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> DoubleProperty:
        """Read a DoubleProperty from the archive."""
        index = header.index
        if worldsave_format:
            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
        elif is_asa:
            extra_byte = reader.read_uint8()
            if extra_byte & 0x01:
                index = reader.read_int32()
        value = reader.read_double()
        return cls(name=header.name, index=index, _value=value)


# =============================================================================
# Boolean Property
# =============================================================================


@dataclass
class BoolProperty(Property):
    """
    Boolean property.

    SPECIAL: The value is stored in the header, not the data section.
    - ASE: UInt8 value after index
    - ASA: Int16 value after index

    The data_size in the header is always 0 for BoolProperty.
    """

    name: str
    index: int = 0
    _value: bool = False

    @property
    def type_name(self) -> str:
        return "BoolProperty"

    @property
    def value(self) -> bool:
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> BoolProperty:
        """Read a BoolProperty from the archive.

        WorldSave: The flag byte after length can encode both array index AND value.
            - If flag & 0x01: next 4 bytes are array_index
            - The bool value is determined by flag != 0 (any non-zero is true)
            Note: For BoolProperty, data_size is always 0.
        ASE: The value (UInt8) is read immediately after the header.
        ASA: extra_byte(1) where the value is stored in the extra_byte itself.
        """
        index = header.index
        if worldsave_format:
            # For BoolProperty, format is: 8 zeros + Length(0) + Flag(=value with potential index)
            _data_size, flag, arr_index = _read_worldsave_simple_prefix(reader)
            # For BoolProperty, ANY non-zero flag means true
            # But if flag & 0x01, the array_index was already read
            # The true "value" is whether flag was non-zero
            # Note: flag values like 0x00=false, 0x01=has_index+false, 0x10=true, 0x11=has_index+true
            # Actually, looking at data: 0x00=false (no index), 0x10=true (no index)
            # If 0x01: index follows, and value is... hmm
            # Safest: value = (flag & ~0x01) != 0 or (flag == 0x01 means just has index, value false?)
            # Actually based on testing: flag=0x00 means false, flag=0x10 means true
            # flag=0x01 means has_index+false?, flag=0x11 means has_index+true?
            # Let's use: value = (flag >> 4) != 0  or just value = flag >= 0x10
            value = (flag & 0x10) != 0  # Bit 4 is the actual bool value
            index = arr_index
        elif is_asa:
            extra_byte = reader.read_uint8()
            value = extra_byte != 0
        else:
            value = reader.read_uint8() != 0
        return cls(name=header.name, index=index, _value=value)


# =============================================================================
# String Properties
# =============================================================================


@dataclass
class StrProperty(Property):
    """String property (length-prefixed string)."""

    name: str
    index: int = 0
    _value: str = ""

    @property
    def type_name(self) -> str:
        return "StrProperty"

    @property
    def value(self) -> str:
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> StrProperty:
        """Read a StrProperty from the archive."""
        index = header.index
        if worldsave_format:
            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
        elif is_asa:
            extra_byte = reader.read_uint8()
            if extra_byte & 0x01:
                index = reader.read_int32()
        value = reader.read_string()
        return cls(name=header.name, index=index, _value=value)


@dataclass
class NameProperty(Property):
    """
    Name property (UE4 FName).

    Stores a name with optional instance index.
    Without name table: reads as string with "_N" suffix parsing.
    With name table: reads index + instance from table.
    """

    name: str
    index: int = 0
    _value: str = ""  # Stored as string for simplicity

    @property
    def type_name(self) -> str:
        return "NameProperty"

    @property
    def value(self) -> str:
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> NameProperty:
        """Read a NameProperty from the archive.

        WorldSave: terminator(1) + (name_id + name_instance)
        ASA: extra(1), [index(4) if extra & 1], value(string)
        ASE: name string (or name table reference)
        """
        index = header.index
        if worldsave_format:
            # WorldSave format: simple prefix + name table reference
            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
            if name_table and isinstance(name_table, dict):
                name_id = reader.read_int32()
                name_instance = reader.read_int32()
                value = name_table.get(name_id, f"__UNKNOWN_{name_id}__")
                if name_instance > 0:
                    value = f"{value}_{name_instance - 1}"
            else:
                value = reader.read_string()
        elif is_asa:
            extra_byte = reader.read_uint8()
            if extra_byte & 0x01:
                index = reader.read_int32()
            value = reader.read_string()
        else:
            # ASE: Read name (uses name table if available)
            value = read_name(reader, name_table)
        return cls(name=header.name, index=index, _value=value)


# =============================================================================
# Object Reference Property
# =============================================================================


@dataclass
class ObjectProperty(Property):
    """
    Object reference property.

    References another game object in the save file.
    - ASE: Int32 type (0=index, 1=name) + value
    - ASA: Int16 isName + (GUID or Name)
    """

    name: str
    index: int = 0
    _object_id: int | None = None
    _object_name: str | None = None

    @property
    def type_name(self) -> str:
        return "ObjectProperty"

    @property
    def value(self) -> int | str | None:
        """Returns the object ID (int) or name (str)."""
        if self._object_id is not None:
            return self._object_id
        return self._object_name

    @property
    def object_id(self) -> int | None:
        """The referenced object's ID (ASE style)."""
        return self._object_id

    @property
    def object_name(self) -> str | None:
        """The referenced object's name (if by-name reference)."""
        return self._object_name

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> ObjectProperty:
        """Read an ObjectProperty from the archive.

        ASE format (depends on data_size):
        - data_size >= 8: Read type (4 bytes) + value (object ID or name)
        - data_size == 4: Read only object ID (4 bytes)

        ASA format:
        - In ASA string-based files, header.index contains the data size
        - extra(1), [index(4) if extra & 0x01], existsFlag(4)
        - If existsFlag == 1 and dataSize > 5: path(string)
        - DataSize > 5 accounts for: extra(1) + existsFlag(4) = 5 bytes minimum

        WorldSave format:
        - prefix(9) + ushort marker(2)
        - If marker == 1: name reference (name_id(4) + name_instance(4) = 8 bytes)
        - If marker != 1: GUID reference (16 bytes)
        """
        if worldsave_format:
            # WorldSave format: prefix + 2 byte marker + name(8) or GUID(16)
            from uuid import UUID

            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
            index = header.index
            marker = reader.read_uint16()

            if marker == 1:
                # Name reference: read name from name table (8 bytes)
                name_id = reader.read_int32()
                name_instance = reader.read_int32()
                if name_table and isinstance(name_table, dict):
                    ref_name = name_table.get(name_id, f"__UNKNOWN_{name_id}__")
                else:
                    ref_name = f"__UNKNOWN_{name_id}__"
                if name_instance > 0:
                    ref_name = f"{ref_name}_{name_instance - 1}"
                return cls(name=header.name, index=index, _object_name=ref_name)
            else:
                # GUID reference: read 16-byte GUID
                guid_bytes = reader.read_bytes(16)
                if all(b == 0 for b in guid_bytes):
                    return cls(name=header.name, index=index)
                guid = UUID(bytes_le=guid_bytes)
                return cls(name=header.name, index=index, _object_name=str(guid))
        elif is_asa:
            extra_byte = reader.read_uint8()
            index = header.index
            if extra_byte & 0x01:
                index = reader.read_int32()
            exists_flag = reader.read_int32()

            # In ASA, use header.index as the data size indicator
            # If data_size is 0, check index instead
            data_size = header.index if header.data_size == 0 else header.data_size

            if exists_flag == 1:
                # Check if there's more data after exists_flag
                # Minimum is extra(1) + exists_flag(4) = 5 bytes
                if data_size > 5:
                    # Has path string
                    path = reader.read_string()
                    return cls(name=header.name, index=index, _object_name=path)
                else:
                    # No path, just null reference
                    return cls(name=header.name, index=index)
            elif exists_flag == -1:
                # Null reference
                return cls(name=header.name, index=index)
            elif exists_flag == 0:
                # Null reference with extra -1 marker
                _marker = reader.read_int32()
                return cls(name=header.name, index=index)
            else:
                # Unknown flag
                return cls(name=header.name, index=index)
        else:
            # ASE format: Reading depends on data_size
            data_size = header.data_size

            if data_size >= 8:
                # Full format: Int32 type + value
                ref_type = reader.read_int32()
                if ref_type == 0:
                    # Object index
                    obj_id = reader.read_int32()
                    return cls(name=header.name, index=header.index, _object_id=obj_id)
                elif ref_type == 1:
                    # Object name (uses name table if available)
                    name_value = read_name(reader, name_table)
                    return cls(name=header.name, index=header.index, _object_name=name_value)
                else:
                    # Unknown type, seek back and read as name (TypePathNoType case from C#)
                    reader.skip(-4)
                    name_value = read_name(reader, name_table)
                    return cls(name=header.name, index=header.index, _object_name=name_value)
            elif data_size == 4:
                # Short format (Version 5): Only object ID, no type field
                obj_id = reader.read_int32()
                return cls(name=header.name, index=header.index, _object_id=obj_id)
            else:
                # Unknown format, skip remaining bytes
                reader.skip(data_size)
                return cls(name=header.name, index=header.index)


# =============================================================================
# Soft Object Reference Property
# =============================================================================


@dataclass
class SoftObjectProperty(Property):
    """
    Soft object reference property.

    Used for soft references to assets (like blueprint paths).
    Format (ASA): data_size(4), index(4), extra(1), path(string), name(string), padding(4)
    The padding is always 0x00000000 (empty string marker).
    """

    name: str
    index: int = 0
    _path: str = ""
    _sub_path: str = ""

    @property
    def type_name(self) -> str:
        return "SoftObjectProperty"

    @property
    def value(self) -> dict[str, str]:
        """Returns the path and sub-path as a dict."""
        return {"path": self._path, "name": self._sub_path}

    @property
    def path(self) -> str:
        """The asset path."""
        return self._path

    @property
    def sub_path(self) -> str:
        """The sub-path/name."""
        return self._sub_path

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> SoftObjectProperty:
        """Read a SoftObjectProperty from the archive.

        WorldSave: terminator(1) + path(string) + name(string)
        ASA: extra(1), [index(4) if extra & 0x01], path(string), name(string), padding(4)
        ASE: path(string), name(string)
        """
        index = header.index
        if worldsave_format:
            _data_size, _flag, index = _read_worldsave_simple_prefix(reader)
            # WorldSave stores path as name table reference (8 bytes), not inline string
            if name_table and isinstance(name_table, dict):
                path = read_name(reader, name_table)
            else:
                path = reader.read_string()
            # Remaining data is padding (typically 4 zero bytes)
            _padding = reader.read_int32()
            return cls(name=header.name, index=index, _path=path, _sub_path="")
        elif is_asa:
            extra_byte = reader.read_uint8()
            if extra_byte & 0x01:
                index = reader.read_int32()
            path = reader.read_string()
            sub_path = reader.read_string()
            # Read the trailing padding (always 0)
            _padding = reader.read_int32()
            return cls(name=header.name, index=index, _path=path, _sub_path=sub_path)
        else:
            # ASE format - just path and sub-path
            path = reader.read_string()
            sub_path = reader.read_string()
            return cls(name=header.name, index=index, _path=path, _sub_path=sub_path)
