# Output folder

```text
<package>-beats-<stack>/
├── VERSION-MATRIX.md
├── INSTALL.md
├── elasticsearch/
│   ├── 00_ingest_pipeline/       # Fleet 命名：{type}-{dataset}-{pkgVersion}.json
│   ├── 01_component_template/    # @package（mapping+TSDS）和 @custom
│   ├── 02_index_template/        # {type}-{dataset}-*
│   ├── install_assets.py         # 写入数据前执行；完成后中文打印已安装资产清单
│   └── manifest.json
├── kibana/                       # full packages/<pkg>/kibana @ chosen version
│   ├── dashboard/
│   ├── visualization/            # if present
│   ├── search/
│   └── lens/
├── filebeat/                     # omit if unused
│   └── filebeat.yml
├── winlogbeat/
│   └── winlogbeat.yml
├── metricbeat/
│   └── metricbeat.yml
├── packetbeat/                   # omit if unused
│   └── packetbeat.yml
└── samples/                      # sample_event.json per stream
```

`INSTALL.md` **必须用中文**（配置键、路径、命令、官方看板英文标题保持原样）。骨架：

1. 版本说明（对照 VERSION-MATRIX）  
2. 安装与 ES 同小版本的 Beats  
3. **先跑** `python3 elasticsearch/install_assets.py`（pipeline / 模板，HTTPS 不校验证书；完成后打印中文安装清单），再启动 Beat  
4. 导入 `kibana/` 看板  
5. 放下 yml（`ssl.verification_mode: none`），`test config`，启动服务  
6. Discover 核对 + 列出拷出来的看板标题  

Beat YAML 和 `install_assets.py` 一律跳过 TLS 证书校验（Beat 用 `ssl.verification_mode: none`）。  

## INSTALL.md verification queries

```text
data_stream.dataset: "<package>.<stream>"
```

看板：列出从 integration 包拷出的官方英文标题，并用中文说明用途和对应 dataset。
