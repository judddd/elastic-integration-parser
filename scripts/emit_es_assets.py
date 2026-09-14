#!/usr/bin/env python3
"""Emit Fleet-equivalent Elasticsearch assets from an official integration package.

Source of truth: packages/<name>/data_stream/*/fields/*.yml and
data_stream/*/elasticsearch/ingest_pipeline/*.yml — the same files Fleet EPM
uses. Index/component templates are NOT stored as JSON in the EPR zip; Fleet
generates them at install. This script performs that generation so Beats can
run without Kibana Fleet.

Usage:
  python3 emit_es_assets.py <package-dir> <output-elasticsearch-dir> --stack-version 8.12.1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("Need PyYAML: pip install pyyaml\n")
    raise


SKIP_MAPPING_KEYS = {
    "description",
    "title",
    "example",
    "footnote",
    "group",
    "level",
    "required",
    "short",
    "normalize",
    "multi_fields",
    "pattern",
    "doc_values",
    "copy_to",
    "format",
    "unit",
    "metric_type",
    "dimension",
    "default",
    "external",
    "release",
    "ignore_above",
}


def parse_stack_version(s: str) -> tuple[int, int, int]:
    parts = str(s).strip().split(".")
    major = int(parts[0])
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int("".join(c for c in (parts[2] if len(parts) > 2 else "0") if c.isdigit()) or "0")
    return major, minor, patch


def ver_gte(have: tuple[int, int, int], need: tuple[int, int, int]) -> bool:
    return have >= need


def strip_tsds_mapping(node):
    if isinstance(node, dict):
        node.pop("time_series_dimension", None)
        node.pop("time_series_metric", None)
        for v in node.values():
            strip_tsds_mapping(v)
    elif isinstance(node, list):
        for v in node:
            strip_tsds_mapping(v)


def collect_dimension_paths(mapping: dict, prefix: str = "") -> list[str]:
    """Field paths with time_series_dimension: true — used as index.routing_path for TSDS.

    ES rejects component templates that set index.mode=time_series without a non-empty
    index.routing_path when mode lives on the component (each component must be valid alone).
    Fleet derives the same list from dimension fields.
    """
    out: list[str] = []
    props = mapping.get("properties") if isinstance(mapping, dict) else None
    if not isinstance(props, dict):
        return out
    for name, node in props.items():
        if not isinstance(node, dict):
            continue
        path = f"{prefix}.{name}" if prefix else name
        if node.get("time_series_dimension") is True:
            out.append(path)
        if "properties" in node:
            out.extend(collect_dimension_paths(node, path))
    return out


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def dotted_set(root: dict, dotted: str, leaf: dict) -> None:
    parts = [p for p in dotted.split(".") if p]
    cur = root
    for part in parts[:-1]:
        node = cur.setdefault(part, {})
        props = node.setdefault("properties", {})
        cur = props
    last = parts[-1]
    existing = cur.get(last)
    if existing and "properties" in existing and "properties" in leaf:
        existing["properties"].update(leaf["properties"])
        if "type" in leaf:
            existing.setdefault("type", leaf["type"])
        cur[last] = existing
    elif existing and "properties" in leaf:
        leaf_props = leaf["properties"]
        existing.setdefault("properties", {}).update(leaf_props)
        cur[last] = existing
    elif existing and "properties" not in existing and "properties" not in leaf:
        cur[last] = merge_field_leaf(existing, leaf)
    else:
        cur[last] = leaf


def field_leaf(spec: dict) -> dict:
    ftype = spec.get("type") or "keyword"
    if ftype == "group":
        return {"properties": {}}

    mapping: dict = {"type": ftype}
    is_dim = spec.get("dimension") is True
    # ES forbids ignore_above together with time_series_dimension (TSDS).
    # Never invent ignore_above on dimension fields; Fleet/elastic-package skip it too.
    if is_dim:
        mapping["time_series_dimension"] = True
    elif ftype == "keyword":
        if "ignore_above" in spec:
            mapping["ignore_above"] = spec["ignore_above"]
        else:
            mapping["ignore_above"] = 1024
    if spec.get("metric_type"):
        mapping["time_series_metric"] = spec["metric_type"]
    if ftype == "constant_keyword" and "value" in spec and spec["value"] is not None:
        mapping["value"] = spec["value"]
    if ftype == "scaled_float" and "scaling_factor" in spec:
        mapping["scaling_factor"] = spec["scaling_factor"]
    if spec.get("doc_values") is False:
        mapping["doc_values"] = False
    if spec.get("copy_to"):
        mapping["copy_to"] = spec["copy_to"]
    if spec.get("enabled") is False:
        mapping["enabled"] = False
    return mapping


def merge_field_leaf(existing: dict, incoming: dict) -> dict:
    """Merge two leaf field mappings. Dimension wins over ignore_above."""
    out = dict(existing)
    out.update(incoming)
    if out.get("time_series_dimension") is True:
        out.pop("ignore_above", None)
    return out


def sanitize_tsds_mapping(mapping: dict) -> None:
    """Strip illegal combos ES rejects on TSDS (safety net after field merges)."""
    props = mapping.get("properties") if isinstance(mapping, dict) else None
    if not isinstance(props, dict):
        return
    for node in props.values():
        if not isinstance(node, dict):
            continue
        if node.get("time_series_dimension") is True:
            node.pop("ignore_above", None)
            node.pop("normalizer", None)
        if "properties" in node:
            sanitize_tsds_mapping(node)


def ingest_fields(fields_list, properties: dict) -> None:
    if not fields_list:
        return
    for spec in fields_list:
        if not isinstance(spec, dict) or "name" not in spec:
            continue
        name = spec["name"]
        ftype = spec.get("type") or "keyword"
        if ftype == "group" or spec.get("fields"):
            child_props: dict = {}
            ingest_fields(spec.get("fields") or [], child_props)
            node: dict = {"properties": child_props}
            dotted_set(properties, name, node)
            continue
        dotted_set(properties, name, field_leaf(spec))


def stream_mapping(stream_dir: Path, ds_type: str, dataset: str) -> dict:
    properties: dict = {}
    fields_dir = stream_dir / "fields"
    if fields_dir.is_dir():
        for yml in sorted(fields_dir.glob("*.yml")):
            data = load_yaml(yml) or []
            if isinstance(data, dict):
                data = [data]
            ingest_fields(data, properties)
    # Fleet fills constant_keyword values from the data stream identity
    ds = properties.setdefault("data_stream", {}).setdefault("properties", {})
    if "type" in ds:
        ds["type"].setdefault("type", "constant_keyword")
        ds["type"]["value"] = ds_type
    if "dataset" in ds:
        ds["dataset"].setdefault("type", "constant_keyword")
        ds["dataset"]["value"] = dataset
    return {"properties": properties, "dynamic": True}


def pipeline_docs(stream_dir: Path) -> dict[str, dict]:
    out = {}
    pdir = stream_dir / "elasticsearch" / "ingest_pipeline"
    if not pdir.is_dir():
        return out
    for yml in sorted(pdir.glob("*.yml")):
        doc = load_yaml(yml) or {}
        if not isinstance(doc, dict):
            continue
        # ES ingest API does not want YAML document start metadata keys unknown to it
        allowed = {k: v for k, v in doc.items() if k in ("description", "processors", "on_failure", "version")}
        out[yml.stem] = allowed
    return out


def package_meta(pkg_dir: Path) -> tuple[str, str]:
    man = load_yaml(pkg_dir / "manifest.yml")
    return man["name"], str(man["version"])


def stream_manifest(stream_dir: Path) -> dict:
    return load_yaml(stream_dir / "manifest.yml") or {}


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def emit(pkg_dir: Path, out_dir: Path, stack_version: tuple[int, int, int]) -> None:
    pkg_name, pkg_ver = package_meta(pkg_dir)
    ds_root = pkg_dir / "data_stream"
    # Fleet composes ecs@mappings onto *integration* templates from 8.13.0.
    # The component exists from 8.9 on logs-*-* only — do not use it on 8.12 integration templates.
    include_ecs = ver_gte(stack_version, (8, 13, 0))
    tsds_ok = ver_gte(stack_version, (8, 7, 0))
    out_dir.mkdir(parents=True, exist_ok=True)

    streams = []
    for stream_dir in sorted(p for p in ds_root.iterdir() if p.is_dir()):
        man = stream_manifest(stream_dir)
        ds_type = man.get("type") or "logs"
        dataset = f"{pkg_name}.{stream_dir.name}"
        index_mode = (man.get("elasticsearch") or {}).get("index_mode")

        pipes = pipeline_docs(stream_dir)
        default_pipe = None
        for stem, body in pipes.items():
            # Fleet names: {type}-{dataset}-{packageVersion} for default.yml
            if stem == "default":
                es_name = f"{ds_type}-{dataset}-{pkg_ver}"
                default_pipe = es_name
            else:
                es_name = f"{ds_type}-{dataset}-{pkg_ver}-{stem}"
            dump(out_dir / "00_ingest_pipeline" / f"{es_name}.json", body)

        mapping = stream_mapping(stream_dir, ds_type, dataset)
        if not tsds_ok:
            strip_tsds_mapping(mapping)
        else:
            sanitize_tsds_mapping(mapping)
        settings: dict = {
            "index.default_pipeline": default_pipe or f"{ds_type}-{dataset}-{pkg_ver}",
        }
        if index_mode == "time_series" and tsds_ok:
            settings["index.mode"] = "time_series"
            # Required when index.mode is on the component template (ES validates each
            # component alone). Same dimension list Fleet would derive.
            dims = collect_dimension_paths(mapping)
            if not dims:
                raise SystemExit(
                    f"{dataset}: index_mode=time_series but no dimension fields in mapping"
                )
            settings["index.routing_path"] = dims
        elif index_mode == "time_series" and not tsds_ok:
            index_mode = None
        streams.append((stream_dir, ds_type, dataset, index_mode, man))

        package_component = {
            "template": {
                "settings": settings,
                "mappings": mapping,
            },
            "_meta": {
                "package": {"name": pkg_name, "version": pkg_ver},
                "managed_by": "elastic-integration-parser",
                "managed": True,
            },
        }
        dump(out_dir / "01_component_template" / f"{ds_type}-{dataset}@package.json", package_component)

        custom_component = {
            "template": {"settings": {}, "mappings": {"properties": {}}},
            "_meta": {
                "package": {"name": pkg_name},
                "managed_by": "elastic-integration-parser",
                "managed": False,
            },
        }
        dump(out_dir / "01_component_template" / f"{ds_type}-{dataset}@custom.json", custom_component)

        composed = []
        if include_ecs:
            composed.append("ecs@mappings")
        composed.extend(
            [
                f"{ds_type}-{dataset}@package",
                f"{ds_type}-{dataset}@custom",
            ]
        )
        index_template = {
            "priority": 200,
            "index_patterns": [f"{ds_type}-{dataset}-*"],
            "data_stream": {},
            "composed_of": composed,
            "ignore_missing_component_templates": [f"{ds_type}-{dataset}@custom"],
            "allow_auto_create": True,
            "_meta": {
                "package": {"name": pkg_name, "version": pkg_ver},
                "managed_by": "elastic-integration-parser",
                "managed": True,
            },
        }
        dump(out_dir / "02_index_template" / f"{ds_type}-{dataset}.json", index_template)

    manifest = {
        "package": pkg_name,
        "version": pkg_ver,
        "stack_version": ".".join(str(x) for x in stack_version),
        "compose_ecs_mappings": include_ecs,
        "tsds_enabled": tsds_ok,
        "order": [
            "PUT _ingest/pipeline/{name}  from 00_ingest_pipeline/",
            "PUT _component_template/{name}  from 01_component_template/ (@package then @custom)",
            "PUT _index_template/{name}  from 02_index_template/",
        ],
        "notes": [
            "ecs@mappings is composed only on Stack >= 8.13 (Fleet integration templates). 8.12 keeps ECS fields inside @package.",
            "Do this before starting Beats. Beats must not run setup.template.",
            "TSDS streams set index.mode=time_series on the @package component template.",
        ],
        "data_streams": [
            {
                "dataset": dataset,
                "type": ds_type,
                "index_mode": index_mode or "standard",
                "pattern": f"{ds_type}-{dataset}-*",
            }
            for _, ds_type, dataset, index_mode, _ in streams
        ],
    }
    dump(out_dir / "manifest.json", manifest)

    installer = r'''#!/usr/bin/env python3
"""Install parsed Elasticsearch assets. Run BEFORE starting Beats.

  export ES_URL=https://127.0.0.1:9200 ES_USER=elastic ES_PASSWORD=...
  python3 elasticsearch/install_assets.py

