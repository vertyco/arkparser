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
from arkparser.export import _SyntheticGameObject, _float, _gps_payload, _tamed_dict
from arkparser.game_objects.game_object import MAX_OBJECT_COUNT, read_object_list


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
