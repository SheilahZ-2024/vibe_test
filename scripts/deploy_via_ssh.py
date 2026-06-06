#!/usr/bin/env python3
"""从本机 SSH 远程部署到阿里云 Linux 实例（上传本地代码，不依赖 GitHub 克隆）。"""

from __future__ import annotations

import getpass
import os
import re
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

try:
    import paramiko
except ImportError:
    print("正在安装 paramiko …")
    import subprocess

    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
    import paramiko

HOST = os.environ.get("DEPLOY_HOST", "47.99.155.107")
USER = "root"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_LOCAL = PROJECT_ROOT / "scripts" / "vendor" / "docker-compose-linux-x86_64"
COMPOSE_URLS = [
    "https://github.com/docker/compose/releases/download/v2.24.5/docker-compose-linux-x86_64",
    "https://mirror.ghproxy.com/https://github.com/docker/compose/releases/download/v2.24.5/docker-compose-linux-x86_64",
]
SKIP_DIR_NAMES = {".venv", "node_modules", "__pycache__", "dist", ".git", "postgres_data", "redis_data"}
SKIP_FILES = {".env", "tsconfig.tsbuildinfo"}


def read_llm_key() -> str:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^LLM_API_KEY=(.*)$", line.strip())
        if m:
            return m.group(1).strip()
    return ""


def should_skip(rel: Path) -> bool:
    if rel.name in SKIP_FILES:
        return True
    return any(part in SKIP_DIR_NAMES for part in rel.parts)


def build_tarball() -> str:
    fd, path = tempfile.mkstemp(suffix=".tar.gz")
    os.close(fd)
    print("==> 打包本地项目 …")
    count = 0
    with tarfile.open(path, "w:gz") as tar:
        for item in PROJECT_ROOT.rglob("*"):
            rel = item.relative_to(PROJECT_ROOT)
            if should_skip(rel):
                continue
            tar.add(item, arcname=rel.as_posix(), recursive=False)
            count += 1
    print(f"    已打包 {count} 个文件")
    return path


def ensure_compose_binary() -> Path | None:
    if COMPOSE_LOCAL.exists() and COMPOSE_LOCAL.stat().st_size > 5_000_000:
        print("==> 使用缓存的 docker-compose")
        return COMPOSE_LOCAL
    COMPOSE_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    print("==> 本机下载 docker-compose（供上传到服务器）…")
    for url in COMPOSE_URLS:
        try:
            print(f"    尝试 {url[:56]}…")
            urllib.request.urlretrieve(url, COMPOSE_LOCAL)
            if COMPOSE_LOCAL.stat().st_size > 5_000_000:
                print("    下载成功")
                return COMPOSE_LOCAL
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"    失败: {exc}")
    return None


REMOTE_SCRIPT = """\
set -e
export PUBLIC_IP={host}
export LLM_API_KEY='{llm}'
export WEB_PORT=5173
ENV_BACKUP=""
if [[ -f /root/smart-assistant/.env ]]; then
  ENV_BACKUP="$(cat /root/smart-assistant/.env)"
fi
rm -rf /root/smart-assistant
mkdir -p /root/smart-assistant
tar -xzf /tmp/smart-assistant.tar.gz -C /root/smart-assistant
if [[ -n "$ENV_BACKUP" ]]; then
  printf '%s' "$ENV_BACKUP" > /root/smart-assistant/.env
  echo "==> 已恢复上一份 .env（保留数据库密码）"
fi
cd /root/smart-assistant
bash scripts/deploy-aliyun.sh
echo "==> 等待服务就绪 …"
for i in $(seq 1 24); do
  if curl -fsS http://127.0.0.1:5173/health >/dev/null 2>&1; then
    curl -fsS http://127.0.0.1:5173/health
    echo
    echo "=== DEPLOY_OK http://{host}:5173 ==="
    exit 0
  fi
  sleep 5
done
echo "ERROR: health check timeout" >&2
/usr/local/bin/docker-compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail 40 api web || true
exit 1
"""


def stream_command(client: paramiko.SSHClient, script: str) -> int:
    stdin, stdout, stderr = client.exec_command(f"bash -s <<'EOF'\n{script}\nEOF", get_pty=True)
    stdin.close()
    channel = stdout.channel
    channel.settimeout(900.0)

    while True:
        if stdout.channel.recv_ready():
            data = stdout.channel.recv(4096).decode(errors="replace")
            if data:
                print(data, end="", flush=True)
        if stdout.channel.recv_stderr_ready():
            data = stdout.channel.recv_stderr(4096).decode(errors="replace")
            if data:
                print(data, end="", file=sys.stderr, flush=True)
        if stdout.channel.exit_status_ready():
            while stdout.channel.recv_ready():
                print(stdout.channel.recv(4096).decode(errors="replace"), end="", flush=True)
            break
        if not stdout.channel.active:
            break

    return channel.recv_exit_status()


def main() -> int:
    password = os.environ.get("DEPLOY_PASSWORD") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not password:
        password = getpass.getpass(f"{USER}@{HOST} 密码: ")

    llm = read_llm_key().replace("'", "'\\''")
    tar_path = build_tarball()
    compose_path = ensure_compose_binary()

    print(f"==> 连接 {HOST} …")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, username=USER, password=password, timeout=30, allow_agent=False, look_for_keys=False)
    except Exception as exc:
        print(f"SSH 连接失败: {exc}")
        print("提示：密码错误时会报 Authentication failed，请用控制台重置 root 密码后再试。")
        os.unlink(tar_path)
        return 1

    transport = client.get_transport()
    if transport:
        transport.set_keepalive(15)

    code = 1
    try:
        sftp = client.open_sftp()
        print("==> 上传代码到服务器 …")

        def progress(sent, total):
            if total and sent > 0 and sent % max(total // 10, 1) < 65536:
                print(f"    代码上传 {sent * 100 // total}%")

        sftp.put(tar_path, "/tmp/smart-assistant.tar.gz", callback=progress)
        print("    代码上传完成")

        if compose_path:
            print("==> 上传 docker-compose …")
            sftp.put(str(compose_path), "/usr/local/bin/docker-compose")
            sftp.chmod("/usr/local/bin/docker-compose", 0o755)
            print("    docker-compose 上传完成")

        sftp.close()

        print("==> 远程部署中（约 5～15 分钟，请勿关闭终端）…")
        script = REMOTE_SCRIPT.format(host=HOST, llm=llm)
        code = stream_command(client, script)
    finally:
        client.close()
        os.unlink(tar_path)

    print(f"\n退出码: {code}")
    if code == 0:
        print(f"\n访问 Demo: http://{HOST}:5173")
    else:
        print("\n部署失败。请把终端最后 30 行发我。")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
