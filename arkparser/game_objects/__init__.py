"""
ARK Game Objects.

This module provides classes for representing game objects from ARK save files.

Game objects are the fundamental entities - creatures, items, structures, players,
and other game entities.

Usage:
    from arkparser.game_objects import GameObject, GameObjectContainer, LocationData

    # Read objects from binary
    objects = read_object_list(reader, is_asa=False)

    # Create a container for lookup
    container = GameObjectContainer(objects=objects)
    container.build_relationships()

    # Find creatures
    creatures = container.get_creatures()
"""

from .container import GameObjectContainer
from .game_object import GameObject, read_object_list
from .location import LocationData

__all__ = [
    "LocationData",
    "GameObject",
    "GameObjectContainer",
    "read_object_list",
]
