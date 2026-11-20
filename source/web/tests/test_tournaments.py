"""Use a throwaway save and independently construct the original B2/W2 PWT footer."""

import binascii
import hashlib
import shutil
import struct
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from api import tournaments
from api.server import create_app


def checksum(data):
    return binascii.crc_hqx(data, 0xFFFF)


def test_tournament_browser_and_verified_cache(tmp_path):
    page = create_app().test_client().get("/campaign/japan/tournaments/")
    rows = tournaments.catalog()
    assert page.status_code == 200 and len(rows) == 10
    assert len({row["number"] for row in rows.values()}) == 9
    assert all(sha.encode() in page.data for sha in rows)
    block = bytes(4884)
    sha = hashlib.sha1(b"blob 4884\0" + block).hexdigest()
    with patch.object(tournaments, "SAVE_DIR", tmp_path), patch.object(tournaments, "urlopen") as fetch:
        fetch.return_value.__enter__.return_value.read.return_value = block
        row = {"sha": sha, "file": "fixture.pwt"}
        assert tournaments.tournament_file(row) == block
        assert tournaments.tournament_file(row) == block and fetch.call_count == 1
        with pytest.raises(ValueError):
            tournaments.tournament_file(dict(row, sha="a" * 40))


@pytest.mark.skipif(not shutil.which("node"), reason="Browser-module check requires Node")
def test_install_preserves_other_slots_and_original(tmp_path):
    save = bytearray(0x80000)
    save[0x1941E:0x19420] = bytes((1, 23))
    save[0x70000:0x70004] = b"KEEP"
    for offset in (0x194B2, 0x25F36):
        struct.pack_into("<H", save, offset, checksum(save[0x19400:0x194B0]))
    struct.pack_into("<H", save, 0x25FA2, checksum(save[0x25F00:0x25F94]))
    original = tmp_path / "test.sav"
    original.write_bytes(save)
    block = bytearray(0x1314)
    struct.pack_into("<H", block, 8, 10001)
    crc = checksum(block[:0x1214])
    struct.pack_into("<HH", block, 0x1214, 1, crc)
    struct.pack_into("<4I", block, 0x1300, crc, 1, len(block), 0x31053527)
    struct.pack_into("<H", block, 0x1312, checksum(block[0x1300:0x1304]))
    (tmp_path / "event.pwt").write_bytes(block)
    module = (Path(__file__).resolve().parents[1] / "static/pwt-save.mjs").as_uri()
    script = tmp_path / "check.mjs"
    script.write_text(
        f'import {{inspect,install}} from "{module}";\n'
        + """
import assert from "node:assert/strict";
import fs from "node:fs";
const save=new Uint8Array(fs.readFileSync("test.sav")), file=new Uint8Array(fs.readFileSync("event.pwt"));
const output=install(save,file);
assert.equal(inspect(output)[0].number,10001);
assert.equal(inspect(save).filter(s=>s.empty).length,3);
assert.throws(()=>install(output,file),/already/);
fs.writeFileSync("copy.sav",output);
save[0x1941f]=21;
assert.throws(()=>inspect(save),/invalid/);
""",
        encoding="utf8",
    )
    subprocess.run(["node", script], cwd=tmp_path, check=True)
    output = (tmp_path / "copy.sav").read_bytes()
    assert output[0x7A000:0x7B314] == block
    allowed = {
        0x19452,
        0x19453,
        0x194A0,
        0x194A1,
        0x194A2,
        0x194A3,
        0x194B2,
        0x194B3,
        0x25F36,
        0x25F37,
        0x25FA2,
        0x25FA3,
    }
    assert all(
        i in allowed or 0x7A000 <= i < 0x7B314 for i, (a, b) in enumerate(zip(save, output, strict=True)) if a != b
    )
