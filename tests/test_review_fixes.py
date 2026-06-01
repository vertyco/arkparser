"""Regression tests for the code-review fix batch (fixture-free, pure logic).

Each test pins a specific reviewed defect so it cannot silently regress:
  #1  tamer blanked when a creature is imprinted
  #2  inf/nan floats never reach JSON (strict-parser safe)
  #5  in-world cryo/vivarium id negated; dinoid stays positive
  #13 read_string bounds-checks the length==1 / length==-1 fast paths
  #15 read_object_list rejects an absurd (corrupt-header) object count
"""

import json
import types

import pytest

from arkparser.common.binary_reader import BinaryReader
from arkparser.common.exceptions import CorruptDataError, EndOfDataError
from arkparser.common.normalization import normalize_indexed_list
from arkparser.data_models import UploadedCreature, UploadedItem
from arkparser.export import (
    _SyntheticGameObject,
    _dino_id_str,
    _float,
    _gps_payload,
    _structure_dict,
    _tamed_dict,
    _wild_dict,
)
from arkparser.files.world_save import _checked_count
from arkparser.game_objects.game_object import MAX_OBJECT_COUNT, read_object_list
from arkparser.properties.compound import _read_array_elements


def _status() -> _SyntheticGameObject:
    return _SyntheticGameObject("DinoCharacterStatusComponent_BP_C", {})


# --- #2: finite floats only -------------------------------------------------

def test_float_coerces_non_finite_to_default() -> None:
    assert _float(float("inf")) == 0.0
    assert _float(float("-inf")) == 0.0
    assert _float(float("nan")) == 0.0
    assert _float(float("inf"), default=1.5) == 1.5
    # finite values pass through unchanged
    assert _float(3.25) == 3.25
    assert _float(0.0) == 0.0


def test_gps_payload_is_strict_json_safe() -> None:
    loc = types.SimpleNamespace(x=float("inf"), y=float("nan"), z=-float("inf"))
    # _gps_payload only reads ``obj.location``; a namespace stand-in is enough.
    obj = types.SimpleNamespace(location=loc)
    payload = _gps_payload(obj, None)
    # No NaN/Infinity tokens survive — strict parsers (JS, Pydantic) reject them.
    text = json.dumps(payload)
    assert "Infinity" not in text and "NaN" not in text
    json.loads(text, parse_constant=lambda tok: pytest.fail(f"non-finite: {tok}"))
    assert payload["ccc"] == "0.0 0.0 0.0"


# --- #1: tamer blanked on imprint ------------------------------------------

def test_tamed_dict_blanks_tamer_when_imprinted_by_player_id() -> None:
    actor = _SyntheticGameObject(
        "Dodo_C", {"TamerString": "Bob", "ImprinterPlayerDataID": 42}
    )
    rec = _tamed_dict(actor, _status(), {}, None)
    assert rec["tamer"] == ""
    assert rec["imprinter_player_id"] == 42


def test_tamed_dict_blanks_tamer_when_imprinter_name_present() -> None:
    actor = _SyntheticGameObject(
        "Dodo_C", {"TamerString": "Bob", "ImprinterName": "Alice"}
    )
    rec = _tamed_dict(actor, _status(), {}, None)
    assert rec["tamer"] == ""
    assert rec["imprinter"] == "Alice"


def test_tamed_dict_keeps_tamer_when_not_imprinted() -> None:
    actor = _SyntheticGameObject("Dodo_C", {"TamerString": "Bob"})
    rec = _tamed_dict(actor, _status(), {}, None)
    assert rec["tamer"] == "Bob"


# --- #5: cryo/vivarium id negation (dinoid stays positive) ------------------

def test_tamed_dict_negates_id_when_stored() -> None:
    actor = _SyntheticGameObject("Dodo_C", {"DinoID1": 100, "DinoID2": 200})
    live = _tamed_dict(actor, _status(), {}, None, stored=False)
    stored = _tamed_dict(actor, _status(), {}, None, stored=True)
    assert live["id"] > 0
    assert stored["id"] == -live["id"]
    # dinoid is the stable positive identity in BOTH cases (legacy parity).
    assert stored["dinoid"] == live["dinoid"]
    assert not stored["dinoid"].startswith("-")


def test_tamed_dict_negates_id_via_is_in_cryo_prop() -> None:
    actor = _SyntheticGameObject(
        "Dodo_C", {"DinoID1": 1, "DinoID2": 2, "IsInCryo": True}
    )
    rec = _tamed_dict(actor, _status(), {}, None)
    assert rec["id"] < 0
    assert not rec["dinoid"].startswith("-")


