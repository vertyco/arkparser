"""
Tribe model class - ARK tribe data.

Wraps tribe data with intuitive attribute access.
"""

from __future__ import annotations

import re
import typing as t
from dataclasses import dataclass, field


@dataclass
class TribeMember:
    """
    A tribe member.

    Attributes:
        player_id: Unique player ID.
        name: Player name.
        rank: Rank within the tribe.
    """

    player_id: int = 0
    name: str = ""
    rank: int = 0

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary."""
        return {
            "player_id": self.player_id,
            "name": self.name,
            "rank": self.rank,
        }


@dataclass
class TribeLogEntry:
    """
    A tribe log entry.

    Log entries follow the format: "Day X, HH:MM:SS: <RichColor ...>message</>"

    Attributes:
        day: In-game day number.
        time: Time string (HH:MM:SS).
        message: Full raw log message (including rich color tags).
        clean_message: Message with rich color tags stripped.
    """

    day: int = 0
    time: str = ""
    message: str = ""

    # Regex to parse "Day X, HH:MM:SS: rest"
    _LOG_PATTERN: t.ClassVar[re.Pattern[str]] = re.compile(r"Day\s+(\d+),?\s+([\d:]+):\s*(.*)", re.DOTALL)
    # Regex to strip RichColor tags
    _RICH_COLOR_PATTERN: t.ClassVar[re.Pattern[str]] = re.compile(r"<RichColor[^>]*>|</>")

    @classmethod
    def from_string(cls, raw: str) -> TribeLogEntry:
        """
        Parse a tribe log entry from a raw string.

        Args:
            raw: Raw log string (e.g., "Day 387, 22:35:36: message").

        Returns:
            A TribeLogEntry with parsed fields.
        """
        match = cls._LOG_PATTERN.match(raw.strip())
        if match:
            return cls(
                day=int(match.group(1)),
                time=match.group(2),
                message=raw.strip(),
            )
        return cls(message=raw.strip())

    @property
    def clean_message(self) -> str:
        """Message with RichColor XML tags stripped."""
        match = self._LOG_PATTERN.match(self.message)
        body = match.group(3) if match else self.message
        return self._RICH_COLOR_PATTERN.sub("", body).strip()

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary."""
        return {
            "day": self.day,
            "time": self.time,
            "message": self.message,
            "clean_message": self.clean_message,
        }


@dataclass
class Tribe:
    """
    An ARK tribe.

    Wraps tribe data with intuitive property access.

    Attributes:
        tribe_id: Unique tribe identifier.
        name: Tribe name.
        owner_id: Player ID of the tribe owner.
        members: List of tribe members.
        log: List of tribe log entries.

    Example:
        >>> tribe = Tribe.from_game_object(obj)
        >>> print(f"{tribe.name} (ID: {tribe.tribe_id})")
        >>> print(f"Members: {len(tribe.members)}")
    """

    _game_object: t.Any = field(default=None, repr=False)

    # Cached values
    _members: list[TribeMember] | None = field(default=None, repr=False)
    _log: list[TribeLogEntry] | None = field(default=None, repr=False)

    @classmethod
    def from_game_object(cls, game_object: t.Any) -> Tribe:
        """
        Create a Tribe from a GameObject.

        Args:
            game_object: The tribe's game object.

        Returns:
            A Tribe instance.
        """
        return cls(_game_object=game_object)

    @property
    def guid(self) -> str:
        """Unique identifier (ASA only)."""
        return self._game_object.guid if self._game_object else ""

    @property
    def tribe_id(self) -> int:
        """Unique tribe identifier."""
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("TribeID", default=0)
        return int(val) if val else 0

    @property
    def name(self) -> str:
        """Tribe name."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("TribeName", default="") or ""

    @property
    def owner_id(self) -> int:
        """Player ID of the tribe owner."""
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("OwnerPlayerDataID", default=0)
        return int(val) if val else 0

    @property
    def owner_name(self) -> str:
        """Name of the tribe owner."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("OwnerPlayerName", default="") or ""

    @property
    def member_count(self) -> int:
        """Number of tribe members (from MembersPlayerDataID count)."""
        if not self._game_object:
            return 0
        count = 0
        while True:
            val = self._game_object.get_property_value("MembersPlayerDataID", index=count, default=None)
            if val is None:
                break
            count += 1
        return max(count, 1)  # At least the owner

    @property
    def members(self) -> list[TribeMember]:
        """List of tribe members."""
        if self._members is None:
            self._members = []
            if self._game_object:
                i = 0
                while True:
                    player_id = self._game_object.get_property_value("MembersPlayerDataID", index=i, default=None)
                    if player_id is None:
                        break
                    name = self._game_object.get_property_value("MembersPlayerName", index=i, default="") or ""
                    rank = self._game_object.get_property_value("MembersRankGroups", index=i, default=0) or 0
                    self._members.append(
                        TribeMember(
                            player_id=int(player_id),
                            name=name,
                            rank=int(rank) if rank else 0,
                        )
                    )
                    i += 1
        return self._members

    @property
    def alliance_ids(self) -> list[int]:
        """IDs of allied tribes."""
        if not self._game_object:
            return []
        ids = []
        i = 0
        while True:
            val = self._game_object.get_property_value("TribeAlliances", index=i, default=None)
            if val is None:
                break
            ids.append(int(val) if val else 0)
            i += 1
        return ids

    @property
    def log(self) -> list[TribeLogEntry]:
        """
        Tribe log entries.

        Parses the TribeLog property (array of strings) into
        structured TribeLogEntry objects.
        """
        if self._log is None:
            self._log = []
            if self._game_object:
                log_val = self._game_object.get_property_value("TribeLog", default=None)
                if isinstance(log_val, list):
                    for entry in log_val:
                        if isinstance(entry, str) and entry.strip():
                            self._log.append(TribeLogEntry.from_string(entry))
                else:
                    # Try indexed access (some formats store as repeated props)
                    i = 0
                    while True:
                        val = self._game_object.get_property_value("TribeLog", index=i, default=None)
                        if val is None:
                            break
                        if isinstance(val, str) and val.strip():
                            self._log.append(TribeLogEntry.from_string(val))
                        i += 1
        return self._log

    @property
    def raw_logs(self) -> list[str]:
        """
        Raw tribe log strings (as stored in the save file).

        Returns:
            List of raw log message strings.
        """
        return [entry.message for entry in self.log]

    def get_property(self, name: str, index: int = 0, default: t.Any = None) -> t.Any:
        """
        Get a raw property value from the underlying game object.

        Args:
            name: Property name.
            index: Array index for repeated properties.
            default: Value to return if not found.

        Returns:
            The property value.
        """
        if self._game_object:
            return self._game_object.get_property_value(name, default=default, index=index)
        return default

    def to_dict(self) -> dict[str, t.Any]:
        """Convert to dictionary matching C# ASV_Tribes export format."""
        return {
            "tribeid": self.tribe_id,
            "tribe": self.name,
            "players": self.member_count,
            "members": [m.to_dict() for m in self.members],
            "owner_id": self.owner_id,
            "owner_name": self.owner_name,
            "alliance_ids": self.alliance_ids,
            "logs": self.raw_logs,
        }

    def __repr__(self) -> str:
        return f"Tribe({self.name!r}, id={self.tribe_id}, members={self.member_count})"
