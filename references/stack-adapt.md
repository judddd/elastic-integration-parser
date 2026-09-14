# Stack adaptation (target ES/Kibana version)

Selecting a package whose `conditions.kibana.version` includes the user’s Stack is **necessary but not sufficient**. After generating assets, walk settings, mappings, pipelines, Beat YAML, and Kibana saved objects, and **automatically rewrite anything that 8.12.1 (or whichever target) cannot apply**. Do not leave a “upgrade your cluster” note in place of a working kit.

Record every rewrite in `VERSION-MATRIX.md` under **适配清单**.

## Always do

1. Pick newest package that **installs** on that Kibana (semver range in `manifest.yml`).  
2. Generate ES assets with `scripts/emit_es_assets.py --stack-version X.Y.Z` (not only major).  
3. Run the adaptation pass below.  
4. If a feature cannot be emulated, drop it and say so (do not emit a template that PUT will 400).

## Elasticsearch templates / mappings / settings

| Target | Do this |
| --- | --- |
| **&lt; 8.13** | Do **not** `composed_of: ecs@mappings` on **integration** index templates. Fleet only wired that in at 8.13. The component exists from 8.9 on `logs-*-*`, but composing it on `metrics-<pkg>.*` the 8.13 way is not how 8.12 Fleet behaves. Keep ECS fields from the **package** `fields/*.yml` inside `@package`. |
| **≥ 8.13 / 9** | Compose `ecs@mappings` as Fleet does. |
| **&lt; 8.7** | No TSDS: strip `index.mode: time_series`, `time_series_dimension`, `time_series_metric`. |
| **≥ 8.7** | Keep TSDS if the package stream sets `elasticsearch.index_mode: time_series`. When `index.mode: time_series` is on the **@package component template**, also set **`index.routing_path`** to every field with `time_series_dimension: true` (same component must carry mode + routing_path + those mappings). Omitting `routing_path` makes `PUT _component_template` return 400: `[index.mode=time_series] requires a non-empty [index.routing_path]`. Dimension keyword fields must **not** have `ignore_above` (ES: cannot set together with `time_series_dimension`). |
| Any | Drop index settings / mapping params introduced **after** the target (unknown `index.*`, mapping `meta`, synthetic `_source` overrides, data-stream lifecycle blocks that 8.12 rejects). Prefer omitting over hoping ES ignores them. |
| **8.11–8.12** | `ignore_missing_component_templates` and `allow_auto_create` are fine. Do not emit 8.15+ only mapping types. |

`scripts/emit_es_assets.py` must take `--stack-version 8.12.1` and apply the template compose / TSDS rules above. Do not use `stack_major >= 8` as the `ecs@mappings` switch.

## Ingest pipelines

- Drop processors or options added after the target (if PUT `_ingest/pipeline` would 400).  
- Keep official processor order otherwise (`sql` → `mssql` rename must stay — TSDS dimensions depend on it).

## Beat YAML

Match **Beats X.Y** (same minor as ES):

- 8.12 Filebeat: `filestream` + multiline parsers; do not require `allow_deprecated_use` (later).  
- 8.12 Metricbeat `sql`: keep `module: sql` `metricsets: [query]`. If a package flag (`fetch_from_all_databases`, etc.) is **not** in that Beat minor, expand queries in YAML instead of emitting the unknown key.  
- `ssl.verification_mode: none` always.  
- `setup.template.enabled: false`.

## Dashboards / Kibana saved objects

Copy from the **chosen package version** first (already built for that Kibana range). Then:

- If a saved object `type` or panel vis type does not exist on the target Kibana (ES\|QL viz, later Lens, `alerting_rule_template` on old Kibana), drop that object and list it in 适配清单 — do not import a JSON that Kibana 8.12 rejects.  
- Do **not** rewrite dataset filters to `filebeat-*`.  
- Keep `data_stream.dataset` filters.  
- Data view vs index-pattern: 8.0+ uses data views; 7.x may need `index-pattern`. Convert references if importing on 7.17.  
- Do not bump `kibanaSavedObjectMeta` / dashboard `version` past the target.

## Beat vs package features

If the package has a stream the target Beat cannot collect (input type added later), omit that Beat folder, document the gap, still ship ES assets + dashboards for the streams you can collect.
