"""Endpoints the client calls that aren't implemented yet, which all answer with {}.

Placeholders that return made-up data live with the real endpoints of their module, and
their docstrings say they return a placeholder.
"""
from api.routes import Query, endpoint

EMPTY_STUBS = {
    "GET": (
        "hb",  # heartbeat
        "gbu.journal.season_list",
        "gbu.worldbattle.get_battle_history",
    ),
    "POST": (
        "pgl.member.profile.pdw_login",
    ),
}


def empty_response(_query: Query) -> dict:
    """Return an empty response. Every name in EMPTY_STUBS shares this handler."""
    return {}


for _method, _names in EMPTY_STUBS.items():
    for _name in _names:
        endpoint(_name, methods=(_method,))(empty_response)
