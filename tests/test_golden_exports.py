"""Golden export regression tests: the safety net for the streaming refactor.

For every local save fixture present on this machine, re-run ``export_all`` and
assert the resulting manifest (per-dataset count + field-key union + content
hash) exactly matches the committed golden in ``tests/golden/``. Any change to
record count, field set, or record content fails loudly with a readable diff.

Behaviour when something is missing:

- save absent  → test skips (fixtures are large, not committed).
- golden absent → test skips with a hint to run ``gen_golden.py``, UNLESS the
  env var ``ARKPARSER_UPDATE_GOLDEN=1`` is set, in which case the golden is
  generated in place (first-run bootstrap) and the test passes.

The hash is order-independent (records are sorted before hashing), so a
chunked/streaming rewrite that emits records in a different order still passes
as long as the *content* is identical, which is exactly the refactor's
contract.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from .golden_manifest import (
    build_manifest,
    diff_manifest,
    load_manifest,
    write_manifest,
)
from .golden_targets import GOLDEN_DIR, discover_targets, load_target

_TARGETS = discover_targets()
_UPDATE = os.environ.get("ARKPARSER_UPDATE_GOLDEN") == "1"


def _ids() -> list[str]:
    return [name for name, _ in _TARGETS]


@pytest.mark.skipif(not _TARGETS, reason="no local save fixtures present")
@pytest.mark.parametrize(("name", "ark_path"), _TARGETS, ids=_ids())
def test_export_matches_golden(name: str, ark_path: Path) -> None:
    if not ark_path.exists():
        pytest.skip(f"save fixture absent: {ark_path}")

    golden_path = GOLDEN_DIR / f"{name}.json"
    golden = load_manifest(golden_path)
    if golden is None and not _UPDATE:
        pytest.skip(
            f"no golden for {name}; run "
            f"`python references/scripts/gen_golden.py {name}` "
            f"or set ARKPARSER_UPDATE_GOLDEN=1"
        )

    save, map_config, obj_count = load_target(ark_path)
    actual = build_manifest(save, map_config, name, obj_count)

    if golden is None:  # bootstrap path
        write_manifest(golden_path, actual)
        pytest.skip(f"generated golden for {name} (bootstrap)")

    problems = diff_manifest(golden, actual)
    assert not problems, f"export drift for {name}:\n  " + "\n  ".join(problems)


def test_at_least_one_target_discovered() -> None:
    """Sanity guard: the discovery logic finds *something* on a dev machine.

    Skips (not fails) when no fixtures exist so CI without saves stays green.
    """
    if not _TARGETS:
        pytest.skip("no fixtures on this machine")
    assert all(p.suffix == ".ark" for _, p in _TARGETS), "non-.ark target discovered"
    assert len({n for n, _ in _TARGETS}) == len(_TARGETS), "duplicate target names"
