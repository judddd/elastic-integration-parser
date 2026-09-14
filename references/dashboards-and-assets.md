# Dashboards and Elasticsearch assets

## Where dashboards come from

| Source | Path | Index / filter | Use in this skill |
| --- | --- | --- | --- |
| **Integration package (canonical)** | `packages/<pkg>/kibana/dashboard/*.json` plus `search/`, `visualization/`, `lens/`, `map/` as needed | `data_stream.dataset: <pkg>.<stream>` | **Always copy these** |
| Beats module | `<beat>/module/<mod>/_meta/kibana/` | `filebeat-*`, `metricbeat-*`, `winlogbeat-*` | Only as fallback when no integration package exists for that Stack |
| `winlogbeat setup --dashboards` | Beat distro `kibana/` | `winlogbeat-*` | Not for Fleet integration UIs |

Official comparison: Agent/Fleet “Kibana dashboard loading” is done by **installing the integration**, not `filebeat setup --dashboards`. See [Beats vs Agent](https://www.elastic.co/docs/reference/fleet/beats-agent-comparison).

Example: `microsoft_sqlserver` dashboards query `microsoft_sqlserver.transaction_log` (dataset), not `metricbeat-*`. Metricbeat’s mssql `_meta/kibana` is a separate, older asset set.

## Elasticsearch assets the dashboards need

The source package stores **pipelines + field YAMLs**, not ready-made index templates. Fleet EPM turns those into:

- Ingest pipeline `{type}-{dataset}-{packageVersion}`  
- Component template `{type}-{dataset}@package` (mappings, `default_pipeline`, TSDS `index.mode` when set)  
- Empty `{type}-{dataset}@custom`  
- Index template `{type}-{dataset}` matching `{type}-{dataset}-*` with `data_stream: {}`  
- Kibana saved objects  

Always **generate the equivalent JSON** with `scripts/emit_es_assets.py` so the user can PUT them before Beats start. Do not stop at “install via Fleet”.

Standalone Beats **do not** upload those when you only drop a `filebeat.yml`. If Beat `setup` runs with defaults, you get `filebeat-*` templates instead — dashboards stay empty.

## Required install path (perfect match)

1. **Apply ES assets first**: `python3 elasticsearch/install_assets.py` (or Fleet-install the same package version — same names). When the script finishes, it must print a **Chinese summary** listing every pipeline, component template, index template, and data-stream pattern it installed (read from `manifest.json`), not just `Done.`  
2. **Import** `kibana/` if dashboards are not already loaded.  
3. **Beats** only ship data:
   - `setup.template.enabled: false`  
   - `setup.ilm.enabled: false`  
   - `output.elasticsearch.index` (8+/9) or `@metadata.raw_index` → `logs-<dataset>-default`  

8.x Filebeat routing pattern (community + Elastic engineers; requires existing Fleet template):

```yaml
fields_under_root: true
fields:
  data_stream.type: logs
  data_stream.dataset: microsoft_sqlserver.log
  data_stream.namespace: default
  event.dataset: microsoft_sqlserver.log
  event.module: microsoft_sqlserver
processors:
  - add_fields:
      target: '@metadata'
      fields:
        raw_index: logs-microsoft_sqlserver.log-default
setup.template.enabled: false
setup.ilm.enabled: false
output.elasticsearch:
  ssl.verification_mode: none
```

`add_fields` → `@metadata` needs **Filebeat 8.0+**. For **7.x** use a `script` processor writing `@metadata._raw_index` (see Elastic gist “Routing Filebeat data to a Fleet integration data stream”).

## Do not rewrite dashboards

Do not replace dataset filters with `filebeat-*` “to make Beats work”. That breaks the integration definition. Change the **Beat output**, not the dashboard.

## Exporting extra Kibana objects

Dashboards reference searches/visualizations by id. Copy the whole `packages/<pkg>/kibana/` tree for that version, not only `dashboard/`.

If panels reference `logs-*` / `metrics-*` index-pattern (data view) ids, and the target has no Fleet, **emit those saved objects** into `kibana/index-pattern/` and put them **first** in `import.ndjson`. See `references/stack-adapt.md`.