def test_tamed_dict_zero_id_not_negated() -> None:
    actor = _SyntheticGameObject("Dodo_C", {"DinoID1": 0, "DinoID2": 0})
    rec = _tamed_dict(actor, _status(), {}, None, stored=True)
    assert rec["id"] == 0


# --- #13: read_string fast-path bounds checks -------------------------------

def test_read_string_len1_truncated_raises() -> None:
    # length prefix == 1 (single null byte) but no byte follows it.
    reader = BinaryReader.from_bytes((1).to_bytes(4, "little"))
    with pytest.raises(EndOfDataError):
        reader.read_string()


def test_read_string_utf16_null_truncated_raises() -> None:
    # length prefix == -1 (UTF-16 null, needs 2 bytes) but none follow.
    reader = BinaryReader.from_bytes((-1).to_bytes(4, "little", signed=True))
    with pytest.raises(EndOfDataError):
        reader.read_string()


def test_read_string_len1_valid_roundtrips() -> None:
    # Happy path still works: prefix 1 + the null byte present -> "".
    reader = BinaryReader.from_bytes((1).to_bytes(4, "little") + b"\x00")
    assert reader.read_string() == ""


# --- #15: object-count sanity bound -----------------------------------------

def test_read_object_list_rejects_absurd_count() -> None:
    # 0xFFFFFFFF as uint32 is far above MAX_OBJECT_COUNT (a misaligned header).
    reader = BinaryReader.from_bytes(b"\xff\xff\xff\xff")
    with pytest.raises(CorruptDataError):
        read_object_list(reader, is_asa=False)


def test_read_object_list_zero_count_ok() -> None:
    reader = BinaryReader.from_bytes((0).to_bytes(4, "little"))
    assert read_object_list(reader, is_asa=False) == []
    assert MAX_OBJECT_COUNT > 1_000_000


# --- code-review (max): tamed `traits` shape is legacy object-list -----------

def test_tamed_traits_emitted_as_objects() -> None:
    # Legacy ASVExport emits tamed traits as [{"trait": <class>}], not [str]
    # (ContentPack.cs:723-735).
    actor = _SyntheticGameObject(
        "Dodo_C", {"CreatureTraits": ["Rabid_Tier1", "Aggressive_Tier2"]}
    )
    rec = _tamed_dict(actor, _status(), {}, None)
    assert rec["traits"] == [{"trait": "Rabid_Tier1"}, {"trait": "Aggressive_Tier2"}]


def test_tamed_traits_empty_list_when_absent() -> None:
    rec = _tamed_dict(_SyntheticGameObject("Dodo_C", {}), _status(), {}, None)
    assert rec["traits"] == []


# --- code-review (max): ASE/ASA `dinoid` string form ------------------------

def test_tamed_dinoid_ase_is_decimal_concat() -> None:
    # ASE (save absent -> is_asa False): str(DinoID1) + str(DinoID2).
    actor = _SyntheticGameObject("Dodo_C", {"DinoID1": 475230717, "DinoID2": 97170314})
    rec = _tamed_dict(actor, _status(), {}, None)
    assert rec["dinoid"] == "47523071797170314"


def test_tamed_dinoid_asa_is_combined_id() -> None:
    # ASA: decimal of the combined 64-bit id (== the positive `id`).
    actor = _SyntheticGameObject("Dodo_C", {"DinoID1": 475230717, "DinoID2": 97170314})
    save = types.SimpleNamespace(is_asa=True)
    rec = _tamed_dict(actor, _status(), {}, None, save=save)
    assert rec["dinoid"] == "2041100387666801546"
    assert rec["dinoid"] == str(rec["id"])


def test_wild_dinoid_ase_vs_asa() -> None:
    obj = _SyntheticGameObject("Raptor_C", {"DinoID1": 475230717, "DinoID2": 97170314})
    assert _wild_dict(obj, _status(), None, False)["dinoid"] == "47523071797170314"
    assert _wild_dict(obj, _status(), None, True)["dinoid"] == "2041100387666801546"


def test_dino_id_str_ase_halves_are_signed_int32() -> None:
    # ASE concat reinterprets each uint32 half as signed int32 (matches C#
    # GetPropertyValue<int>); both-zero collapses to "0" not "00".
    assert _dino_id_str(0x90000000, 5, is_asa=False) == "-18790481925"
    assert _dino_id_str(0, 0, is_asa=False) == "0"
    assert _dino_id_str(0, 0, is_asa=True) == "0"


