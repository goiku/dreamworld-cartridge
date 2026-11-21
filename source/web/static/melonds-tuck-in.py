"""Local Windows melonDS launcher for Gen V saves. Only the player chooses files."""
import binascii
import csv
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from threading import Thread
import tomllib
import uuid
from contextlib import contextmanager, ExitStack


GAME = {b"IRA": 20, b"IRB": 21, b"IRD": 22, b"IRE": 23}
CONFIG = "游玩配置.json"
PROGRAM = "解除睡眠限制.pyw"
OLD_PROGRAM = "中文游玩助手.pyw"
REPAIRED_WHITE = "f96ba764ed6033f1f39e189a02eca579fb6369eb94fcaef916084b4a6c65903b"


def available_sync_date(packed, today):
    """Game Sync compares day-of-year, including for its initial 0xDA010100 date."""
    weekday, day, month, year = packed
    if packed == b"\x00\x01\x01\xda":
        previous = date(2001, 1, 1)
    else:
        if year > 99 or weekday > 6:
            raise ValueError("存档中的游戏同步日期无法识别。")
        previous = date(2000 + year, month, day)
    if previous.timetuple().tm_yday != today.timetuple().tm_yday:
        return packed
    yesterday = today - timedelta(days=1) if today != date(2000, 1, 1) else date(2099, 12, 31)
    return bytes((yesterday.isoweekday() % 7, yesterday.day, yesterday.month, yesterday.year - 2000))


def checked_save(raw, today=None):
    """Validate each populated slot before preparing any bytes for writing."""
    if today is not None and not 2000 <= today.year <= 2099:
        raise ValueError("请使用掌机支持的日期（2000 至 2099 年）。")
    if len(raw) != 0x80000:
        raise ValueError("请选择游戏内保存的 512 KiB 原始 .sav 文件。")
    game = raw[0x1941F]
    if game not in GAME.values():
        raise ValueError("无法识别《黑／白／黑2／白2》的训练家数据。")
    sequel = game in (22, 23)
    stride, table, table_len, table_sum, trainer_len = (
        (0x26000, 0x25F00, 0x94, 0x25FA2, 0xB0) if sequel
        else (0x24000, 0x23F00, 0x8C, 0x23F9A, 0x68)
    )
    updated = bytearray(raw)
    waits = []
    for base in (0, stride):
        if base and raw[base:base+stride] in (bytes(stride), b"\xff" * stride):
            continue
        def crc(start, size):
            return binascii.crc_hqx(updated[base+start:base+start+size], 0xFFFF)
        def word(start):
            return struct.unpack_from("<H", updated, base+start)[0]
        def set_word(start, value):
            struct.pack_into("<H", updated, base+start, value)
        if (updated[base+0x1941F] != game
                or crc(table, table_len) != word(table_sum)
                or not crc(0x19400, trainer_len) == word(0x19400+trainer_len+2) == word(table+54)
                or not crc(0x1D300, 0x1AC) == word(0x1D4AE) == word(table+70)
                or not crc(0x1D900, 0x5C) == word(0x1D95E) == word(table+74)):
            raise ValueError("存档数据校验失败，请重新导出完整的游戏内存档。")
        penalty = struct.unpack_from("<I", updated, base+0x1D944)[0]
        if penalty > 1440:
            raise ValueError("存档中的等待值超出已知范围。")
        waits.append(penalty)
        # Never change a slot's in-progress tuck-in, including its clock data.
        if updated[base+0x1D4A3]:
            continue
        sync_date = raw[base+0x1D300:base+0x1D304]
        next_date = available_sync_date(sync_date, today) if today is not None else sync_date
        if next_date != sync_date:
            updated[base+0x1D300:base+0x1D304] = next_date
            checksum = crc(0x1D300, 0x1AC)
            set_word(0x1D4AE, checksum)
            set_word(table+70, checksum)
        if penalty:
            struct.pack_into("<I", updated, base+0x1D944, 0)
            checksum = crc(0x1D900, 0x5C)
            set_word(0x1D95E, checksum)
            set_word(table+74, checksum)
        if penalty or next_date != sync_date:
            set_word(table_sum, crc(table, table_len))
    return bytes(updated), waits


