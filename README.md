# qshare

无需登录账号，一行命令即可把本地文件临时分享至公网。文件由本机 HTTP 服务提供，并通过临时 TryCloudflare 隧道传输，不会上传到 qshare 服务器留存。

## 特点

- 无需注册或登录账号
- 一行命令快速分享本地文件
- 文件不在 qshare 服务器保存
- 默认有效期 2 小时，可通过 `--ttl` 调整
- 结果链接醒目显示，并提供终端二维码
- 支持 Linux、Windows 和 macOS
- PyPI 平台 wheel 内置对应的官方 `cloudflared` 二进制
- 运行时不从 GitHub 下载二进制，适合网络受限环境

启动后会提示：私密文件请先加密，再进行中转分享。公网链接本身没有访问控制，请勿直接分享未加密的敏感文件。

## 安装

```bash
python -m pip install -U qshare
```

pip 会根据操作系统和架构选择对应 wheel，每个 wheel 只包含自身平台的二进制。

如果不信任 PyPI wheel 中的二进制，可以从 Cloudflare 官方发布页下载匹配版本，按官方校验和验证后放入 `PATH`：

<https://github.com/cloudflare/cloudflared/releases>

qshare 会优先使用 `PATH` 中已有的 `cloudflared`。没有匹配平台 wheel 时，也可以手动安装 `cloudflared` 后使用。

## 使用

```bash
qshare /path/to/file.zip
qshare /path/to/file.zip --ttl 2h
qshare /path/to/file.zip --ttl 900
qshare /path/to/file.zip --port 8000
qshare /path/to/file.zip --cnb
```

成功后会显示醒目的公网文件链接及二维码。程序只接受真实的 `*.trycloudflare.com` 分享域名，会拒绝 `api.trycloudflare.com` 并自动重试。Unix-like 系统可在提示处输入 `d` 后台运行；Windows 始终前台运行。前台运行达到 TTL 后会提示并停止分享。

使用 `--cnb` 会将文件上传到 CNB Release 并返回下载地址；文件会存储在 CNB，请先加密私密文件。上传过程中会显示进度。

## DNS 排查

如果打开链接时提示找不到 IP，通常是本地 DNS 解析或网络限制。可以尝试使用 Cloudflare DNS `1.1.1.1`、`1.0.0.1`，或 Google DNS `8.8.8.8`、`8.8.4.4`，然后刷新本地 DNS 缓存并重试。`1.1.1.1` 可能改善解析，但无法解决隧道过期或网络屏蔽 Cloudflare 的问题。

## 开发与发布

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
PYTHONPATH=src pytest -q
```

使用本地准备好的 Cloudflare 二进制构建平台 wheel：

```bash
uv build
python scripts/build_platform_wheels.py --assets-dir /path/to/cloudflared-assets
```

## 说明

- 默认有效期为 2 小时。
- 端口被占用时会自动选择其他空闲端口。
- `--ttl` 支持 `30m`、`90s`、`2h` 或秒数。
