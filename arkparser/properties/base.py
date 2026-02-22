"""
Property Base Classes.

Properties are the core data storage mechanism in ARK save files.
Each game object has a list of properties that store its state.

Property Format:
    +--------+--------+--------+--------+
    | Name   | Name   | Int32  | Int32  |
    | name   | type   | size   | index  |
    +--------+--------+--------+--------+

The property list is terminated by a property with name "None".
"""

from __future__ import annotations

import typing as t
from abc import ABC, abstractmethod
from dataclasses import dataclass

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader


@dataclass
class Property(ABC):
    """
    Base class for all ARK properties.

    Properties store named, typed values on game objects.
    Each property has:
    - name: The property name (e.g., "Health", "TamedName")
    - type_name: The property type (e.g., "FloatProperty", "StrProperty")
    - index: Array index for properties with the same name
    - value: The property value (type depends on property type)

    Subclasses implement reading the value based on the type.
    """

    name: str
    index: int = 0

    @property
    @abstractmethod
    def type_name(self) -> str:
        """The property type name (e.g., 'FloatProperty')."""
        ...

    @property
    @abstractmethod
    def value(self) -> t.Any:
        """The property value."""
        ...

    def __repr__(self) -> str:
        idx_str = f", index={self.index}" if self.index != 0 else ""
        return f"{self.__class__.__name__}(name={self.name!r}{idx_str}, value={self.value!r})"

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        **kwargs: t.Any,
    ) -> Property:
        """
        Read a property value from binary data.

        Subclasses must implement this to parse their specific value format.

        Args:
            reader: The binary reader positioned at the property value.
            header: The property header (name, type, data_size, index).
            is_asa: True for ASA format, False for ASE.
            **kwargs: Additional keyword arguments (name_table, worldsave_format, etc.).

        Returns:
            The parsed property instance.
        """
        raise NotImplementedError(f"{cls.__name__} must implement read()")


@dataclass
class PropertyHeader:
    """
    Property header data read before the value.

    This is used internally during parsing to pass header
    information to property constructors.
    """

    name: str
    type_name: str
    data_size: int
    index: int

    def __repr__(self) -> str:
        return f"PropertyHeader(name={self.name!r}, type={self.type_name!r}, size={self.data_size}, index={self.index})"


# Type alias for name table - can be either list (ASE) or dict (ASA)
NameTable = list[str] | dict[int, str] | None


def _read_name_from_list_table(reader: BinaryReader, name_table: list[str]) -> str:
    """
    Read a name using a list-based name table (ASE world saves).

    Name table format:
    - Int32 index: Index into name table (1-based)
    - Int32 instance: Instance number (0 = no suffix, otherwise append _{instance-1})

    Args:
        reader: The binary reader.
        name_table: The name table list (1-based indexing).

    Returns:
        The full name string with instance suffix if applicable.
    """
    index = reader.read_int32()

    # Convert from 1-based to 0-based index
    internal_index = index - 1

    if internal_index < 0 or internal_index >= len(name_table):
        # Invalid index - return placeholder
        return f"__INVALID_NAME_INDEX_{index}__"

    name = name_table[internal_index]

    # Read instance number
    instance = reader.read_int32()

    # Instance 0 means no suffix, otherwise append _{instance-1}
    if instance > 0:
        return f"{name}_{instance - 1}"
    return name


def _read_name_from_dict_table(reader: BinaryReader, name_table: dict[int, str]) -> str:
    """
    Read a name using a dict-based name table (ASA world saves).

    ASA name table format:
    - Int32 id: Hash key into name table dictionary
    - Int32 instance: Instance number (0 = no suffix, otherwise append _{instance-1})

    Args:
        reader: The binary reader.
        name_table: The name table dictionary (hash keys).

    Returns:
        The full name string with instance suffix if applicable.
    """
    name_id = reader.read_int32()

    if name_id not in name_table:
        # Unknown name - return placeholder
        return f"__UNKNOWN_NAME_{name_id}__"

    name = name_table[name_id]

    # Read instance number
    instance = reader.read_int32()

    # Instance 0 means no suffix, otherwise append _{instance-1}
    if instance > 0:
        return f"{name}_{instance - 1}"
    return name


