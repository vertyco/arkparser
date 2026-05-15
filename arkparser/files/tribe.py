"""
Tribe data parser for .arktribe files.

Tribe files contain:
- Tribe name and ID
- Member list with ranks
- Tribe log entries
- Governance settings
- Alliance information
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from ..common.normalization import normalize_indexed_data, normalize_indexed_list
from .base import ArkFile


@dataclass
class Tribe(ArkFile):
    """
    Parser for .arktribe tribe data files.

    The main object has class name "PrimalTribeData".
    All tribe data is nested inside a "TribeData" struct property.

    Example usage:
        >>> tribe = Tribe.load("examples/ase/map_save/1446520645.arktribe")
        >>> print(f"Tribe: {tribe.name}")
        >>> print(f"Members: {tribe.member_count}")
    """

    VALID_VERSIONS: t.ClassVar[tuple[int, ...]] = (1, 5, 6, 7)
    MAIN_CLASS_NAME: t.ClassVar[str] = "PrimalTribeData"

    @property
    def _tribe_data(self) -> dict[str, t.Any]:
        """Get the nested TribeData struct as a dictionary."""
        tribe_data = self.get_property_value("TribeData")
        if tribe_data is None:
            return {}
        normalized = normalize_indexed_data(tribe_data)
        return normalized if isinstance(normalized, dict) else {}

    # Convenience properties for tribe data

    @property
    def tribe_id(self) -> int | None:
        """Get the tribe's unique ID.

        Note: ASE uses 'TribeId' while ASA uses 'TribeID' (different capitalization).
        """
        if "TribeID" in self._tribe_data:
            return self._tribe_data["TribeID"]
        if "TribeId" in self._tribe_data:
            return self._tribe_data["TribeId"]
        return None

    @property
    def name(self) -> str | None:
        """Get the tribe's name."""
        return self._tribe_data.get("TribeName")

    @property
    def owner_player_id(self) -> int | None:
        """Get the player ID of the tribe owner.

        Note: ASE uses 'OwnerPlayerDataID' while ASA uses 'OwnerPlayerDataId' (different capitalization).
        """
        if "OwnerPlayerDataID" in self._tribe_data:
            return self._tribe_data["OwnerPlayerDataID"]
        if "OwnerPlayerDataId" in self._tribe_data:
            return self._tribe_data["OwnerPlayerDataId"]
        return None

    @property
    def member_ids(self) -> list[int]:
        """Get list of member player IDs."""
        return [int(member_id) for member_id in normalize_indexed_list(self._tribe_data.get("MembersPlayerDataID"))]

    @property
    def member_names(self) -> list[str]:
        """Get list of member player names."""
        return [str(member_name) for member_name in normalize_indexed_list(self._tribe_data.get("MembersPlayerName"))]

    @property
    def member_ranks(self) -> list[int]:
        """Get list of member rank indices."""
        return [int(rank) for rank in normalize_indexed_list(self._tribe_data.get("MembersRankGroups"))]

    @property
    def member_count(self) -> int:
        """Get the number of tribe members."""
        return len(self.member_ids)

    @property
    def log_entries(self) -> list[str]:
        """Get tribe log entries as strings."""
        return [str(entry) for entry in normalize_indexed_list(self._tribe_data.get("TribeLog"))]

    @property
    def rank_groups(self) -> list[dict[str, t.Any]]:
        """
        Get tribe rank group definitions.

        Each rank has:
        - Name
        - Permission flags
        """
        rank_names = normalize_indexed_list(self._tribe_data.get("TribeRankGroupNames"))
        # Could also get permissions from TribeRankGroupPermissions
        return [{"name": name} for name in rank_names]

    @property
    def alliance_ids(self) -> list[int]:
        """Get IDs of allied tribes."""
        return [int(alliance_id) for alliance_id in normalize_indexed_list(self._tribe_data.get("TribeAlliances"))]

    @property
    def government_type(self) -> int:
        """Get tribe government type (0=Player Owned, 1=Tribe Owned, 2=Personal Owned)."""
        return self._tribe_data.get("TribeGovernment", 0)

    def get_members(self) -> list[dict[str, t.Any]]:
        """
        Get detailed member information.

        Returns:
            List of dicts with member data (id, name, rank, etc.)
        """
        ids = self.member_ids
        names = self.member_names
        ranks = self.member_ranks

        members = []
        for i in range(len(ids)):
            member = {
                "player_id": ids[i] if i < len(ids) else None,
                "name": names[i] if i < len(names) else None,
                "rank": ranks[i] if i < len(ranks) else 0,
            }
            members.append(member)

        return members

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary with tribe-specific fields."""
        base_dict = super().to_dict()
        base_dict.update(
            {
                "tribe_id": self.tribe_id,
                "name": self.name,
                "owner_player_id": self.owner_player_id,
                "member_count": self.member_count,
                "members": self.get_members(),
                "log_entries": self.log_entries,
                "alliance_ids": self.alliance_ids,
                "government_type": self.government_type,
            }
        )
        return base_dict
