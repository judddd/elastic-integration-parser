# Outbound network / proxy

This environment often cannot reach GitHub, EPR, or elastic.co without an HTTP/SOCKS proxy. Direct `curl`/`git`/`gh` to those hosts hangs or fails.

## Before any outbound fetch

If the next step needs **GitHub**, **epr.elastic.co**, **artifacts.elastic.co**, **elastic.co docs**, or any other public internet host, **stop and ask the user for a proxy**. Do not retry without one. Do not guess `127.0.0.1:7890` or similar.

Ask for any of:

- `http://host:port`
- `socks5://host:port`
- `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` / `NO_PROXY`

Wait until they reply. If they say no proxy is needed, proceed direct. If they give an address, use it **only for that session’s fetch commands**.

## How to use the address they gave

Export for the fetch process (do not write these into generated Beat YAML or INSTALL secrets):

```bash
export HTTPS_PROXY='<user-provided>'
export HTTP_PROXY='<user-provided>'
export ALL_PROXY='<user-provided>'
# git over HTTPS
git config --global --get http.proxy >/dev/null || true
# per-command is enough:
curl -x "$HTTPS_PROXY" ...
GIT_SSL_NO_VERIFY=  git -c http.proxy="$HTTPS_PROXY" clone ...
```

For SOCKS: `ALL_PROXY=socks5://host:port` (curl `--socks5-hostname` if HTTP_PROXY form is not accepted).

Do **not** persist proxy into:

- generated `filebeat.yml` / `metricbeat.yml` / `winlogbeat.yml`
- `INSTALL.md` as a required env for production Beats
- git user config (`git config --global http.proxy`) unless the user explicitly asked to save it

## Local sources first

If the user already has a clone of `elastic/integrations` or an unpacked `.zip` from EPR, use that path and skip the network. Still record the package version in `VERSION-MATRIX.md`.