# --- code-review (max): maturation newborn default --------------------------

def test_tamed_maturation_newborn_is_zero() -> None:
    # A baby with no BabyAge is a newborn -> "0" (legacy default), not "100".
    baby = _SyntheticGameObject("Dodo_C", {"bIsBaby": True})
    assert _tamed_dict(baby, _status(), {}, None)["maturation"] == "0"


def test_tamed_maturation_adult_is_hundred() -> None:
    adult = _SyntheticGameObject("Dodo_C", {})
    assert _tamed_dict(adult, _status(), {}, None)["maturation"] == "100"


# --- code-review (max): structure `created` is "" not null ------------------

def test_structure_created_empty_string_when_no_anchor() -> None:
    # Legacy CreatedDateTime is DateTime? -> interpolates to "" (never null).
    struct = _SyntheticGameObject("Wall_C", {})
    # _structure_dict now takes a tribe_names map (resolved owning-tribe names).
    assert _structure_dict(struct, None, {}, None, {})["created"] == ""


# --- code-review (max): non-finite floats never crash strict JSON -----------

def test_uploaded_item_nan_rating_is_legacy_sentinel() -> None:
    item = UploadedItem.from_ark_data(
        {"ArkTributeItem": {"ItemRating": float("nan"), "ItemDurability": float("inf")}}
    )
    assert item.rating == 0.0001  # legacy ContentItem.cs:62 substitution
    assert item.durability == 0.0
    json.dumps(item.to_dict())  # strict serialization must not raise


def test_uploaded_creature_nan_experience_zeroed() -> None:
    c = UploadedCreature.from_ark_data({"DinoExperiencePoints": float("nan")})
    assert c.experience == 0.0


# --- code-review (max): ASE byte-array enum-name discriminator (C1) ----------

def test_byte_array_raw_uint8_path_bytes() -> None:
    # data_size == count+4 -> raw uint8 array. Since 0.5.2 the raw path returns
    # a single bytes blob (lighter than list[int]); the no-drift invariant
    # (reader fully consumed) is what this guards.
    reader = BinaryReader.from_bytes(b"\x0a\x14\x1e")
    vals = _read_array_elements(reader, "ByteProperty", 3, 3 + 4, "Foo", False, None)
    assert vals == bytes([10, 20, 30])
    assert isinstance(vals, bytes)
    assert reader.remaining == 0


def test_normalize_indexed_list_expands_bytes_to_ints() -> None:
    # Regression: once raw ByteProperty arrays became `bytes` (0.5.2), element
    # consumers that iterate them (tribe MembersRankGroups -> int(rank)) blew up
    # because normalize_indexed_list wrapped the blob as [b'...'] instead of
    # exposing its ints. A bytes value must normalize to a list of ints.
    assert normalize_indexed_list(bytes([0, 2, 5])) == [0, 2, 5]
    assert normalize_indexed_list(b"") == []
    assert [int(r) for r in normalize_indexed_list(b"\x00")] == [0]


def test_byte_array_enum_name_path_no_drift() -> None:
    # data_size > count+4 -> 8-byte name refs, not 1-byte uint8 (would drift).
    def _ref(index: int, instance: int) -> bytes:
        return index.to_bytes(4, "little") + instance.to_bytes(4, "little")

    reader = BinaryReader.from_bytes(_ref(1, 0) + _ref(2, 0))
    vals = _read_array_elements(reader, "ByteProperty", 2, 2 * 8 + 4, "Colors", False, ["Foo", "Bar"])
    assert vals == ["Foo", "Bar"]
    assert reader.remaining == 0  # consumed 8 bytes/elem -> no cursor drift


# --- code-review (max): corrupt count caps survive python -O (D1/D2) ---------

def test_checked_count_rejects_absurd_and_negative() -> None:
    absurd = BinaryReader.from_bytes((MAX_OBJECT_COUNT + 1).to_bytes(4, "little"))
    with pytest.raises(CorruptDataError):
        _checked_count(absurd, "test")
    negative = BinaryReader.from_bytes((-1).to_bytes(4, "little", signed=True))
    with pytest.raises(CorruptDataError):
        _checked_count(negative, "test")


def test_checked_count_accepts_valid() -> None:
    assert _checked_count(BinaryReader.from_bytes((42).to_bytes(4, "little")), "test") == 42
