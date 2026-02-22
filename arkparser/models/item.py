"""
Item model class - Inventory items.

Wraps GameObject with intuitive attribute access for item data.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field


@dataclass
class Item:
    """
    An inventory item.

    Wraps a GameObject representing an item with intuitive property access.

    Attributes:
        class_name: Blueprint class name.
        name: Custom name (if renamed).
        quantity: Stack quantity.
        quality: Item quality/tier.
        durability: Current durability.
        is_blueprint: True if this is a blueprint.
        is_engram: True if this is an engram.

    Example:
        >>> item = Item.from_game_object(obj)
        >>> print(f"{item.class_name} x{item.quantity}")
        >>> if item.is_blueprint:
        ...     print("  (Blueprint)")
    """

    _game_object: t.Any = field(default=None, repr=False)

    @classmethod
    def from_game_object(cls, game_object: t.Any) -> Item:
        """
        Create an Item from a GameObject.

        Args:
            game_object: The item's game object.

        Returns:
            An Item instance.
        """
        return cls(_game_object=game_object)

    @property
    def class_name(self) -> str:
        """Blueprint class name."""
        return self._game_object.class_name if self._game_object else ""

    @property
    def guid(self) -> str:
        """Unique identifier (ASA only)."""
        return self._game_object.guid if self._game_object else ""

    @property
    def name(self) -> str:
        """Custom name (if renamed by player)."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("CustomItemName", default="") or ""

    @property
    def description(self) -> str:
        """Custom description (if modified)."""
        if not self._game_object:
            return ""
        return self._game_object.get_property_value("CustomItemDescription", default="") or ""

    @property
    def quantity(self) -> int:
        """Stack quantity."""
        if not self._game_object:
            return 1
        val = self._game_object.get_property_value("ItemQuantity", default=1)
        return int(val) if val else 1

    @property
    def quality(self) -> float:
        """Item quality rating."""
        if not self._game_object:
            return 0.0
        val = self._game_object.get_property_value("ItemRating", default=0.0)
        return float(val) if val else 0.0

    @property
    def quality_index(self) -> int:
        """
        Quality tier index.

        0 = Primitive, 1 = Ramshackle, 2 = Apprentice,
        3 = Journeyman, 4 = Mastercraft, 5 = Ascendant
        """
        if not self._game_object:
            return 0
        val = self._game_object.get_property_value("ItemQualityIndex", default=0)
        return int(val) if val else 0

    @property
    def quality_name(self) -> str:
        """Quality tier name."""
        names = [
            "Primitive",
            "Ramshackle",
            "Apprentice",
            "Journeyman",
            "Mastercraft",
            "Ascendant",
        ]
        idx = self.quality_index
        return names[idx] if 0 <= idx < len(names) else "Unknown"

    @property
    def durability(self) -> float:
        """Current durability."""
        if not self._game_object:
            return 0.0
        val = self._game_object.get_property_value("SavedDurability", default=0.0)
        return float(val) if val else 0.0

    @property
    def is_blueprint(self) -> bool:
        """True if this is a blueprint."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("bIsBlueprint", default=False)

    @property
    def is_engram(self) -> bool:
        """True if this is an engram."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("bIsEngram", default=False)

    @property
    def is_equipped(self) -> bool:
        """True if currently equipped."""
        if not self._game_object:
            return False
        return self._game_object.get_property_value("bIsEquipped", default=False)

    @property
    def stat_values(self) -> list[int]:
        """
        Item stat values (for armor, weapons, etc.).

        Returns:
            List of stat modifier values.
        """
        if not self._game_object:
            return []
        values = []
        for i in range(8):
            val = self._game_object.get_property_value("ItemStatValues", index=i, default=0)
            values.append(int(val) if val else 0)
        return values

    @property
    def crafting_skill_bonus(self) -> float:
        """Crafting skill bonus applied during crafting."""
        if not self._game_object:
            return 0.0
        val = self._game_object.get_property_value("CraftingSkillBonusMultiplier", default=0.0)
        return float(val) if val else 0.0

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
        """Convert to dictionary."""
        result: dict[str, t.Any] = {
            "class_name": self.class_name,
            "guid": self.guid,
            "quantity": self.quantity,
            "quality": self.quality,
            "quality_name": self.quality_name,
            "is_blueprint": self.is_blueprint,
        }
        if self.name:
            result["name"] = self.name
        if self.durability:
            result["durability"] = self.durability
        return result

    def __repr__(self) -> str:
        name = self.name or self.class_name
        if self.quantity > 1:
            return f"Item({name!r}, quantity={self.quantity})"
        return f"Item({name!r})"