完成后用中文打印安装说明（装了哪些 pipeline / 模板 / 数据流）。
"""
from __future__ import annotations
import json, os, ssl, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path

root = Path(__file__).resolve().parent
base = os.environ.get("ES_URL", "https://127.0.0.1:9200").rstrip("/")
user = os.environ.get("ES_USER", "elastic")
password = os.environ.get("ES_PASSWORD", "")
# Match Beat output.elasticsearch.ssl.verification_mode: none
ctx = ssl._create_unverified_context()

installed = {
    "pipelines": [],
    "component_package": [],
    "component_custom": [],
    "component_custom_skipped": [],
    "index_templates": [],
}

def put(path: str, body: dict, create_only: bool = False) -> str:
    """Returns 'ok' or 'skipped'."""
    q = "?create=true" if create_only else ""
    url = base + path + q
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", "application/json")
    if user:
        import base64
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            print(resp.status, path, resp.read()[:200].decode())
            return "ok"
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        if create_only and e.code == 400 and "already_exists" in err:
            print("skip existing", path)
            return "skipped"
        print("FAIL", path, e.code, err[:800])
        sys.exit(1)

def load_json(p: Path):
    return json.loads(p.read_text())

def enc(name: str) -> str:
    return urllib.parse.quote(name, safe="")

def print_summary() -> None:
    man = {}
    mp = root / "manifest.json"
    if mp.is_file():
        man = load_json(mp)
    pkg = man.get("package") or "?"
    ver = man.get("version") or "?"
    stack = man.get("stack_version") or "?"
    print()
    print("=" * 60)
    print("安装完成 — Elasticsearch 资产说明")
    print("=" * 60)
    print(f"目标集群: {base}")
    print(f"集成包:   {pkg} {ver}")
    print(f"适配 Stack: {stack}")
    print()
    print(f"1) Ingest pipeline（{len(installed['pipelines'])}）")
    for n in installed["pipelines"]:
        print(f"   - {n}")
    print()
    print(f"2) Component template @package（{len(installed['component_package'])}）")
    for n in installed["component_package"]:
        print(f"   - {n}  （mapping / default_pipeline / TSDS 如适用）")
    print()
    print(f"3) Component template @custom（新建 {len(installed['component_custom'])}，已存在跳过 {len(installed['component_custom_skipped'])}）")
    for n in installed["component_custom"]:
        print(f"   - {n}  （空壳，供本地覆盖）")
    for n in installed["component_custom_skipped"]:
        print(f"   - {n}  （已存在，未覆盖）")
    print()
    print(f"4) Index template（{len(installed['index_templates'])}）")
    for n in installed["index_templates"]:
        print(f"   - {n}")
    print()
    streams = man.get("data_streams") or []
    if streams:
        print("5) 对应数据流（Beat 应写入这些 pattern）")
        for s in streams:
            mode = s.get("index_mode") or "standard"
            print(f"   - {s.get('pattern')}  dataset={s.get('dataset')}  mode={mode}")
        print()
    print("下一步:")
    print("  1. 如未用 Fleet：导入 ../kibana/import.ndjson（看板）")
    print("  2. 放下 Beat 配置并启动（setup.template.enabled: false）")
    print("  3. Discover 用 data_stream.dataset 核对")
    print("=" * 60)

print("Installing pipelines")
for p in sorted((root / "00_ingest_pipeline").glob("*.json")):
    put(f"/_ingest/pipeline/{enc(p.stem)}", load_json(p))
    installed["pipelines"].append(p.stem)

print("Installing @package component templates")
for p in sorted((root / "01_component_template").glob("*@package.json")):
    put(f"/_component_template/{enc(p.stem)}", load_json(p))
    installed["component_package"].append(p.stem)

print("Installing @custom component templates (create-only)")
for p in sorted((root / "01_component_template").glob("*@custom.json")):
    status = put(f"/_component_template/{enc(p.stem)}", load_json(p), create_only=True)
    if status == "skipped":
        installed["component_custom_skipped"].append(p.stem)
    else:
        installed["component_custom"].append(p.stem)

print("Installing index templates")
for p in sorted((root / "02_index_template").glob("*.json")):
    put(f"/_index_template/{enc(p.stem)}", load_json(p))
    installed["index_templates"].append(p.stem)

print_summary()
'''
    (out_dir / "install_assets.py").write_text(installer, encoding="utf-8")
    (out_dir / "install_assets.py").chmod(0o755)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("package_dir")
    ap.add_argument("output_dir")
    ap.add_argument("--stack-version", default=None, help="e.g. 8.12.1")
    ap.add_argument("--stack", type=int, default=None, help="major only; prefer --stack-version")
    args = ap.parse_args()
    if args.stack_version:
        ver = parse_stack_version(args.stack_version)
    elif args.stack is not None:
        ver = (args.stack, 0, 0)
    else:
        ver = (9, 0, 0)
    emit(Path(args.package_dir).resolve(), Path(args.output_dir).resolve(), ver)
    print("wrote", args.output_dir)


if __name__ == "__main__":
    main()
