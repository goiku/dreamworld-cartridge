"""pgl.member.profile.*: avatar, privacy settings, Game Sync ID linking, and profile pages."""
from flask import session
from werkzeug.exceptions import BadRequest, Forbidden

from api.pdw_dreamland import recent_dream_friends
from api.pgl_pals import current_save, profile_target
from api.routes import Query, endpoint, query_int
from game_sync_server.entralinked.utility.db_manager import db
from utils import language, pokemon, save_data, text, visits
from utils.account_manager import accounts
from utils.constants import PlayerStatus
from utils.messages import message
from utils.models import Member
from utils.profile_avatars import AVATAR_IDS, avatar_name

GSCD_LENGTH = 10
MAX_LINKED_GSCDS = 4  # one for each of Black, White, Black 2 and White 2
DEMO_AVATAR_ID = 4

def _field_error(field: str, message_id: str, **values: object) -> dict:
    """Return the response that makes the form show a message next to `field`."""
    return {"error": {"details": {field: message(message_id, **values)}}}


def _cartridge_contacts(subject: str) -> dict[str, bool]:
    contacts = dict.fromkeys(visits.cartridge_pals(subject), True)
    rows = db.read_rows(
        """SELECT DISTINCT other.gscd FROM wfc_cartridge_profiles me
           JOIN wfc_cartridge_keys mk ON mk.gscd=me.gscd
           JOIN gts_profile_events e ON (me.pid=e.pid_a AND mk.identity=e.key_a)
                                     OR (me.pid=e.pid_b AND mk.identity=e.key_b)
           JOIN wfc_cartridge_profiles other ON other.pid=CASE WHEN e.pid_a=me.pid THEN e.pid_b ELSE e.pid_a END
           JOIN wfc_cartridge_keys peer ON peer.gscd=other.gscd
               AND peer.identity=CASE WHEN e.pid_a=me.pid THEN e.key_b ELSE e.key_a END
           WHERE me.gscd=?""", subject)
    for row in rows:
        contacts.setdefault(row["gscd"], False)
    return contacts


def _game_pals(viewer: str | None, subject: str | None, query: Query) -> dict:
    if not viewer or not subject or not visits.published(subject, viewer, dream_world=False, roster=True):
        return {"list": [], "cnt": 0}
    blocked = save_data.read_member(subject).get("blocked_profiles", [])
    entries = []
    for other, is_ds in _cartridge_contacts(subject).items():
        if query.get("filter") in ("2", "3") and is_ds != (query["filter"] == "3"):
            continue
        member = save_data.read_member(other)
        if not member.get("pgl_name"):
            continue
        visible = visits.published(other, viewer, dream_world=False)
        if not visible and not (viewer == subject and (is_ds or other in blocked)):
            continue
        if viewer != subject and other in blocked:
            continue
        entries.append({
            "member_savedata_id": str(member["member_savedata_id"]), "pgl_name": member["pgl_name"],
            "avator_id": member.get("avator_id", DEMO_AVATAR_ID), "is_ds": is_ds,
            "is_blocked": str(int(other in blocked)), "disable_flag": str(int(not visible)),
            "country_code": (text.lookup_str("country", member.get("country_id")) or "") if visible else "",
        })
    if query.get("sort", "2") == "2":
        entries.sort(key=lambda entry: (entry["pgl_name"].casefold(), entry["member_savedata_id"]))
    else:
        entries.sort(key=lambda entry: (not entry["is_ds"], entry["pgl_name"].casefold()))
    if query.get("dir") == "1":
        entries.reverse()
    offset, count = max(0, query_int(query, "offset", 0)), max(0, query_int(query, "rowcount", 5))
    return {"list": entries[offset:offset + count], "cnt": len(entries)}


@endpoint("pgl.member.profile.friend_list")
def game_pals(query: Query) -> dict:
    viewer = current_save()
    return _game_pals(viewer, viewer, query)


@endpoint("pgl.member.profile.friend_friend_list")
def visiting_game_pals(query: Query) -> dict:
    return _game_pals(current_save(), profile_target(query), query)


@endpoint("pgl.member.profile.friend_block", methods=("POST",))
def block_profile(query: Query) -> dict:
    viewer = current_save()
    target_id = query.get("friend_member_savedata_id", "")
    if not viewer or not target_id.isascii() or not target_id.isdigit() or len(target_id) > 18:
        return _field_error("friend", "unavailable_invitation")
    other = db.find_gscd(int(target_id))
    if not other or other not in _cartridge_contacts(viewer) or query.get("is_block") not in ("0", "1"):
        return _field_error("friend", "unavailable_invitation")
    def update_block(member):
        blocked = set(member.get("blocked_profiles", []))
        if query["is_block"] == "1":
            blocked.add(other)
        else:
            blocked.discard(other)
        member["blocked_profiles"] = sorted(blocked)
    save_data.change_member(update_block, viewer)
    return {}


