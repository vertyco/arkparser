"""Tests pinning ASA cryopod creature decode + export integration.

ARK strips the actor for every cryopodded / soultrapped / vivariumed /
dinoballed creature and embeds a serialised snapshot into the item's
``CustomItemDatas``. ``WorldSave.iter_cryopod_creatures`` walks these
items, and ``export_tamed`` then surfaces them as ``ASV_Tamed`` entries
with ``cryo=True``. Two regressions tested here:

- ASA cryopod blobs carry 11 current stats (no CraftingSkill in the
  current block), 11 max stats, and 14 extras (36 floats total). The
  pre-0.3.3 parser walked 12 names against an 11-wide block, leaking
  ``max[0]`` (Health) into ``current_stats["CraftingSkill"]`` and
  surfacing ``hp == craft`` on every cryopod tame.
- ``from_asa_cryopod_data`` did not populate ``creature_props`` /
  ``status_props``; the ``_SyntheticGameObject`` adapter the exporter
  uses then saw empty dicts and emitted records with ``lvl=1``,
  ``name=""``, all-zero colors, and ``current_stats: null``.
"""

from __future__ import annotations

import typing as t

from arkparser.data_models import CryopodCreature
from arkparser.export import export_tamed
from arkparser.game_objects.location import LocationData


def _asa_blob(current: list[float], max_: list[float]) -> dict[str, object]:
    """Synthesise the smallest ASA cryopod CustomItemDatas entry we can.

    36 floats total: 11 current + 11 max + 14 extras (zeros).
    """
    assert len(current) == 11
    assert len(max_) == 11
    floats = current + max_ + [0.0] * 14
    return {
        "CustomDataName": "Dino",
        "CustomDataStrings": [
            "Argent_Character_BP_C_2094073921",  # [0] class_name
            "dada - Lvl 259 (Argentavis)",       # [1] display
            "37,0,37,0,0,0,",                    # [2] colors
            "", "", "", "", "", "", "Argentavis",  # [9] species
        ],
        "CustomDataFloats": floats,
        "CustomDataNames": [],
    }


def test_asa_cryopod_eleven_current_stats_does_not_leak_max_into_craft() -> None:
    """ASA cryopod blob: current[0..10] then max[0..10]. craft must come
    from current[11], which does not exist, so it must stay 0.0, NOT pick
    up max[0]."""
    current = [6206.46, 2411.2, 0.0, 750.0, 13153.03, 100.0, 0.0, 63.6, 6.69, 0.09, 0.0]
    max_ = [6206.46, 2411.2, 0.0, 750.0, 13153.03, 100.0, 0.0, 63.6, 6.69, 0.09, 0.0]
    cryo = CryopodCreature.from_asa_cryopod_data(_asa_blob(current, max_))
    assert cryo is not None
    assert "Health" in cryo.current_stats
    assert cryo.current_stats["Health"] == 6206.46
    # CraftingSkill must NOT be in current_stats on ASA cryopods (only
    # 11 slots are populated). Pre-0.3.3 set it equal to max[0]=Health.
    assert "CraftingSkill" not in cryo.current_stats
    # Max block round-trips properly
    assert cryo.max_stats["Health"] == 6206.46


def test_asa_cryopod_populates_creature_and_status_props() -> None:
    """The exporter adapter (``_SyntheticGameObject``) reads via
    ``get_property_value`` keyed by ARK property name + index suffix. The
    ASA cryopod decoder must mirror those keys into ``creature_props`` /
    ``status_props`` so the synthetic adapter surfaces tamed-name, level,
    colors, and CurrentStatusValues per stat index."""
    current = [3000.0, 800.0, 0.0, 500.0, 5000.0, 100.0, 0.0, 200.0, 2.5, 0.05, 0.0]
    max_ = [3000.0] * 11
    cryo = CryopodCreature.from_asa_cryopod_data(_asa_blob(current, max_))
    assert cryo is not None

    # TamedName from display-name parse
    assert cryo.creature_props.get("TamedName") == "dada"
    # Level from display-name parse
    assert cryo.status_props.get("BaseCharacterLevel") == 259
    # Colors at expected indices (first non-zero is c0=37, then c2=37)
    assert cryo.creature_props.get("ColorSetIndices") == 37
    assert cryo.creature_props.get("ColorSetIndices_2") == 37
    # CurrentStatusValues indexed by EPrimalCharacterStatusValue
    # 0=Health, 1=Stamina, 3=Oxygen, 4=Food, 7=Weight, 8=MeleeDamage
    assert cryo.status_props.get("CurrentStatusValues") == 3000.0      # health
    assert cryo.status_props.get("CurrentStatusValues_1") == 800.0     # stam
    assert cryo.status_props.get("CurrentStatusValues_4") == 5000.0    # food
    assert cryo.status_props.get("CurrentStatusValues_7") == 200.0     # weight
    assert cryo.status_props.get("CurrentStatusValues_8") == 2.5       # melee


