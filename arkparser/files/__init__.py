"""
File parsers for ARK save data.

This module provides parsers for various ARK save file formats:
- Profile: Player profile data (.arkprofile)
- Tribe: Tribe data (.arktribe)
- CloudInventory: Obelisk/cloud inventory data (no extension)
- WorldSave: World save data (.ark) — auto-detects ASE binary and ASA SQLite

All parsers support both ASE and ASA formats with automatic detection.
"""

from .base import ArkFile
from .cloud_inventory import CloudInventory
from .profile import Profile
from .tribe import Tribe
from .world_save import WorldSave

__all__ = [
    "ArkFile",
    "Profile",
    "Tribe",
    "CloudInventory",
    "WorldSave",
]