def read_name(reader: BinaryReader, name_table: NameTable = None) -> str:
    """
    Read a name from the archive.

    If a name table is provided, reads from the table.
    Otherwise, reads a raw string.

    Args:
        reader: The binary reader.
        name_table: Optional name table for world saves.
                   - list: ASE format (1-based index)
                   - dict: ASA format (hash key)
                   - None: Read raw string

    Returns:
        The name string.
    """
    if name_table is None:
        return reader.read_string()
    elif isinstance(name_table, dict):
        return _read_name_from_dict_table(reader, name_table)
    else:
        return _read_name_from_list_table(reader, name_table)


def read_property_header(
    reader: BinaryReader,
    is_asa: bool = False,
    name_table: NameTable = None,
    worldsave_format: bool = False,
) -> PropertyHeader | None:
    """
    Read a property header from the archive.

    Returns None if the property name is "None" (end of property list).

    ASE Property header format:
        - Name: property name (string or name table index)
        - Name: property type (string or name table index)
        - Int32: data size (size of value in bytes)
        - Int32: index (for array elements with same name)

    ASA Property header format (CloudInventory, Profile, Tribe):
        - Name: property name
        - Name: property type
        - Int32: data_size
        - Int32: index

    ASA WorldSave Property header format (SQLite objects):
        - Name ID (Int32) + Name Instance (Int32)
        - Type ID (Int32) + 8 zero bytes
        - Int32: data_size
        - Byte: terminator (usually 0)

    Args:
        reader: The binary reader positioned at the property header.
        is_asa: True for ASA format, False for ASE.
        name_table: Optional name table for world saves.
                   - list: ASE format (1-based index)
                   - dict: ASA format (hash key)
        worldsave_format: True for ASA WorldSave SQLite object format.

    Returns:
        PropertyHeader or None if this is the terminator.
    """
    if worldsave_format:
        return _read_worldsave_property_header(reader, name_table)

    # Read property name
    name = read_name(reader, name_table)

    # Check for terminator
    if name == "None" or name == "" or name is None:
        return None

    # Read property type
    type_name = read_name(reader, name_table)

    # Both ASE and ASA have data_size and index in the header
    data_size = reader.read_int32()
    index = reader.read_int32()

    return PropertyHeader(
        name=name,
        type_name=type_name,
        data_size=data_size,
        index=index,
    )


def _read_worldsave_property_header(
    reader: BinaryReader,
    name_table: dict[int, str] | None,
) -> PropertyHeader | None:
    """
    Read a property header in ASA WorldSave format.

    WorldSave property header format (from TypeScript docs):
        Common header:
        - Name ID (Int32): Hash key into name table
        - Name Instance (Int32): Usually 0, for array indices use name_instance - 1
        - Type ID (Int32): Hash key for type name
        - Type Instance (Int32): Usually 0

    After the common header, the format depends on the property type:
        - Simple properties (Int, Float, etc.): 4 zeros + Length(4) + Terminator(1) + Value
        - ArrayProperty: ArrayHeader(4) + ElementTypeID(4) + ... (complex structure)
        - StructProperty: similar complex structure

    Args:
        reader: The binary reader.
        name_table: The name table dictionary (hash keys to names).

    Returns:
        PropertyHeader or None if this is the terminator.
    """
    if name_table is None:
        raise ValueError("WorldSave format requires a name table")

    # Read name: ID (4) + Instance (4)
    name_id = reader.read_int32()
    name_instance = reader.read_int32()

    # Lookup name
    name = name_table.get(name_id, f"__UNKNOWN_NAME_{name_id}__")

    # Apply instance suffix (for array-like properties with same name)
    index = 0
    if name_instance > 0:
        index = name_instance - 1
        # Don't append to name - use index field instead

    # Check for terminator
    if name == "None":
        return None

    # Read type: ID (4) + Instance (4)
    # Type instance is almost always 0 (padding), but must be read
    type_id = reader.read_int32()
    _type_instance = reader.read_int32()  # Usually 0
    type_name = name_table.get(type_id, f"__UNKNOWN_TYPE_{type_id}__")

    # NOTE: The property-type-specific data (including data_size and terminator)
    # is read by individual property readers. For the header, we return data_size=0
    # and the actual readers will determine the size from their own format.
    # This is because:
    # - Simple properties: 4 zeros + Length(4) + Term(1) + Value
    # - ArrayProperty: ArrayHeader + ElementTypeID + 8zeros + ByteLength + Term + Count
    # - StructProperty: similar complex format

    return PropertyHeader(
        name=name,
        type_name=type_name,
        data_size=0,  # Will be determined by property-specific reader
        index=index,
    )
