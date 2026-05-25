"""
Player profile parser for .arkprofile files.

Profile files contain player character data including:
- Platform gamertag and character name
- Level and experience
- Engrams learned
- Inventory items (if saved)
- Tribe affiliation
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from ..common.normalization import normalize_indexed_data, normalize_indexed_list
from .base import ArkFile


@dataclass
class Profile(ArkFile):
    """
    Parser for .arkprofile player profile files.

    The main object has class name "PrimalPlayerData" or "PrimalPlayerDataBP_C".
    All player data is nested inside a "MyData" struct property.

    Example usage:
        >>> profile = Profile.load("examples/ase/map_save/2533274977850953.arkprofile")
        >>> print(f"Gamertag: {profile.player_name}")
        >>> print(f"Character: {profile.character_name}")
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
        normalized = normalize_indexed_data(player_data)
        return normalized if isinstance(normalized, dict) else {}

    @property
    def _persistent_stats(self) -> dict[str, t.Any]:
        """Get the nested MyPersistentCharacterStats struct."""
        stats = self._player_data.get("MyPersistentCharacterStats")
        if stats is None:
            return {}
        normalized = normalize_indexed_data(stats)
        return normalized if isinstance(normalized, dict) else {}

    # Convenience properties for common player data

    @property
    def player_name(self) -> str | None:
        """Get the player's platform gamertag (Steam / Xbox / PSN display name).

        Note: despite the historical name, this is NOT the in-game character
        name. For that, use ``character_name``. The C# reference (ContentPlayer.cs
        line 77) reads this same ``PlayerName`` field into its ``Name`` property.
        """
        return self._player_data.get("PlayerName")

    @property
    def character_name(self) -> str | None:
        """Get the player's in-game character name.

        Purpose: returns the name the player chose when creating their
        character (e.g. "Alex"), distinct from the platform gamertag (e.g.
        "Itz0Alex") which ``player_name`` returns.
        Preconditions: profile file is loaded; ``_player_data`` is accessible.
        Postconditions: returns ``MyPlayerCharacterConfig.PlayerCharacterName``
        when present, including empty-string values, falling back to
        ``player_name`` (gamertag) only when the config field is absent -
        matches the C# reference behavior
        (ContentPlayer.cs line 86: ``CharacterName = playerConfig.GetPropertyValue<string>("PlayerCharacterName") ?? Name;``).
        Side effects: none.
        Failure modes: returns ``None`` only when both the config struct and
        ``PlayerName`` are missing.
        """
        config = self._player_data.get("MyPlayerCharacterConfig")
        if isinstance(config, dict):
            character_name = config.get("PlayerCharacterName")
            if character_name is not None:
                return character_name
        return self.player_name

    @property
    def is_female(self) -> bool | None:
        """Get the player's character gender (True = female, False = male, None = unknown).

        Same nested location as ``character_name``: read from
        ``MyPlayerCharacterConfig.bIsFemale``. Returns None when the config
        struct is absent (treat as gender unknown / default male in display code).
        """
        config = self._player_data.get("MyPlayerCharacterConfig")
        if isinstance(config, dict):
            value = config.get("bIsFemale")
            if value is not None:
                return bool(value)
        return None

    @property
    def player_id(self) -> int | None:
        """Get the player's unique ID."""
        return self._player_data.get("PlayerDataID")

    @property
    def unique_id(self) -> str | None:
        """Get the player's network unique ID (Steam ID, Xbox ID, etc.)."""
        unique_id = normalize_indexed_data(self._player_data.get("UniqueID"))
        if unique_id and isinstance(unique_id, dict):
            return str(unique_id.get("net_id", ""))
        if unique_id:
            return str(unique_id)
        return None

    @property
    def tribe_id(self) -> int | None:
        """Get the player's tribe ID.

        Purpose: return the tribe id ARK actually uses for this player.
        Solo players (never joined a non-default tribe) carry only an
        "auto-tribe" whose id equals their ``PlayerDataID``; the profile
        stores ``TribeId=0`` for them. To match the legacy ASVExport / ARK
        engine convention (and to give consumers a unique-per-player tribe
        id they can group by), fall back to ``player_id`` in that case.

        Preconditions: ``_player_data`` is parsed; ``PlayerDataID`` (used by
        the auto-tribe fallback) may be missing for malformed profiles.
        Postconditions: returns the explicit ``TribeId``/``TribeID`` when
        non-zero, otherwise returns ``player_id``. Returns ``None`` only
        when ``player_id`` is also missing.
        Side effects: none.
        Failure modes: returns ``None`` when neither field is recoverable.

        Note: ASE uses "TribeId" (lowercase d), ASA uses "TribeID" (uppercase D).
        """
        raw = self._player_data.get("TribeId")
        if raw is None:
            raw = self._player_data.get("TribeID")
        if raw:  # non-zero, non-None
            return raw
        # Solo player or freshly-left a tribe: ARK's auto-tribe id == player_id.
        # Matches ASVExport behavior (and gives every player a stable, unique
        # tribe id even when they're not in a multi-member tribe).
        return self.player_id

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
    def last_login_time(self) -> float | None:
        """In-game seconds when this player last logged in.

        Read from ``LastLoginTime`` on the profile's ``MyData`` struct.
        Returns ``None`` when the field is absent. Combine with a
        ``WorldSave``'s ``file_mtime`` + ``game_time`` to convert to a real
        wall-clock datetime.
        """
        val = self._player_data.get("LastLoginTime")
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    @property
    def last_net_address(self) -> str | None:
        """Last client IP / network address ARK persisted for this player.

        Read from ``SavedNetworkAddress`` on the profile's ``MyData`` struct
        (same level as ``LastLoginTime``). Legacy ASVExport reads this exact
        field (ContentPlayer.cs:157 ASE / :341 ASA) and emits it as the
        ``netAddress`` player key. Returns ``None`` when the field is absent
        (e.g. empty placeholder profiles that were never played).

        ASA stores a clean IPv4/IPv6 string; some ASE saves store an
        engine-truncated value (e.g. ``"[2001"``) which is reproduced
        verbatim - matching what legacy ASVExport emits for the same save.
        """
        val = self._player_data.get("SavedNetworkAddress")
        if val is None:
            return None
        return str(val)

    @property
    def total_engram_points(self) -> int:
        """Get total engram points spent."""
        return self._persistent_stats.get("PlayerState_TotalEngramPoints", 0) or 0

    @property
    def engram_blueprints(self) -> list[str]:
        """Get list of learned engram blueprint paths."""
        engrams = self._persistent_stats.get("EngramBlueprints")
        if not engrams:
            engrams = self._persistent_stats.get("PlayerState_EngramBlueprints")
        return [str(engram) for engram in normalize_indexed_list(engrams)]

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

        if isinstance(points_value, dict):
            # Sparse indexed dict (preserved by normalize). Lookup by index.
            raw_value = points_value.get(stat_index)
            if isinstance(raw_value, int):
                added = raw_value
        elif isinstance(points_value, list):
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
                "character_name": self.character_name,
                "player_id": self.player_id,
                "unique_id": self.unique_id,
                "tribe_id": self.tribe_id,
                "tribe_name": self.tribe_name,
                "is_female": self.is_female,
                "experience": self.experience,
                "total_engram_points": self.total_engram_points,
            }
        )
        return base_dict
