"""Point just the owner's Flash title fields at the selected cartridge's trainer."""
from functools import lru_cache
import zlib


# Each context surrounds "getlex PDWHomeData; getproperty myPGLName" in a
# title renderer. The replacement reads PokemonBridge.player_name. The two
# operations occupy the same bytes, preserving branch targets and stack depth.
# Other reads of myPGLName (including map identity checks) are left alone.
TITLE_READS = {
    "pdw_garden.swf": ("601f66e502", "6026669206", [("152ccb154202", "46ca0a0285")]),
    "pdw_room.swf": ("602e66ee0d", "603366c010", [("66cb072c9529", "4fed1103f0")]),
    "pdw_farm.swf": ("60850166970f", "60870166b511", [
        ("6680032cc419", "4f991303d0"), ("66fd052cd81a", "4f991303d0")]),
    "pdw_share.swf": ("605766e109", "605866e40a", [("66ce032cc216", "4fe20d03d0")]),
}


@lru_cache(maxsize=4)
def trainer_titles(filename: str, movie: bytes) -> bytes:
    old, new, contexts = TITLE_READS[filename]
    compressed = movie[:3] == b"CWS"
    body = zlib.decompress(movie[8:]) if compressed else movie[8:]
    for before, after in contexts:
        pattern = bytes.fromhex(before + old + after)
        if body.count(pattern) != 1:
            # An independently rebuilt movie can have different constant indices.
            # Keep it playable without substituting unrelated instructions.
            return movie
        body = body.replace(pattern, bytes.fromhex(before + new + after))
    return movie[:8] + (zlib.compress(body) if compressed else body)
