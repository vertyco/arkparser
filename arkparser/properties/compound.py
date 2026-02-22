"""
Compound Property Types.

These are complex property types that contain other values or properties:
- ArrayProperty: Contains a list of values of the same type
- StructProperty: Contains structured data (either native format or property list)
- MapProperty: Contains key-value pairs (less common)
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

from .base import Property, PropertyHeader, read_name

if t.TYPE_CHECKING:
    from ..common.binary_reader import BinaryReader


# =============================================================================
# Array Property
# =============================================================================


@dataclass
class ArrayProperty(Property):
    """
    Array property - contains a list of values of the same type.

    Format:
        Header + Name arrayType + Int32 count + [elements...]

    For ASA, there's an extra unknown byte after the index.

    Element types are determined by arrayType:
        - IntProperty, FloatProperty, etc. -> simple values
        - ObjectProperty -> object references
        - StructProperty -> struct arrays (have additional header data)
        - ByteProperty -> raw bytes (if enum_name is "None") or enum values
    """

    name: str
    index: int = 0
    array_type: str = ""
    _values: list[t.Any] = field(default_factory=list)

    @property
    def type_name(self) -> str:
        return "ArrayProperty"

    @property
    def value(self) -> list[t.Any]:
        return self._values

    @property
    def count(self) -> int:
        return len(self._values)

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> ArrayProperty:
        """
        Read an ArrayProperty from the archive.

        ASE format after header:
            - ElementType (name)
            - Count (int32)
            - Elements...

        ASA format after header (CloudInventory/Profile/Tribe):
            For primitive arrays:
            - Index (int32)
            - ElementType (string)
            - Zeros (int32)
            - DataSize (int32)
            - Extra (byte)
            - Count (int32)
            - Elements...

            For struct arrays:
            - Index (int32)
            - ElementType (string) = "StructProperty"
            - Extra1 (int32, usually 1)
            - StructType (string)
            - Extra2 (int32, usually 1)
            - ScriptPath (string)
            - Zeros (int32)
            - DataSize (int32)
            - Extra3 (byte)
            - Count (int32)
            - Elements...

        ASA WorldSave format (SQLite objects):
            - ArrayHeader (int32) = 1
            - ElementTypeID (int32) + Instance (int32)
            - Zeros (int32)
            - ArrayByteLength (int32)
            - ArrayIndex (byte) = property array index
            - Count (int32)
            - Elements...

        Args:
            reader: The binary reader.
            header: The property header.
            is_asa: True for ASA format.
            name_table: Optional name table for world saves (version 6+).
            worldsave_format: True for ASA WorldSave SQLite object format.
        """
        if worldsave_format:
            return cls._read_worldsave_array(reader, header, name_table)

        # ASA cloud inventory (version 7+) uses a special format where:
        # - header.data_size is a flag (1) instead of actual size
        # - header.index contains the element type string length
        # ASA profiles/tribes (version 6) use ASE-style format with actual sizes
        use_asa_cloud_format = is_asa and header.data_size == 1 and header.index > 0

        if use_asa_cloud_format:
            # ASA CloudInventory format
            # The property header already read data_size and index, where:
            # - data_size is a flag (usually 1)
            # - index is the length of the element type string
            # So we read the element type string directly (its length is header.index)
            array_type_len = header.index
            array_type_bytes = reader.read_bytes(array_type_len)
            array_type = array_type_bytes[:-1].decode("latin-1")  # Remove null terminator
            index = header.data_size

            if array_type == "StructProperty":
                # Struct arrays have completely different header - pass count as -1 to signal
                # that the struct array handler should read its own header
                count = -1  # Sentinel value
            else:
                # Primitive arrays have zeros, dataSize, extra byte before count
                _zeros = reader.read_int32()  # Usually 0
                _data_size = reader.read_int32()  # Size of array data
                _extra = reader.read_uint8()  # Extra byte
                count = reader.read_int32()
        else:
            # ASE format / ASA profile/tribe format - element type first, then count
            # Use name table if available
            index = header.index
            array_type = read_name(reader, name_table)
            if is_asa:
                # ASA v6 profiles/tribes have an extra byte between array_type and count
                # (same as primitive properties). If bit 0 is set, an index override follows.
                extra_byte = reader.read_uint8()
                if extra_byte & 0x01:
                    index = reader.read_int32()
            count = reader.read_int32()

        # For now, read raw values based on simple types
        # Complex types (structs, objects) will need special handling
        values: list[t.Any] = []

        if count != 0:  # -1 for ASA struct arrays, > 0 for regular arrays
            values = _read_array_elements(reader, array_type, count, header.data_size, header.name, is_asa, name_table)

        return cls(
            name=header.name,
            index=index,
            array_type=array_type,
            _values=values,
        )

    @classmethod
    def _read_worldsave_array(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        name_table: dict[int, str] | None,
    ) -> ArrayProperty:
        """
        Read an ArrayProperty in ASA WorldSave format.

        WorldSave array format (after property header: Name ID + Instance + Type ID):

        For primitive arrays (non-struct):
            - ArrayHeader (int32) = 1
            - ElementTypeID (int32)
            - ElementTypeInstance (int32)
            - 8 zero bytes
            - ArrayByteLength (int32)
            - ArrayIndex (byte)
            - Count (int32)
            - Elements...

        For struct arrays (element type = StructProperty):
            - ArrayHeader (int32) = 1
            - ElementTypeID (int32) = StructProperty
            - ElementTypeInstance (int32) = 0
            - StructHeader (int32) = 1
            - StructTypeID (int32)
            - StructTypeInstance (int32)
            - StructHeader2 (int32) = 1
            - ScriptPathID (int32)
            - ScriptPathInstance (int32)
            - 4 zero bytes
            - ArrayByteLength (int32)
            - Flag (byte) - NOT array_index for struct arrays
            - Count (int32)
            - Elements... (each is a property list ending with None)

        Args:
            reader: The binary reader.
            header: The property header (already parsed).
            name_table: The name table dictionary.

        Returns:
            ArrayProperty with parsed values.
        """
        if name_table is None:
            raise ValueError("WorldSave array format requires a name table")

        # Read array header (should be 1)
        _array_header = reader.read_int32()

        # Read element type from name table
        element_type_id = reader.read_int32()
        element_type = name_table.get(element_type_id, f"__UNKNOWN_{element_type_id}__")

        struct_type: str | None = None
        array_index = 0

        if element_type == "StructProperty":
            # Struct arrays have additional header fields after element type ID:
            # - 4 zeros (padding = element_type_instance)
            # - StructHeader (4): Usually 1. If > 1, extra name references follow.
            # - StructTypeID (4) + StructTypeInstance (4)
            # - StructHeader2 (4) = 1
            # - ScriptPathID (4) + ScriptPathInstance (4)
            # - 4 zeros (padding)
            # - [If StructHeader > 1: extra (NameID(4) + NameInstance(4) + Zeros(4)) groups]
            # - ByteLength (4)
            # - Flag (1)
            # - Count (4)
            _zeros1 = reader.read_int32()  # Padding after element type ID
            _struct_header = reader.read_int32()  # Usually 1, sometimes 2+
            struct_type_id = reader.read_int32()
            struct_type = name_table.get(struct_type_id, f"__UNKNOWN_{struct_type_id}__")
            _zeros2 = reader.read_int32()  # Padding after struct type ID

            _struct_header2 = reader.read_int32()  # Usually 1
            _script_path_id = reader.read_int32()
            _zeros3 = reader.read_int32()  # Padding after script path ID
            _zeros4 = reader.read_int32()  # Additional padding

            # If _struct_header > 1, read extra name reference groups
            # Each extra group is: name_id(4) + name_inst(4) + zeros(4) = 12 bytes
            for _ in range(_struct_header - 1):
                _extra_name_id = reader.read_int32()
                _extra_name_inst = reader.read_int32()
                _extra_zeros = reader.read_int32()

            _array_byte_length = reader.read_int32()
            _flag_byte = reader.read_uint8()  # Not array_index for struct arrays
            count = reader.read_int32()
        else:
            # Primitive arrays: 8 zeros + byte_length + array_index + count
            _zeros1 = reader.read_int32()
            _zeros2 = reader.read_int32()
            _array_byte_length = reader.read_int32()
            array_index = reader.read_uint8()
            count = reader.read_int32()

        # Read elements
        values: list[t.Any] = []

        if count > 0:
            if element_type == "StructProperty" and struct_type:
                values = _read_worldsave_struct_array_elements(reader, struct_type, count, name_table)
            else:
                values = _read_worldsave_array_elements(reader, element_type, count, name_table)

        return cls(
            name=header.name,
            index=array_index,
            array_type=element_type,
            _values=values,
        )


def _read_array_elements(
    reader: BinaryReader,
    array_type: str,
    count: int,
    data_size: int,
    array_name: str,
    is_asa: bool,
    name_table: list[str] | None = None,
) -> list[t.Any]:
    """
    Read array elements based on the array type.

    This is a simplified implementation for primitive array types.

    Args:
        reader: The binary reader.
        array_type: The element type name.
        count: Number of elements to read.
        data_size: Total data size from property header.
        array_name: The array property name (for debugging).
        is_asa: True for ASA format.
        name_table: Optional name table for world saves (version 6+).
    """
    values: list[t.Any] = []

    # Simple numeric types
    if array_type == "IntProperty":
        for _ in range(count):
            values.append(reader.read_int32())
    elif array_type == "UInt32Property":
        for _ in range(count):
            values.append(reader.read_uint32())
    elif array_type == "Int64Property":
        for _ in range(count):
            values.append(reader.read_int64())
    elif array_type == "UInt64Property":
        for _ in range(count):
            values.append(reader.read_uint64())
    elif array_type == "Int16Property":
        for _ in range(count):
            values.append(reader.read_int16())
    elif array_type == "UInt16Property":
        for _ in range(count):
            values.append(reader.read_uint16())
    elif array_type == "Int8Property":
        for _ in range(count):
            values.append(reader.read_int8())
    elif array_type == "ByteProperty":
        for _ in range(count):
            values.append(reader.read_uint8())
    elif array_type == "FloatProperty":
        for _ in range(count):
            values.append(reader.read_float())
    elif array_type == "DoubleProperty":
        for _ in range(count):
            values.append(reader.read_double())
    elif array_type == "BoolProperty":
        for _ in range(count):
            values.append(reader.read_uint8() != 0)
    elif array_type == "StrProperty":
        for _ in range(count):
            values.append(reader.read_string())
    elif array_type == "NameProperty":
        for _ in range(count):
            # Names in arrays use name table if available
            values.append(read_name(reader, name_table))
    elif array_type == "ObjectProperty":
        # Object references in arrays
        for _ in range(count):
            if is_asa:
                # ASA: Int32 type (-1=null, 0=id, 1=path)
                ref_type = reader.read_int32()
                if ref_type == -1:
                    # Null reference
                    values.append(None)
                elif ref_type == 0:
                    # ID reference
                    ref_id = reader.read_int32()
                    if ref_id == -1:
                        values.append(None)
                    else:
                        values.append(("id", ref_id))
                elif ref_type == 1:
                    # Path reference
                    path = reader.read_string()
                    values.append(("path", path))
                else:
                    # Unknown type - might be path without marker
                    reader.skip(-4)
                    path = reader.read_string()
                    values.append(("path", path))
            else:
                # ASE: Int32 type + value
                ref_type = reader.read_int32()
                if ref_type == 0:
                    values.append(("id", reader.read_int32()))
                elif ref_type == 1:
                    # Name reference (uses name table if available)
                    values.append(("name", read_name(reader, name_table)))
                else:
                    values.append(("unknown", reader.read_int32()))
    elif array_type == "SoftObjectProperty":
        # Soft object references in arrays (asset paths)
        for _ in range(count):
            path = reader.read_string()
            sub_path = reader.read_string()
            # In arrays, SoftObjectProperty also has trailing padding (always 0)
            _padding = reader.read_int32()
            values.append({"path": path, "name": sub_path})
    elif array_type == "StructProperty":
        # Struct arrays have special handling
        if is_asa and count < 0:
            # ASA v7 cloud format struct array header (count == -1 sentinel):
            # - Extra1 (int32, usually 1)
            # - StructType (string)
            # - Extra2 (int32, usually 1)
            # - ScriptPath (string)
            # - Zeros (int32, usually 0)
            # - DataSize (int32)
            # - Extra3 (byte)
            # - Count (int32)

            _extra1 = reader.read_int32()
            struct_type = reader.read_string()
            _extra2 = reader.read_int32()
            _script_path = reader.read_string()
            _zeros = reader.read_int32()
            array_data_size = reader.read_int32()
            extra3 = reader.read_uint8()

            # Record position after extra3 - this is where data_size counts from
            # The data_size INCLUDES the count field (4 bytes), so:
            # array_data_end = position_after_extra3 + array_data_size
            data_region_start = reader.position
            array_data_end = data_region_start + array_data_size

            actual_count = reader.read_int32()

            # extra3 appears to be a flag byte. When it's 8 (bit 3 set), the
            # struct array has 4 padding bytes after each element's None terminator.
            # When it's 0, there's no padding between elements.
            has_element_padding = (extra3 & 0x08) != 0

            # Read struct elements
            # For ASA string-based files (no name table), struct array elements
            # do NOT have per-element headers. They directly start with properties.
            # The struct_type from the array header applies to all elements.
            from ..structs.registry import read_struct

            # All elements are read as property-list structs with the same type
            for struct_idx in range(actual_count):
                struct_value = read_struct(reader, struct_type, is_asa, name_table=name_table)
                if hasattr(struct_value, "to_dict"):
                    values.append(struct_value.to_dict())
                else:
                    values.append(struct_value)

                # If this array type has padding between elements, skip it
                # (except for the last element where we position to array end)
                if has_element_padding and struct_idx < actual_count - 1:
                    reader.skip(4)

            # After reading all elements, ensure we're at the expected end.
            # This handles any remaining padding after the last element.
            if reader.position < array_data_end:
                reader.skip(array_data_end - reader.position)
        else:
            # ASE struct arrays - read as property-based structs
            from ..structs.registry import read_struct_for_array

            for _ in range(count):
                struct = read_struct_for_array(reader, array_name, is_asa, name_table=name_table)
                if hasattr(struct, "to_dict"):
                    values.append(struct.to_dict())
                else:
                    values.append(struct)
    else:
        # Unknown array type - read as raw bytes
        # We can't determine element size, so just note it
        values.append(f"<UnknownArray({array_type}): {count} elements>")

    return values


def _read_worldsave_array_elements(
    reader: BinaryReader,
    element_type: str,
    count: int,
    name_table: dict[int, str],
) -> list[t.Any]:
    """
    Read array elements for ASA WorldSave format.

    WorldSave arrays have different element formats:
    - ObjectProperty: 2 bytes + 16 byte GUID
    - Primitive types: Same as other formats

    Args:
        reader: The binary reader.
        element_type: The element type name from name table.
        count: Number of elements.
        name_table: The name table dictionary.

    Returns:
        List of element values.
    """
    values: list[t.Any] = []

    # Simple numeric types - same as other formats
    if element_type == "IntProperty":
        for _ in range(count):
            values.append(reader.read_int32())
    elif element_type == "UInt32Property":
        for _ in range(count):
            values.append(reader.read_uint32())
    elif element_type == "Int64Property":
        for _ in range(count):
            values.append(reader.read_int64())
    elif element_type == "UInt64Property":
        for _ in range(count):
            values.append(reader.read_uint64())
    elif element_type == "Int16Property":
        for _ in range(count):
            values.append(reader.read_int16())
    elif element_type == "UInt16Property":
        for _ in range(count):
            values.append(reader.read_uint16())
    elif element_type == "Int8Property":
        for _ in range(count):
            values.append(reader.read_int8())
    elif element_type == "ByteProperty":
        for _ in range(count):
            values.append(reader.read_uint8())
    elif element_type == "FloatProperty":
        for _ in range(count):
            values.append(reader.read_float())
    elif element_type == "DoubleProperty":
        for _ in range(count):
            values.append(reader.read_double())
    elif element_type == "BoolProperty":
        for _ in range(count):
            values.append(reader.read_uint8() != 0)
    elif element_type == "StrProperty":
        for _ in range(count):
            values.append(reader.read_string())
    elif element_type == "NameProperty":
        # Names use the name table
        for _ in range(count):
            name_id = reader.read_int32()
            name_instance = reader.read_int32()
            name = name_table.get(name_id, f"__UNKNOWN_{name_id}__")
            if name_instance > 0:
                name = f"{name}_{name_instance - 1}"
            values.append(name)
    elif element_type == "ObjectProperty":
        # WorldSave object references: 2 bytes marker + name(8) or GUID(16)
        from uuid import UUID

        for _ in range(count):
            marker = reader.read_uint16()
            if marker == 1:
                # Name reference: name_id(4) + name_instance(4)
                ref_name_id = reader.read_int32()
                ref_name_inst = reader.read_int32()
                ref_name = name_table.get(ref_name_id, f"__UNKNOWN_{ref_name_id}__")
                if ref_name_inst > 0:
                    ref_name = f"{ref_name}_{ref_name_inst - 1}"
                values.append(ref_name)
            else:
                # GUID reference: 16 bytes
                guid_bytes = reader.read_bytes(16)
                if all(b == 0 for b in guid_bytes):
                    values.append(None)
                else:
                    guid = UUID(bytes_le=guid_bytes)
                    values.append(str(guid))
    elif element_type == "StructProperty":
        # This shouldn't be called anymore - struct arrays use
        # _read_worldsave_struct_array_elements instead
        values.append(f"<WorldSaveStructArray: {count} elements>")
    elif element_type == "SoftObjectProperty":
        # WorldSave SoftObjectProperty array elements:
        # Each element is: name_ref(8) + padding(4) = 12 bytes
        for _ in range(count):
            name_id = reader.read_int32()
            name_instance = reader.read_int32()
            ref_name = name_table.get(name_id, f"__UNKNOWN_{name_id}__")
            if name_instance > 0:
                ref_name = f"{ref_name}_{name_instance - 1}"
            _padding = reader.read_int32()
            values.append(ref_name)
    else:
        # Unknown type
        values.append(f"<UnknownWorldSaveArray({element_type}): {count} elements>")

    return values


def _read_worldsave_struct_array_elements(
    reader: BinaryReader,
    struct_type: str,
    count: int,
    name_table: dict[int, str],
) -> list[t.Any]:
    """
    Read struct array elements for ASA WorldSave format.

    There are two categories of struct types:
    1. **Native structs** (Color, LinearColor, Vector, etc.): Fixed binary size,
       no property headers or None terminators. Each element is read using the
       native struct reader from the struct registry.
    2. **Property-list structs** (CustomItemData, etc.): Each element is a list
       of properties terminated by a None marker (8 bytes: name_id + inst).

    Args:
        reader: The binary reader.
        struct_type: The struct type name from array header.
        count: Number of struct elements.
        name_table: The name table dictionary.

    Returns:
        List of struct element values (dicts for native, dicts for prop-lists).
    """
    from ..structs.registry import STRUCT_REGISTRY, read_struct
    from .registry import read_property

    values: list[t.Any] = []

    # Check if this is a native struct type (fixed binary format)
    if struct_type in STRUCT_REGISTRY:
        # Native struct: each element is a fixed-size binary blob
        for _ in range(count):
            struct_obj = read_struct(
                reader,
                struct_type,
                is_asa=True,
                name_table=name_table,
                worldsave_format=True,
            )
            if hasattr(struct_obj, "to_dict"):
                values.append(struct_obj.to_dict())
            else:
                values.append(struct_obj)
        return values

    # Property-list struct: each element is properties until None terminator
    for _ in range(count):
        struct_props: dict[str, t.Any] = {"_struct_type": struct_type}

        while True:
            prop = read_property(
                reader,
                is_asa=True,
                name_table=name_table,
                worldsave_format=True,
            )
            if prop is None:
                # None terminator marks end of struct element
                break

            # Add property to struct
            # Handle array indices for same-named properties
            key = prop.name
            if prop.index > 0:
                key = f"{prop.name}[{prop.index}]"

            if hasattr(prop, "value"):
                struct_props[key] = prop.value
            else:
                struct_props[key] = prop

        values.append(struct_props)

    return values


# =============================================================================
# Struct Property
# =============================================================================


@dataclass
class StructProperty(Property):
    """
    Struct property - contains structured data.

    Format:
        Header + Name structType + [type-specific fields] + value

    Structs come in two forms:
    1. Native structs: Fixed format known by name (Vector, Rotator, Color, etc.)
    2. Property-based structs: List of properties terminated by "None"
    """

    name: str
    index: int = 0
    struct_type: str = ""
    _value: t.Any = None  # Struct object from structs module

    @property
    def type_name(self) -> str:
        return "StructProperty"

    @property
    def value(self) -> t.Any:
        """Returns the struct value (Struct object or dict for serialization)."""
        if hasattr(self._value, "to_dict"):
            return self._value.to_dict()
        return self._value

    @property
    def struct(self) -> t.Any:
        """Returns the raw Struct object."""
        return self._value

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> StructProperty:
        """
        Read a StructProperty from the archive.

        Uses the struct registry to dispatch to the appropriate struct type.

        ASE format after header (also used by ASA profiles/tribes):
            - StructType (name)
            - [struct data]

        ASA CloudInventory format after header (version 7+):
            - StructType (string, length from header.index)
            - Extra1 (int32, usually 1)
            - ScriptPath (string, e.g. "/Script/ShooterGame")
            - Zeros (int32, usually 0)
            - DataSize (int32)
            - ExtraByte (byte) - bit 0 indicates struct data has index prefix
            - [struct data]

        ASA WorldSave format after header:
            - Index (int32) = 1
            - StructTypeID (int32, name table ref) + Instance (int32)
            - 8 zero bytes
            - DataSize (int32)
            - ArrayIndex (byte) = property array index
            - [struct data]

        Detection: ASA cloud inventory uses header.data_size=1 as a flag, while
        profiles/tribes have actual data sizes > 1.

        Args:
            reader: The binary reader.
            header: The property header.
            is_asa: True for ASA format.
            name_table: Optional name table for world saves (version 6+).
            worldsave_format: True for ASA WorldSave SQLite object format.
        """
        has_index_prefix = False

        if worldsave_format:
            return cls._read_worldsave_struct(reader, header, name_table)

        # ASA cloud inventory (version 7+) uses a special format where:
        # - header.data_size is a flag (1) instead of actual size
        # - header.index contains the struct_type string length
        # ASA profiles/tribes (version 6) use ASE-style format with actual sizes
        use_asa_cloud_format = is_asa and header.data_size == 1 and header.index > 0

        if use_asa_cloud_format:
            # ASA CloudInventory format
            # The property header already read data_size and index, where:
            # - data_size is a flag (usually 1)
            # - index is the length of the struct_type string
            # So we read the struct_type string directly (its length is header.index)
            struct_type_len = header.index
            struct_type_bytes = reader.read_bytes(struct_type_len)
            struct_type = struct_type_bytes[:-1].decode("latin-1")  # Remove null terminator

            _extra1 = reader.read_int32()  # Usually 1
            _script_path = reader.read_string()  # e.g. "/Script/ShooterGame"
            _zeros = reader.read_int32()  # Usually 0
            _data_size = reader.read_int32()  # Size of struct data

            # Use header.data_size as the index for ASA (usually 1, but could vary)
            index = header.data_size

            # Read the extra byte that appears before struct data
            extra_byte = reader.read_uint8()

            # If extra_byte bit 0 is set, struct data has an index prefix
            has_index_prefix = bool(extra_byte & 0x01)
        else:
            # ASE format / ASA profile/tribe format - uses name table if available
            index = header.index
            struct_type = read_name(reader, name_table)

            # ASA profiles/tribes (version 6) have a 17-byte header after the struct type
            # for property-list structs (structs NOT in the native struct registry).
            # This 17-byte block is: extra1(4) + script_path_len(4, value 0) + zeros(4) +
            # data_size(4) + extra_byte(1) — all zeros in v6 files.
            # Native structs (UniqueNetIdRepl, LinearColor, Vector, etc.) have their raw data
            # immediately after the struct_type string with no padding.
            if is_asa:
                from ..structs.registry import STRUCT_REGISTRY

                if struct_type not in STRUCT_REGISTRY:
                    reader.skip(17)

        # Use the struct registry to read the value
        from ..structs.registry import read_struct

        struct_value = read_struct(reader, struct_type, is_asa, has_index_prefix, name_table=name_table)

        return cls(
            name=header.name,
            index=index,
            struct_type=struct_type,
            _value=struct_value,
        )

    @classmethod
    def _read_worldsave_struct(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        name_table: dict[int, str] | None,
    ) -> StructProperty:
        """
        Read a StructProperty in ASA WorldSave format.

        WorldSave struct format (after property header NameID + NameInstance + TypeID):
            - Struct Header (int32) = 1
            - StructTypeID (int32) = name table reference (e.g., ItemNetID)
            - 4 zero bytes
            - Second Struct Header (int32) = 1
            - BlueprintTypeID (int32) = name table reference (e.g., /Script/ShooterGame)
            - 8 zero bytes
            - DataSize (int32) = size of struct data
            - Flag/Terminator byte (1 byte)
            - [struct data - property list or native struct]

        Args:
            reader: The binary reader.
            header: The property header (already parsed).
            name_table: The name table dictionary.

        Returns:
            StructProperty with parsed value.
        """
        if name_table is None:
            raise ValueError("WorldSave struct format requires a name table")

        # Read first struct header: usually 1, sometimes 2+ for structs with extra type refs
        _struct_header1 = reader.read_int32()

        # Read struct type from name table
        struct_type_id = reader.read_int32()
        struct_type = name_table.get(struct_type_id, f"__UNKNOWN_{struct_type_id}__")

        # 4 zeros after struct type (struct_type_instance)
        _zeros1 = reader.read_int32()

        # Read second struct header (should be 1)
        _struct_header2 = reader.read_int32()

        # Read blueprint type from name table
        _blueprint_type_id = reader.read_int32()

        # Padding after blueprint (blueprint_instance + additional zeros)
        _zeros2 = reader.read_int32()
        _zeros3 = reader.read_int32()

        # If _struct_header1 > 1, read extra name reference groups
        # Each extra group is: name_id(4) + name_inst(4) + zeros(4) = 12 bytes
        for _ in range(_struct_header1 - 1):
            _extra_name_id = reader.read_int32()
            _extra_name_inst = reader.read_int32()
            _extra_zeros = reader.read_int32()

        # Read data size
        _data_size = reader.read_int32()

        # Read flag/terminator byte
        flag_byte = reader.read_uint8()

        # Array index is encoded in flag if bit 0 is set
        array_index = 0
        if flag_byte & 0x01:
            array_index = reader.read_int32()

        # Use the struct registry to read the value
        # For WorldSave, we pass worldsave_format=True to the struct reader
        from ..structs.registry import read_struct

        struct_value = read_struct(
            reader,
            struct_type,
            is_asa=True,
            has_index_prefix=False,
            name_table=name_table,
            worldsave_format=True,
        )

        return cls(
            name=header.name,
            index=array_index,
            struct_type=struct_type,
            _value=struct_value,
        )


# =============================================================================
# Map Property
# =============================================================================


@dataclass
class MapProperty(Property):
    """
    Map property - contains key-value pairs.

    Format:
        Header + Name keyType + Name valueType + UInt8 unknown + Int32 count + [entries...]

    Less common than arrays and structs.
    """

    name: str
    index: int = 0
    key_type: str = ""
    value_type: str = ""
    _entries: dict[t.Any, t.Any] = field(default_factory=dict)

    @property
    def type_name(self) -> str:
        return "MapProperty"

    @property
    def value(self) -> dict[t.Any, t.Any]:
        return self._entries

    @property
    def count(self) -> int:
        return len(self._entries)

    @classmethod
    def read(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        is_asa: bool = False,
        name_table: list[str] | None = None,
        worldsave_format: bool = False,
    ) -> MapProperty:
        """
        Read a MapProperty from the archive.

        Args:
            reader: The binary reader.
            header: The property header.
            is_asa: True for ASA format.
            name_table: Optional name table for world saves (version 6+).
            worldsave_format: True for ASA WorldSave SQLite object format.
        """
        if worldsave_format:
            return cls._read_worldsave_map(reader, header, name_table)

        # Read key and value types - uses name table if available
        key_type = read_name(reader, name_table)
        value_type = read_name(reader, name_table)

        if is_asa:
            reader.skip(1)  # ASA has extra byte

        # Unknown byte
        _unknown = reader.read_uint8()

        # Read count
        count = reader.read_int32()

        # For now, store raw bytes for the entries
        # Full implementation needs type-specific parsing
        entries: dict[t.Any, t.Any] = {}

        if count > 0:
            # Read remaining data as raw bytes
            # This is a placeholder - full implementation needs type registry
            remaining = header.data_size - 4 - len(key_type) - 5 - len(value_type) - 5 - 1 - 4
            if remaining > 0:
                raw_data = reader.read_bytes(remaining)
                entries["_raw"] = raw_data
                entries["_note"] = f"Map with {count} entries, needs type-specific parsing"

        return cls(
            name=header.name,
            index=header.index,
            key_type=key_type,
            value_type=value_type,
            _entries=entries,
        )

    @classmethod
    def _read_worldsave_map(
        cls,
        reader: BinaryReader,
        header: PropertyHeader,
        name_table: dict[int, str] | None,
    ) -> MapProperty:
        """
        Read a MapProperty in ASA WorldSave format.

        WorldSave MapProperty format after 16-byte header:
            - Marker (4) = 2 (two type references: key + value)
            - Key type name: ID(4) + Instance(4)
            - If key type is NOT StructProperty: padding(4)
            - If key type IS StructProperty: struct sub-header
            - Value type name: ID(4) + Instance(4)
            - If value type is NOT StructProperty: padding(4)
            - If value type IS StructProperty: struct sub-header
              (marker(4)=1 + struct_type(8) + marker2(4)=1 + script_path(8) + zeros(4))
            - DataSize(4) + Flag(1) + SkipCount(4) + MapCount(4)
            - [Entries...]
        """
        if name_table is None:
            raise ValueError("WorldSave MapProperty requires a name table")

        # Read marker (should be 2 for Map: key + value types)
        _marker = reader.read_int32()

        # Read key type
        key_type_id = reader.read_int32()
        _key_type_inst = reader.read_int32()
        key_type = name_table.get(key_type_id, f"__UNKNOWN_{key_type_id}__")

        # Handle key type sub-header
        if key_type == "StructProperty":
            # Key is a struct - read struct sub-header
            _struct_marker = reader.read_int32()
            _key_struct_type_id = reader.read_int32()
            _key_struct_type_inst = reader.read_int32()
            _script_marker = reader.read_int32()
            _key_script_path_id = reader.read_int32()
            _key_script_path_inst = reader.read_int32()
            _key_zeros = reader.read_int32()
        else:
            # Simple key type - just padding
            _pad_after_key = reader.read_int32()

        # Read value type
        value_type_id = reader.read_int32()
        _value_type_inst = reader.read_int32()
        value_type = name_table.get(value_type_id, f"__UNKNOWN_{value_type_id}__")

        # Handle value type sub-header
        if value_type == "StructProperty":
            _struct_marker = reader.read_int32()  # Usually 1, sometimes 2+
            struct_type_id = reader.read_int32()
            _struct_type_inst = reader.read_int32()
            _script_marker = reader.read_int32()
            _script_path_id = reader.read_int32()
            _script_path_inst = reader.read_int32()
            _zeros = reader.read_int32()
            # If _struct_marker > 1, read extra name reference groups
            for _ in range(_struct_marker - 1):
                _extra_name_id = reader.read_int32()
                _extra_name_inst = reader.read_int32()
                _extra_zeros = reader.read_int32()
        else:
            _pad_after_value = reader.read_int32()

        # Read data_size, flag, skipCount, mapCount
        data_size = reader.read_int32()
        _flag = reader.read_uint8()
        _skip_count = reader.read_int32()
        map_count = reader.read_int32()

        # Calculate the end position for the map data
        # data_size appears to be total bytes from after flag to end of entries
        # which includes: skipCount(4) + mapCount(4) + entry_data
        entries_end = reader.position + (data_size - 8) if data_size > 8 else reader.position

        entries: dict[t.Any, t.Any] = {}

        if map_count > 0:
            try:
                for _ in range(map_count):
                    # Read key based on key type
                    if key_type == "NameProperty":
                        key_name_id = reader.read_int32()
                        _key_name_inst = reader.read_int32()
                        key_val = name_table.get(key_name_id, f"__UNKNOWN_{key_name_id}__")
                    elif key_type == "ObjectProperty":
                        # Object reference as key
                        key_val = reader.read_bytes(16).hex()
                        reader.skip(1)
                    else:
                        # Generic: read name reference
                        key_id = reader.read_int32()
                        _key_inst = reader.read_int32()
                        key_val = name_table.get(key_id, f"__UNKNOWN_{key_id}__")

                    # Read value based on value type
                    if value_type == "StructProperty":
                        # Value is a struct property list (ends with None)
                        from .registry import read_properties

                        struct_props = read_properties(
                            reader,
                            is_asa=True,
                            name_table=name_table,
                            worldsave_format=True,
                        )
                        # Convert to dict of name → value
                        val_dict: dict[str, t.Any] = {}
                        for p in struct_props:
                            val_dict[p.name] = p.value
                        entries[key_val] = val_dict
                    else:
                        # For other value types, try reading a simple value
                        entries[key_val] = f"<{value_type} value>"

            except Exception:
                # If entry parsing fails, skip to calculated end
                if reader.position < entries_end:
                    reader.position = entries_end

        return cls(
            name=header.name,
            index=header.index,
            key_type=key_type,
            value_type=value_type,
            _entries=entries,
        )
