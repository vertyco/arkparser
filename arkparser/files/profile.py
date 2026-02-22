"""
Player profile parser for .arkprofile files.

Profile files contain player character data including:
- Character name and stats
- Level and experience
- Engrams learned
- Inventory items (if saved)
- Tribe affiliation
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from .base import ArkFile


@dataclass
class Profile(ArkFile):
    """
    Parser for .arkprofile player profile files.

    The main object has class name "PrimalPlayerData" or "PrimalPlayerDataBP_C".
    All player data is nested inside a "MyData" struct property.

    Example usage:
        >>> profile = Profile.load("examples/ase/map_save/2533274977850953.arkprofile")
        >>> print(f"Player: {profile.player_name}")
        >>> print(f"Level: {profile.level}")
    """

    VALID_VERSIONS: t.ClassVar[tuple[int, ...]] = (1, 5, 6, 7)
    MAIN_CLASS_NAME: t.ClassVar[str] = "PrimalPlayerData"

    @property
    def main_object(self):
        """Get the main player data object (handles both class name variants).

        ASE class names: "PrimalPlayerData", "PrimalPlayerDataBP_C"
        ASA class names: "/Game/PrimalEarth/CoreBlueprints/PrimalPlayerDataBP.PrimalPlayerDataBP_C"
        """
        for obj in self.objects:
            # Check for various naming conventions
            if "PrimalPlayerData" in obj.class_name:
                return obj
        return None

    @property
    def _player_data(self) -> dict[str, t.Any]:
        """Get the nested MyData struct as a dictionary."""
        player_data = self.get_property_value("MyData")
        if player_data is None:
            return {}
        return player_data if isinstance(player_data, dict) else {}

    @property
    def _persistent_stats(self) -> dict[str, t.Any]:
        """Get the nested MyPersistentCharacterStats struct."""
        stats = self._player_data.get("MyPersistentCharacterStats")
        if stats is None:
            return {}
        return stats if isinstance(stats, dict) else {}

    # Convenience properties for common player data

    @property
    def player_name(self) -> str | None:
        """Get the player's character name."""
        return self._player_data.get("PlayerName")

    @property
    def player_id(self) -> int | None:
        """Get the player's unique ID."""
        return self._player_data.get("PlayerDataID")

    @property
    def unique_id(self) -> str | None:
        """Get the player's network unique ID (Steam ID, Xbox ID, etc.)."""
        unique_id = self._player_data.get("UniqueID")
        if unique_id and isinstance(unique_id, dict):
            return str(unique_id.get("net_id", ""))
        return None

    @property
    def tribe_id(self) -> int | None:
        """
        Get the player's tribe ID (0 if not in a tribe).

        Note: ASE uses "TribeId" (lowercase d), ASA uses "TribeID" (uppercase D).
        """
        # ASE uses "TribeId", ASA uses "TribeID"
        return self._player_data.get("TribeId") or self._player_data.get("TribeID")

    @property
    def tribe_name(self) -> str | None:
        """
        Get the player's tribe name.

        Note: Tribe name is NOT stored in the player profile file.
        This property will always return None. To get the tribe name,
        load the corresponding .arktribe file using the tribe_id.
        """
        return None  # Tribe name is not stored in profile files

    @property
    def level(self) -> int:
        """
        Get the player's current level.

        Calculated from CharacterStatusComponent_ExtraCharacterLevel + 1.
        """
        extra_level = self._persistent_stats.get("CharacterStatusComponent_ExtraCharacterLevel", 0)
        return (extra_level or 0) + 1

    @property
    def experience(self) -> float:
        """Get the player's total experience points."""
        return self._persistent_stats.get("CharacterStatusComponent_ExperiencePoints", 0.0) or 0.0

    @property
    def total_engram_points(self) -> int:
        """Get total engram points spent."""
        return self._persistent_stats.get("PlayerState_TotalEngramPoints", 0) or 0

    @property
    def engram_blueprints(self) -> list[str]:
        """Get list of learned engram blueprint paths."""
        engrams = self._persistent_stats.get("EngramBlueprints")
        if not engrams:
            engrams = self._persistent_stats.get("PlayerState_EngramBlueprints", [])
        return [str(e) for e in engrams] if engrams else []

    def get_stat(self, stat_index: int) -> dict[str, t.Any]:
        """
        Get a specific stat value by index.

        Stat indices:
            0: Health
            1: Stamina
            2: Torpidity
            3: Oxygen
            4: Food
            5: Water
            6: Temperature
            7: Weight
            8: Melee Damage
            9: Movement Speed
            10: Fortitude
            11: Crafting Skill

        Returns:
            Dict with base and added values
        """
        added = 0
        stats = self._persistent_stats
        points_key = "CharacterStatusComponent_NumberOfLevelUpPointsApplied"
        points_value = stats.get(points_key)

        if isinstance(points_value, list):
            if 0 <= stat_index < len(points_value):
                raw_value = points_value[stat_index]
                if isinstance(raw_value, int):
                    added = raw_value
        elif isinstance(points_value, int):
            if stat_index == 0:
                added = points_value

        indexed_prefix = f"{points_key}["
        for key, value in stats.items():
            if not isinstance(key, str) or not key.startswith(indexed_prefix):
                continue
            if not isinstance(value, int):
                continue
            suffix = key[len(indexed_prefix) :]
            if not suffix.endswith("]"):
                continue
            index_text = suffix[:-1]
            if not index_text.isdigit():
                continue
            if int(index_text) == stat_index:
                added = value
                break

        return {
            "stat_index": stat_index,
            "added": added,
        }

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary with player-specific fields."""
        base_dict = super().to_dict()
        base_dict.update(
            {
                "player_name": self.player_name,
                "player_id": self.player_id,
                "unique_id": self.unique_id,
                "tribe_id": self.tribe_id,
                "tribe_name": self.tribe_name,
                "experience": self.experience,
                "total_engram_points": self.total_engram_points,
            }
        )
        return base_dict