def atomic_write(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        swap = Path(f.name)
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        except BaseException:
            f.close()
            swap.unlink(missing_ok=True)
            raise
    try:
        os.replace(swap, path)
    finally:
        swap.unlink(missing_ok=True)


def game_code(path):
    with path.open("rb") as f:
        f.seek(12)
        return f.read(4)


def is_repaired_white(path):
    if game_code(path) != b"IRAJ" or path.stat().st_size != 0x10000000:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == REPAIRED_WHITE


def use_repaired_white(work, path):
    profile = work / CONFIG
    cfg = json.loads(profile.read_text(encoding="utf-8"))
    if game_code(Path(cfg["regular"])) != b"IRAJ" or not is_repaired_white(path):
        raise ValueError("请选择为日版《白》简体中文 2.1 生成的游戏同步修复版。")
    cfg.update(regular=str(path), sync=str(path), chinese_sync=True)
    atomic_write(profile, json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8"))


def instance_settings(emulator):
    portable = emulator.parent / "portable"
    config = (portable if portable.is_dir() else emulator.parent) / "melonDS.toml"
    if not portable.is_dir() and not config.is_file() and os.environ.get("LOCALAPPDATA"):
        # Non-portable Windows builds use Qt ConfigLocation/<melonDS>.
        config = Path(os.environ["LOCALAPPDATA"]) / "melonDS" / "melonDS" / "melonDS.toml"
    if not config.is_file():
        raise ValueError("请先打开 melonDS 1.1，配置网络，正常退出后再选择该程序。")
    with config.open("rb") as f:
        return tomllib.load(f).get("Instance0", {})


def save_path(emulator, rom):
    folder = instance_settings(emulator).get("SaveFilePath", "")
    dest = (emulator.parent / folder).resolve() if folder else rom.parent
    return dest / rom.with_suffix(".sav").name


def prepare(parent, emulator, regular, sync, saved):
    data = saved.read_bytes()
    checked_save(data)
    code = game_code(sync)
    if GAME.get(code[:3]) != data[0x1941F] or game_code(regular) != code:
        raise ValueError("两个游戏文件要对应同一版本和地区，存档也要匹配该版本。")
    # A distinct basename also isolates players who configured a common save folder.
    name = "DW-" + uuid.uuid4().hex[:12] + ".nds"
    work = Path(tempfile.mkdtemp(prefix="梦世界游玩-", dir=parent))
    with ExitStack() as cleanup:
        cleanup.callback(work.rmdir)
        slot = save_path(emulator, work / name)
        slot.parent.mkdir(parents=True, exist_ok=True)
        with slot.open("xb") as f:
            cleanup.callback(slot.unlink, missing_ok=True)
            f.write(data)
        profile = {"emulator": str(emulator), "regular": str(regular), "sync": str(sync),
                   "rom": name, "save": str(slot), "chinese_sync": is_repaired_white(sync)}
        for path in (work / CONFIG, work / PROGRAM, work / "DreamWorld.cmd"):
            cleanup.callback(path.unlink, missing_ok=True)
        (work / CONFIG).write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.copyfile(__file__, work / PROGRAM)
        interpreter = Path(sys.executable).with_name("pythonw.exe")
        if not interpreter.is_file():
            interpreter = Path(sys.executable)
        command = str(interpreter).replace("%", "%%")
        (work / "DreamWorld.cmd").write_text(
            '@echo off\nsetlocal DisableDelayedExpansion\nchcp 65001 >nul\n'
            f'start "" "{command}" "%~dp0{PROGRAM}"\n',
            encoding="utf-8", newline="\r\n")
        cleanup.pop_all()
    return work


@contextmanager
def first_emulator():
    import msvcrt
    lock = Path(tempfile.gettempdir()) / "dreamworld-melonds-launch.lock"
    with lock.open("a+b") as f:
        if f.seek(0, 2) == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ValueError("请先保存并退出另一个窗口启动的游戏。") from exc
        try:
            result = subprocess.check_output(
                ["tasklist.exe", "/FI", "IMAGENAME eq melonDS.exe", "/FO", "CSV", "/NH"],
                creationflags=subprocess.CREATE_NO_WINDOW)
            rows = csv.reader(result.decode("mbcs", errors="replace").splitlines())
            if any(row and row[0].lower() == "melonds.exe" for row in rows):
                raise ValueError("请先在已打开的 melonDS 中保存并退出，再切换版本。")
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def clear_for_tuck(slot, backup, today=None):
    raw = slot.read_bytes()
    cleared, waits = checked_save(raw, today or date.today())
    if raw != cleared:
        atomic_write(backup, raw)
        atomic_write(slot, cleared)
    return waits


def launch(work, mode):
    cfg = json.loads((work / CONFIG).read_text(encoding="utf-8"))
    source_key = {"regular": "regular", "sleep": "sync", "wake": "sync"}[mode]
    emu, source, slot = (Path(cfg[key]) for key in ("emulator", source_key, "save"))
    rom = work / cfg["rom"]
    with first_emulator():
        if slot != save_path(emu, rom):
            raise ValueError("melonDS 存档目录已改变。请恢复之前的目录，或用最新进度重新配置。")
        raw = slot.read_bytes()
        if len(raw) != 0x80000 or GAME.get(game_code(source)[:3]) != raw[0x1941F]:
            raise ValueError("当前游戏与进度版本不一致。")
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            link = Path(tmp) / "game.nds"
            try:
                os.link(source, link)
            except OSError:
                shutil.copyfile(source, link)
            os.replace(link, rom)
        if mode == "sleep":
            offset = instance_settings(emu).get("RTC", {}).get("Offset", 0)
            game_date = datetime.fromtimestamp(time.time() + offset).date()
            clear_for_tuck(slot, work / "上次清除等待前.sav", game_date)
        subprocess.run([str(emu), str(rom)], cwd=emu.parent, check=True)


def save_copy(root):
    from tkinter import filedialog, messagebox, simpledialog
    src = filedialog.askopenfilename(parent=root, title="选择自己的掌机存档备份", filetypes=[("原始存档", "*.sav")])
    if not src:
        return
    target = simpledialog.askstring("掌机日期", "请输入准备让宝可梦入睡当天的掌机日期（年-月-日）",
                                    initialvalue=date.today().isoformat(), parent=root)
    if target is None:
        return
    original = Path(src).read_bytes()
    data, _ = checked_save(original, date.fromisoformat(target.strip()))
    if data == original:
        messagebox.showinfo("存档检查", "所选日期没有需要解除的入睡等待。已入睡的宝可梦可照常唤醒。", parent=root)
        return
    folder = filedialog.askdirectory(parent=root, title="选择新副本的保存目录")
    if folder:
        with tempfile.NamedTemporaryFile(prefix="解除等待-", suffix=".sav", dir=folder, delete=False) as f:
            f.write(data)
        messagebox.showinfo("已生成存档副本", "副本位置\n"+f.name, parent=root)


def update_profile_program(folder):
    cfg = json.loads((folder / CONFIG).read_text(encoding="utf-8"))
    old, current = folder / OLD_PROGRAM, folder / PROGRAM
    if not (old.is_file() or current.is_file()) or not (folder / "DreamWorld.cmd").is_file() or not Path(cfg["save"]).is_file():
        raise ValueError("请选择之前设置过的游玩文件夹。")
    atomic_write(current, Path(__file__).read_bytes())
    if old.is_file():
        # Older shortcuts and DreamWorld.cmd may still point to the first filename.
        shim = f'from pathlib import Path\nimport runpy\nrunpy.run_path(str(Path(__file__).with_name("{PROGRAM}")), run_name="__main__")\n'
        atomic_write(old, shim.encode("utf8"))


def main():
    from tkinter import Tk, filedialog, messagebox, ttk
    root = Tk()
    root.title("解除睡眠限制")
    root.resizable(False, False)
    box = ttk.Frame(root, padding=18)
    box.pack()
    work = Path(__file__).resolve().parent
    results = Queue()
    playing = False

    def start_game(mode):
        nonlocal playing
        if playing:
            messagebox.showinfo("游戏正在运行", "请先在游戏内保存并退出，再切换版本。", parent=root)
            return
        playing = True
        def worker():
            try:
                launch(work, mode)
            except Exception as exc:
                results.put(str(exc))
            else:
                results.put("")
        Thread(target=worker).start()
        root.after(300, poll)

    def poll():
        nonlocal playing
        try:
            error = results.get_nowait()
        except Empty:
            root.after(300, poll)
            return
        playing = False
        if error:
            messagebox.showerror("无法启动游戏", error, parent=root)

    def guard(fn):
        def run():
            try:
                fn()
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
                messagebox.showerror("无法继续", str(exc), parent=root)
        return run

    def setup():
        nonlocal work
        chosen = []
        for label, pattern in (("选择平时用的 melonDS.exe", "melonDS.exe"),
                               ("选择平时玩的游戏（可以是汉化版）", "*.nds"),
                               ("选择能联网的同版本原版或汉化修复版", "*.nds"),
                               ("选择该玩家最新的游戏内存档", "*.sav")):
            picked = filedialog.askopenfilename(parent=root, title=label, filetypes=[(label, pattern)])
            if not picked:
                return
            chosen.append(Path(picked))
        parent = filedialog.askdirectory(parent=root, title="选择保存「解除睡眠限制」和游戏进度的文件夹")
        if parent:
            work = prepare(Path(parent), *chosen)
            messagebox.showinfo("共用进度已建立", "以后请从这个文件夹双击 DreamWorld.cmd\n"+str(work), parent=root)
            draw()

    def use_existing():
        nonlocal work
        selected = filedialog.askdirectory(parent=root, title="选择已有 DreamWorld.cmd 的游玩文件夹")
        if not selected:
            return
        path = Path(selected)
        update_profile_program(path)
        work = path
        draw()

    def choose_repair():
        if playing:
            raise ValueError("请先在游戏内保存并退出。")
        choice = filedialog.askopenfilename(parent=root, title="选择《白》汉化同步修复版", filetypes=[("NDS 游戏", "*.nds")])
        if choice:
            use_repaired_white(work, Path(choice))
            draw()

    def draw():
        for widget in box.winfo_children():
            widget.destroy()
        def note(s):
            ttk.Label(box, text=s, wraplength=455, justify="left").pack(fill="x", pady=4)
        def button(label, fn):
            ttk.Button(box, text=label, command=guard(fn)).pack(fill="x", pady=3)
        if (work / CONFIG).is_file():
            cfg = json.loads((work / CONFIG).read_text(encoding="utf-8"))
            sync_version = "汉化修复版" if cfg.get("chinese_sync") else "原版"
            note("三个入口共用一份进度。切换前，在游戏内保存并退出模拟器。")
            button("平时游玩（汉化版）", lambda: start_game("regular"))
            button(f"申请入睡（{sync_version}）", lambda: start_game("sleep"))
            button(f"唤醒并领取（{sync_version}）", lambda: start_game("wake"))
            if not cfg.get("chinese_sync") and Path(cfg["regular"]).is_file() and game_code(Path(cfg["regular"])) == b"IRAJ":
                button("改用《白》汉化同步修复版", choose_repair)
        else:
            note("每位玩家选择自己的游戏和存档。首次设置会创建一份独立的游玩进度。")
            button("设置我的 melonDS 和存档", setup)
            button("更新「解除睡眠限制」", use_existing)
        note("下屏 Wi-Fi → ゲームシンク（游戏同步）。はい＝是，いいえ＝否。\n"
             "レポート＝保存。ねかしつける／ねむらせる＝让宝可梦入睡。おこす＝唤醒。")
        note("「申请入睡」会按游戏日期解除当天再次入睡的限制，也会清除换机／改时钟等待。其他受同一计时器限制的活动也会解锁。"
             "实体卡带可导出备份，清除后恢复副本。")
        button("为掌机存档生成清除等待的副本", lambda: save_copy(root))
    draw()
    root.mainloop()


if __name__ == "__main__":
    main()
