"""Exercise the local launcher on synthetic Gen V saves, without starting melonDS."""
from binascii import crc_hqx
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import struct

import pytest


helper_path = Path(__file__).resolve().parents[1] / "static/melonds-tuck-in.py"
spec = importlib.util.spec_from_file_location("melonds_tuck_in", helper_path)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


def save_fixture(game, waits):
    sequel = game in (22, 23)
    table, stride, table_crc = (0x25F00, 0x26000, 0x25FA2) if sequel else (0x23F00, 0x24000, 0x23F9A)
    table_length = 148 if sequel else 140
    trainer_length = 176 if sequel else 104
    raw = bytearray(512 * 1024)
    for index, minutes in enumerate(waits):
        base = index * stride
        raw[base + 0x1941F] = game
        raw[base + 0x18E00] = 4 + index
        struct.pack_into("<I", raw, base + 0x1D944, minutes)
        for pos, size, mirror in ((0x19400, trainer_length, 54), (0x1D900, 92, 74)):
            check = crc_hqx(raw[base+pos:base+pos+size], 0xffff)
            for offset in (pos + size + 2, table + mirror):
                struct.pack_into("<H", raw, base + offset, check)
        check = crc_hqx(raw[base+table:base+table+table_length], 0xffff)
        struct.pack_into("<H", raw, base+table_crc, check)
    return bytes(raw)


@pytest.mark.parametrize("game", [20, 21, 22, 23])
@pytest.mark.parametrize("waits", [[339, 1440], [0, 13], [5], [0]])
def test_all_titles_keep_every_other_byte(game, waits):
    original = save_fixture(game, waits)
    prepared, actual = helper.checked_save(original)
    assert actual == waits
    expected = save_fixture(game, [0] * len(waits))
    assert prepared == expected
    assert helper.checked_save(prepared) == (prepared, [0] * len(waits))


@pytest.mark.parametrize("offset", [0x19400, 0x1D944, 0x23F00, 0x24000+0x1D95E])
def test_corruption_is_rejected(offset, tmp_path):
    bad = bytearray(save_fixture(20, [73, 11]))
    bad[offset] ^= 64
    slot, undo = tmp_path / "game.sav", tmp_path / "before.sav"
    slot.write_bytes(bad)
    with pytest.raises(ValueError):
        helper.clear_for_tuck(slot, undo)
    assert slot.read_bytes() == bad and not undo.exists()


def test_two_players_each_keep_one_save_across_languages(tmp_path, monkeypatch):
    emulator = tmp_path / "melonDS.exe"
    emulator.touch()
    (tmp_path / "melonDS.toml").write_text('[Instance0]\nSaveFilePath = "saves"\n')
    args = [tmp_path / name for name in ("translation.nds", "original.nds", "player.sav")]
    regular, sync, original = args
    for index, rom in enumerate((regular, sync)):
        rom.write_bytes(bytes(12) + b"IRAJ" + bytes([index]))
    raw = save_fixture(20, [73, 24])
    original.write_bytes(raw)
    profile, other = (helper.prepare(tmp_path, emulator, *args) for _ in range(2))
    settings = json.loads((profile / helper.CONFIG).read_text("utf8"))
    slot = Path(settings["save"])
    other_slot = Path(json.loads((other / helper.CONFIG).read_text("utf8"))["save"])
    assert other_slot != slot
    monkeypatch.setattr(helper, "first_emulator", nullcontext)
    runs = []
    def record(argv, cwd, check):
        rom = Path(argv[1])
        runs.append((rom, rom.read_bytes(), slot.read_bytes()))
    monkeypatch.setattr(helper.subprocess, "run", record)
    for mode in ("regular", "wake", "sleep"):
        helper.launch(profile, mode)
    assert len({rom for rom, _, _ in runs}) == 1
    assert [game for _, game, _ in runs] == [regular.read_bytes(), sync.read_bytes(), sync.read_bytes()]
    assert [data for _, _, data in runs] == [raw, raw, save_fixture(20, [0, 0])]
    before = profile / "上次清除等待前.sav"
    assert before.read_bytes() == raw
    helper.launch(profile, "sleep")
    assert before.read_bytes() == raw
    advanced = save_fixture(20, [17, 2])
    slot.write_bytes(advanced)
    helper.launch(profile, "sleep")
    assert before.read_bytes() == advanced
    assert other_slot.read_bytes() == raw == original.read_bytes()


def test_wrong_size_wait_or_rom_is_rejected(tmp_path):
    for raw in (b"", save_fixture(20, [1441])):
        with pytest.raises(ValueError):
            helper.checked_save(raw)
    original = tmp_path / "B.sav"
    original.write_bytes(save_fixture(21, [1, 1]))
    rom = tmp_path / "W.nds"
    rom.write_bytes(bytes(12) + b"IRAJ")
    with pytest.raises(ValueError):
        helper.prepare(tmp_path, tmp_path / "melonDS.exe", rom, rom, original)
    assert not list(tmp_path.glob("梦世界游玩-*"))


def test_portable_settings_override_the_file_by_the_executable(tmp_path):
    emulator, rom = tmp_path / "melonDS.exe", tmp_path / "games/example.nds"
    (tmp_path / "portable").mkdir()
    for directory, folder in ((tmp_path, "old"), (tmp_path / "portable", "new")):
        (directory / "melonDS.toml").write_text(f'[Instance0]\nSaveFilePath = "{folder}"\n')
    assert helper.save_path(emulator, rom) == tmp_path / "new/example.sav"
