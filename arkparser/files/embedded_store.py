"""
Player and tribe store packed inside an ASA world save.

Some ASA servers (Nitrado observed) never write ``.arkprofile`` / ``.arktribe``
files. The same files are packed into the save's ``custom`` table under the
``GameModeCustomBytes`` key instead. Servers that do write the files leave that
row at a few dozen bytes.

Blob layout (int32 little-endian)::

    Int32  format                     # 1
    repeat (tribes, then profiles):
      Int32  section_size             # bytes of packed files that follow
      Int32  count                    # size 0 + count 0 = terminator, ends the blob
      Bytes  files[section_size]      # complete .arktribe / .arkprofile files
      count x { Bytes(8) key, Int32 offset, Int32 size }

The store is append-style: each save writes a fresh copy of a changed tribe or
profile and zeroes the old copy's key. Only entries with a non-zero key are
current. Each packed file is byte-identical in format to a sidecar file, so it
loads with ``Tribe.load(bytes)`` / ``Profile.load(bytes)`` unchanged.

Pieces are read with ``substr()`` slices so a large store never sits in memory
whole: the index first, then one current file at a time.
"""

from __future__ import annotations

import logging
import sqlite3
import struct
import typing as t
from dataclasses import dataclass, field

from ..common.exceptions import CorruptDataError
from ..game_objects.game_object import MAX_OBJECT_COUNT
from .profile import Profile
from .tribe import Tribe

logger = logging.getLogger(__name__)

STORE_KEY = "GameModeCustomBytes"
STORE_FORMAT = 1
NO_STORE_FORMAT = 0
# Tribes + profiles + one spare for a future section type.
MAX_SECTIONS = 3
INDEX_ENTRY = struct.Struct("<8sii")
ZERO_KEY = b"\x00" * 8
# Where the class-name string sits in a v7 packed file: version, two header
# ints, object count, then the first object's 16-byte GUID.
CLASS_NAME_OFFSET = 32
MAX_CLASS_NAME = 256

_SIZE_SQL = "SELECT length(value) FROM custom WHERE key = ?"
_SLICE_SQL = "SELECT substr(value, ?, ?) FROM custom WHERE key = ?"


@dataclass
class EmbeddedStore:
    """Current profiles and tribes read out of a save's packed store.

    Attributes:
        profiles: One ``Profile`` per player (latest copy).
        tribes: One ``Tribe`` per tribe (latest copy).
        superseded_profiles: Old profile copies skipped (zero key).
        superseded_tribes: Old tribe copies skipped (zero key).
        errors: Problems found, one line each. A bad entry is skipped and the
            rest still load; a bad layout empties the result.
    """

    profiles: list[Profile] = field(default_factory=list)
    tribes: list[Tribe] = field(default_factory=list)
    superseded_profiles: int = 0
    superseded_tribes: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StoreSection:
    """One section's location in the blob plus its raw index entries."""

    data_start: int
    data_size: int
    entries: list[tuple[bytes, int, int]]


class BlobSlicer:
    """Reads byte ranges of the store row without loading the whole value."""

    def __init__(self, conn: sqlite3.Connection, size: int) -> None:
        assert size >= 0, "negative blob size"
        self.conn = conn
        self.size = size

    def read(self, offset: int, length: int) -> bytes:
        """Return ``length`` bytes at 0-based ``offset``, or raise if out of range."""
        if offset < 0 or length < 0 or offset + length > self.size:
            raise CorruptDataError(
                f"store read {offset}+{length} past blob end {self.size}"
            )
        if length == 0:
            return b""
        row = self.conn.execute(_SLICE_SQL, (offset + 1, length, STORE_KEY)).fetchone()
        data = bytes(row[0]) if row is not None and row[0] is not None else b""
        if len(data) != length:
            raise CorruptDataError(f"store read {offset}+{length} returned {len(data)} bytes")
        return data

    def read_int32_pair(self, offset: int) -> tuple[int, int]:
        """Read two little-endian int32 values at ``offset``."""
        first, second = struct.unpack("<2i", self.read(offset, 8))
        return first, second


def load_embedded_store(conn: sqlite3.Connection) -> EmbeddedStore:
    """Read the packed profile/tribe store from an open ASA save connection.

    Pre: ``conn`` is an open connection to an ASA save (has a ``custom``
    table). Post: returns the current entries; an absent or near-empty store
    returns an empty result with no errors, and a malformed layout returns an
    empty result with one error line. Never raises for bad store data.
    """
    assert conn is not None, "connection required"
    row = conn.execute(_SIZE_SQL, (STORE_KEY,)).fetchone()
    size = int(row[0]) if row is not None and row[0] is not None else 0
    store = EmbeddedStore()
    if size <= 8:
        return store
    slicer = BlobSlicer(conn, size)
    # Servers that write sidecar files leave this row all zeros (20-28 bytes
    # observed), so format 0 means "no store", not a malformed one.
    if struct.unpack("<i", slicer.read(0, 4))[0] == NO_STORE_FORMAT:
        return store
    try:
        sections = read_sections(slicer)
    except CorruptDataError as exc:
        store.errors.append(f"store layout: {exc}")
        return store
    for number, section in enumerate(sections):
        load_section(slicer, section, number, store)
    assert len(store.profiles) + len(store.tribes) <= MAX_OBJECT_COUNT, "store overflow"
    return store


