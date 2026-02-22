"""
ARK File Format Detection.

Detects whether an ARK save file is in ASE or ASA format based on
header information. This allows the parser to automatically choose
the correct parsing strategy.

Detection Strategy for profiles/tribes/cloud data:
    1. Read the version number from the file header (Int32)
    2. Version 7+ is always ASA
    3. For versions 1-6, check for a GUID at bytes 8-24:
       - All zeros = ASE
       - Non-zero = ASA (uses GUIDs for object identification)

World saves (.ark files) have different headers:
    - ASE: Int16 version at offset 0 (typically 5-7)
    - ASA: SQLite database format
"""

from __future__ import annotations

import typing as t
from enum import Enum
from pathlib import Path


class ArkFileFormat(Enum):
    """
    ARK save file format types.

    ASE (ARK: Survival Evolved):
        - Save format versions 5-6
        - Uses floats for vectors
        - Object references by index

    ASA (ARK: Survival Ascended):
        - Save format version 7+
        - Uses doubles for vectors
        - Object references by GUID
        - World saves use SQLite database format
    """

    ASE = "ASE"
    ASA = "ASA"
    UNKNOWN = "UNKNOWN"


class ArkFileType(Enum):
    """
    ARK save file types based on extension and content.
    """

    PROFILE = "profile"  # .arkprofile
    TRIBE = "tribe"  # .arktribe
    CLOUD_INVENTORY = "cloud_inventory"  # No extension (obelisk data)
    WORLD_SAVE = "world_save"  # .ark
    UNKNOWN = "unknown"


def detect_file_type(source: bytes | str | Path) -> ArkFileType:
    """
    Detect the type of ARK save file based on extension.

    Args:
        source: File path string, Path object, or bytes (for bytes, returns UNKNOWN).

    Returns:
        The detected file type.

    Example:
        >>> detect_file_type("player.arkprofile")
        ArkFileType.PROFILE
    """
    if isinstance(source, bytes):
        return ArkFileType.UNKNOWN

    path = Path(source)
    suffix = path.suffix.lower()

    if suffix == ".arkprofile":
        return ArkFileType.PROFILE
    elif suffix == ".arktribe":
        return ArkFileType.TRIBE
    elif suffix == ".ark":
        return ArkFileType.WORLD_SAVE
    elif suffix == "":
        # No extension - likely cloud inventory / obelisk data
        return ArkFileType.CLOUD_INVENTORY

    return ArkFileType.UNKNOWN


def detect_format(source: bytes | str | Path) -> ArkFileFormat:
    """
    Detect the format of an ARK save file.

    Automatically determines whether a file uses ASE or ASA format
    by examining the file header. Works for:
    - .arkprofile (player profiles)
    - .arktribe (tribe data)
    - Cloud/obelisk data (no extension)
    - .ark world saves

    Args:
        source: Raw bytes, file path string, or Path object.

    Returns:
        ArkFileFormat.ASE, ArkFileFormat.ASA, or ArkFileFormat.UNKNOWN.

    Example:
        >>> format = detect_format("examples/ase/map_save/1446520645.arktribe")
        >>> print(format)
        ArkFileFormat.ASE
    """
    # Load data if given a path
    path: Path | None = None
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists() or path.stat().st_size == 0:
            return ArkFileFormat.UNKNOWN
        data = path.read_bytes()
    else:
        data = source

    # Need at least some bytes to detect
    if len(data) < 24:
        return ArkFileFormat.UNKNOWN

    # Check for SQLite header (ASA world saves)
    if data[:16] == b"SQLite format 3\x00":
        return ArkFileFormat.ASA

    # Check if this is a world save by file extension
    is_world_save = path is not None and path.suffix.lower() == ".ark"

    if is_world_save:
        # World saves use Int16 version at offset 0
        int16_version = int.from_bytes(data[0:2], "little", signed=True)
        # ASE world saves have versions 5-12
        if 5 <= int16_version <= 12:
            return ArkFileFormat.ASE
        return ArkFileFormat.UNKNOWN

    # For profiles/tribes/cloud data, version is Int32
    version = int.from_bytes(data[0:4], "little", signed=True)

    # Version 7+ is ASA for profiles/tribes/cloud
    if version >= 7:
        return ArkFileFormat.ASA

    # For versions 1-6, check for GUID at bytes 8-24
    # ASE files have all zeros here; ASA files have a non-zero GUID
    if 1 <= version <= 6:
        guid_bytes = data[8:24]
        has_guid = any(b != 0 for b in guid_bytes)
        return ArkFileFormat.ASA if has_guid else ArkFileFormat.ASE

    return ArkFileFormat.UNKNOWN


def get_save_version(source: bytes | str | Path) -> int:
    """
    Read the save version number from a file header.

    For profiles/tribes/cloud data, this reads an Int32.
    For world saves, this reads an Int16.

    Args:
        source: Raw bytes, file path string, or Path object.

    Returns:
        The version number, or -1 if the file is invalid.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists() or path.stat().st_size == 0:
            return -1
        data = path.read_bytes()
    else:
        data = source

    if len(data) < 4:
        return -1

    # Check for SQLite (ASA world save)
    if data[:16] == b"SQLite format 3\x00":
        return -1  # SQLite doesn't have a simple version

    # Check if it looks like a world save (Int16 version 5-9)
    int16_version = int.from_bytes(data[0:2], "little", signed=True)
    if 5 <= int16_version <= 9:
        return int16_version

    # Otherwise read as Int32
    return int.from_bytes(data[0:4], "little", signed=True)
