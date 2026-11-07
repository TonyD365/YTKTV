"""Make the patch from the previous release's build to this one (used by release.yml).

    python scripts/make_patch.py patch OLD_DIR NEW_DIR OUT_DIR --app YTKTV \\
        --from 4.0.1 --to 4.0.2 --tag macos-arm64 --installer dist/YTKTV-...pkg
    python scripts/make_patch.py unpack-pkg PKG ARCH OUT_DIR   # prints the .app's path
    python scripts/make_patch.py verify OLD_DIR NEW_DIR PATCH.zip

verify applies the patch the way the app does (the same sh or PowerShell script) to a copy
of OLD_DIR, and checks the result is NEW_DIR file for file, byte for byte.

No patch is made across major versions, or when it would be more than half the
installer: then the installer is the only way to update, as before.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Loaded by path: the job that runs this has no YTKTV (or its dependencies) installed.
_spec = importlib.util.spec_from_file_location(
    "patching", Path(__file__).resolve().parents[1] / "src" / "ytktv" / "patching.py"
)
assert _spec and _spec.loader
patching = importlib.util.module_from_spec(_spec)
sys.modules["patching"] = patching
_spec.loader.exec_module(patching)


def unpack_pkg(pkg: Path, arch: str, out: Path) -> Path:
    """The .app inside a macOS package: the *arch* one of a universal package."""
    subprocess.run(["pkgutil", "--expand-full", str(pkg), str(out)], check=True)
    for pattern in (f"*-{arch}.pkg/Payload/*.app", "Payload/*.app"):
        found = sorted(out.glob(pattern))
        if found:
            return found[0]
    raise SystemExit(f"no app for {arch} in {pkg}")


def make(args: argparse.Namespace) -> int:
    if args.old_version.split(".")[0] != args.new_version.split(".")[0]:
        print("a new major version: no patch")
        return 0
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / patching.patch_name(args.app, args.old_version, args.new_version, args.tag)
    meta = {"app": args.app, "from": args.old_version, "to": args.new_version, "platform": args.tag}
    manifest = patching.make_patch(Path(args.old), Path(args.new), target, meta)
    size, limit = target.stat().st_size, Path(args.installer).stat().st_size // 2
    print(f"{target.name}: {len(manifest['changed'])} changed, {len(manifest['deleted'])} gone")
    print(f"{size // 2**20} MB (installer {limit * 2 // 2**20} MB)")
    if size > limit:
        print("more than half the installer: no patch")
        target.unlink()
    return 0


def verify(old: Path, new: Path, archive: Path) -> int:
    with tempfile.TemporaryDirectory() as work:
        root, staged, marker = Path(work) / "app", Path(work) / "staged", Path(work) / "failed"
        shutil.copytree(old, root, symlinks=True)
        manifest = patching.stage(archive, staged)
        if not patching.check_base(manifest, root):
            print(f"{archive.name}: the patch does not fit {old}")
            return 1
        if sys.platform == "win32":
            script = staged / "apply.ps1"
            text = patching.powershell_script(manifest, staged, root, marker, 2**22)
            # Not the app's last step: starting the patched app.
            text = "\n".join(
                line for line in text.splitlines() if not line.startswith("Start-Process")
            )
            script.write_text(text, encoding="utf-8-sig")
            command = [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ]
        else:
            script = staged / "apply.sh"
            script.write_text(patching.shell_script(manifest, staged, root, marker))
            command = ["/bin/sh", str(script)]
        subprocess.run(command, check=False, timeout=600)
        if marker.exists():
            print(f"{archive.name}: the patch failed: {marker.read_text().strip()}")
            return 1
        got, want = patching.scan(root), patching.scan(new)
        if got != want:
            wrong = sorted(
                set(got) ^ set(want) | {k for k in got.keys() & want.keys() if got[k] != want[k]}
            )
            print(f"{archive.name}: {len(wrong)} files differ from the new build, e.g. {wrong[:5]}")
            return 1
        print(f"{archive.name}: verified, {len(want)} files match the new build")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    patch = commands.add_parser("patch")
    patch.add_argument("old")
    patch.add_argument("new")
    patch.add_argument("out_dir")
    patch.add_argument("--app", required=True)
    patch.add_argument("--from", dest="old_version", required=True)
    patch.add_argument("--to", dest="new_version", required=True)
    patch.add_argument("--tag", required=True)
    patch.add_argument("--installer", required=True)
    unpack = commands.add_parser("unpack-pkg")
    unpack.add_argument("pkg")
    unpack.add_argument("arch")
    unpack.add_argument("out")
    check = commands.add_parser("verify")
    check.add_argument("old")
    check.add_argument("new")
    check.add_argument("patch")
    args = parser.parse_args()
    if args.command == "verify":
        return verify(Path(args.old), Path(args.new), Path(args.patch))
    if args.command == "unpack-pkg":
        print(unpack_pkg(Path(args.pkg), args.arch, Path(args.out)))
        return 0
    return make(args)


if __name__ == "__main__":
    raise SystemExit(main())
