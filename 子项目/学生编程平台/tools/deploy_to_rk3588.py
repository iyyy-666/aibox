from __future__ import annotations

import gzip
import os
import posixpath
import shlex
import sys
import tarfile
import tempfile
from pathlib import Path


DEFAULT_HOST = "192.168.11.106"
DEFAULT_USER = "root"
REMOTE_ARCHIVE = "/tmp/aibox-studio.tar.gz"


def _included_files(project_root: Path):
    fixed = (project_root / "pyproject.toml", project_root / "README.md")
    for path in fixed:
        if path.is_file():
            yield path
    for directory in ("src", "deploy"):
        for path in sorted((project_root / directory).rglob("*")):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and not any(part.endswith(".egg-info") for part in path.parts)
                and path.suffix != ".pyc"
            ):
                yield path


def build_bundle(project_root: str | Path, output_dir: str | Path) -> Path:
    project_root = Path(project_root).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / "aibox-studio.tar.gz"
    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as bundle:
                for source in _included_files(project_root):
                    relative = source.relative_to(project_root)
                    info = bundle.gettarinfo(str(source), f"aibox-studio/{relative.as_posix()}")
                    info.uid = 0
                    info.gid = 0
                    info.uname = "root"
                    info.gname = "root"
                    info.mtime = 0
                    info.mode = 0o755 if source.suffix == ".sh" else 0o644
                    with source.open("rb") as stream:
                        bundle.addfile(info, stream)
    return archive


def remote_install_command(remote_archive: str = REMOTE_ARCHIVE) -> str:
    archive = shlex.quote(remote_archive)
    return (
        "set -eu; "
        "stage=$(mktemp -d /tmp/aibox-studio-install.XXXXXX); "
        "trap 'rm -rf \"$stage\"' EXIT; "
        f"tar -xzf {archive} -C \"$stage\"; "
        "AIBOX_APP_ROOT=/opt/aibox-studio "
        "AIBOX_DESKTOP_DIR=/home/ztl/Desktop "
        "bash \"$stage/aibox-studio/deploy/install_aibox_studio.sh\""
    )


def _check(command, label: str) -> str:
    _, stdout, stderr = command
    output = stdout.read().decode("utf-8", errors="replace")
    errors = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if status != 0:
        raise RuntimeError(f"{label}失败（退出码 {status}）\n{errors or output}")
    if output:
        print(output, end="")
    return output


def deploy(host: str, username: str, password: str | None, project_root: Path) -> None:
    try:
        import paramiko
    except ImportError as error:
        raise SystemExit("缺少 paramiko，请先运行：python -m pip install paramiko") from error

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        host,
        username=username,
        password=password,
        timeout=12,
        allow_agent=True,
        look_for_keys=True,
    )
    try:
        inventory = _check(
            client.exec_command(
                "uname -m; python3 --version; "
                "python3 -c 'import PySide6; print(PySide6.__version__)'; "
                "df -Pk /opt /home/ztl | tail -n +2",
                timeout=30,
            ),
            "环境检查",
        )
        if not any(arch in inventory for arch in ("aarch64", "arm64")):
            raise RuntimeError("目标设备不是 ARM64，已停止安装")

        with tempfile.TemporaryDirectory(prefix="aibox-deploy-") as temporary:
            archive = build_bundle(project_root, temporary)
            sftp = client.open_sftp()
            try:
                sftp.put(str(archive), REMOTE_ARCHIVE)
            finally:
                sftp.close()

        _check(client.exec_command(remote_install_command(), timeout=180), "安装")
        _check(
            client.exec_command("/usr/local/bin/verify_aibox_studio.sh", timeout=90),
            "安装验证",
        )
    finally:
        client.close()


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    host = os.environ.get("RK3588_HOST", DEFAULT_HOST)
    username = os.environ.get("RK3588_USER", DEFAULT_USER)
    password = os.environ.get("RK3588_PASSWORD")
    try:
        deploy(host, username, password, project_root)
    except Exception as error:
        print(f"部署失败：{error}", file=sys.stderr)
        return 1
    print("部署完成：请在 ztl 桌面双击“AIBox学生编程平台”。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
