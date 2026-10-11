#!/usr/bin/env python3
import argparse
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

APP_DIR = Path("/opt/flipai")
LLAMA_DIR = Path("/opt/llama.cpp")
SERVICE_USER = "debian"

def run(cmd, check=True, cwd=None):
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=check, cwd=cwd)

def write(path, content, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)

def apt_install():
    run(["apt-get", "update"])
    run([
        "apt-get", "install", "-y",
        "git", "cmake", "build-essential", "curl",
        "libssl-dev", "pkg-config", "python3-venv",
        "python3-pip", "caddy"
    ])

def build_llama():
    if not LLAMA_DIR.exists():
        run(["git", "clone", "https://github.com/ggml-org/llama.cpp.git", str(LLAMA_DIR)])
    else:
        run(["git", "pull", "--ff-only"], cwd=str(LLAMA_DIR))

    build = LLAMA_DIR / "build"
    if build.exists():
        shutil.rmtree(build)

    run([
        "cmake", "-S", ".", "-B", "build",
        "-DGGML_NATIVE=ON",
        "-DLLAMA_OPENSSL=ON"
    ], cwd=str(LLAMA_DIR))
    run(["cmake", "--build", "build", "--config", "Release", "-j", str(os.cpu_count() or 2)],
        cwd=str(LLAMA_DIR))

def install_backend():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).resolve().parent / "app"
    for name in ("main.py", "requirements.txt"):
        shutil.copy2(src / name, APP_DIR / name)

    venv = APP_DIR / ".venv"
    run(["python3", "-m", "venv", str(venv)])
    run([str(venv / "bin" / "pip"), "install", "--upgrade", "pip"])
    run([str(venv / "bin" / "pip"), "install", "-r", str(APP_DIR / "requirements.txt")])

def create_env(domain, model_repo, model_alias, public_api_key, internal_api_key):
    env = f"""FLIPAI_DOMAIN={domain}
FLIPAI_MODEL_REPO={model_repo}
FLIPAI_MODEL_ALIAS={model_alias}
FLIPAI_PUBLIC_API_KEY={public_api_key}
FLIPAI_INTERNAL_API_KEY={internal_api_key}
LLAMA_URL=http://127.0.0.1:8080/v1/chat/completions
"""
    write("/etc/flipai.env", env, 0o600)

def create_services(model_repo, model_alias):
    llama_service = f"""[Unit]
Description=FlipAI llama.cpp server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={SERVICE_USER}
WorkingDirectory={LLAMA_DIR}
EnvironmentFile=/etc/flipai.env
ExecStart={LLAMA_DIR}/build/bin/llama-server -hf {model_repo}:Q4_K_M --alias {model_alias} --host 127.0.0.1 --port 8080 -c 4096 --reasoning off --api-key ${{FLIPAI_INTERNAL_API_KEY}}
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
"""
    api_service = f"""[Unit]
Description=FlipAI Python API
After=network-online.target flipai-model.service
Requires=flipai-model.service

[Service]
Type=simple
User={SERVICE_USER}
WorkingDirectory={APP_DIR}
EnvironmentFile=/etc/flipai.env
ExecStart={APP_DIR}/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 3000
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
"""
    write("/etc/systemd/system/flipai-model.service", llama_service)
    write("/etc/systemd/system/flipai-api.service", api_service)

def configure_caddy(domain):
    caddyfile = f"""{domain} {{
    encode zstd gzip
    reverse_proxy 127.0.0.1:3000
}}
"""
    write("/etc/caddy/Caddyfile", caddyfile)
    run(["caddy", "validate", "--config", "/etc/caddy/Caddyfile"])

def enable_services():
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", "flipai-model.service"])
    run(["systemctl", "enable", "--now", "flipai-api.service"])
    run(["systemctl", "enable", "--now", "caddy"])
    run(["systemctl", "restart", "caddy"])

def main():
    if os.geteuid() != 0:
        print("Run with sudo: sudo python3 install.py", file=sys.stderr)
        sys.exit(1)

    p = argparse.ArgumentParser(description="Install FlipAI on Debian/Ubuntu VPS")
    p.add_argument("--domain", default="api.flipai.cc")
    p.add_argument("--model-repo", default="Qwen/Qwen3-4B-GGUF")
    p.add_argument("--model-alias", default="flipai-v1")
    p.add_argument("--public-api-key", default="")
    args = p.parse_args()

    public_key = args.public_api_key or ("flipai_pk_" + secrets.token_hex(32))
    internal_key = "flipai_internal_" + secrets.token_hex(32)

    apt_install()
    build_llama()
    install_backend()
    create_env(args.domain, args.model_repo, args.model_alias, public_key, internal_key)
    create_services(args.model_repo, args.model_alias)
    configure_caddy(args.domain)
    enable_services()

    print("\n=== FlipAI installed ===")
    print("Domain:", f"https://{args.domain}")
    print("Model:", args.model_alias)
    print("Public API key:", public_key)
    print("\nIMPORTANT: save the public API key now.")
    print("Health:", f"curl https://{args.domain}/health")
    print("\nTest:")
    print(
        f"""curl https://{args.domain}/v1/chat/completions \\
  -H 'Authorization: Bearer {public_key}' \\
  -H 'Content-Type: application/json' \\
  -d '{{"model":"{args.model_alias}","messages":[{{"role":"user","content":"Szia! Ki vagy te?"}}]}}'"""
    )

if __name__ == "__main__":
    main()
