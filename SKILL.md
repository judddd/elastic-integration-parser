---
name: elastic-integration-parser
description: >
  Parse an official Elastic Fleet integration into a Beat-classified folder
  (filebeat/winlogbeat/metricbeat/…) that runs after installing matching Beats,
  writes to the same data streams the integration uses, and includes that
  integration’s index templates, ingest pipelines, and Kibana dashboards.
  Use whenever the user pastes an Agent/Fleet policy YAML, names a package
  (microsoft_sqlserver, system, nginx, fortinet_fortigate, …), asks to “不用
  集成/自己装 Beat/拆成 filebeat metricbeat winlogbeat”, wants integration
  dashboards with standalone Beats, or specifies Elastic Stack 7/8/9. Prefer
  this skill over rewriting configs from memory. Do not use this to invent a
  new custom integration (use elastic-integration-builder for that).
---

# Elastic Integration → Beats Parser

Turn an **existing official integration** into a **standalone Beats install kit** that still uses that integration’s Elasticsearch assets and dashboards.

Authoritative sources (in this order):

1. [elastic/integrations](https://github.com/elastic/integrations) package source  
2. [Elastic Package Registry](https://epr.elastic.co/) / package `manifest.yml` `conditions.kibana.version`  
3. [Beats + Agent comparison](https://www.elastic.co/docs/reference/fleet/beats-agent-comparison)  
4. Matching Beats version docs (`filebeat` / `metricbeat` / `winlogbeat` for the **same Stack major.minor**)

## Ask first (required)

1. **Stack version family**: `7` / `8` / `9` (prefer full `8.12.2` if known).  
2. **Package name** (or pasted Fleet `inputs:` YAML).  
3. Output directory (default: `./<package>-beats-<stack>/`).  
4. **Proxy for GitHub / EPR / elastic.co** — required before any outbound fetch. See below.

Do not generate until (1) and (2) are known. Do not hit the public internet until (4) is answered (or the user already supplied a local package tree).

## Outbound network / proxy

Official sources live on GitHub and [epr.elastic.co](https://epr.elastic.co/). This machine often **cannot** reach them without a proxy.

Before `curl`, `git`, `gh`, or any download to GitHub, EPR, artifacts.elastic.co, or elastic.co:

1. **Ask the user for a proxy address.** Do not invent one. Accept `http://host:port`, `socks5://host:port`, or `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`.  
2. Wait for their reply. If they provide a local clone or zip, use that instead and skip the network.  
3. Use the proxy **only** for fetch commands in this session. Do not write it into generated Beat configs, and do not `git config --global http.proxy` unless they asked to save it.

Details: `references/network-proxy.md`.

## Version rule (do not use “latest” blindly)

Pick the **newest integration package whose Kibana constraint includes the user’s Stack**. Latest on `main` often requires 8.19/9.2+ and **will not** install on 8.12.

Details: `references/version-alignment.md` and `references/stack-adapt.md`. After picking the package, **automatically adapt** remaining incompatibilities (index settings, mappings, ingest processors, dashboard saved objects, Beat keys) so the kit applies on that exact Stack. Log every rewrite in `VERSION-MATRIX.md`.

Beats binary version: **same major.minor as Elasticsearch** (8.12 Beats ↔ 8.12 ES). Mixing 7 Beats with 8 ES or 9 Beats with 8 ES is unsupported.

## Dashboards: integration package, not Beats modules

Integration dashboards live in:

```text
packages/<pkg>/kibana/dashboard/*.json
```

They filter on **`data_stream.dataset`** (e.g. `microsoft_sqlserver.performance`), not `filebeat-*` / `metricbeat-*`.

Beats module `_meta/kibana` dashboards (if any) target **Beat index patterns** and are a **different, usually smaller** set. Copying those will **not** match the Integrations UI assets.

To make integration dashboards work with Beats:

1. Install the **integration’s ES + Kibana assets** (templates, pipelines, dashboards).  
2. Configure Beats to **write the same data streams** (`logs-<dataset>-<namespace>`, `metrics-<dataset>-<namespace>`).  
3. Disable Beat default template/ILM so they do not fight Fleet templates.  
4. Ship the integration `kibana/` files in the output folder for offline import.

Details: `references/dashboards-and-assets.md`.

## Workflow

### 1) Resolve package version

After the proxy (or a local package path) is available, from EPR or GitHub `packages/<name>/changelog.yml` + historical `manifest.yml`:

- List versions and `conditions.kibana.version`  
- Select newest compatible with the given Stack  
- Record package version in `VERSION-MATRIX.md`

Checkout/source that **tag or commit**, not `main`, unless it matches.

Then read `references/stack-adapt.md` and adapt emitted assets to the **exact** Stack (8.12.1 ≠ 8.19). Typical 8.12 rewrites: no `ecs@mappings` on integration templates; keep package `fields/ecs.yml`; add `logs-*`/`metrics-*` data views if dashboards reference them; omit Beat keys that 8.12 Metricbeat/Filebeat reject.

### 2) Map each stream to a Beat

Read `data_stream/*/manifest.yml` `streams[].input` and Agent policy `type:`.

| Agent / integration input | Beat |
| --- | --- |
| `logfile`, `log`, `filestream`, `tcp`, `udp`, `syslog`, `httpjson`, `cel`, `journald`, `aws-s3`, … | **Filebeat** |
| `winlog` | **Winlogbeat** (Filebeat `winlog` input only if Winlogbeat is unavailable) |
| `sql/metrics`, `http/metrics`, `vsphere/metrics`, `prometheus/metrics`, module-style metrics | **Metricbeat** |
| `packet` / network capture | **Packetbeat** |
| `osquery` | **Osquerybeat** (rare) |

If one package has mixed inputs, **split into multiple Beat folders**. See `references/input-to-beat.md`.

### 3) Translate streams → Beat YAML

For each stream:

- Copy listen paths, event IDs, multiline, SQL `hosts`/`sql_queries`, periods, tags.  
- Set `data_stream.type/dataset/namespace` and `event.dataset` / `event.module` to match the package.  
- Route Elasticsearch `index` (or `@metadata.raw_index`) to `logs|metrics-<dataset>-<namespace>`.  
- `setup.template.enabled: false` and `setup.ilm.enabled: false`.  
- `output.elasticsearch.ssl.verification_mode: none` on **every** Beat YAML (skip TLS certificate verification; do not use `full` or an env default of `full`).  
- Match Beat config syntax for the **target Beat version** (7 vs 8: `log` vs `filestream`; 7 routing to data streams needs the 7.x `script` processor, not 8.x `add_fields` on `@metadata`).

### 4) Extract Elasticsearch assets the user can PUT before Beats start

The EPR/source zip **does not** contain ready-made index templates. It contains `fields/*.yml` + ingest pipelines; **Fleet / elastic-package generates** component and index templates at install. This skill must **re-implement that generation** in `scripts/emit_es_assets.py` (not invent a freestyle mapping). Pipelines and `kibana/` are copied from the package; templates are synthesized and must match ES validation (TSDS `routing_path`, no `ignore_above` on dimensions, Stack-specific `ecs@mappings` compose, etc.). Every PUT 400 from `install_assets.py` is a generator bug — fix the script and `references/known-failures.md`, then regenerate.

Run `scripts/emit_es_assets.py <package-dir> <out>/elasticsearch --stack-version 8.12.1`.

Then apply `references/stack-adapt.md`: rewrite settings / mappings / pipelines / dashboards / Beat YAML that the **exact** target cannot apply. Do not ship a kit that 400s on PUT or fails Kibana import.

It must emit, in apply order:

1. `elasticsearch/00_ingest_pipeline/{type}-{dataset}-{pkgVersion}.json` — from `data_stream/*/elasticsearch/ingest_pipeline/` (Fleet name)  
2. `elasticsearch/01_component_template/{type}-{dataset}@package.json` — mappings from all `fields/*.yml` (`dimension` → `time_series_dimension`, `metric_type` → `time_series_metric`), `index.default_pipeline`, and when TSDS: `index.mode: time_series` **plus** `index.routing_path` listing every dimension field path (required or ES returns 400)  
3. `elasticsearch/01_component_template/{type}-{dataset}@custom.json` — empty overlay, install with `?create=true`  
4. `elasticsearch/02_index_template/{type}-{dataset}.json` — `index_patterns: {type}-{dataset}-*`, `data_stream: {}`, `composed_of: [ecs@mappings only if target ≥ 8.13, @package, @custom]`, priority 200  
5. `elasticsearch/install_assets.py` — PUT the above against `ES_URL` **before** starting Beats. HTTPS must skip certificate verification (`ssl._create_unverified_context()`), matching Beat `ssl.verification_mode: none`. Do not add an `ES_SSL_VERIFY=1` path.  
   After all PUTs succeed, the script **must print a Chinese summary** of what was installed: package/version, target `ES_URL`, each ingest pipeline name, each `@package` / `@custom` component template (note skipped `@custom`), each index template, and the data-stream patterns from `manifest.json`, plus short next steps (import kibana, start Beats). Do not end with only `Done.`

Also copy `kibana/` and sample events. Do **not** rewrite dashboard JSON. Do **not** tell the user “just install via Fleet” and skip these files.

### 5) Write install docs

`INSTALL.md` **用中文写**（专有名词、字段名、路径、命令可保留英文原文，例如 `data_stream.dataset`、`filebeat.yml`）。读者是要照着装的人，不是英文文档。`VERSION-MATRIX.md` 可用中文或中英对照。Beat YAML 仍用英文键名。

`INSTALL.md` 必须按这个顺序写：

1. 安装与 ES 同小版本的 Beats **N.M.x**  
2. **先执行** `elasticsearch/install_assets.py`（pipeline → component template → index template；脚本 HTTPS 不校验证书，与 Beat 的 `ssl.verification_mode: none` 一致）。跑完后脚本会**用中文打印安装说明**（装了哪些 pipeline / 模板 / 数据流）。也可改用 Fleet 上传原包，效果应等价。  
3. 导入 `kibana/` 看板（Fleet 已装则可跳过）  
4. 放下生成的 `*-beat.yml`（其中 `ssl.verification_mode: none`），`test config`，启动  
5. Discover 查询：`data_stream.dataset: "<package>.<stream>"`  
6. 打开拷出来的看板（列出中文说明 + 官方英文标题）  

## Output layout

See `references/output-layout.md`. Always classify by Beat; omit empty Beat dirs.

## Compatibility warnings (state them)

- **Metrics TSDS**: 8.8+ 不少 integration 指标流是 ES `index_mode: time_series`。这不是「Metricbeat 不支持 TSDS」——Agent 的 `*/metrics` 输入底下就是 Metricbeat，独立 Metricbeat 同样能写。写失败通常是没装 Fleet 模板、写到了 `metricbeat-*`、或 ingest pipeline 没把 `sql.*` 改成包里的维度字段。在 VERSION-MATRIX / INSTALL 里写清这三点，不要写成 Beat 能力缺陷。  
- **7.x**: Fleet integrations from 7.14+; data-stream routing from Beats is limited. Prefer 7.17 Beats + the last package whose Kibana constraint includes 7.17, or warn that perfect dashboard parity may require 8.x.  
- **Secrets**: never copy real passwords from pasted policies into git; use env placeholders.

## Error → skill sync (mandatory)

If install, import, or Beat runtime fails because of something this skill generated:

1. Fix the **generator** (`scripts/emit_es_assets.py`, Beat YAML rules, dashboard adapt), not only the one output folder.  
2. Record the failure in `references/known-failures.md` (error text, cause, where the rule lives).  
3. Update `references/stack-adapt.md` / this SKILL.md / INSTALL wording so the same mistake cannot ship again.  
4. Regenerate the user’s kit when they still need it.

Do not treat a one-off file edit as done. The skill must learn from every production error.

## Anti-patterns

- Fixing a PUT/import error in one kit folder without updating the skill / `emit_es_assets.py` / `known-failures.md`.  
- Using `main` / latest integration for an older Stack, or emitting 8.13+ `ecs@mappings` compose / new vis types onto 8.12.  
- Shipping templates/dashboards that the target Stack cannot PUT/import instead of adapting them.  
- Emitting TSDS `@package` with `index.mode: time_series` but no `index.routing_path`.  
- Putting `ignore_above` on a `time_series_dimension` field.  
- Claiming templates were “copied from the package zip” — the zip has no index templates; they are synthesized.  
- Putting `ignore_above` on keyword fields that also have `time_series_dimension: true`.  
- `install_assets.py` 成功后不打印中文安装清单（只打 `Done.`）。  
- Exporting Beats-module dashboards and calling them “integration dashboards”.  
- Letting Filebeat `setup` install `filebeat-*` templates while dashboards query `logs-pkg.dataset-*`.  
- Merging all inputs into one `filebeat.yml` when `sql/metrics` belongs in Metricbeat.  
- Coupling this skill to any local demo repo.  
- Fetching GitHub / EPR / elastic.co without first asking the user for a proxy (or a local package path).  
- 把 `INSTALL.md` 写成英文说明（正文必须是中文）。  
- 只拷 pipeline、不生成可 PUT 的 index/component template。  
- `ssl.verification_mode` 写成 `full` 或留给环境变量默认校验证书。

## References

| File | When |
| --- | --- |
| `references/network-proxy.md` | Ask for proxy before GitHub / EPR / elastic.co |  
| `references/stack-adapt.md` | 按目标 Stack 自动改 setting / mapping / dashboard |
| `references/known-failures.md` | 安装/生成报错 → 必须回写 skill 的案例表 |
| `references/input-to-beat.md` | Input → Beat + YAML translation |
| `references/dashboards-and-assets.md` | Where dashboards live; how to install assets |
| `references/output-layout.md` | Folder tree and INSTALL steps |
| `scripts/emit_es_assets.py` | 从官方包生成可 PUT 的 pipeline / 模板 |
