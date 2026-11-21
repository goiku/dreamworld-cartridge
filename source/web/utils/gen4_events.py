"""Archived event cards, their cartridge wire format, and read-only Gen IV album inspection."""
import binascii
import hashlib
import re
import struct
from functools import cache

from game_sync_server.entralinked.model.save_file import BLOCK_POSITION, _crypt_array
from utils.data import load_json_data

REGIONS = {"J":"JPN", "E":"ENG", "P":"ENG", "D":"GER", "F":"FRE", "S":"SPA", "I":"ITA", "K":"KOR"}
EDITIONS = {"ADA":"D", "APA":"P", "CPU":"Pt", "IPK":"HG", "IPG":"SS"}
BITS = {"D":10, "P":11, "Pt":12, "HG":7, "SS":8}
LANG_IDS = {"J":1, "E":2, "P":2, "F":3, "I":4, "D":5, "S":7, "K":8}


@cache
def events():
    return load_json_data("gen4_event_cards")


def versions(event):
    # Tokenize Pt before P so a Platinum-only event cannot appear for Pearl.
    return re.findall("Pt|HG|SS|D|P", event["versions"])


def choose_individually(event, counts):
    # The Japanese Crown movie promotion offered a choice among three separate card IDs.
    return counts[event["number"]] > 1 or (
        event["path"].startswith("JPN/") and event["number"] in (59,60,61))


@cache
def selection(game):
    region = REGIONS[game[-1]]
    edition = EDITIONS.get(game[:-1])
    return {key: event for key,event in events().items()
            if event["path"].startswith(region + "/") and (not edition or edition in versions(event))}


def packet(raw, event):
    if len(raw) != 856 or int.from_bytes(raw[0x150:0x152], "little") != event["number"]:
        raise ValueError("Invalid Generation IV event card")
    card = bytearray(raw)
    if card[0] in (1, 2):
        pk = bytearray(card[8:244])
        pid, _, checksum = struct.unpack_from("<IHH", pk)
        if sum(struct.unpack_from("<64H", pk, 8)) & 65535 != checksum:
            raise ValueError("Invalid archived Pokémon checksum")
        shift = ((pid >> 13) & 31) * 4
        core = bytearray(128)
        for i, dest in enumerate(BLOCK_POSITION[shift:shift+4]):
            core[dest*32:dest*32+32] = pk[8+i*32:40+i*32]
        _crypt_array(core, checksum)
        tail = pk[136:]
        _crypt_array(tail, pid)
        card[16:244] = core + tail
    # The outer header controls the WFC offer. The original inner card is filed in the album.
    header = card[0x104:0x154]
    struct.pack_into("<I", header, 0x48, sum(1 << BITS[v] for v in versions(event)))
    return bytes(header + card)


def signature(card):
    # The slot index, share count and date change when a cartridge saves its card.
    return hashlib.sha256(card[:2] + card[4:0x348]).hexdigest()


def album(raw, game):
    """Read the active, checksum-valid general block; keep only identity and received card numbers."""
    if len(raw) != 0x80000:
        raise ValueError("Expected a 512 KiB Gen IV save")
    family = game[:3]
    if family in ("ADA","APA"):
        size, footer, trainer, offset, sentinels = 0xc100,0x14,0x64,0xa6d0,44
    elif family == "CPU":
        size, footer, trainer, offset, sentinels = 0xcf2c,0x14,0x68,0xb4c0,0
    else:
        size, footer, trainer, offset, sentinels = 0xf628,0x10,0x64,0x9d3c,0
    valid = []
    for base in (0,0x40000):
        block = raw[base:base+size]
        if (int.from_bytes(block[-12:-8],"little") != size
                or binascii.crc_hqx(block[:-footer],65535) != int.from_bytes(block[-2:],"little")):
            continue
        valid.append((struct.unpack_from("<II",block,size-20), block))
    if not valid:
        raise ValueError("Invalid general block")
    counts, block = valid[0]
    if len(valid) == 2:
        other, backup = valid[1]
        for a,b in zip(counts,other):
            if a != b:
                if (b > a) ^ (max(a,b) == 0xffffffff and min(a,b) != 0xfffffffe):
                    block = backup
                break
    if block[trainer+0x19] != LANG_IDS[game[-1]]:
        raise ValueError("Wrong save language")
    identity = hashlib.sha256(block[trainer:trainer+20]).hexdigest()
    flags = block[offset:offset+256]
    received = {str(i):"received" for i in range(1,2047) if flags[i//8] & (1 << (i%8))}
    pgt = offset+256+sentinels
    pending = {block[pgt+slot*260+2] & 3 for slot in range(8)
               if 1 <= int.from_bytes(block[pgt+slot*260:pgt+slot*260+2],"little") <= 14}
    for slot in range(3):
        start = pgt+8*260+slot*856
        num = int.from_bytes(block[start+0x150:start+0x152],"little")
        if 0 < num < 2047 and 1 <= block[start] <= 14:
            state = "pending_pickup" if slot in pending else "collected"
            received[str(num)] = state
            received[signature(block[start:start+856])] = state
    return identity, received
