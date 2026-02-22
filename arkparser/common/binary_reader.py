"""
Binary Reader - Low-level binary reading utilities.

ARK save files are binary and use little-endian byte order throughout.
This module provides a simple interface for reading all the primitive
types found in ARK files.

Binary Format Basics:
    - All integers are little-endian
    - Strings are length-prefixed (negative length = UTF-16)
    - GUIDs are 16 bytes, read as little-endian

Example:
    >>> reader = BinaryReader.from_file("save.ark")
    >>> version = reader.read_int32()
    >>> name = reader.read_string()
    >>> reader.close()

    # Or use as context manager:
    >>> with BinaryReader.from_file("save.ark") as reader:
    ...     version = reader.read_int32()
"""

from __future__ import annotations

import struct
import typing as t
from io import BytesIO
from pathlib import Path
from uuid import UUID

from .exceptions import EndOfDataError


class BinaryReader:
    """
    Binary data reader for ARK save files.

    All ARK files use little-endian byte order. This class provides
    methods for reading all primitive types used in the format.

    The reader tracks its position and supports slicing to create
    sub-readers for parsing nested structures.

    Attributes:
        position: Current read position in bytes.
        size: Total size of the data in bytes.
        remaining: Number of bytes left to read.
    """

    # Struct format characters (little-endian)
    _FMT_INT8 = "<b"
    _FMT_UINT8 = "<B"
    _FMT_INT16 = "<h"
    _FMT_UINT16 = "<H"
    _FMT_INT32 = "<i"
    _FMT_UINT32 = "<I"
    _FMT_INT64 = "<q"
    _FMT_UINT64 = "<Q"
    _FMT_FLOAT = "<f"
    _FMT_DOUBLE = "<d"

    def __init__(self, stream: t.BinaryIO) -> None:
        """
        Initialize with a binary stream.

        Args:
            stream: A binary file-like object supporting read/seek/tell.
        """
        self._stream = stream
        # Determine size by seeking to end
        self._stream.seek(0, 2)
        self._size = self._stream.tell()
        self._stream.seek(0)

    def __enter__(self) -> BinaryReader:
        """Context manager entry."""
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit - closes the stream."""
        self.close()

    def close(self) -> None:
        """Close the underlying stream."""
        self._stream.close()

    # =========================================================================
    # Factory Methods
    # =========================================================================

    @classmethod
    def from_file(cls, path: str | Path) -> BinaryReader:
        """
        Create a reader from a file path.

        The entire file is read into memory for faster access.

        Args:
            path: Path to the binary file.

        Returns:
            A new BinaryReader instance.
        """
        data = Path(path).read_bytes()
        return cls(BytesIO(data))

    @classmethod
    def from_bytes(cls, data: bytes) -> BinaryReader:
        """
        Create a reader from raw bytes.

        Args:
            data: Raw bytes to read from.

        Returns:
            A new BinaryReader instance.
        """
        return cls(BytesIO(data))

    # =========================================================================
    # Position Management
    # =========================================================================

    @property
    def position(self) -> int:
        """Current read position in the stream (0-indexed)."""
        return self._stream.tell()

    @position.setter
    def position(self, value: int) -> None:
        """
        Set the read position.

        Args:
            value: New position (0-indexed byte offset).
        """
        self._stream.seek(value)

    @property
    def size(self) -> int:
        """Total size of the data in bytes."""
        return self._size

    @property
    def remaining(self) -> int:
        """Number of bytes remaining to read."""
        return self._size - self.position

    def skip(self, count: int) -> None:
        """
        Skip forward by the specified number of bytes.

        Args:
            count: Number of bytes to skip (can be negative to go back).
        """
        self._stream.seek(count, 1)  # SEEK_CUR

    def slice(self, size: int) -> BinaryReader:
        """
        Create a sub-reader for the next `size` bytes.

        This reads `size` bytes from the current position and returns
        a new BinaryReader for just those bytes. The original reader's
        position advances past the sliced region.

        Useful for parsing nested structures with known sizes.

        Args:
            size: Number of bytes to slice.

        Returns:
            A new BinaryReader for the sliced bytes.

        Raises:
            EndOfDataError: If not enough bytes remain.
        """
        if size > self.remaining:
            raise EndOfDataError(size, self.remaining)
        data = self._stream.read(size)
        return BinaryReader.from_bytes(data)

    # =========================================================================
    # Raw Bytes
    # =========================================================================

    def read_bytes(self, count: int) -> bytes:
        """
        Read raw bytes from the stream.

        Args:
            count: Number of bytes to read.

        Returns:
            The raw bytes.

        Raises:
            EndOfDataError: If not enough bytes remain.
        """
        if count > self.remaining:
            raise EndOfDataError(count, self.remaining)
        return self._stream.read(count)

    # =========================================================================
    # Integer Types
    # =========================================================================

    def read_int8(self) -> int:
        """Read a signed 8-bit integer (-128 to 127)."""
        return struct.unpack(self._FMT_INT8, self._stream.read(1))[0]

    def read_uint8(self) -> int:
        """Read an unsigned 8-bit integer (0 to 255)."""
        return struct.unpack(self._FMT_UINT8, self._stream.read(1))[0]

    def read_int16(self) -> int:
        """Read a signed 16-bit integer."""
        return struct.unpack(self._FMT_INT16, self._stream.read(2))[0]

    def read_uint16(self) -> int:
        """Read an unsigned 16-bit integer."""
        return struct.unpack(self._FMT_UINT16, self._stream.read(2))[0]

    def read_int32(self) -> int:
        """Read a signed 32-bit integer."""
        return struct.unpack(self._FMT_INT32, self._stream.read(4))[0]

    def read_uint32(self) -> int:
        """Read an unsigned 32-bit integer."""
        return struct.unpack(self._FMT_UINT32, self._stream.read(4))[0]

    def read_int64(self) -> int:
        """Read a signed 64-bit integer."""
        return struct.unpack(self._FMT_INT64, self._stream.read(8))[0]

    def read_uint64(self) -> int:
        """Read an unsigned 64-bit integer."""
        return struct.unpack(self._FMT_UINT64, self._stream.read(8))[0]

    # =========================================================================
    # Floating Point Types
    # =========================================================================

    def read_float(self) -> float:
        """Read a 32-bit IEEE 754 float."""
        return struct.unpack(self._FMT_FLOAT, self._stream.read(4))[0]

    def read_double(self) -> float:
        """Read a 64-bit IEEE 754 double."""
        return struct.unpack(self._FMT_DOUBLE, self._stream.read(8))[0]

    # =========================================================================
    # Boolean
    # =========================================================================

    def read_bool32(self) -> bool:
        """
        Read a boolean stored as a 32-bit integer.

        This is how booleans are stored outside of BoolProperty in ASE.
        Returns True if the value is non-zero.
        """
        return self.read_uint32() != 0

    def read_bool16(self) -> bool:
        """
        Read a boolean stored as a 16-bit integer.

        This is how BoolProperty values are stored in ASA.
        Returns True if the value is non-zero.
        """
        return self.read_int16() != 0

    def read_bool8(self) -> bool:
        """
        Read a boolean stored as an 8-bit integer.

        This is how BoolProperty values are stored in ASE.
        Returns True if the value is non-zero.
        """
        return self.read_uint8() != 0

    # =========================================================================
    # Strings
    # =========================================================================

    def read_string(self) -> str:
        """
        Read a length-prefixed string.

        ARK string format:
            - Int32 length (negative = UTF-16, positive = Latin-1/ASCII)
            - String bytes including null terminator

        Special cases:
            - length = 0: Returns empty string
            - length = 1: Single null byte, returns empty string
            - length = -1: UTF-16 null (2 bytes), returns empty string

        Returns:
            The decoded string (without null terminator).
        """
        length = self.read_int32()

        # Handle special cases
        if length == 0:
            return ""
        if length == 1:
            self.skip(1)  # Skip single null byte
            return ""
        if length == -1:
            self.skip(2)  # Skip UTF-16 null (2 bytes)
            return ""

        # Determine encoding based on sign
        if length < 0:
            # UTF-16 (multibyte) - common for non-ASCII characters
            byte_count = abs(length) * 2
            data = self.read_bytes(byte_count)
            # Exclude null terminator (2 bytes for UTF-16)
            return data[:-2].decode("utf-16-le")
        else:
            # Latin-1 (single byte) - most common
            data = self.read_bytes(length)
            # Exclude null terminator (1 byte)
            return data[:-1].decode("latin-1")

    # =========================================================================
    # GUID (ASA)
    # =========================================================================

    def read_guid(self) -> UUID:
        """
        Read a 16-byte GUID (UUID).

        GUIDs in ARK are stored in little-endian format.
        Used primarily in ASA for object identification.

        Returns:
            A UUID object.
        """
        guid_bytes = self.read_bytes(16)
        return UUID(bytes_le=guid_bytes)

    def read_guid_bytes(self) -> bytes:
        """
        Read a 16-byte GUID as raw bytes.

        Useful when you just need to check if a GUID is all zeros.

        Returns:
            The raw 16 GUID bytes.
        """
        return self.read_bytes(16)

    # =========================================================================
    # Debugging
    # =========================================================================

    def peek_bytes(self, count: int) -> bytes:
        """
        Peek at the next bytes without advancing position.

        Useful for debugging or format detection.

        Args:
            count: Number of bytes to peek.

        Returns:
            The bytes (position unchanged).
        """
        pos = self.position
        data = self.read_bytes(min(count, self.remaining))
        self.position = pos
        return data

    def debug_context(self, before: int = 16, after: int = 16) -> str:
        """
        Get a hex dump of bytes around the current position.

        Useful for debugging parse errors.

        Args:
            before: Bytes to show before current position.
            after: Bytes to show after current position.

        Returns:
            Formatted hex dump string.
        """
        start = max(0, self.position - before)
        end = min(self.size, self.position + after)

        self._stream.seek(start)
        data = self._stream.read(end - start)
        self._stream.seek(self.position)  # Restore position

        # Format as hex with position marker
        hex_str = data.hex(" ")
        marker_pos = (self.position - start) * 3  # 2 hex chars + 1 space per byte
        marker = " " * marker_pos + "^"

        return f"Position 0x{self.position:X}:\n{hex_str}\n{marker}"
