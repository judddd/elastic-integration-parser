# Agent input → Beat

Elastic Agent inputs are implemented by Beat-like subprocesses. Map from package `streams[].input` / policy `type:`.

## Mapping table

| `type` / `input` | Beat folder | Native config surface |
| --- | --- | --- |
| `logfile`, `log` | filebeat | 8+: prefer `filestream`; 7: `filebeat.inputs` `type: log` |
| `filestream` | filebeat | `type: filestream` |
| `tcp`, `udp`, `syslog` | filebeat | `type: tcp` / `udp` / `syslog` |
| `httpjson`, `cel` | filebeat | `type: httpjson` / `cel` |
| `journald` | filebeat | `type: journald` |
| `aws-s3`, `azure-blob-storage`, `gcs` | filebeat | matching input type (check Beat version support) |
| `winlog` | **winlogbeat** | `winlogbeat.event_logs` (`name`, `event_id`, `ignore_older`, `include_xml`) |
| `sql/metrics` | metricbeat | `module: sql` `metricsets: [query]` (not always `module: mssql`) |
| `http/metrics`, prometheus, vsphere, etc. | metricbeat | matching module or `http` metricset |
| `system/metrics` | metricbeat | `module: system` |
| `packet` | packetbeat | protocols section |

Filebeat also has a `winlog` input. Prefer **Winlogbeat** when the stream is Windows Event Log so operators install the expected binary. Mention Filebeat winlog as an alternative.

## Translating a winlog stream

Policy:

```yaml
type: winlog
streams:
  - name: Security
    event_id: 33205
    ignore_older: 72h
    include_xml: true
    data_stream:
      dataset: microsoft_sqlserver.audit
      type: logs
```

Winlogbeat 8:

```yaml
winlogbeat.event_logs:
  - name: Security
    event_id: 33205
    ignore_older: 72h
    include_xml: true
    fields_under_root: true
    fields:
      data_stream.type: logs
      data_stream.dataset: microsoft_sqlserver.audit
      data_stream.namespace: default
      event.dataset: microsoft_sqlserver.audit
      event.module: microsoft_sqlserver
```

## Translating logfile

Copy `paths`, `exclude_files`, `multiline`, `tags`, `encoding`. On 8.12+ consider `filestream` + `parsers.multiline` if documenting “modern” Filebeat; keep `type: log` if the **chosen Beat 7** has no filestream.

## Translating sql/metrics

Integration often uses **generic SQL metricset** with custom `sql_queries`, not the short `module: mssql` (which lacks Always On AG queries).

```yaml
metricbeat.modules:
  - module: sql
    metricsets: [query]
    period: 60s
    hosts: ["sqlserver://USER:PASS@host"]
    driver: mssql
    sql_queries:
      - query: "..."
        response_format: table
```

URL-encode domain users (`domain%5Cuser`) as in the package. Use `${MSSQL_PASSWORD}` placeholders.

If Metricbeat `sql` module is missing in very old 7.x, fall back to `module: mssql` metricsets and **document lost queries**.

## Output (all Beats)

```yaml
output.elasticsearch:
  hosts: ["https://es:9200"]
  ssl.verification_mode: none
  # 8/9: per-event index via @metadata.raw_index preferred
setup.template.enabled: false
setup.ilm.enabled: false
setup.dashboards.enabled: false
```

Always set `ssl.verification_mode: none` (skip certificate verification). Same policy for `elasticsearch/install_assets.py` (unverified HTTPS). Do not leave this as `full` or `${ES_SSL_VERIFICATION:full}`.

`setup.dashboards.enabled: false` prevents loading Beat-module dashboards that conflict with integration objects.
