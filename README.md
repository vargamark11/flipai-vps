# FlipAI VPS

One-command CPU-only AI deployment for Debian/Ubuntu VPS.

## What it installs

- llama.cpp
- Qwen3 4B GGUF Q4_K_M by default
- FastAPI gateway on `127.0.0.1:3000`
- llama.cpp on `127.0.0.1:8080`
- systemd services
- Caddy HTTPS reverse proxy
- separate public and internal API keys

## Requirements

- Debian 12 / Ubuntu
- x86_64 VPS
- recommended: 6 vCPU, 12 GB RAM+
- DNS A record for your API domain pointing to the VPS IP
- ports 80/443 open

## Install

```bash
git clone https://github.com/vargamark11/flipai-vps.git
cd flipai-vps
sudo python3 install.py --domain api.flipai.cc
```

The installer prints a generated public API key. Save it.

## Test

```bash
curl https://api.flipai.cc/health
```

Authenticated chat request:

```bash
curl https://api.flipai.cc/v1/chat/completions \
  -H "Authorization: Bearer YOUR_PUBLIC_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"flipai-v1","messages":[{"role":"user","content":"Szia! Ki vagy te?"}]}'
```

## Useful commands

```bash
sudo systemctl status flipai-model
sudo systemctl status flipai-api
sudo journalctl -u flipai-model -f
sudo journalctl -u flipai-api -f
```

## Security

Do not commit `/etc/flipai.env` or API keys to GitHub.
The model backend binds only to localhost.
