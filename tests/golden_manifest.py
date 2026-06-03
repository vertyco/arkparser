"""Golden-manifest helpers shared by ``gen_golden.py`` and the golden tests.

A *manifest* is a compact, deterministic fingerprint of a full ``export_all``
run for one save. It captures, per ``ASV_*`` dataset: the record count, the
sorted union of every field key seen, and a SHA-256 over the canonical,
**order-independent** serialization of the records. Two runs of a
content-equivalent parser produce byte-identical manifests regardless of the
order records happen to be emitted in. That is exactly the guarantee a streaming /
chunked refactor needs (it may legitimately reorder records, but must never
change their content, field set, or count).

This module is a test helper, not a parser hot path: Pythonic style wins here
(see CLAUDE.md "When a rule conflicts with Pythonic style").

Pre/postconditions
------------------
- ``canonical_record`` : in = one export record dict; out = a stable str. Pure.
- ``dataset_manifest``  : in = list[dict]; out = {count, keys, sha256}. Pure.
- ``build_manifest``    : in = loaded save-like + map_config; out = full manifest
  dict. Performs the real ``export_all`` (cluster excluded for determinism).
"""

from __future__ import annotations

import hashlib
import json
import typing as t
from pathlib import Path

# Bounds (Power-of-10 rule 2: every loop statically bounded).
MAX_DATASETS = 32
MAX_RECORDS = 50_000_000


def canonical_record(record: dict[str, t.Any]) -> str:
    """Serialize one export record to a stable canonical string.

    ``sort_keys`` makes key order irrelevant; ``default=str`` mirrors the
    exporter's own JSON writer so values serialize identically to the files.
    """
    assert isinstance(record, dict), "record must be a dict"
    out = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
    assert out, "canonical serialization produced empty string"
    return out


def dataset_manifest(records: list[dict[str, t.Any]]) -> dict[str, t.Any]:
    """Fingerprint one dataset: count + sorted key union + order-independent hash."""
    assert isinstance(records, list), "records must be a list"
    assert len(records) < MAX_RECORDS, "record stream exceeded bound"
    keys: set[str] = set()
    lines: list[str] = [None] * len(records)  # type: ignore[list-item]
    for i, rec in enumerate(records):
        assert i < MAX_RECORDS, "record index exceeded bound"
        keys.update(rec.keys())
        lines[i] = canonical_record(rec)
    lines.sort()
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    result = {"count": len(records), "keys": sorted(keys), "sha256": digest}
    assert result["count"] == len(records), "count mismatch post-build"
    return result


def build_manifest(
    save: t.Any,
    map_config: t.Any,
    target: str,
    object_count: int,
) -> dict[str, t.Any]:
    """Run ``export_all`` (no cluster) and reduce it to a manifest.

    ``object_count`` is passed in (not read off ``save``) so callers control
    which counter they trust; it is recorded for drift visibility only.
    """
    from arkparser import export_all  # local import: helper, not hot path

    assert isinstance(target, str) and target, "target label required"
    assert object_count >= 0, "object_count must be non-negative"
    payload = export_all(save, map_config, cluster=None)
    assert len(payload) <= MAX_DATASETS, "dataset count exceeded bound"
    datasets = {
        name: dataset_manifest(list(records))
        for name, records in sorted(payload.items())
    }
    return {"target": target, "object_count": object_count, "datasets": datasets}


def load_manifest(path: Path) -> dict[str, t.Any] | None:
    """Read a manifest file, or ``None`` if absent."""
    assert isinstance(path, Path), "path must be a Path"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and "datasets" in data, "malformed manifest"
    return data


def write_manifest(path: Path, manifest: dict[str, t.Any]) -> None:
    """Write a manifest as pretty JSON (diff-friendly in git)."""
    assert isinstance(manifest, dict) and "datasets" in manifest, "bad manifest"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def diff_manifest(
    expected: dict[str, t.Any], actual: dict[str, t.Any]
) -> list[str]:
    """Return human-readable mismatch lines; empty list == identical content.

    Ignores ``object_count`` (informational only, a parse-graph internal counter
    that may shift without changing exported content).
    """
    assert "datasets" in expected and "datasets" in actual, "bad manifests"
    problems: list[str] = []
    exp_ds, act_ds = expected["datasets"], actual["datasets"]
    for name in sorted(set(exp_ds) | set(act_ds)):
        if name not in exp_ds:
            problems.append(f"{name}: present now, absent in golden")
            continue
        if name not in act_ds:
            problems.append(f"{name}: missing (golden has it)")
            continue
        e, a = exp_ds[name], act_ds[name]
        if e["count"] != a["count"]:
            problems.append(f"{name}.count: golden {e['count']} != now {a['count']}")
        if e["keys"] != a["keys"]:
            added = sorted(set(a["keys"]) - set(e["keys"]))
            removed = sorted(set(e["keys"]) - set(a["keys"]))
            problems.append(f"{name}.keys: +{added} -{removed}")
        if e["sha256"] != a["sha256"]:
            problems.append(
                f"{name}.sha256: content drift (golden {e['sha256'][:12]} "
                f"!= now {a['sha256'][:12]})"
            )
    return problems
