#!/usr/bin/env python3
"""Adapt integration Kibana dashboard JSON for older Stack (e.g. 8.12).

Usage:
  python3 adapt_kibana_dashboards.py <kit-kibana-dir> --stack-version 8.12.1

Rewrites in place: dashboard/*.json and regenerates import.ndjson if present
(index-pattern lines first, then other saved objects).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_version(v: str) -> tuple[int, int, int]:
    parts = (v or "0.0.0").split(".")
    nums = []
    for p in parts[:3]:
        try:
            nums.append(int("".join(c for c in p if c.isdigit()) or "0"))
        except ValueError:
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return nums[0], nums[1], nums[2]


def fix_lens_state_for_812(state: dict) -> bool:
    """Lens XY terms with otherBucket:true builds phrase filters; on some 8.12
    data views that surfaces as:
      [layeredXyVis] > [esaggs] > The "<field>" field can not be used for filtering.
    Disable otherBucket and includeEmptyRows when a terms split is present.
    """
    if not isinstance(state, dict):
        return False
    changed = False
    layers = (
        state.get("datasourceStates", {})
        .get("formBased", {})
        .get("layers", {})
    )
    for layer in layers.values():
        cols = layer.get("columns") or {}
        has_terms = any(c.get("operationType") == "terms" for c in cols.values())
        for col in cols.values():
            if col.get("operationType") == "terms":
                params = col.setdefault("params", {})
                if params.get("otherBucket") is True:
                    params["otherBucket"] = False
                    changed = True
            if has_terms and col.get("operationType") == "date_histogram":
                params = col.setdefault("params", {})
                if params.get("includeEmptyRows") is True:
                    params["includeEmptyRows"] = False
                    changed = True
    state.setdefault("adHocDataViews", {})
    state.setdefault("internalReferences", [])
    return changed


def adapt_dashboard_obj(dash: dict, stack: tuple[int, int, int]) -> bool:
    attrs = dash.get("attributes") or {}
    raw = attrs.get("panelsJSON")
    if not raw:
        return False
    panels = json.loads(raw) if isinstance(raw, str) else raw
    changed = False
    if stack < (8, 13, 0):
        for p in panels:
            if p.get("type") != "lens":
                continue
            attrs_p = (p.get("embeddableConfig") or {}).get("attributes") or {}
            state = attrs_p.get("state")
            if isinstance(state, dict) and fix_lens_state_for_812(state):
                attrs_p["state"] = state
                changed = True
    if changed:
        attrs["panelsJSON"] = json.dumps(panels, separators=(",", ":"))
        dash["attributes"] = attrs
    return changed


def rebuild_import_ndjson(kibana_dir: Path) -> None:
    ndjson = kibana_dir / "import.ndjson"
    if not ndjson.exists():
        return
    lines = [ln for ln in ndjson.read_text().splitlines() if ln.strip()]
    by_id = {}
    order = []
    for ln in lines:
        obj = json.loads(ln)
        oid = obj.get("id")
        by_id[oid] = ln
        order.append(oid)

    for path in sorted((kibana_dir / "dashboard").glob("*.json")):
        dash = json.loads(path.read_text())
        oid = dash.get("id") or path.stem
        so = {
            "attributes": dash["attributes"],
            "coreMigrationVersion": dash.get("coreMigrationVersion", "8.8.0"),
            "created_at": dash.get("created_at", "2024-01-01T00:00:00.000Z"),
            "id": oid,
            "managed": False,
            "references": dash.get("references") or json.loads(by_id.get(oid, "{}")).get("references", []),
            "type": "dashboard",
            "typeMigrationVersion": dash.get("typeMigrationVersion", "8.9.0"),
        }
        # Prefer references from existing ndjson line
        if oid in by_id:
            old = json.loads(by_id[oid])
            if old.get("references"):
                so["references"] = old["references"]
        by_id[oid] = json.dumps(so, separators=(",", ":"))

    header = [by_id[i] for i in order if json.loads(by_id[i]).get("type") == "index-pattern"]
    body = [by_id[i] for i in order if json.loads(by_id[i]).get("type") != "index-pattern"]
    ndjson.write_text("\n".join(header + body) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("kibana_dir", type=Path)
    ap.add_argument("--stack-version", required=True)
    args = ap.parse_args()
    stack = parse_version(args.stack_version)
    kibana_dir = args.kibana_dir
    dash_dir = kibana_dir / "dashboard"
    if not dash_dir.is_dir():
        print(f"no dashboard dir: {dash_dir}", file=sys.stderr)
        return 1
    n = 0
    for path in sorted(dash_dir.glob("*.json")):
        dash = json.loads(path.read_text())
        if adapt_dashboard_obj(dash, stack):
            path.write_text(json.dumps(dash, indent=2) + "\n")
            n += 1
            print(f"adapted {path.name}")
    rebuild_import_ndjson(kibana_dir)
    print(f"done: {n} dashboard file(s) changed for stack {args.stack_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
