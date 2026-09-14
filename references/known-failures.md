# Known install / generation failures → skill fixes

Whenever the user hits a PUT/import/Beat error from a kit this skill produced, **fix the generator and write the lesson here and into SKILL.md / stack-adapt.md / emit_es_assets.py**. Do not only patch the one output folder.

## Honest scope

The EPR zip ships **pipelines + `fields/*.yml` + kibana JSON**. It does **not** ship ready-made index/component templates. Fleet/elastic-package builds those at install time. This skill **re-implements** that build in `emit_es_assets.py`. Pipelines/dashboards are real package copies; templates are synthesized and must obey ES+Fleet rules or PUT will 400. Prefer validating with `install_assets.py` against a real cluster after every generator change.

| Error (symptom) | Root cause | Skill fix |
| --- | --- | --- |
| `PUT _component_template/...@package` 400: `[index.mode=time_series] requires a non-empty [index.routing_path]` | TSDS `index.mode` on the **component** template without `index.routing_path`. ES validates each component alone. | `emit_es_assets.py`: set `index.routing_path` to every `time_series_dimension` path in the same `@package`. |
| `PUT _component_template/...@package` 400: `Field [ignore_above] cannot be set in conjunction with field [time_series_dimension]` | Generator (or field merge from `agent.yml` then `ecs.yml`) put `ignore_above: 1024` on keyword dimensions. ES forbids that combo. | Never set `ignore_above` on dimension fields; `merge_field_leaf` + `sanitize_tsds_mapping` strip it if a later/earlier file conflicts. |

## When you fix a new error

1. Patch `scripts/emit_es_assets.py` and/or Beat/dashboard generation so the **next** parse cannot reproduce it.  
2. Add a row to the table above (error text, cause, where the rule lives).  
3. Update `references/stack-adapt.md` or the relevant reference if it is a Stack/TSDS/mapping rule.  
4. Mention the rewrite in that kit’s `VERSION-MATRIX.md` 适配清单.  
5. Regenerate affected kits if the user still needs them.
