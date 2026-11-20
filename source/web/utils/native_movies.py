"""Read-only visit entry points for two original movies, using the installed shared assets."""
import hashlib
import zlib
from functools import lru_cache

from config import ROOT_DIR
from utils.assets import SHARED_DIR
from utils.data import load_json_data


@lru_cache(maxsize=2)
def visit_movie(name: str) -> bytes:
    # Both movies construct sibling asset URLs from their own path. They are served
    # at their normal location with a visit query parameter in every language.
    source = (ROOT_DIR / "patches/main.patched.swf" if name == "main" else
              SHARED_DIR / "src/swf/pdw/assets/pdw_main.swf").read_bytes()
    patch = load_json_data("island_movie_patch")[name]
    uncompressed = source[:8] + (zlib.decompress(source[8:]) if source[:3] == b"CWS" else source[8:])
    if hashlib.sha256(uncompressed).hexdigest() != patch["input"]:
        raise ValueError(f"Unsupported {name} movie revision")
    result = b"".join(bytes.fromhex(segment) if isinstance(segment, str) else
                      uncompressed[segment[0]:segment[0]+segment[1]] for segment in patch["spans"])
    if hashlib.sha256(result).hexdigest() != patch["output"]:
        raise ValueError(f"Invalid {name} movie patch")
    return result[:8] + (zlib.compress(result[8:]) if result[:3] == b"CWS" else result[8:])