def test_asa_cryopod_display_name_parses_level_and_species() -> None:
    """Display-name format ``"Name - Lvl N (Species)"`` must yield all three."""
    cryo = CryopodCreature.from_asa_cryopod_data(_asa_blob([0.0] * 11, [0.0] * 11))
    assert cryo is not None
    assert cryo.name == "dada"
    assert cryo.level == 259
    # Species comes from strings[9] when present, falling back to display parse
    assert cryo.species == "Argentavis"


class FakeObject:
    """Minimal GameObject stand-in for exporter graph tests."""

    def __init__(
        self,
        obj_id: int,
        class_name: str,
        props: dict[str, t.Any] | None = None,
        location: LocationData | None = None,
        is_item: bool = False,
    ) -> None:
        self.id = obj_id
        self.guid = ""
        self.names: list[str] = []
        self.class_name = class_name
        self.location = location
        self.is_item = is_item
        self.properties: list[t.Any] = []
        self.components: dict[str, t.Any] = {}
        self.props = props or {}

    def get_property_value(self, name: str, default: t.Any = None, index: int | None = None) -> t.Any:
        key = name if not index else f"{name}_{index}"
        val = self.props.get(key)
        return default if val is None else val


class FakeSave:
    """Save stand-in exposing just what export_tamed needs."""

    is_asa = True

    def __init__(self, objects: list[FakeObject], cryos: list[tuple[FakeObject, CryopodCreature]]) -> None:
        self.objects = objects
        self.cryos = cryos

    def get_tamed_creatures(self) -> list[FakeObject]:
        return []

    def iter_cryopod_creatures(self) -> t.Iterator[tuple[FakeObject, CryopodCreature]]:
        yield from self.cryos


def test_cryopod_inherits_owning_container_location() -> None:
    """ASA cryopod items live in inventories, not the world: they carry no
    actor transform, so ``item_obj.location`` is None. The exported record
    must fall back to the owning container's (cryofridge / pawn) location
    instead of emitting 0/0/0."""
    fridge = FakeObject(
        10,
        "CryoFridge_C",
        props={
            "MyInventoryComponent": (None, 11),
            "TargetingTeam": 1500000001,
            "TribeName": "Frisky Dingo",
        },
        location=LocationData(x=10000.0, y=-20000.0, z=300.0),
    )
    inventory = FakeObject(11, "PrimalInventoryBP_C", props={"InventoryItems": [(None, 12)]})
    pod = FakeObject(12, "PrimalItem_WeaponEmptyCryopod_C", is_item=True)
    cryo = CryopodCreature.from_asa_cryopod_data(_asa_blob([0.0] * 11, [0.0] * 11))
    assert cryo is not None
    save = FakeSave([fridge, inventory, pod], [(pod, cryo)])

    records = export_tamed(save, None)
    assert len(records) == 1
    record = records[0]
    assert record["cryo"] is True
    assert record["tribe"] == "Frisky Dingo"
    assert record["ccc"] == "10000.0 -20000.0 300.0"


def test_ase_cryopod_keeps_twelve_stat_layout() -> None:
    """ASE cryopod blobs carry 12 current stats + 12 max stats (25 floats).
    The ASA fix must not break the ASE path: walking all 12 names is the
    correct behaviour when ``len(floats) < 36``."""
    # 25 floats = 12 current + 12 max + 1 extra
    floats = [float(i + 1) for i in range(12)] + [float(i + 100) for i in range(12)] + [0.0]
    blob = {
        "CustomDataName": "Dino",
        "CustomDataStrings": [
            "Raptor_Character_BP_C", "Bluey - Lvl 30 (Raptor)", "0,0,0,0,0,0,",
        ],
        "CustomDataFloats": floats,
        "CustomDataNames": [],
    }
    cryo = CryopodCreature.from_asa_cryopod_data(blob)
    assert cryo is not None
    # All 12 current and 12 max should be populated on ASE blobs
    assert len(cryo.current_stats) == 12
    assert len(cryo.max_stats) == 12
    assert cryo.current_stats["Health"] == 1.0
    assert cryo.current_stats["CraftingSkill"] == 12.0
    assert cryo.max_stats["Health"] == 100.0
    assert cryo.max_stats["CraftingSkill"] == 111.0
