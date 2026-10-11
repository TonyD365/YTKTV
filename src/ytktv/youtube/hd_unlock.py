"""Optional component that unlocks HD for videos YouTube restricts.

Some videos (mostly ones marked "made for kids") are refused by yt-dlp's
default clients, and the one client that still serves them without extra
credentials only offers 360p. YouTube does hand out the HD streams to its TV
client when the request carries a "PO token", which has to be computed by
running YouTube's own JavaScript.

This component provides that: the Deno JavaScript runtime plus the BgUtils
token generator (github.com/Brainicism/bgutil-ytdlp-pot-provider), whose yt-dlp
plugin ships with the app. It is downloaded on request because it is large and
only matters for a small share of videos.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import os
import platform
import shutil
import stat
import subprocess
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ytktv.config import data_dir
from ytktv.net import urlopen

log = logging.getLogger(__name__)

PLUGIN_PACKAGE = "bgutil-ytdlp-pot-provider"
PROVIDER_REPO = "Brainicism/bgutil-ytdlp-pot-provider"
DENO_RELEASES = "https://github.com/denoland/deno/releases/latest/download"
MARKER = "component.json"
REVISION = 1
DOWNLOAD_SIZE = "about 150 MB"
# The YouTube client that serves restricted videos in HD once a PO token is supplied.
CLIENT = "tv_simply"

Report = Callable[[str], None]
Fetch = Callable[[str, Path], None]
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def deno_target(system: str | None = None, machine: str | None = None) -> str | None:
    """Name of Deno's release build for this platform, or None if there is none."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    arm = machine in ("arm64", "aarch64")
    if system == "Darwin":
        return "aarch64-apple-darwin" if arm else "x86_64-apple-darwin"
    if system == "Windows":
        return None if arm else "x86_64-pc-windows-msvc"
    if system == "Linux":
        return "aarch64-unknown-linux-gnu" if arm else "x86_64-unknown-linux-gnu"
    return None


def plugin_version() -> str | None:
    """Version of the bundled yt-dlp plugin; the generator must be the same version."""
    try:
        return importlib.metadata.version(PLUGIN_PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        return None


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "YTKTV"})
    with urlopen(request, timeout=60) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)


def _run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("errors", "replace")
    kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.run(command, **kwargs)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def self_check(report: Report = print) -> int:
    """Check that this build carries what the component needs (used by the release build).

    yt-dlp must be able to discover the bundled token-provider plugin and the
    challenge solver's JavaScript; both are easy to lose when the app is frozen.
    """
    problems = []
    try:
        from yt_dlp.extractor.youtube.pot import _registry
        from yt_dlp.plugins import load_all_plugins

        load_all_plugins()
        providers = set(_registry._pot_providers.value)
        report(f"token providers: {sorted(providers)}")
        if "BgUtilScriptDeno" not in providers:
            problems.append("the BgUtils token provider plugin was not discovered by yt-dlp")
    except Exception as exc:
        problems.append(f"could not load yt-dlp plugins: {exc}")
    try:
        import yt_dlp_ejs

        scripts = list(Path(yt_dlp_ejs.__file__).parent.rglob("*.js"))
        report(f"challenge solver scripts: {len(scripts)}")
        if not scripts:
            problems.append("the challenge solver's JavaScript files are missing")
    except Exception as exc:
        problems.append(f"the challenge solver package is missing: {exc}")
    report(f"plugin version: {plugin_version()}  deno target: {deno_target()}")
    if plugin_version() is None:
        problems.append("the plugin's package metadata is missing")
    for problem in problems:
        report(f"FAILED: {problem}")
    if not problems:
        report("OK")
    return 1 if problems else 0


class HdUnlock:
    def __init__(self, root: Path | None = None, system: str | None = None) -> None:
        self.root = root or data_dir() / "hd-unlock"
        self.system = system or platform.system()

    @property
    def deno(self) -> Path:
        return self.root / ("deno.exe" if self.system == "Windows" else "deno")

    @property
    def server_home(self) -> Path:
        return self.root / "server"

    @property
    def deno_dir(self) -> Path:
        return self.root / "deno-cache"

    def supported(self) -> bool:
        return plugin_version() is not None and deno_target(self.system) is not None

    def installed(self) -> bool:
        try:
            marker = json.loads((self.root / MARKER).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return (
            marker.get("revision") == REVISION
            and marker.get("plugin") == plugin_version()  # an app update may bring a new plugin
            and self.deno.exists()
            and (self.server_home / "src" / "generate_once.ts").exists()
        )

    def ytdlp_options(self) -> dict[str, Any]:
        """Extra yt-dlp options that route a request through the TV client with a PO token."""
        return {
            "js_runtimes": {"deno": {"path": str(self.deno)}},
            "extractor_args": {
                "youtube": {"player_client": [CLIENT]},
                "youtubepot-bgutilscript": {"server_home": [str(self.server_home)]},
            },
        }

    def activate(self) -> None:
        """Point Deno at our private cache; call before yt-dlp uses the component."""
        os.environ["DENO_DIR"] = str(self.deno_dir)

    def install(
        self, report: Report = lambda _line: None, fetch: Fetch = _download, run: Runner = _run
    ) -> None:
        """Download Deno and the token generator. Raises on failure, leaving nothing behind."""
        version = plugin_version()
        target = deno_target(self.system)
        if version is None or target is None:
            raise RuntimeError("HD unlock is not available on this platform")
        self.remove()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            report("Downloading the JavaScript runtime (Deno)...")
            archive = self.root / "deno.zip"
            fetch(f"{DENO_RELEASES}/deno-{target}.zip", archive)
            sums = self.root / "deno.zip.sha256sum"
            fetch(f"{DENO_RELEASES}/deno-{target}.zip.sha256sum", sums)
            expected = sums.read_text(encoding="utf-8", errors="replace").split()[0].lower()
            if _sha256(archive) != expected:
                raise RuntimeError("the Deno download is corrupt (checksum mismatch)")
            with zipfile.ZipFile(archive) as bundle:
                bundle.extract(self.deno.name, self.root)
            self.deno.chmod(self.deno.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            archive.unlink()
            sums.unlink()

            report("Downloading the token generator...")
            source = self.root / "provider.zip"
            fetch(f"https://github.com/{PROVIDER_REPO}/archive/refs/tags/{version}.zip", source)
            with zipfile.ZipFile(source) as bundle:
                prefix = next(n for n in bundle.namelist() if n.endswith("/server/"))
                for name in bundle.namelist():
                    if not name.startswith(prefix) or name.endswith("/"):
                        continue
                    target_file = self.server_home / name[len(prefix) :]
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    target_file.write_bytes(bundle.read(name))
            source.unlink()

            report("Installing its JavaScript packages (this takes a minute)...")
            env = dict(os.environ)
            env["DENO_DIR"] = str(self.deno_dir)
            command = [str(self.deno), "install", "--allow-scripts=npm:canvas", "--frozen"]
            result = run(command, cwd=str(self.server_home), env=env, timeout=30 * 60)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()[-500:]
                raise RuntimeError(f"installing the JavaScript packages failed: {detail}")

            marker = {"revision": REVISION, "plugin": version, "target": target}
            (self.root / MARKER).write_text(json.dumps(marker), encoding="utf-8")
        except BaseException:
            self.remove()
            raise

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
