from datetime import date
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.test_melonds_tuck_in import helper, save_fixture
from utils import player_dns


def test_dns_before_a_console_or_emulator_connects(monkeypatch):
    monkeypatch.setenv("DW_GAME_BIND", "127.0.0.1")
    monkeypatch.setenv("DW_WEB_LAN", "192.168.4.8/24")
    assert player_dns.get_player_dns("127.0.0.1")["address"] == "192.168.4.8"
    assert player_dns.get_player_dns("192.168.4.17", "192.168.4.8")["address"] == "192.168.4.8"
    assert player_dns.get_player_dns("127.75.2.1")["address"] is None
    assert player_dns.emulator_dns("127.0.0.1", "localhost")["address"] == "10.64.0.1"
    monkeypatch.setenv("DW_GAME_BIND", "192.168.4.9")
    assert player_dns.emulator_dns("127.0.0.1", "localhost")["address"] == "192.168.4.9"
    assert player_dns.emulator_dns("127.75.2.1", "localhost")["address"] is None


def test_tuck_web_matches_desktop_for_both_slots(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to run the browser module")
    static = Path(__file__).resolve().parents[1] / "static"
    cases = []
    for game in (20, 21, 22, 23):
        for today, previous, waits, asleep in [
            (date(2024, 3, 1), bytes([0, 2, 3, 19]), [1440, 0], [1]),
            (date(2000, 1, 1), bytes.fromhex("000101da"), [0], []),
            (date(2026, 5, 3), bytes.fromhex("000101da"), [0, 0], []),
            (date(2026, 5, 3), bytes.fromhex("000101da"), [0, 33], [0, 1]),
        ]:
            raw = save_fixture(game, waits, [previous] * len(waits), asleep=asleep)
            index = len(cases)
            output, _ = helper.checked_save(raw, today)
            (tmp_path / f"{index}.sav").write_bytes(raw)
            (tmp_path / f"{index}.expected").write_bytes(output)
            state = "prepared" if raw != output else ("asleep" if len(asleep) == len(waits) else "ready")
            cases.append([today.isoformat(), state])
    module = (static / "tuck-save.mjs").as_uri()
    script = """
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const {prepareTuckSave} = await import(process.argv[1]);
const cases = JSON.parse(process.argv[2]);
for (const [i, [date, expected]] of cases.entries()) {
    const file = readFileSync(i+'.sav'), before = Buffer.from(file);
    const {bytes, status} = prepareTuckSave(file, date);
    assert.equal(status, expected);
    assert.deepEqual(Buffer.from(bytes), readFileSync(i+'.expected'));
    assert.deepEqual(file, before);
    assert.notEqual(prepareTuckSave(bytes, date).status, 'prepared');
}
const broken = readFileSync('0.sav');
broken[0x24000 + 0x1d95e] ^= 1;
assert.throws(() => prepareTuckSave(broken, '2024-03-01'), /invalid/);
assert.throws(() => prepareTuckSave(broken, '2024-02-31'), /date/);
"""
    subprocess.run([node, "--input-type=module", "-e", script, module, json.dumps(cases)],
                   cwd=tmp_path, check=True)
