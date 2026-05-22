"""
ARK Save Parser - Parse ARK: Survival Evolved/Ascended save files.

This package provides tools to parse various ARK save file formats:

- Profile: Player profile data (.arkprofile)
- Tribe: Tribe data (.arktribe)
- CloudInventory: Obelisk/cloud inventory data (no extension)
- WorldSave: World save data (.ark), auto-detects ASE binary and ASA SQLite

Supports both ASE (ARK: Survival Evolved) and ASA (ARK: Survival Ascended)
formats with automatic detection.

Example usage:
    >>> from arkparser import Profile, Tribe, CloudInventory, WorldSave
    >>> profile = Profile.load("path/to/profile.arkprofile")
    >>> tribe = Tribe.load("path/to/tribe.arktribe")
    >>> inv = CloudInventory.load("path/to/obelisk_file")
    >>> save = WorldSave.load("path/to/TheIsland.ark")    # ASE
    >>> save = WorldSave.load("path/to/Extinction_WP.ark")  # ASA
"""

from arkparser.common.exceptions import ArkParseError
from arkparser.common.map_config import MapConfig, get_map_config, get_map_config_by_name
from arkparser.common.version_detection import (
    ArkFileFormat,
    ArkFileType,
    detect_file_type,
    detect_format,
)
from arkparser.data_models import (
    CryopodCreature,
    DinoStats,
    UploadedCreature,
    UploadedItem,
)
from arkparser.export import (
    export_all,
    export_cloud_inventory,
    export_cluster_items,
    export_cluster_uploads,
    export_map_structures,
    export_players,
    export_structures,
    export_tamed,
    export_to_files,
    export_tribe_logs,
    export_tribes,
    export_wild,
)
from arkparser.files import CloudInventory, Profile, Tribe, WorldSave
from arkparser.game_objects import GameObject, GameObjectContainer, LocationData

# Convenience alias - users may know this as "Obelisk" from the game
Obelisk = CloudInventory

__all__ = [
    # File parsers
    "Profile",
    "Tribe",
    "CloudInventory",
    "Obelisk",
    "WorldSave",
    # Cloud-inventory data models
    "UploadedCreature",
    "UploadedItem",
    "CryopodCreature",
    "DinoStats",
    # Game objects
    "GameObject",
    "GameObjectContainer",
    "LocationData",
    # Map config
    "MapConfig",
    "get_map_config",
    "get_map_config_by_name",
    # Export
    "export_all",
    "export_tamed",
    "export_wild",
    "export_players",
    "export_tribes",
    "export_structures",
    "export_tribe_logs",
    "export_map_structures",
    "export_cluster_uploads",
    "export_cluster_items",
    "export_cloud_inventory",
    "export_to_files",
    # Utilities
    "detect_format",
    "detect_file_type",
    "ArkFileFormat",
    "ArkFileType",
    "ArkParseError",
]

__version__ = "0.4.1"
