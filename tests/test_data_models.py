from arkparser.data_models import CryopodCreature


def test_cryopod_stats_use_current_torpidity() -> None:
    cryo = CryopodCreature(
        current_stats={"Torpidity": 12.5},
        max_stats={"Torpidity": 42.0},
    )

    stats = cryo.stats

    assert stats.torpidity == 12.5
    assert stats.max_torpidity == 42.0


def test_cryopod_stats_default_percentages_match_dino_defaults() -> None:
    stats = CryopodCreature().stats

    assert stats.melee_damage == 100.0
    assert stats.movement_speed == 100.0
    assert stats.crafting_skill == 100.0