@endpoint("pgl.member.profile.init_create_confirm")
def init_create_confirm(query: Query) -> dict:
    """Validate the sign-up form before init_create."""
    gscd = query.get("gscd", "").strip()

    if gscd and len(gscd) != GSCD_LENGTH:
        return _field_error("gscd", "bad_gscd_length", length=GSCD_LENGTH)

    return {}


@endpoint("pgl.member.profile.my_pdw_profile_by_pgl")
def my_pdw_profile(_query: Query) -> dict:
    gscd = current_save()
    return _pdw_profile(gscd) if gscd else {"encount_pokemons": []}


@endpoint("pgl.member.profile.friend_pdw_profile_by_pgl")
def friend_pdw_profile(query: Query) -> dict:
    target = profile_target(query, dream_world=True)
    return _pdw_profile(target) if target else _field_error("profile", "unavailable_island")


def _pdw_profile(gscd: str) -> dict:
    member = save_data.read_member(gscd)
    sleeper = pokemon.get_sleeper(gscd)
    profile = {
        "island_id":        member["island_id"],
        "experiment_point": member["experiment_point"],
        "encount_pokemons": recent_dream_friends(gscd),
    }
    if not sleeper:
        return profile
    return {
        **profile,
        "pokemon_name":     text.lookup_str("pokemon", member["pokemon_no"]),
        "pokemon_nickname": sleeper["pokemon_nickname"],
        "level":            sleeper["level"],
        "sex_id":           sleeper["sex"],
        "pokemon_no":       member["pokemon_no"],
        "form_no":          member["form_no"],
        "oyaname":          sleeper["oyaname"],
        "type1":            text.lookup_str("type", member["type1"]),
        "type2":            text.lookup_str("type", member["type2"]),
        "personality":      text.lookup_str("nature", sleeper["personality"]),
        "shiny":            pokemon.shows_shiny(sleeper.get("is_shiny", False)),
    }


def _demo_profile() -> dict:
    """The profile of a demo player, who has an account but no Game Sync ID."""
    account = accounts.get_account_by_username(session.get("username"))
    return {
        "avator_id":            DEMO_AVATAR_ID,
        "pgl_name":             account["username"] if account else "",
        "country_name":         text.lookup_str("country", account["country"] if account else None),
        "rom_name":             "",
        "rom_id":               "",
        "trial_flag":           "1",
        "player_badge_num":     0,
        "langcode":             None,
        "trainer_name":         "",
        "playtime":             "",
        "disclosure_flag":      0,
        "list_disclosure_flag": 0,
        "friends":              [],
        "friends_count":        0,
        "medals":               [],
    }


@endpoint("pgl.member.profile.my_profile")
def my_profile(_query: Query) -> dict:
    gscd = current_save()
    return _profile(gscd) if gscd else _demo_profile()


@endpoint("pgl.member.profile.friend_profile")
def friend_profile(query: Query) -> dict:
    target = profile_target(query)
    return _profile(target) if target else _field_error("profile", "unavailable_island")


def _profile(gscd: str) -> dict:
    member = save_data.read_member(gscd)
    game_sync = db.read(gscd, "game_sync") or {}
    country_id = accounts.get_country_id(accounts.get_gscd_owner(gscd))
    friends = _game_pals(current_save(), gscd, {})

    return {
        "avator_id":            member["avator_id"],
        "pgl_name":             member["pgl_name"],
        "country_name":         text.lookup_str("country", country_id),
        "rom_name":             text.lookup_str("game", member["rom_id"]),
        "rom_id":               str(member["rom_id"]),
        "trial_flag":           str(member["trial_flag"]),
        "player_badge_num":     member["player_badge_num"],
        "langcode":             member["langcode"],
        "trainer_name":         member["player_name"],
        "playtime":             f"{game_sync.get('hours_played', 0):02}:{game_sync.get('minutes_played', 0):02}",
        "disclosure_flag":      member["disclosure_flag"],
        "list_disclosure_flag": member["list_disclosure_flag"],
        "friends":              friends["list"],
        "friends_count":        friends["cnt"],
        "medals":               save_data.read_medals(gscd),
    }


@endpoint("pgl.member.profile.my_state")
def my_state(_query: Query) -> dict:
    """Make the tucked-in Pokémon start dreaming."""
    save_data.set_play_status(PlayerStatus.DREAMING)
    return {}


@endpoint("pgl.member.profile.pdw_end_by_pgl")
def pdw_end_by_pgl(_query: Query) -> dict:
    """End the Dream World session so the Pokémon can be woken up."""
    save_data.set_play_status(PlayerStatus.WAKE_READY)
    return {}


@endpoint("pgl.member.profile.rom_check")
def rom_check(query: Query) -> dict:
    """Which game a Game Sync ID belongs to."""
    gscd = query.get("gscd", "").strip()
    if gscd and not db.gscd_exists(gscd):
        return _field_error("gscd", "gscd_not_found")
    rom = save_data.read_member(gscd).get("rom_id") if gscd else None
    if gscd and rom is None:
        return _field_error("gscd", "gsid_waiting_upload")
    return {"rom_id": rom}


