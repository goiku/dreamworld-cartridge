"""Shared entry point for the Nintendo DS games and the Gen IV wireless catalog."""
from collections import Counter
import hashlib
import secrets
import unicodedata
from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from config import LANG, LANGUAGE_NAMES
from utils import gen4_events, gen4_gifts, text
from utils.data import load_json_data

generations = Blueprint("generations", __name__, template_folder="../templates", static_folder="../static",
                        static_url_path="/generation-assets")
_labels = load_json_data("generation_portal")
GAME_CODES = ("ADA", "APA", "CPU", "IPK", "IPG")
LANG_CODES = {"ja":"J", "en":"E", "en-EU":"P", "fr":"F", "it":"I", "de":"D", "es":"S", "ko":"K"}
EVENT_UI = load_json_data("gen4_event_ui")
SHARED_UI = load_json_data("distribution_ui")
PAGE_SIZE = 24


def _browser():
    username = session.get("username")
    if username and not session.get("visit_guest"):
        return "account:" + username
    return "browser:" + session.setdefault("g4_browser", secrets.token_hex(24))


def _target(dev):
    return hashlib.sha256((dev["owner"] + "/" + dev["game"]).encode()).hexdigest()[:24] if dev else ""


def _fold(value):
    return unicodedata.normalize("NFKC",value).casefold().strip()


