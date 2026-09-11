# Version alignment

## Why not “always latest”

Each integration `manifest.yml` has:

```yaml
conditions:
  kibana:
    version: "^8.19.0 || ^9.2.1"
```

Kibana **refuses** to install a package outside that range. Example: `microsoft_sqlserver` **2.17.x** needs 8.19/9.2; **2.6.x** listed **8.12.0** as minimum. Installing 2.17 on 8.12 fails.

Beats similarly ship with the Stack: 8.12 Filebeat talks to 8.12 ES templates/ILM conventions.

## Procedure

1. User gives Stack family or exact version (`8.12.2`).  
2. Query versions (**only after** a proxy or local package path — see `network-proxy.md`):
   - GitHub `packages/<name>/changelog.yml` (has “Minimum Kibana version” per release in docs; changelog + old manifests on tags).  
   - EPR: `https://epr.elastic.co/search?package=<name>` or package listing.  
3. Choose **max package version V** where `conditions.kibana.version` **matches** the user’s Kibana.  
4. Fetch package tree at that version tag (`v<package>` if tagged, else commit from changelog).  
5. Beats download: `https://www.elastic.co/downloads/beats/...` for **same ES major.minor** (patch: prefer equal or nearest lower Beat patch).  
6. **Adapt** remaining incompatibilities (`references/stack-adapt.md`). Example: 8.12 must not compose `ecs@mappings` on integration templates (Fleet did that from 8.13); keep ECS in `@package`.

## Stack-family defaults

| User says | ES/Kibana | Beats | Integration pick |
| --- | --- | --- | --- |
| `7` | Prefer **7.17.x** (last 7) | 7.17.x | Newest package whose constraint includes `7.17` (many packages have **no** 7.x support — say so and stop or offer 8.x upgrade) |
| `8` | Use given minor, else ask | Same 8.minor | Newest package compatible with that 8.minor |
| `9` | Use given minor, else ask | Same 9.minor | Newest package compatible with that 9.minor |

Fleet/Agent GA: **7.14**. Before that, only Beats modules exist — parser cannot invent Fleet dashboards.

## Index / data stream model by Stack

| Stack | Typical Beat default | Integration default | Parser target |
| --- | --- | --- | --- |
| 7.x | `filebeat-7.x.x` indices (data streams optional late 7.16+) | `logs-*` / `metrics-*` if package installed | Prefer integration data streams **if** package installs on that 7.17; otherwise Beat indices + **Beats-module dashboards** and warn parity is incomplete |
| 8.x | Data streams `filebeat-8.x.x` **unless** overridden | `logs-<dataset>-<ns>` | **Always** override Beat output to integration streams after assets installed |
| 9.x | Same as 8 | Same as 8, often stricter package mins | Same as 8 |

## Recording

Write `VERSION-MATRIX.md`:

```text
Stack: 8.12.2
Package: microsoft_sqlserver 2.6.0 (kibana ^8.12.0)  # example
Rejected latest: 2.17.1 (needs ^8.19 || ^9.2)
Beats: filebeat/winlogbeat/metricbeat 8.12.2
Dashboards: from packages/microsoft_sqlserver/kibana @ 2.6.0
```