def read_sections(slicer: BlobSlicer) -> list[StoreSection]:
    """Walk the blob's section headers and index tables.

    Pre: blob is longer than 8 bytes. Post: returns every section up to the
    terminator, with bounds checked; raises ``CorruptDataError`` on any
    impossible count, size, or a missing terminator.
    """
    assert slicer.size > 8, "store too small to hold a section"
    fmt = struct.unpack("<i", slicer.read(0, 4))[0]
    if fmt != STORE_FORMAT:
        raise CorruptDataError(f"unknown store format {fmt}")
    sections: list[StoreSection] = []
    pos = 4
    for _ in range(MAX_SECTIONS + 1):
        data_size, count = slicer.read_int32_pair(pos)
        pos += 8
        if data_size == 0 and count == 0:
            assert pos <= slicer.size, "terminator past blob end"
            return sections
        if data_size < 0 or not 0 <= count <= MAX_OBJECT_COUNT:
            raise CorruptDataError(f"section size {data_size} / count {count} out of range")
        if len(sections) == MAX_SECTIONS:
            raise CorruptDataError(f"more than {MAX_SECTIONS} sections")
        index_start = pos + data_size
        raw_index = slicer.read(index_start, count * INDEX_ENTRY.size)
        entries = [tuple(e) for e in INDEX_ENTRY.iter_unpack(raw_index)]
        sections.append(StoreSection(pos, data_size, t.cast(list[tuple[bytes, int, int]], entries)))
        pos = index_start + count * INDEX_ENTRY.size
    raise CorruptDataError("no section terminator")


def entry_in_bounds(section: StoreSection, offset: int, size: int) -> bool:
    """True when an index entry's file lies inside its section's data."""
    assert section.data_size >= 0, "negative section size"
    return 0 <= offset and 0 < size and offset + size <= section.data_size


def section_kind(slicer: BlobSlicer, section: StoreSection) -> type[Profile] | type[Tribe] | None:
    """Classify a section by the class name in its first in-bounds file.

    Pre: section bounds already validated. Post: ``Tribe``, ``Profile``, or
    ``None`` when no entry names a known class.
    """
    assert section.entries is not None, "section has no index"
    for _, offset, size in section.entries:
        if not entry_in_bounds(section, offset, size) or size < CLASS_NAME_OFFSET + 4:
            continue
        head = slicer.read(section.data_start + offset, min(size, CLASS_NAME_OFFSET + 4 + MAX_CLASS_NAME))
        length = struct.unpack_from("<i", head, CLASS_NAME_OFFSET)[0]
        name = head[CLASS_NAME_OFFSET + 4 : CLASS_NAME_OFFSET + 4 + max(0, length)]
        if Tribe.MAIN_CLASS_NAME.encode() in name:
            return Tribe
        if Profile.MAIN_CLASS_NAME.encode() in name:
            return Profile
        return None
    return None


def load_section(slicer: BlobSlicer, section: StoreSection, number: int, store: EmbeddedStore) -> None:
    """Load the current entries of one section into ``store``.

    Pre: ``section`` came from :func:`read_sections`. Post: current files are
    parsed and de-duplicated by id (latest in index order wins); superseded
    copies are counted; per-entry failures are recorded, never raised.
    """
    assert number >= 0, "negative section number"
    kind = section_kind(slicer, section)
    if kind is None:
        store.errors.append(f"section {number}: unknown content, skipped")
        return
    label = "tribe" if kind is Tribe else "profile"
    latest: dict[int, Profile | Tribe] = {}
    superseded = 0
    for i, (key, offset, size) in enumerate(section.entries):
        if key == ZERO_KEY:
            superseded += 1
            continue
        loaded = load_entry(slicer, section, kind, offset, size)
        if isinstance(loaded, str):
            store.errors.append(f"{label} #{i}: {loaded}")
            continue
        ident = loaded.tribe_id if isinstance(loaded, Tribe) else loaded.player_id
        latest[ident if isinstance(ident, int) else -1 - i] = loaded
    if kind is Tribe:
        store.tribes.extend(t.cast(list[Tribe], list(latest.values())))
        store.superseded_tribes += superseded
    else:
        store.profiles.extend(t.cast(list[Profile], list(latest.values())))
        store.superseded_profiles += superseded
    assert superseded <= len(section.entries), "superseded count exceeds entries"


def load_entry(
    slicer: BlobSlicer,
    section: StoreSection,
    kind: type[Profile] | type[Tribe],
    offset: int,
    size: int,
) -> Profile | Tribe | str:
    """Parse one packed file; return the object or an error string.

    Pre: ``kind`` is ``Profile`` or ``Tribe``. Post: never raises for bad
    entry data; out-of-bounds entries, unknown versions, and parse failures
    come back as a one-line reason.
    """
    assert kind in (Profile, Tribe), "unsupported entry kind"
    if not entry_in_bounds(section, offset, size) or size < 4:
        return f"offset {offset} size {size} outside section of {section.data_size} bytes"
    raw = slicer.read(section.data_start + offset, size)
    version = struct.unpack_from("<i", raw, 0)[0]
    if version not in kind.VALID_VERSIONS:
        return f"unsupported file version {version}"
    try:
        return kind.load(raw)
    except Exception as exc:  # noqa: BLE001 - one bad entry must not sink the store
        logger.debug("Embedded %s entry failed to parse", kind.__name__, exc_info=True)
        return f"{type(exc).__name__}: {exc}"
