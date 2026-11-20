"""Apply the two source patches to a pinned checkout or extracted upstream archives."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


SOURCE = Path(__file__).resolve().parents[1] / "source"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return path.read_bytes().replace(b"\r\n", b"\n") if path.exists() else None


def file_hash(path):
    content = read(path)
    return digest(content) if content is not None else None


def plan_component(label, destination, manifest, scratch):
    if not destination.is_dir():
        raise ValueError(f"Missing upstream directory: {destination}")
    patch = (SOURCE / (label + ".patch")).read_bytes().replace(b"\r\n", b"\n")
    if digest(patch) != manifest["patch_sha256"]:
        raise ValueError(f"Checksum mismatch in {label}.patch")
    scratch.mkdir()
    pending = {}
    for name, record in manifest["files"].items():
        path = (destination / name).resolve()
        path.relative_to(destination)
        installed = file_hash(path)
        if installed == record["after"]:
            continue
        if installed != record["before"]:
            raise ValueError(f"Unexpected contents in {path}. Expected upstream {manifest['revision']} or the applied patch.")
        staged = scratch / name
        staged.parent.mkdir(parents=True, exist_ok=True)
        if installed is not None:
            staged.write_bytes(read(path))
        pending[name] = path
    if not pending:
        return []
    # Limit changes to files still requiring the update so a partial installation
    # can be retried. All personal saves and other working-tree files stay outside.
    subprocess.run(["git", "init", "-q", str(scratch)], check=True)
    includes = [f"--include={name}" for name in pending]
    subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-C", str(scratch), "apply", "--whitespace=nowarn", *includes, "-"],
        input=patch, check=True,
    )
    plan = []
    for name, path in pending.items():
        staged = scratch / name
        record = manifest["files"][name]
        if file_hash(staged) != record["after"]:
            raise ValueError(f"Output checksum mismatch in {label}/{name}")
        plan.append((staged, path, record["before"]))
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("web_root", type=Path, help="Upstream Dream World folder containing game_sync_server")
    parser.add_argument("--check", action="store_true", help="Verify that all patches apply without updating the checkout")
    args = parser.parse_args()
    if not shutil.which("git"):
        parser.error("Git must be installed and available on PATH.")
    web = args.web_root.resolve()
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="dreamworld-source-") as temp:
        try:
            plan = []
            for label, destination in (("web", web), ("game-sync", web / "game_sync_server")):
                plan.extend(plan_component(label, destination, manifest[label], Path(temp) / label))
            if not args.check:
                for staged, path, old_hash in plan:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if file_hash(path) != old_hash:
                        raise ValueError(f"File changed during installation: {path}. Retry after checking your edits.")
                    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
                        temp_path = Path(output.name)
                    try:
                        shutil.copyfile(staged, temp_path)
                        if path.exists():
                            shutil.copymode(path, temp_path)
                        os.replace(temp_path, path)
                    finally:
                        temp_path.unlink(missing_ok=True)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            parser.exit(1, f"Source patch failed: {exc}\n")
    if args.check:
        print(f"Verified both source patches; {len(plan)} files would be updated.")
    else:
        print(f"Source patches ready; {len(plan)} files updated.")


if __name__ == "__main__":
    main()
