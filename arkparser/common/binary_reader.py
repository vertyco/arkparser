"""
Binary Reader - Low-level binary reading utilities.

ARK save files are binary and use little-endian byte order throughout. This
module provides a fast interface for reading the primitive types used in
ARK saves.

Implementation note:
    The reader operates on a single ``bytes`` buffer with an integer position
    cursor instead of a ``BytesIO`` stream. Integer reads use ``int.from_bytes``
    (significantly faster than ``struct.unpack`` for ints) and float reads
    use pre-instantiated ``struct.Struct`` unpackers. On a ~80k-object ASE
    save this cuts load time roughly in half compared to the BytesIO-based
    implementation.

Example:
    >>> reader = BinaryReader.from_file("save.ark")
    >>> version = reader.read_int32()
    >>> name = reader.read_string()
"""

from __future__ import annotations

import ctypes
import mmap
import struct
import sys
from pathlib import Path
from uuid import UUID

from .exceptions import EndOfDataError

# Pre-instantiated struct unpackers (faster than struct.unpack with a format
# string each call. The Struct objects compile the format once.
_S_FLOAT = struct.Struct("<f")
_S_DOUBLE = struct.Struct("<d")
_S_INT32_PAIR = struct.Struct("<ii")
_S_INT32_X4 = struct.Struct("<4i")


def guid_str_le(raw: bytes) -> str:
    """Format a 16-byte little-endian GUID as its canonical string.

    Byte-for-byte equivalent to ``str(uuid.UUID(bytes_le=raw))`` (asserted in
    tests) at ~40% of the cost; ASA saves key every game row and actor
    transform by GUID, so this runs hundreds of thousands of times per load.
    """
    assert len(raw) == 16, "GUID must be 16 bytes"
    h = raw.hex()
    return (
        h[6:8] + h[4:6] + h[2:4] + h[0:2]
        + "-" + h[10:12] + h[8:10]
        + "-" + h[14:16] + h[12:14]
        + "-" + h[16:20]
        + "-" + h[20:32]
    )


