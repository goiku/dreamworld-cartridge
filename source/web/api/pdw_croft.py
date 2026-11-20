"""pdw.croft.*: the Berry garden (pdw_farm.swf)."""
from werkzeug.exceptions import BadRequest

from api import native_islands
from api.pdw_dreamland import _require_playing
from api.pdw_home import STARTER_BERRY_IDS
from api.routes import GET_AND_POST, Query, endpoint
from game_sync_server.entralinked.model.player.starting_save import GARDEN_COLUMNS, GARDEN_ROWS
from game_sync_server.entralinked.utility.db_manager import db
from utils import managers, save_data, text, visits
from utils.berries import to_berry_id
from utils.constants import WATERINGCAN_ID
from utils.decor import get_decor, owned_wateringcans
from utils.models import CropData


@endpoint("pdw.croft.my_croft_list")
def my_croft_list(_query: Query) -> CropData:
    """Return the player's Berry garden, after growing the Berries and checking for an expansion."""
    gscd = save_data.require_gscd()
    if not (db.read(gscd, "crop_data") or {}).get("croft_list"):
        return {"croft_list": [], "diglett_flag": 0}
    crops = managers.get_crops(gscd)
    crops.process_berry_growth()
    crops.check_garden_expansion()
    return crops.data


@endpoint("pdw.croft.tutorial_start")
def tutorial_start(_query: Query) -> dict:
    """Describe the sample Berry without consuming or awarding items."""
    gscd = save_data.require_gscd()
    _require_playing(save_data.read_member(gscd))
    items = (db.read(gscd, "chest_data") or {}).get("list", [])
    berry = next((stack["pokeitem_id"] for stack in items if stack["pokeitem_id"] in STARTER_BERRY_IDS),
                STARTER_BERRY_IDS[0])
    desc1, desc2, desc3, *_ = text.lookup_description("item_descriptions", berry)
    return {"pokeitem_id": berry, "kinomi_id": to_berry_id(berry), "kinomi": text.lookup_str("item", berry),
            "desc1": desc1, "desc2": desc2, "desc3": desc3}


@endpoint("pdw.croft.tutorial_end")
def tutorial_end(_query: Query) -> dict:
    """Complete an old save's starter garden before the movie requests its plots again."""
    gscd = save_data.require_gscd()
    with db.transaction():
        _require_playing(save_data.read_member(gscd))
        garden = db.read(gscd, "crop_data") or {}
        plots = garden.get("croft_list") or []
        # The movie sends the tutorial requests only when the garden has zero or one plot.
        if len(plots) <= 1:
            occupied = {(plot["x"], plot["y"]) for plot in plots}
            missing = [(x, y) for y in range(1, GARDEN_ROWS + 1) for x in range(1, GARDEN_COLUMNS + 1)
                       if (x, y) not in occupied]
            ids = db.next_id("my_croft_id", len(missing))
            new_plots = [{"my_croft_id": plot_id, "x": x, "y": y} for plot_id, (x, y) in zip(ids, missing, strict=True)]
            db.update(gscd, "crop_data", lambda stored: stored.update(croft_list=plots + new_plots))
    return {}


@endpoint("pdw.croft.waterpot_list", methods=GET_AND_POST)
def wateringcan_list(_query: Query) -> dict:
    """Return the player's Watering Cans and which one is in use.

    IDs technically range from 1-6, but 2-6 were never implemented.
    """
    selected_id = save_data.read_member().get("wateringpot_id", WATERINGCAN_ID)
    wateringcans = owned_wateringcans()
    selected = next((can for can in wateringcans if can["interior_id"] == selected_id), wateringcans[0])
    return {
        "waterpot_list": [
            {
                "my_interior_id": can["my_interior_id"],
                "interior_id":    can["interior_id"],
                "selected_flag":  int(can is selected),
                "interior_name":  get_decor(can["interior_id"]).name,
            }
            for can in wateringcans
        ]
    }


@endpoint("pdw.croft.kinomi_harvesting", methods=("POST",))
def harvest(query: Query) -> dict:
    """Put a plot's Berries into the Treasure Chest."""
    with db.transaction():
        harvest_result = managers.get_crops().harvest(int(query["my_croft_id"]))
        managers.get_chest().add_item(harvest_result["pokeitem_id"], harvest_result["count"])
    return harvest_result


@endpoint("pdw.croft.kinomi_sowing", methods=("POST",))
def sow(query: Query) -> CropData:
    """Plants one Berry from the Treasure Chest."""
    pokeitem_id = int(query["pokeitem_id"])
    with db.transaction():
        managers.get_chest().remove_item(pokeitem_id, 1)
        crops = managers.get_crops()
        crops.sow(int(query["my_croft_id"]), pokeitem_id)
    return crops.data


@endpoint("pdw.croft.kinomi_watering", methods=("POST",))
def water(query: Query) -> CropData:
    """Waters a plot."""
    crops = managers.get_crops()
    crops.water_plot(int(query["my_croft_id"]))
    return crops.data


@endpoint("pdw.croft.friend_croft_list")
def friend_croft_list(query: Query) -> dict:
    """Return another player's Berry garden, and how many times the player can still water it today."""
    member_id = int(query["member_savedata_id"])
    snapshot = native_islands.resolve(member_id)
    if snapshot is not None:
        return {**managers.CropManager.snapshot(snapshot["content"]["garden"]), "remains_watering": 0}
    crops = managers.get_crops(visits.find_player(member_id))
    crops.process_berry_growth()
    return {**crops.data, "remains_watering": visits.friend_waterings_left()}


@endpoint("pdw.croft.friend_kinomi_watering", methods=("POST",))
def friend_water(query: Query) -> dict:
    """Waters a plot in another player's garden, using up one of today's waterings."""
    member_id = int(query["member_savedata_id"])
    if native_islands.resolve(member_id) is not None:
        return native_islands.read_only("my_croft_id")
    with db.transaction():
        member = save_data.read_member()
        _require_playing(member)
        island = visits.find_player(member_id)
        if island == save_data.require_gscd():
            raise BadRequest("Choose another player's garden.")
        crops = managers.get_crops(island)
        waterings_left = visits.friend_waterings_left()
        if waterings_left and crops.water_plot(int(query["my_croft_id"])):
            waterings_left = visits.use_friend_watering()
            visits.record_visit(island, watered=True)
            save_data.award_points(10)
    return {**crops.data, "remains_watering": waterings_left}
