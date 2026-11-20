"""Read-only display of nicknames using the retail Generation V cartridge font."""

import json
import unicodedata

from config import ROOT_DIR

# Per-codepoint coverage distinguishes supported Japanese kanji and Korean syllables
# from unrenderable characters in the same Unicode blocks.
_coverage = json.loads((ROOT_DIR / "json_data/gen5_nickname_glyphs.json").read_text(encoding="utf8"))
_NICKNAME_CHARS = frozenset("".join(_coverage["characters"]))
# The cartridge uses circled 14/15 for the half-width male/female signs.
GENDER_SIGNS = {0x246D: "♂", 0x246E: "♀"}


def display_nickname(value: object, *, verified: bool = False) -> str | None:
    """Omit the whole nickname when any character cannot be displayed faithfully."""
    if not isinstance(value, str) or not value.strip():
        return None
    name = unicodedata.normalize("NFC", value.translate(GENDER_SIGNS))
    if any(ch not in _NICKNAME_CHARS for ch in name):
        return None
    # Older uploads replaced unknown glyphs with '?'. Bare runs are ambiguous without the original.
    if not verified and len(name) > 1 and name.strip("?") == "":
        return None
    return name
