"""
ARK Save Parser - Parse ARK: Survival Evolved/Ascended save files.

This package provides tools to parse various ARK save file formats:

- Profile: Player profile data (.arkprofile)
- Tribe: Tribe data (.arktribe)
- CloudInventory: Obelisk/cloud inventory data (no extension)
- WorldSave: World save data (.ark) — auto-detects ASE binary and ASA SQLite

Supports both ASE (ARK: Survival Evolved) and ASA (ARK: Survival Ascended)
formats with automatic detection.

Example usage:
    >>> from arkparser import Profile, Tribe, CloudInventory, WorldSave
    >>>
    >>> # Load a player profile
    >>> profile = Profile.load("path/to/profile.arkprofile")
    >>> print(f"Player: {profile.player_name}")
    >>>
    >>> # Load tribe data
    >>> tribe = Tribe.load("path/to/tribe.arktribe")
    >>> print(f"Tribe: {tribe.name}, Members: {tribe.member_count}")
    >>>
    >>> # Load cloud inventory (obelisk data)
    >>> inv = CloudInventory.load("path/to/obelisk_file")
    >>> print(f"Creatures: {inv.creature_count}, Items: {inv.item_count}")
    >>>
    >>> # Load any world save — ASE or ASA, auto-detected
    >>> save = WorldSave.load("path/to/TheIsland.ark")    # ASE
    >>> save = WorldSave.load("path/to/Extinction_WP.ark")  # ASA
"""

from arkparser.common.exceptions import ArkParseError
from arkparser.common.map_config import MapConfig, get_map_config, get_map_config_by_name
from arkparser.common.version_detection import ArkFileFormat, ArkFileType, detect_file_type, detect_format
from arkparser.data_models import DinoStats, UploadedCreature, UploadedItem
from arkparser.export import (
    export_all,
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
from arkparser.models import (
    Character,
    Creature,
    CreatureStats,
    Item,
    Location,
    Player,
    Structure,
    TamedCreature,
    TribeLogEntry,
    TribeMember,
    WildCreature,
)
from arkparser.models import Tribe as TribeModel

__all__ = [
    # File parsers
    "Profile",
    "Tribe",
    "CloudInventory",
    "Obelisk",
    "WorldSave",
    # Data models (legacy)
    "UploadedCreature",
    "UploadedItem",
    "DinoStats",
    # Game objects
    "GameObject",
    "GameObjectContainer",
    "LocationData",
    # Models
    "Creature",
    "TamedCreature",
    "WildCreature",
    "Item",
    "Player",
    "TribeModel",
    "TribeMember",
    "TribeLogEntry",
    "Structure",
    "Character",
    "CreatureStats",
    "Location",
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
    "export_to_files",
    # Utilities
    "detect_format",
    "detect_file_type",
    "ArkFileFormat",
    "ArkFileType",
    "ArkParseError",
]

__version__ = "0.1.0"
