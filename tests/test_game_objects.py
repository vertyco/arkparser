"""Tests for game object container and property-list serialization."""

from arkparser.game_objects.container import GameObjectContainer
from arkparser.game_objects.game_object import GameObject
from arkparser.properties.primitives import IntProperty, StrProperty
from arkparser.structs.property_list import StructPropertyList


class TestGameObjectContainer:
    """Tests for top-level creature filtering."""

    def test_get_creatures_excludes_status_and_inventory_components(self) -> None:
        container = GameObjectContainer(
            objects=[
                GameObject(class_name="Archa_Character_BP_C"),
                GameObject(class_name="DinoCharacterStatusComponent_BP_Archa_C"),
                GameObject(class_name="DinoTamedInventoryComponent_Archa_C"),
                GameObject(class_name="PlayerPawnTest_Male_C"),
            ]
        )

        creatures = container.get_creatures()

        assert [obj.class_name for obj in creatures] == ["Archa_Character_BP_C"]


class TestStructPropertyList:
    """Tests for property-list serialization."""

    def test_to_dict_preserves_indexed_properties(self) -> None:
        struct = StructPropertyList(
            _struct_type="TestStruct",
            properties=[
                IntProperty(name="ColorSetIndices", index=0, _value=14),
                IntProperty(name="ColorSetIndices", index=2, _value=35),
                StrProperty(name="TamedName", _value="escobar"),
            ],
        )

        assert struct.to_dict() == {
            "ColorSetIndices": {0: 14, 2: 35},
            "TamedName": "escobar",
        }
