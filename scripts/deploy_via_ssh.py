#!/usr/bin/env python3
"""从本机 SSH 远程部署到阿里云 Linux 实例。"""

from __future__ import annotations

import getpass
import os
import re
import sys
import time

try:
    import paramiko
except ImportError:
    print("正在安装 paramiko …")
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
    import paramiko

HOST = os.environ.get("DEPLOY_HOST", "47.99.155.107")
USER = "root"
REPO = "https://github.com/SheilahZ-2024/vibe_test.git"


def read_llm_key() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root, ".env")
    if not os.path.isfile(env_path):
        return ""
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^LLM_API_KEY=(.*)$", line.strip())
            if m:
                return m.group(1).strip()
    return ""


REMOTE_SCRIPT = """\
set -e
export PUBLIC_IP={host}
export LLM_API_KEY='{llm}'
export WEB_PORT=5173
if command -v dnf >/dev/null 2>&1; then dnf install -y git curl 2>/dev/null || true; fi
if command -v yum >/dev/null 2>&1; then yum install -y git curl 2>/dev/null || true; fi
if command -v apt-get >/dev/null 2>&1; then apt-get update -qq && apt-get install -y git curl 2>/dev/null || true; fi
if [ -d /root/smart-assistant/.git ]; then
  cd /root/smart-assistant && git pull
else
  rm -rf /root/smart-assistant
  git clone {repo} /root/smart-assistant
  cd /root/smart-assistant
fi
bash scripts/deploy-aliyun.sh
curl -fsS http://127.0.0.1:5173/health
echo
echo "=== DEPLOY_OK http://{host}:5173 ==="
"""


def main() -> int:
    password = os.environ.get("DEPLOY_PASSWORD") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not password:
        password = getpass.getpass(f"{USER}@{HOST} 密码: ")

    llm = read_llm_key().replace("'", "'\\''")
    script = REMOTE_SCRIPT.format(host=HOST, llm=llm, repo=REPO)

    print(f"==> 连接 {HOST} …")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, username=USER, password=password, timeout=30, allow_agent=False, look_for_keys=False)
    except Exception as exc:
        print(f"SSH 连接失败: {exc}")
        print("请确认：1) 已换成 Linux  2) 安全组放行 22  3) root 密码正确")
        return 1

    print("==> 远程部署中（约 3～8 分钟，请耐心等待）…")
    stdin, stdout, stderr = client.exec_command(f"bash -s <<'EOF'\n{script}\nEOF", get_pty=True)
    stdin.close()

    for line in iter(stdout.readline, ""):
        print(line, end="")

    err = stderr.read().decode()
    if err:
        print(err, file=sys.stderr)

    code = stdout.channel.recv_exit_status()
    client.close()

    print(f"\n退出码: {code}")
    if code == 0:
        print(f"\n访问 Demo: http://{HOST}:5173")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
