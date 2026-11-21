"""Build a localized White Game Sync ROM from the player's two matching local files."""
import argparse
import hashlib
import mmap
import os
from pathlib import Path
import shutil
import struct
import tempfile


JAPANESE = "4c1532045e17a62b9bd36a2e99d51260145f7cf95b59774885131eb95de52c14"
CHINESE_21 = "902922a15d83304ac5e14af1a84ada1655affc6cfce7b4eb118362717e58238b"
# Only translated text, fonts and artwork. The wireless settings bundle (483)
# has the same internal names and 32 changed graphics, font or message resources.
ASSETS = (244, 245, 253, 265, 268, 320, 325, 330, 360, 366, 381, 462, 483)


def localize_sync_labels(blob):
    """Keep every original text slot, encryption key, control code and section offset."""
    data = bytearray(blob)
    names = 0x10 + struct.unpack_from("<I", data, 0x14)[0]
    image = names + struct.unpack_from("<I", data, names + 4)[0]
    if data[image:image+4] != b"GMIF":
        raise ValueError("无法识别汉化版的文字档案。")
    for bank, message, label in ((20, 3, "ＧａｍｅＳｙｎｃ"), (20, 11, "ＧＡＭＥＳＹＮＣ"),
                                 (22, 13, "ＧＡＭＥ　ＳＹＮＣ"), (39, 0, "ＧＡＭＥ　ＳＹＮＣ")):
        bank_pos = image + 8 + struct.unpack_from("<I", data, 0x1C + bank * 8)[0]
        for section in range(struct.unpack_from("<H", data, bank_pos)[0]):
            section_pos = bank_pos + struct.unpack_from("<I", data, bank_pos + 12 + section * 4)[0]
            offset, size = struct.unpack_from("<IH", data, section_pos + 4 + message * 8)
            at = section_pos + offset
            words = struct.unpack_from(f"<{size}H", data, at)
            keys = [0] * size
            key = words[-1] ^ 0xFFFF
            for i in reversed(range(size)):
                keys[i] = key
                key = ((key >> 3) | (key << 13)) & 0xFFFF
            text = "".join(chr(word ^ mask) for word, mask in zip(words, keys))
            if text.count(label) != 1:
                raise ValueError("这份汉化版的游戏同步文字不匹配。")
            text = text.replace(label, "游戏同步").ljust(size, "\uffff")
            struct.pack_into(f"<{size}H", data, at, *(ord(c) ^ mask for c, mask in zip(text, keys)))
    return data


def read_table(rom):
    start, size = struct.unpack_from("<II", rom, 0x48)
    return start, list(struct.iter_unpack("<II", rom[start:start+size]))


def build(japanese, chinese, output):
    if output.exists():
        raise FileExistsError("输出文件已存在，请另选新文件名。")
    with japanese.open("rb") as jp_file, chinese.open("rb") as cn_file:
        with mmap.mmap(jp_file.fileno(), 0, access=mmap.ACCESS_READ) as jp, mmap.mmap(
                cn_file.fileno(), 0, access=mmap.ACCESS_READ) as cn:
            if hashlib.sha256(jp).hexdigest() != JAPANESE or hashlib.sha256(cn).hexdigest() != CHINESE_21:
                raise ValueError("需要匹配的日版《白》和以它为底本的简体中文 2.1 版。")
            fat, src = read_table(jp)
            _, trans = read_table(cn)
            # The localized Wi-Fi settings artwork is larger. Store it in the
            # excess space of the shorter translated menu archive, before its original end.
            wifi = (src[244][0] + trans[244][1] - trans[244][0] + 511) & ~511
            tmp = None
            try:
                with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as f:
                    tmp = Path(f.name)
                    shutil.copyfileobj(jp_file, f, 1024 * 1024)
                    # Translation 2.1 mistakenly installed the localized a/0/4/3
                    # (47 files) at a/1/4/3 (28 files). Keep the JP sync archive,
                    # and return the localized artwork to its matching 47-file slot.
                    for dest, source in [(i, i) for i in ASSETS] + [(285, 385)]:
                        data = cn[slice(*trans[source])]
                        if dest == 244:
                            data = localize_sync_labels(data)
                        start, end = (wifi, src[244][1]) if dest == 483 else src[dest]
                        if start + len(data) > end:
                            raise ValueError("素材超出日版预留空间。")
                        f.seek(start)
                        f.write(data)
                        f.seek(fat + dest * 8)
                        f.write(struct.pack("<II", start, start + len(data)))
                    f.flush()
                    os.fsync(f.fileno())
                if os.name == "nt":
                    tmp.rename(output)  # Fails if another process created the destination.
                else:
                    os.link(tmp, output)
            finally:
                if tmp:
                    tmp.unlink(missing_ok=True)


def main():
    import sys
    if len(sys.argv) == 1:
        from tkinter import Tk, filedialog, messagebox
        root = Tk()
        root.withdraw()
        try:
            opts = {"parent": root, "filetypes": [("NDS 游戏", "*.nds")]}
            jp = filedialog.askopenfilename(title="选择未修改的日版《白》", **opts)
            if not jp:
                return
            cn = filedialog.askopenfilename(title="选择简体中文版《白》2.1", **opts)
            if not cn:
                return
            out = filedialog.asksaveasfilename(title="保存新的汉化同步修复版", defaultextension=".nds",
                                               initialfile="宝可梦 白（游戏同步修复版）.nds", **opts)
            if out:
                build(Path(jp), Path(cn), Path(out))
                messagebox.showinfo("已生成修复版", str(out), parent=root)
        except (ValueError, OSError) as exc:
            messagebox.showerror("无法生成修复版", str(exc), parent=root)
        finally:
            root.destroy()
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("japanese", type=Path, help="unmodified Japanese Pokémon White")
    parser.add_argument("chinese", type=Path, help="Simplified Chinese White v2.1")
    parser.add_argument("output", type=Path, help="a new .nds path")
    args = parser.parse_args()
    try:
        build(args.japanese, args.chinese, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
