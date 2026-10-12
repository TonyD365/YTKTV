"""Build the separate mpv download: python packaging/build_mpv_pack.py <platform> <dist>.

Produces <dist>/YTKTV-mpv-<platform>.zip, a flat folder of libmpv, the libraries it
needs, their license texts and a list of where each came from. mpv must already be
installed the way the release workflow installs it (Homebrew, apt, or the Windows
build fetched by ytktv.bootstrap).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from ytktv import bootstrap, mpv_pack

HERE = Path(__file__).resolve().parent
MPV_RAW = "https://raw.githubusercontent.com/mpv-player/mpv/master"
SHARED = (".dylib", ".dll")


def run(*command: str) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def is_library(path: Path) -> bool:
    name = path.name
    if name.startswith(("libpython", "Python")):
        return False  # the stub program's own interpreter, not a dependency of mpv
    return name.endswith(SHARED) or ".so" in name


def collect_with_pyinstaller(work: Path, staging: Path) -> None:
    """Let PyInstaller gather libmpv's dependency tree, then keep only the libraries."""
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(HERE / "mpv_pack" / "mpv_pack.spec"),
            "--noconfirm",
            "--distpath",
            str(work / "dist"),
            "--workpath",
            str(work / "build"),
        ],
        check=True,
    )
    internal = work / "dist" / "mpvpack" / "_internal"
    for path in sorted(internal.iterdir()):
        if path.is_file() and is_library(path):  # is_file follows links: real copies only
            shutil.copy(path, staging / path.name)


def linux(work: Path, staging: Path) -> list[str]:
    collect_with_pyinstaller(work, staging)
    packages: set[str] = set()
    for library in sorted(staging.iterdir()):
        # Each library looks for the others next to itself, wherever the pack is unpacked.
        subprocess.run(["patchelf", "--set-rpath", "$ORIGIN", str(library)], check=True)
        found = subprocess.run(
            ["sh", "-c", f"ldconfig -p | grep -F '{library.name} ' | head -1"],
            capture_output=True,
            text=True,
        ).stdout
        origin = found.split("=>")[-1].strip() if "=>" in found else ""
        owner = subprocess.run(["dpkg", "-S", origin], capture_output=True, text=True).stdout
        if origin and owner:
            packages.add(owner.split(":")[0])
    for name in ("GPL-2", "GPL-3", "LGPL-2.1", "LGPL-3"):
        shutil.copy(f"/usr/share/common-licenses/{name}", staging / f"LICENSE-{name}.txt")
    for package in ("libmpv2", "libavcodec60"):
        notice = Path(f"/usr/share/doc/{package}/copyright")
        if notice.exists():
            shutil.copy(notice, staging / f"LICENSE-{package}-copyright.txt")
    release = run("lsb_release", "-ds").strip()
    lines = [f"Ubuntu packages ({release}); sources: apt-get source <package>=<version>", ""]
    for package in sorted(packages):
        lines.append(
            run("dpkg-query", "-W", "-f=${Package} ${Version} (source: ${source:Package})", package)
        )
    return lines


def macos(work: Path, staging: Path) -> list[str]:
    collect_with_pyinstaller(work, staging)
    for formula, pattern in (
        ("mpv", "LICENSE*"),
        ("mpv", "Copyright"),
        ("ffmpeg", "COPYING*"),
        ("ffmpeg", "LICENSE*"),
    ):
        prefix = Path(run("brew", "--prefix", formula).strip())
        for path in sorted(prefix.glob(pattern)):
            shutil.copy(path, staging / f"LICENSE-{formula}-{path.name}.txt")
    formulae = ["mpv", *run("brew", "deps", "mpv").split()]
    lines = [
        "Homebrew bottles (https://formulae.brew.sh); each formula names its source archive",
        "",
    ]
    lines += run("brew", "list", "--versions", *formulae).splitlines()
    return lines


def windows(_work: Path, staging: Path) -> list[str]:
    library = bootstrap.lib_dir() / "libmpv-2.dll"
    if not library.exists():
        sys.exit("run ytktv.bootstrap.install_windows_libmpv first")
    shutil.copy(library, staging / library.name)
    for name in ("LICENSE.GPL", "LICENSE.LGPL", "Copyright"):
        with urllib.request.urlopen(f"{MPV_RAW}/{name}", timeout=60) as response:
            (staging / f"LICENSE-mpv-{name}.txt").write_bytes(response.read())
    source = bootstrap.lib_dir() / "libmpv-source.txt"
    origin = source.read_text(encoding="utf-8").strip() if source.exists() else "(unknown build)"
    return [
        f"Windows build from https://github.com/{bootstrap.MPV_WINDOWS_REPO}",
        f"Archive: {origin}",
        "That repository contains the build scripts and names the source of every component.",
    ]


def main() -> None:
    name, dist = sys.argv[1], Path(sys.argv[2])
    work = Path("build") / "mpv_pack"
    staging = work / "staging"
    shutil.rmtree(work, ignore_errors=True)
    staging.mkdir(parents=True)
    builder = {"Darwin": macos, "Linux": linux, "Windows": windows}[platform.system()]
    sources = builder(work, staging)
    libraries = [path for path in staging.iterdir() if path.name in bootstrap._libmpv_names()]
    if not libraries:
        sys.exit("the pack does not contain libmpv")
    # The pack must stand on its own: load it in a fresh process that has loaded none
    # of the libraries a packaged YTKTV happens to bring along.
    check = subprocess.run(
        [sys.executable, "-c", "import ctypes, sys; ctypes.CDLL(sys.argv[1])", str(libraries[0])],
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        sys.exit(f"the pack's libmpv does not load on its own:\n{check.stderr.strip()[-2000:]}")
    print(f"{libraries[0].name} loads on its own")
    shutil.copy(HERE / "mpv_pack" / "NOTICE.txt", staging / "NOTICE.txt")
    (staging / "SOURCES.txt").write_text("\n".join(sources) + "\n", encoding="utf-8")

    dist.mkdir(parents=True, exist_ok=True)
    target = dist / mpv_pack.asset_name(name)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(staging.iterdir()):
            bundle.write(path, path.name)
    total = sum(path.stat().st_size for path in staging.iterdir())
    print(
        f"{target}: {len(list(staging.iterdir()))} files, "
        f"{total // 1048576} MiB unpacked, {target.stat().st_size // 1048576} MiB zipped"
    )


if __name__ == "__main__":
    main()