class BinaryReader:
    """Binary data reader for ARK save files (little-endian)."""

    __slots__ = ("_buf", "_pos", "_size", "save_version")

    def __init__(self, data: bytes | memoryview | mmap.mmap, save_version: int = 0) -> None:
        # Materialize memoryviews to bytes once. CPython 3.14 small-bytes
        # slicing is significantly faster than memoryview slicing for the
        # per-read ``int.from_bytes(buf[a:b], ...)`` hot path used here.
        # ``mmap`` buffers are kept as-is: slicing an mmap returns plain
        # ``bytes``, so every read path behaves identically while the file
        # contents stay out of the Python heap (used by lazy world saves,
        # which retain the reader for the whole export).
        if isinstance(data, memoryview):
            self._buf = bytes(data)
        else:
            self._buf = data
        self._pos = 0
        self._size = len(self._buf)
        # Save format version. Propagated from WorldSave so property readers
        # can branch on version-specific layout quirks (e.g. ASA v13
        # BoolProperty bodies carry an extra trailing byte vs v14+).
        self.save_version = save_version

    def __enter__(self) -> BinaryReader:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        # Plain-bytes buffers have nothing to release; mmap buffers unmap.
        if isinstance(self._buf, mmap.mmap):
            self._buf.close()
        return None

    def trim_working_set(self) -> bool:
        """Drop this reader's clean mmap pages from the process working set.

        A lazy world save touches every property page over the course of an
        export. Those pages are clean and file-backed, but they accumulate in
        the working set until peak RSS approaches heap + whole file size. On
        POSIX, madvise(MADV_DONTNEED) releases just this mapping. Windows has
        no per-range call usable on a read-only mapping, so EmptyWorkingSet
        trims the whole process; evicted heap pages soft-fault back from the
        standby list with no disk I/O.

        Pre: none (safe on any reader). Post: returns True only when the
        reader is mmap-backed and a trim was actually issued; plain-bytes
        readers return False and do nothing.
        """
        if not isinstance(self._buf, mmap.mmap):
            return False
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            handle = kernel32.GetCurrentProcess()
            # EmptyWorkingSet lives in psapi.dll on older Windows and is
            # forwarded from kernel32 as K32EmptyWorkingSet on newer builds.
            empty = getattr(kernel32, "K32EmptyWorkingSet", None)
            if empty is None:
                empty = ctypes.windll.psapi.EmptyWorkingSet
            empty.argtypes = [ctypes.c_void_p]
            empty.restype = ctypes.c_int
            return bool(empty(handle))
        madvise_flag = getattr(mmap, "MADV_DONTNEED", None)
        if madvise_flag is None:
            return False
        self._buf.madvise(madvise_flag)
        return True

    # =========================================================================
    # Factory Methods
    # =========================================================================

    @classmethod
    def from_file(cls, path: str | Path) -> BinaryReader:
        return cls(Path(path).read_bytes())

    @classmethod
    def from_file_mmap(cls, path: str | Path) -> BinaryReader:
        """Memory-map the file instead of reading it onto the heap.

        For readers retained over a long export (lazy world saves): the OS
        pages the contents in on demand and may reclaim them under pressure,
        so the file bytes never count against the Python heap. Falls back to
        :meth:`from_file` for empty files (Windows cannot mmap length 0).
        """
        p = Path(path)
        if p.stat().st_size == 0:
            return cls.from_file(p)
        with open(p, "rb") as fh:
            # mmap duplicates the OS handle; closing fh afterwards is safe.
            buf = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        return cls(buf)

    @classmethod
    def from_bytes(cls, data: bytes) -> BinaryReader:
        return cls(bytes(data) if not isinstance(data, bytes) else data)

    # =========================================================================
    # Position Management
    # =========================================================================

    @property
    def position(self) -> int:
        return self._pos

    @position.setter
    def position(self, value: int) -> None:
        if value < 0 or value > self._size:
            raise EndOfDataError(value, self._size)
        self._pos = value

    @property
    def size(self) -> int:
        return self._size

    @property
    def remaining(self) -> int:
        return self._size - self._pos

    def skip(self, count: int) -> None:
        new_pos = self._pos + count
        if new_pos < 0 or new_pos > self._size:
            raise EndOfDataError(count, self._size - self._pos)
        self._pos = new_pos

    def slice(self, size: int) -> BinaryReader:
        if size > self._size - self._pos:
            raise EndOfDataError(size, self._size - self._pos)
        sub = self._buf[self._pos:self._pos + size]
        self._pos += size
        return BinaryReader(sub)

    # =========================================================================
    # Raw Bytes
    # =========================================================================

    def read_bytes(self, count: int) -> bytes:
        end = self._pos + count
        if end > self._size:
            raise EndOfDataError(count, self._size - self._pos)
        data = self._buf[self._pos:end]
        self._pos = end
        return data

    # =========================================================================
    # Integer Types
    #
    # int.from_bytes is markedly faster than struct.unpack for fixed-width
    # ints in CPython. Each reader inlines the bounds check so the hot path
    # is a single comparison + slice + int.from_bytes call.
    # =========================================================================

    def read_int8(self) -> int:
        if self._pos >= self._size:
            raise EndOfDataError(1, self._size - self._pos)
        v = self._buf[self._pos]
        self._pos += 1
        return v - 256 if v >= 128 else v

    def read_uint8(self) -> int:
        if self._pos >= self._size:
            raise EndOfDataError(1, self._size - self._pos)
        v = self._buf[self._pos]
        self._pos += 1
        return v

    def read_int16(self) -> int:
        if self._pos + 2 > self._size:
            raise EndOfDataError(2, self._size - self._pos)
        v = int.from_bytes(self._buf[self._pos:self._pos + 2], "little", signed=True)
        self._pos += 2
        return v

    def read_uint16(self) -> int:
        if self._pos + 2 > self._size:
            raise EndOfDataError(2, self._size - self._pos)
        v = int.from_bytes(self._buf[self._pos:self._pos + 2], "little")
        self._pos += 2
        return v

    def read_int32(self) -> int:
        if self._pos + 4 > self._size:
            raise EndOfDataError(4, self._size - self._pos)
        v = int.from_bytes(self._buf[self._pos:self._pos + 4], "little", signed=True)
        self._pos += 4
        return v

    def read_uint32(self) -> int:
        if self._pos + 4 > self._size:
            raise EndOfDataError(4, self._size - self._pos)
        v = int.from_bytes(self._buf[self._pos:self._pos + 4], "little")
        self._pos += 4
        return v

    def read_int64(self) -> int:
        if self._pos + 8 > self._size:
            raise EndOfDataError(8, self._size - self._pos)
        v = int.from_bytes(self._buf[self._pos:self._pos + 8], "little", signed=True)
        self._pos += 8
        return v

    def read_uint64(self) -> int:
        if self._pos + 8 > self._size:
            raise EndOfDataError(8, self._size - self._pos)
        v = int.from_bytes(self._buf[self._pos:self._pos + 8], "little")
        self._pos += 8
        return v

    def read_int32_pair(self) -> tuple[int, int]:
        """Read two signed int32 values in a single struct unpack call.

        Hot path for property headers (data_size + index) and ASE name-table
        references (index + instance). One Python call + one C unpack beats
        two read_int32 calls.
        """
        if self._pos + 8 > self._size:
            raise EndOfDataError(8, self._size - self._pos)
        a, b = _S_INT32_PAIR.unpack_from(self._buf, self._pos)
        self._pos += 8
        return a, b

    def read_int32_x4(self) -> tuple[int, int, int, int]:
        """Read four signed int32 values in a single struct unpack call.

        Hot path for ASE property headers: after the name pair, the type
        name-ref (index + instance) and data_size + index are 16 contiguous
        bytes. One call beats two read_int32_pair calls.
        """
        if self._pos + 16 > self._size:
            raise EndOfDataError(16, self._size - self._pos)
        vals = _S_INT32_X4.unpack_from(self._buf, self._pos)
        self._pos += 16
        return vals

    # =========================================================================
    # Floating Point Types
    # =========================================================================

    def read_float(self) -> float:
        if self._pos + 4 > self._size:
            raise EndOfDataError(4, self._size - self._pos)
        v = _S_FLOAT.unpack_from(self._buf, self._pos)[0]
        self._pos += 4
        return v

    def read_double(self) -> float:
        if self._pos + 8 > self._size:
            raise EndOfDataError(8, self._size - self._pos)
        v = _S_DOUBLE.unpack_from(self._buf, self._pos)[0]
        self._pos += 8
        return v

    # =========================================================================
    # Boolean
    # =========================================================================

    def read_bool32(self) -> bool:
        return self.read_uint32() != 0

    def read_bool16(self) -> bool:
        return self.read_int16() != 0

    def read_bool8(self) -> bool:
        return self.read_uint8() != 0

    # =========================================================================
    # Strings
    # =========================================================================

    def read_string(self) -> str:
        """Read a length-prefixed string (negative length = UTF-16)."""
        length = self.read_int32()
        if length == 0:
            return ""
        if length == 1:
            if self._pos + 1 > self._size:
                raise EndOfDataError(1, self._size - self._pos)
            self._pos += 1  # single null byte
            return ""
        if length == -1:
            if self._pos + 2 > self._size:
                raise EndOfDataError(2, self._size - self._pos)
            self._pos += 2  # UTF-16 null
            return ""
        if length < 0:
            byte_count = -length * 2
            end = self._pos + byte_count
            if end > self._size:
                raise EndOfDataError(byte_count, self._size - self._pos)
            data = self._buf[self._pos:end - 2]  # exclude null terminator
            self._pos = end
            return data.decode("utf-16-le")
        end = self._pos + length
        if end > self._size:
            raise EndOfDataError(length, self._size - self._pos)
        data = self._buf[self._pos:end - 1]  # exclude null terminator
        self._pos = end
        return data.decode("latin-1")

    # =========================================================================
    # GUID (ASA)
    # =========================================================================

    def read_guid(self) -> UUID:
        return UUID(bytes_le=self.read_bytes(16))

    def read_guid_bytes(self) -> bytes:
        return self.read_bytes(16)

    # =========================================================================
    # Debugging
    # =========================================================================

    def peek_bytes(self, count: int) -> bytes:
        end = min(self._pos + count, self._size)
        return self._buf[self._pos:end]

    def debug_context(self, before: int = 16, after: int = 16) -> str:
        start = max(0, self._pos - before)
        end = min(self._size, self._pos + after)
        data = self._buf[start:end]
        hex_str = data.hex(" ")
        marker_pos = (self._pos - start) * 3
        marker = " " * marker_pos + "^"
        return f"Position 0x{self._pos:X}:\n{hex_str}\n{marker}"
