"""
ARK Parser - Common Utilities.

This module provides the foundational building blocks for parsing ARK save files:

- BinaryReader: Low-level binary reading with position tracking
- ArkName: Unreal Engine FName type (name + instance)
- ObjectReference: References to game objects
- ArkFileFormat: Enum for ASE vs ASA format detection
- Exceptions: Custom error types for parse failures

Example:
    >>> from arkparser.common import BinaryReader, detect_format
    >>> format = detect_format("save.ark")
    >>> with BinaryReader.from_file("save.ark") as reader:
    ...     version = reader.read_int32()
"""

from .binary_reader import BinaryReader
from .exceptions import (
    ArkParseError,
    CorruptDataError,
    EndOfDataError,
    UnexpectedDataError,
    UnknownPropertyError,
    UnknownStructError,
)
from .map_config import (
    DEFAULT_MAP_CONFIG,
    MapConfig,
    get_map_config,
    get_map_config_by_name,
    list_maps,
)
from .types import (
    NAME_NONE,
    ArkName,
    ObjectReference,
    PropertyValue,
)
from .version_detection import (
    ArkFileFormat,
    detect_format,
    get_save_version,
)

__all__ = [
    # Binary reading
    "BinaryReader",
    # Types
    "ArkName",
    "ObjectReference",
    "PropertyValue",
    "NAME_NONE",
    # Format detection
    "ArkFileFormat",
    "detect_format",
    "get_save_version",
    # Map config
    "MapConfig",
    "DEFAULT_MAP_CONFIG",
    "get_map_config",
    "get_map_config_by_name",
    "list_maps",
    # Exceptions
    "ArkParseError",
    "CorruptDataError",
    "EndOfDataError",
    "UnexpectedDataError",
    "UnknownPropertyError",
    "UnknownStructError",
]
