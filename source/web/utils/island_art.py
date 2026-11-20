"""Use the house icons packaged with the original site's furniture catalogue."""
import struct
import zlib
from functools import lru_cache

from utils.assets import SHARED_DIR
from utils.decor import CATALOG, DecorCategory

_ART = SHARED_DIR / "src/swf/theme/assets/global/parts/interior"


def _png(width: int, height: int, rgba: bytes | bytearray) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    stride = width * 4
    rows = b"".join(b"\0" + rgba[i:i+stride] for i in range(0, len(rgba), stride))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 4)) + chunk(b"IEND", b""))


@lru_cache(maxsize=16)
def house_thumbnail(item_id: int) -> tuple[bytes, str]:
    house = CATALOG.get(item_id)
    if not house or house.category_id != DecorCategory.HOUSE:
        raise FileNotFoundError
    raw = (_ART / f"{item_id}thumb.swf").read_bytes()
    data = zlib.decompress(raw[8:]) if raw[:3] == b"CWS" else raw[8:]
    offset = (5 + (data[0] >> 3) * 4 + 7) // 8 + 4
    while offset + 2 <= len(data):
        tag = int.from_bytes(data[offset:offset + 2], "little")
        size = tag & 63
        offset += 2
        if size == 63:
            size = int.from_bytes(data[offset:offset + 4], "little")
            offset += 4
        block = data[offset:offset + size]
        offset += size
        kind = tag >> 6
        if kind in (21, 35):
            end = 6 + int.from_bytes(block[2:6], "little")
            jpeg = block[6:end] if kind == 35 else block[2:]
            return jpeg.removeprefix(bytes.fromhex("ffd9")), "image/jpeg"
        if kind == 36 and block[2] == 5:
            w, h = struct.unpack_from("<HH", block, 3)
            argb = zlib.decompress(block[7:])
            if len(argb) != w * h * 4:
                raise ValueError("Invalid catalogue thumbnail")
            rgba = bytearray(len(argb))
            rgba[0::4], rgba[1::4], rgba[2::4], rgba[3::4] = argb[1::4], argb[2::4], argb[3::4], argb[0::4]
            return _png(w, h, rgba), "image/png"
    raise FileNotFoundError
