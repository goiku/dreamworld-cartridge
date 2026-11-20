"""Build a fresh Dream World installation from the published source patches."""

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.error import URLError
from urllib.request import Request, urlopen


RELEASE = Path(__file__).resolve().parent
SOURCE = json.loads((RELEASE / "source" / "manifest.json").read_text(encoding="utf-8"))
WEB = ("dreamworld-reawakened", SOURCE["web"]["revision"])
SYNC = ("game-sync-python", SOURCE["game-sync"]["revision"])
ASSETS = ("dreamworld-assets", "6e0550dab8552cd54bd976d4023f9ec0c43f6d7c")


@contextmanager
def archive_stream(project, revision, archive):
    if archive is not None:
        with archive.open("rb") as stream:
            yield stream
        return
    url = f"https://codeload.github.com/minibug1021/{project}/tar.gz/{revision}"
    request = Request(url, headers={"User-Agent": "dreamworld-cartridge-setup"})
    with urlopen(request, timeout=90) as stream:
        yield stream


def install_upstream(spec, destination, archive=None):
    project, revision = spec
    marker = destination / ".dreamworld-source-revision"
    if marker.is_file() and marker.read_text("ascii").strip() == revision:
        return
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"Choose a fresh runtime directory. Existing contents found at {destination}.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Preparing {project} at {revision[:10]} ...", flush=True)
    with tempfile.TemporaryDirectory(prefix=".dreamworld-stage-", dir=destination.parent) as folder:
        stage = Path(folder) / "contents"
        stage.mkdir()
        prefix = f"{project}-{revision}"
        count = 0
        expanded = 0
        next_report = 256 * 1024 * 1024
        with archive_stream(project, revision, archive) as stream, tarfile.open(fileobj=stream, mode="r|gz") as tar:
            for item in tar:
                parts = item.name.rstrip("/").split("/")
                if parts[0] != prefix or any(p in ("", ".", "..") or "\\" in p or ":" in p for p in parts):
                    raise ValueError(f"Unexpected path in the {project} archive: {item.name}")
                path = stage.joinpath(*parts[1:])
                if item.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                elif item.isfile():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(item) as source, path.open("wb") as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                    count += 1
                    expanded += item.size
                    if expanded >= next_report:
                        print(f"  {project}: {expanded // (1024 * 1024)} MiB unpacked", flush=True)
                        next_report = expanded + 256 * 1024 * 1024
                else:
                    raise ValueError(f"Unexpected entry type in the {project} archive: {item.name}")
        if not count:
            raise ValueError(f"No files in the {project} archive.")
        (stage / marker.name).write_text(revision + "\n", encoding="ascii")
        if destination.exists():
            destination.rmdir()  # An empty submodule directory from the outer archive.
        stage.rename(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=RELEASE / "runtime", help="Fresh installation directory")
    parser.add_argument("--assets-archive", type=Path, help="Previously downloaded GitHub tar.gz of the pinned assets revision")
    parser.add_argument("--ruffle-archive", type=Path, help="Previously downloaded matching Ruffle self-hosted ZIP")
    args = parser.parse_args()
    uv = shutil.which("uv")
    if not uv or not shutil.which("git"):
        parser.exit(1, "Install uv and Git, then reopen your terminal and run setup again.\n")
    runtime = args.destination.resolve()
    if args.assets_archive and not args.assets_archive.is_file():
        parser.error("The supplied asset archive does not exist.")
    if args.ruffle_archive and not args.ruffle_archive.is_file():
        parser.error("The supplied Ruffle ZIP does not exist.")
    try:
        install_upstream(WEB, runtime)
        install_upstream(SYNC, runtime / "game_sync_server")
        install_upstream(ASSETS, runtime / "dreamworld_assets", args.assets_archive)
        subprocess.run([sys.executable, str(RELEASE / "tools" / "apply-source.py"), str(runtime)], check=True)
        builder = [uv, "run", "--no-project", "--python", "3.13",
                   "--with", "pillow==13.0.0", "--with", "fonttools==4.68.0",
                   "python", str(RELEASE / "assets-build" / "build.py"), str(runtime)]
        if args.ruffle_archive:
            builder.extend(["--ruffle-archive", str(args.ruffle_archive.resolve())])
        subprocess.run(builder, check=True)
        print(f"Ready at {runtime}. Follow the cartridge guide in the README.")
    except (ValueError, OSError, EOFError, URLError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Setup stopped: {exc}\nCorrect the reported problem and run the same command again.\n")


if __name__ == "__main__":
    main()
