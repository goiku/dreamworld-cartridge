"""The visitor receives an encounter belonging to their own game, never an owner PK5."""
import struct

import pytest

from api import pdw_dreamland as dream
from api.island_adventure import _choose_content
from game_sync_server.entralinked.model.player.dream_data import DreamEncounter
from game_sync_server.entralinked.network.http.pgl_handler import _encounters
from utils.constants import Rom


def postcard(number, form=0):
    return {"island_id": "a"*64, "version": 1, "content": {
        "theme": 8, "board": [], "sleeper": {"pokemon_no": number, "form_no": form,
        "pokemon_nickname": "漢化\ufffd", "level": 100, "is_shiny": True}}}


@pytest.mark.parametrize("rom", list(Rom))
def test_guest_uses_own_version_and_catalog_not_owner_attributes(rom):
    player = {"rom_id": rom, "experiment_point": 99999, "player_badge_num": 8}
    sequel = rom in (Rom.BLACK_2, Rom.WHITE_2)
    versions = {(row["pokemon_no"], row["form_no"]): row for region, slots in dream._DREAMLAND["areas"].items()
                if (int(region) > 100) == sequel for slot in slots for row in dream._SLOTS[slot]["contents"]
                if "pokemon_no" in row}
    for species, form in [*versions, (650, 0), (173, 17)]:
        card = postcard(species, form)
        row = _choose_content(card, player)
        pair = row["pokemon_no"], row["form_no"]
        if (species, form) in versions:
            assert pair == (species, form)
        assert pair in versions
        assert row == _choose_content(card, player)
        move = dream._special_move(row, 3)
        assert move is None or move in row["special_moves"]
        transfer = dream._ds_encounter({"object_id": row["object_pokemon_id"], "move": move})
        assert set(transfer) == {"species", "form", "move", "gender", "animation"}
        packet = _encounters([DreamEncounter(**transfer)])
        assert struct.unpack("<HHBBBB", packet[:8]) == (row["pokemon_no"], move or 0, row["form_no"],
                                                       transfer["gender"], row["action_type"], 0)
        assert not any(packet[8:])
