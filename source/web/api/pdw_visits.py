"""The Dream World Rainbow Bridge and Dream Pal invitations."""
from api import native_islands
from api.routes import Query, endpoint
from utils import save_data, visits
from utils.constants import PlayerStatus
from utils.messages import message


def _error(key: str, message_id: str) -> dict:
    # Flash reads structured errors from the JSON body of a successful HTTP response.
    return {"error": {"code": 400, "details": {key: message(message_id)}}}


@endpoint("pdw.home.my_bridge")
def my_bridge(_query: Query) -> dict:
    from api.pdw_dreamland import _island_state

    data = save_data.read_player_data()
    member = data.get("member", {})
    if (not member.get("sleeping_flag") or member.get("wake_download_pending") or member.get("is_downloaded")
            or member.get("play_status") not in (PlayerStatus.PLAY_READY, PlayerStatus.DREAMING)
            or _island_state(data)["wished"] is not None):
        return _error("err_bridge_temporary_closed", "rainbow_closed")
    return {}


@endpoint("pdw.home.friend_bridge")
def friend_bridge(query: Query) -> dict:
    try:
        ident = int(query["friend_member_savedata_id"])
        if not native_islands.resolve(ident):
            visits.find_player(ident)
    except (KeyError, ValueError):
        return _error("not_found", "unavailable_island")
    return my_bridge(query)


def _invitation(query: Query, field: str, *, accept: bool) -> dict:
    try:
        other = visits.find_player(int(query[field]))
        joined = visits.invite(other, accept=accept)
    except (KeyError, ValueError):
        return _error(field, "unavailable_invitation")
    return {"joined": int(joined)}


@endpoint("pdw.home.friend_request", methods=("POST",))
def friend_request(query: Query) -> dict:
    return _invitation(query, "friend_member_savedata_id", accept=False)


@endpoint("pdw.home.friend_accept", methods=("POST",))
def friend_accept(query: Query) -> dict:
    return _invitation(query, "visitor_member_savedata_id", accept=True)
