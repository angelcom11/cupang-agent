"""포터블 실행 파일 만들기 (PyInstaller).

    python build_portable.py          → dist/WING-Manager-<버전>-<OS>-<CPU>.zip

PyInstaller 는 다른 OS용 파일을 만들 수 없으므로(교차 빌드 불가) 각 OS에서 한 번씩 돌린다.
v0.8.1 부터 GitHub Actions 자동 빌드·릴리스는 하지 않는다(Docker 이미지만 배포). 필요하면 각 OS에서 직접 돌린다.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from version import VERSION

ROOT = Path(__file__).resolve().parent
NAME = "WING-Manager"
OS_NAMES = {"win32": "windows", "darwin": "macos"}
CPU_NAMES = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}


def target() -> str:
    os_name = OS_NAMES.get(sys.platform, "linux")
    cpu = CPU_NAMES.get(platform.machine().lower(), platform.machine().lower())
    return f"{os_name}-{cpu}"


def build() -> Path:
    sep = os.pathsep  # --add-data 구분자: Windows ';' / 그 밖 ':'
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
           "--name", NAME, "--add-data", f"{ROOT / 'templates'}{sep}templates", "--add-data", f"{ROOT / 'static'}{sep}static",
           "--distpath", "dist/bin", "--workpath", "build", "--specpath", "build", str(ROOT / "portable.py")]
    subprocess.run(cmd, cwd=ROOT, check=True)
    exe = ROOT / "dist" / "bin" / (NAME + (".exe" if sys.platform == "win32" else ""))
    if not exe.exists():
        raise SystemExit(f"빌드 결과가 없습니다: {exe}")
    return exe


def package(exe: Path) -> Path:
    out = ROOT / "dist" / f"{NAME}-{VERSION}-{target()}.zip"
    folder = f"{NAME}-{VERSION}"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo(f"{folder}/{exe.name}", date_time=time.localtime(exe.stat().st_mtime)[:6])
        info.external_attr = 0o755 << 16  # Linux·macOS 에서 압축을 풀어도 실행 권한 유지
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, exe.read_bytes())
        z.write(ROOT / "PORTABLE.md", f"{folder}/사용법.md")
        z.write(ROOT / "config.example.json", f"{folder}/config.example.json")
    return out


if __name__ == "__main__":
    shutil.rmtree(ROOT / "dist" / "bin", ignore_errors=True)
    print(package(build()))
