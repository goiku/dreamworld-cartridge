"""Build the browser assets against the pinned upstream mirror."""
import argparse
import bz2
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
import zlib


HERE = Path(__file__).resolve().parent
RUFFLE_URL = "https://github.com/ruffle-rs/ruffle/releases/download/v0.7.1/ruffle-0.7.1-web-selfhosted.zip"
RUFFLE_HASH = "ef12edbee135d581a9cd523837d746da30a07a64dbf1cf472d2e472c656f4b5e"
FONT_URL = (
    "https://raw.githubusercontent.com/google/fonts/a85815a42757630ce188fdad368c2dfc444d4773/"
    "ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"
)
FONT_BLOB = "fb0637bafbcd804fe32152370a1225990745b4bc"


def read_json(path):
    return json.loads(path.read_text("utf-8"))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def require_hash(data, digest, path):
    if sha256(data) != digest:
        raise ValueError(f"File differs from the expected version: {path}")


def write_file(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(data)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "dreamworld-asset-builder"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def font_file(supplied, temporary):
    if supplied:
        return supplied.resolve(strict=True)
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/NotoSansSC-VF.ttf"
    if os.name == "nt" and windows.is_file():
        return windows
    data = download(FONT_URL)
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()
    if blob != FONT_BLOB:
        raise ValueError("Unexpected Noto Sans SC font download")
    result = temporary / "NotoSansSC.ttf"
    result.write_bytes(data)
    return result


def localize_text(assets):
    # Compute outputs before writing. Some translations share a base with a JS repair.
    updates = []
    for entry in read_json(HERE / "text-manifest.json"):
        destination = assets / entry["output"]
        if "file" in entry:
            updates.append((destination, (HERE / entry["file"]).read_bytes()))
            continue
        if destination.is_file():
            current = destination.read_text("utf-8-sig").encode()
            if sha256(current) == entry["text_sha256"]:
                continue
        original = (assets / entry["base"]).read_text("utf-8-sig")
        require_hash(original.encode(), entry["base_sha256"], entry["base"])
        position = 0
        parts = []
        for start, end, replacement in read_json(HERE / entry["edits"]):
            if not position <= start <= end <= len(original):
                raise ValueError(f"Overlapping edits in {entry['edits']}")
            parts.extend([original[position:start], replacement])
            position = end
        parts.append(original[position:])
        data = "".join(parts).encode()
        require_hash(data, entry["text_sha256"], destination)
        updates.append((destination, data))
    for destination, data in updates:
        write_file(destination, data)


def signed_offset(buffer):
    number = int.from_bytes(buffer, "little")
    return -(number & ((1 << 63) - 1)) if number >> 63 else number


def apply_delta(original, patch):
    # BSDIFF40 stores three bzip2 streams: triples of offsets, byte additions and inserts.
    if patch[:8] != b"BSDIFF40":
        raise ValueError("Invalid BSDIFF40 header")
    a, b, size = (signed_offset(patch[i:i+8]) for i in (8, 16, 24))
    control = bz2.decompress(patch[32:32+a])
    diffs = bz2.decompress(patch[32+a:32+a+b])
    extras = bz2.decompress(patch[32+a+b:])
    result = bytearray()
    reference = diff_pos = extra_pos = 0
    for off in range(0, len(control), 24):
        length, insert, skip = (signed_offset(control[i:i+8]) for i in range(off, off+24, 8))
        for i, byte in enumerate(diffs[diff_pos:diff_pos+length], reference):
            result.append((byte + (original[i] if 0 <= i < len(original) else 0)) % 256)
        result.extend(extras[extra_pos:extra_pos+insert])
        diff_pos += length
        extra_pos += insert
        reference += length + skip
    if len(result) != size:
        raise ValueError("BSDIFF40 output has unexpected length")
    return bytes(result)


def patch_client(root, assets):
    for entry in read_json(HERE / "swf-manifest.json"):
        source = (assets / entry["base"]).read_bytes()
        raw = source[:8] + (zlib.decompress(source[8:]) if source.startswith(b"CWS") else source[8:])
        require_hash(raw, entry["base_sha256"], entry["base"])
        fixed = apply_delta(raw, (HERE / entry["delta"]).read_bytes())
        require_hash(fixed, entry["result_sha256"], entry["output"])
        data = fixed[:8] + (zlib.compress(fixed[8:], 9) if fixed.startswith(b"CWS") else fixed[8:])
        write_file(root / entry["output"], data)


def install_ruffle(assets, supplied, temporary):
    archive = supplied or temporary / "ruffle.zip"
    if not supplied:
        archive.write_bytes(download(RUFFLE_URL))
    require_hash(archive.read_bytes(), RUFFLE_HASH, archive)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():
            if Path(member).name != member:
                raise ValueError(f"Unexpected Ruffle archive member {member}")
            write_file(assets / "shared.pokemon-gl.com/_ruffle" / member, bundle.read(member))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("web_root", type=Path)
    parser.add_argument("--font", type=Path, help="Local Noto Sans SC variable TrueType font")
    parser.add_argument("--ruffle-archive", type=Path, help="Local pinned Ruffle 0.7.1 ZIP")
    parser.add_argument("--update-game-text", action="store_true",
                        help="Update Chinese minigames and tutorials in an existing installation")
    args = parser.parse_args()
    root = args.web_root.resolve(strict=True)
    assets = root / "dreamworld_assets"
    if not (root / "raw_text/zh/pokemon.txt").is_file():
        parser.error("Install the web source overlay before building its assets.")
    for path, expected in read_json(HERE / "binary-inputs.json").items():
        require_hash((assets / path).read_bytes(), expected, path)
    with tempfile.TemporaryDirectory() as scratch:
        temporary = Path(scratch)
        font = font_file(args.font, temporary)
        env = {**os.environ, "DW_BUILD_ROOT": str(root), "DW_BUILD_FONT": str(font),
               "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
        game_text = ("zhmoviecards.py", "zhgames.py", "game_art_zh.py", "tutorial_art_zh.py")
        if args.update_game_text:
            if not (assets / "zh.pokemon-gl.com/src/swf/pdw/assets/ja/xml/tutorial_strings.xml").is_file():
                parser.error("Run full setup once before updating the existing Chinese assets.")
            for name in game_text:
                subprocess.run([sys.executable, str(HERE / "recipes" / name)], env=env, check=True)
            return
        localize_text(assets)
        patch_client(root, assets)
        block = assets / "shared.pokemon-gl.com/src/swf/report/images/block.png"
        write_file(assets / "ko.pokemon-gl.com/src/swf/assets/global/images/block.png", block.read_bytes())
        for name in ("korean_report.py", "zhopening.py", "zhmoviecards.py",
                     "report-zh-sprites.py", "zhgames.py", "game_art_zh.py", "tutorial_art_zh.py", "build_fonts.py"):
            print(f"Building {name.removesuffix('.py')}", flush=True)
            subprocess.run([sys.executable, str(HERE / "recipes" / name)], env=env, check=True)
        install_ruffle(assets, args.ruffle_archive, temporary)
    print("Built the Dream World client, localized website, fonts and Ruffle player.")


if __name__ == "__main__":
    main()