def _event_view(queue=False):
    t = _labels[LANG]
    shared = SHARED_UI[LANG]
    extra = EVENT_UI[LANG]
    default_game, default_lang = session.get("g4_last", ["all", LANG if LANG in LANG_CODES else "ja"])
    version = request.args.get("game",default_game)
    version = version if version in GAME_CODES else "all"
    language = request.args.get("language",default_lang)
    language = language if language in LANG_CODES else "ja"
    game = version+LANG_CODES[language]
    catalog = gen4_events.selection(game)
    mode = request.args.get("filter","all")
    query = request.args.get("q","").strip()[:100]
    needle = _fold(query)
    browser = _browser()
    with gen4_gifts.db.transaction() as conn:
        gen4_gifts._schema(conn)
        dev = gen4_gifts.receiver(conn,browser,game)
        devices = conn.execute("SELECT owner,game FROM g4_known WHERE browser=? AND game=? ORDER BY owner",
                               (browser,game)).fetchall()
        orders,album,legacy = gen4_gifts.order_state(conn,dev) if dev else ({},None,set())
        window = conn.execute("SELECT 1 FROM g4_window WHERE browser=? AND game=? AND until>unixepoch() AND attempts<8",
                              (browser,game)).fetchone()
    groups = Counter(event["number"] for event in catalog.values())
    identified = {event["number"] for event in catalog.values() if event["signature"] in (album or {})}
    rows = []
    all_rows = {}
    bulk = 0
    for key, event in catalog.items():
        number = event["number"]
        name = event["path"].split("/")[-1].split(" - ",1)[-1][:-4]
        subject = text.lookup_str(event["noun"],event["subject"],language=LANG) if event["noun"] else ""
        state = gen4_gifts.status(key,event,orders,album,legacy)
        exclusive = gen4_events.choose_individually(event,groups)
        if state in ("received","pending_pickup","collected") and groups[number] > 1:
            state = album.get(event["signature"], "alternative" if number in identified else "same_number")
        row = dict(key=key,number=number,title=event["title"],name=name,subject=subject,status=state,
                   versions=[label for code,label in zip(GAME_CODES,t["versions"]) if gen4_events.EDITIONS[code] in gen4_events.versions(event)],
                   exclusive=exclusive)
        all_rows[key] = row
        if state in ("unknown","available") and not exclusive:
            bulk += 1
        bucket = {"unknown":"unknown_filter","available":"unclaimed","queued":"waiting","sent":"waiting",
                  "received":"complete","same_number":"unknown_filter","pending_pickup":"complete","collected":"complete"}.get(state)
        aliases = [event["title"],name,subject or ""]
        if event["noun"] and needle:
            aliases.extend(text.lookup_str(event["noun"],event["subject"],language=k) or "" for k in ("ja","en","zh"))
        if mode not in ("all",bucket):
            continue
        if needle:
            numeric = needle.lstrip("#")
            if numeric.isdecimal():
                if number != int(numeric):
                    continue
            elif needle not in _fold(" ".join(aliases)):
                continue
        rows.append(row)
    rows.sort(key=lambda r:(r["number"],r["name"]))
    pages = max(1,(len(rows)+PAGE_SIZE-1)//PAGE_SIZE)
    page_no = max(1,min(pages,request.args.get("page",1,type=int)))
    names = dict(LANGUAGE_NAMES, **{"en-EU":"English (Europe)"})
    return render_template("generations.html", four=True, queue=queue, t=t, u=extra, d=shared, lang=LANG,
                           versions=dict(zip(GAME_CODES,t["versions"])), names=names, languages=LANG_CODES,
                           code=game, version=version, language=language, mode=mode, search=query, pages=pages,
                           page_no=page_no, count=len(rows), rows=rows[(page_no-1)*PAGE_SIZE:page_no*PAGE_SIZE],
                           queued=[all_rows[r["gift"]] for r in orders.values() if r["state"]=="queued" and r["gift"] in all_rows],
                           sent=[r for r in all_rows.values() if r["status"]=="sent"],
                           dev=bool(dev), album_known=album is not None, window=bool(window), bulk=bulk,
                           devices=[(_target(device), device["owner"][-4:]) for device in devices],
                           csrf=session.setdefault("g4_csrf",secrets.token_hex(24)), target=_target(dev),
                           notice=session.pop("g4_notice",None)), 200, {"Cache-Control":"private, no-store"}


def page():
    t = _labels[LANG]
    return render_template("generations.html", four=False, t=t, lang=LANG, names=LANGUAGE_NAMES,
                           friends=load_json_data("offline_islands_ui")[LANG]["friends"],
                           arcade=load_json_data("practice")[LANG]["title"])


@generations.get("/gen4/")
def gen4():
    return _event_view()


@generations.get("/gen4/queue/")
def gen4_queue():
    return _event_view(True)


@generations.post("/gen4/gifts/<action>")
def manage(action):
    if action == "album":
        request.max_content_length = 0x80000 + 16384
    expected = session.get("g4_csrf")
    if not expected or not secrets.compare_digest(expected.encode(),request.form.get("csrf","").encode()):
        abort(403)
    version,language = request.form.get("game"),request.form.get("language")
    if version not in GAME_CODES or language not in LANG_CODES:
        abort(400)
    game = version+LANG_CODES[language]
    browser = _browser()
    count = 0
    with gen4_gifts.db.transaction() as conn:
        gen4_gifts._schema(conn)
        if action in ("pair","start"):
            pin = request.form.get("pin","").strip()
            if action=="pair" and (len(pin)!=10 or not pin.isascii() or not pin.isdigit()):
                message = "pair_invalid"
            else:
                message = gen4_gifts.pair(conn,browser,game,pin if action=="pair" else "",request.form.get("friend","").strip())
        elif action=="switch":
            devices = conn.execute("SELECT owner,game FROM g4_known WHERE browser=? AND game=?", (browser,game))
            device = next((r for r in devices if _target(r)==request.form.get("choice")), None)
            if not device:
                abort(403)
            conn.execute("UPDATE g4_bind SET owner=? WHERE browser=? AND game=?", (device["owner"],browser,game))
            message = "paired"
        else:
            dev = gen4_gifts.receiver(conn,browser,game)
            if not dev or request.form.get("target") != _target(dev):
                abort(403)
            if action in ("claim","next","bulk"):
                key = request.form.get("key","")
                if action != "bulk" and key not in gen4_events.selection(game):
                    abort(400)
                count = gen4_gifts.enqueue(conn,dev,action,key)
                message = "added"
            elif action=="album":
                upload = request.files.get("save")
                try:
                    gen4_gifts.scan(conn,dev,upload.stream.read(0x80001) if upload else b"")
                    message = "scanned"
                except ValueError:
                    message = "invalid"
            else:
                abort(404)
    session["g4_notice"] = [message,count]
    if message=="paired":
        session["g4_last"] = [version,language]
    endpoint = "generations.gen4_queue" if request.form.get("queue")=="1" else "generations.gen4"
    return redirect(url_for(endpoint,game=version,language=language,filter=request.form.get("filter","all"),
                            q=request.form.get("q","")[:100],page=request.form.get("page",1,type=int),_anchor="gifts"),code=303)


@generations.get("/gen5/")
def gen5():
    # The archive uses root-relative and document-relative links on the same page.
    return redirect("/index.html")
