"""Local Windows melonDS launcher for Gen V saves. Only the player chooses files."""
import binascii
import csv
import json
import os
from pathlib import Path
from queue import Empty, Queue
import shutil
import struct
import subprocess
import sys
import tempfile
from threading import Thread
import tomllib
import uuid
from contextlib import contextmanager, ExitStack


GAME = {b"IRA": 20, b"IRB": 21, b"IRD": 22, b"IRE": 23}
CONFIG = "游玩配置.json"


def checked_save(raw):
    """Validate every populated trainer, clock block and checksum table before editing."""
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
                or not crc(0x1D900, 0x5C) == word(0x1D95E) == word(table+74)):
            raise ValueError("存档数据校验失败，请重新导出完整的游戏内存档。")
        penalty = struct.unpack_from("<I", updated, base+0x1D944)[0]
        if penalty > 1440:
            raise ValueError("存档中的等待值超出已知范围。")
        waits.append(penalty)
        if penalty:
            struct.pack_into("<I", updated, base+0x1D944, 0)
            checksum = crc(0x1D900, 0x5C)
            set_word(0x1D95E, checksum)
            set_word(table+74, checksum)
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


def save_path(emulator, rom):
    portable = emulator.parent / "portable"
    config = (portable if portable.is_dir() else emulator.parent) / "melonDS.toml"
    if not portable.is_dir() and not config.is_file() and os.environ.get("LOCALAPPDATA"):
        # Non-portable Windows builds use Qt ConfigLocation/<melonDS>.
        config = Path(os.environ["LOCALAPPDATA"]) / "melonDS" / "melonDS" / "melonDS.toml"
    if not config.is_file():
        raise ValueError("请先打开 melonDS 1.1，配置网络，正常退出后再选择该程序。")
    with config.open("rb") as f:
        folder = tomllib.load(f).get("Instance0", {}).get("SaveFilePath", "")
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
                   "rom": name, "save": str(slot)}
        for path in (work / CONFIG, work / "中文游玩助手.pyw", work / "DreamWorld.cmd"):
            cleanup.callback(path.unlink, missing_ok=True)
        (work / CONFIG).write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.copyfile(__file__, work / "中文游玩助手.pyw")
        interpreter = Path(sys.executable).with_name("pythonw.exe")
        if not interpreter.is_file():
            interpreter = Path(sys.executable)
        command = str(interpreter).replace("%", "%%")
        (work / "DreamWorld.cmd").write_text(
            '@echo off\nsetlocal DisableDelayedExpansion\nchcp 65001 >nul\n'
            f'start "" "{command}" "%~dp0中文游玩助手.pyw"\n',
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
            raise ValueError("请先保存并退出另一个游玩助手启动的游戏。") from exc
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


def clear_for_tuck(slot, backup):
    raw = slot.read_bytes()
    cleared, waits = checked_save(raw)
    if any(waits):
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
            clear_for_tuck(slot, work / "上次清除等待前.sav")
        subprocess.run([str(emu), str(rom)], cwd=emu.parent, check=True)


def save_copy(root):
    from tkinter import filedialog, messagebox
    src = filedialog.askopenfilename(parent=root, title="选择自己的掌机存档备份", filetypes=[("原始存档", "*.sav")])
    if not src:
        return
    data, waits = checked_save(Path(src).read_bytes())
    if not any(waits):
        messagebox.showinfo("存档检查", "这份存档的换机／改时钟等待已经是零。", parent=root)
        return
    folder = filedialog.askdirectory(parent=root, title="选择新副本的保存目录")
    if folder:
        with tempfile.NamedTemporaryFile(prefix="解除等待-", suffix=".sav", dir=folder, delete=False) as f:
            f.write(data)
        messagebox.showinfo("已生成存档副本", "副本位置\n"+f.name, parent=root)


def main():
    from tkinter import Tk, filedialog, messagebox, ttk
    root = Tk()
    root.title("梦世界游玩助手")
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
                               ("选择能联网的同版本原版游戏", "*.nds"),
                               ("选择该玩家最新的游戏内存档", "*.sav")):
            picked = filedialog.askopenfilename(parent=root, title=label, filetypes=[(label, pattern)])
            if not picked:
                return
            chosen.append(Path(picked))
        parent = filedialog.askdirectory(parent=root, title="选择保存游玩助手和进度的文件夹")
        if parent:
            work = prepare(Path(parent), *chosen)
            messagebox.showinfo("共用进度已建立", "以后请从这个文件夹双击 DreamWorld.cmd\n"+str(work), parent=root)
            draw()

    def draw():
        for widget in box.winfo_children():
            widget.destroy()
        def note(s):
            ttk.Label(box, text=s, wraplength=455, justify="left").pack(fill="x", pady=4)
        def button(label, fn):
            ttk.Button(box, text=label, command=guard(fn)).pack(fill="x", pady=3)
        if (work / CONFIG).is_file():
            note("三个入口共用一份进度。切换前，在游戏内保存并退出模拟器。")
            button("平时游玩（汉化版）", lambda: start_game("regular"))
            button("申请入睡（原版）", lambda: start_game("sleep"))
            button("唤醒并领取（原版）", lambda: start_game("wake"))
        else:
            note("每位玩家选择自己的游戏和存档。首次设置会创建一份独立的游玩进度。")
            button("设置我的 melonDS 和存档", setup)
        note("下屏 Wi-Fi → ゲームシンク（游戏同步）。はい＝是，いいえ＝否。\n"
             "レポート＝保存。ねかしつける／ねむらせる＝让宝可梦入睡。おこす＝唤醒。")
        note("每次点「申请入睡」都会清除这份进度里的换机／改时钟等待，其他受同一计时器限制的活动也会解锁。"
             "实体卡带可导出备份，清除后恢复副本。")
        button("为掌机存档生成清除等待的副本", lambda: save_copy(root))
    draw()
    root.mainloop()


if __name__ == "__main__":
    main()