@endpoint("pgl.member.profile.avator_list", methods=("POST",))
def avatar_list(_query: Query) -> dict:
    """Return the avatars the picker offers."""
    return {"avator_list": [{"avator_id": avatar_id, "avator_name": avatar_name(avatar_id)} for avatar_id in AVATAR_IDS]}


@endpoint("pgl.member.profile.avator_select", methods=("POST",))
def avatar_select(query: Query) -> dict:
    """Change the player's avatar."""
    gscd = current_save()
    if not gscd:
        raise Forbidden()
    raw = query.get("avator_id", "")
    if not raw.isascii() or not raw.isdigit() or len(raw) > 4 or int(raw) not in AVATAR_IDS:
        raise BadRequest("Unknown avatar.")
    save_data.update_member({"avator_id": int(raw)}, gscd)
    return {}


@endpoint("pgl.member.profile.disclosure_switch", methods=("POST",))
def disclosure_switch(query: Query) -> dict:
    """Save the disclosure_flag privacy setting."""
    save_data.update_member({"disclosure_flag": query_int(query, "disclosure_flag", 0)})
    return {}


@endpoint("pgl.member.profile.list_disclosure_switch", methods=("POST",))
def list_disclosure_switch(query: Query) -> dict:
    """Save the list_disclosure_flag privacy setting."""
    save_data.update_member({"list_disclosure_flag": query_int(query, "list_disclosure_flag", 0)})
    return {}


def _link_gscd(username: str, gscd: str) -> dict | None:
    """Link a Game Sync ID to the account.

    Return a field error, and link nothing, if the Game Sync ID doesn't exist or is
    already linked to any account, this one included. Return None once it's linked.
    """
    with db.transaction() as conn:
        if not db.gscd_exists(gscd):
            return _field_error("gscd", "gscd_not_found")
        owner = accounts.get_gscd_owner(gscd)
        if owner:
            return _field_error("gscd", "gscd_already_yours" if owner == username else "gscd_already_taken")
        linked = accounts.get_gscds_for_account(username)
        rom_id = save_data.read_member(gscd).get("rom_id")
        if rom_id is None:
            return _field_error("gscd", "gsid_waiting_upload")
        if len(linked) >= MAX_LINKED_GSCDS or any(save_data.read_member(other)["rom_id"] == rom_id for other in linked):
            return _field_error("gscd", "gscd_game_already_linked")
        if not accounts.link_gscd(username, gscd, connection=conn):
            return _field_error("gscd", "gscd_already_taken")
        linked.append(gscd)
        for linked_gscd in linked:
            save_data.update_member({"gsid_count": len(linked)}, linked_gscd)
    session.setdefault("gscd", gscd)
    return None


@endpoint("pgl.member.profile.gsid_list")
def gsid_list(_query: Query) -> dict:
    """Cartridges shown by the profile's Change Game Card dialog."""
    games = []
    username = session.get("username")
    for gscd in accounts.get_gscds_for_account(username) if username else ():
        member = save_data.read_member(gscd)
        if not member:
            continue
        rom_id = member.get("rom_id")
        timestamp = member.get("last_started_at_timezone")
        games.append({"gscd": gscd, "rom_id": rom_id, "rom_name": text.lookup_str("game", rom_id),
                      "last_up_time": language.localize_last_up_time(timestamp) if timestamp else member.get("last_up_time")})
    return {"gsid_list": games}


@endpoint("pgl.member.profile.gsid_switch", methods=("POST",))
def switch_game(query: Query) -> dict:
    username = session.get("username")
    gscd = query.get("gscd", "").strip()
    if not username or not accounts.select_gscd(username, gscd):
        return _field_error("gscd", "gscd_not_found")
    session["gscd"] = gscd
    return {}


@endpoint("pgl.member.profile.init_create", methods=("POST",))
def init_create(query: Query) -> dict:
    """Finish sign-up by linking a Game Sync ID (if given) and setting the PGL nickname."""
    gscd = query.get("gscd", "").strip()
    username = session.get("username")
    if not username:
        return {"flg": 0}

    if gscd:
        error = _link_gscd(username, gscd)
        if error:
            return error

    if session.get("gscd"):
        _set_up_member(username, session["gscd"])
    accounts.mark_registered(username)

    return {"flg": 2 if session.get("gscd") else 0}


def _set_up_member(username: str, gscd: str) -> None:
    """Give a newly linked Game Sync ID's save the account's PGL nickname and country."""
    changes: Member = {"pgl_name": username, "trial_flag": 0}
    country_id = accounts.get_country_id(username)
    if country_id is not None:
        changes["country_id"] = country_id
    save_data.update_member(changes, gscd)


@endpoint("pgl.member.profile.gsid_create", methods=("POST",))
def gsid_create(query: Query) -> dict:
    """Link another Game Sync ID to the account, from the profile page.

    A trial player becomes a full member.
    """
    username = session.get("username")
    if not username:
        return _field_error("gscd", "gscd_not_found")
    gscd = query.get("gscd", "").strip()
    error = _link_gscd(username, gscd)
    if error:
        return error
    _set_up_member(username, gscd)
    return {}
