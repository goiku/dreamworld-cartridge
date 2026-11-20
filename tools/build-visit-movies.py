"""Rebuild the two small read-only native visit patches. Requires Java and JPEXS 26.4.0.

Example:
    python tools/build-visit-movies.py installed/ --ffdec tools/ffdec.jar

The runtime must already contain the regular working Dream World client. Ordinary
players use the shipped json_data/island_movie_patch.json without Java or a download.
This utility edits just three AVM2 method bodies, preserving the rest of the movies
and the earlier Ruffle fixes. Never run it on an unrecognized base revision.
"""
import argparse
import hashlib
import json
import re
import subprocess
import zlib
from bisect import bisect
from pathlib import Path
from tempfile import TemporaryDirectory


MAIN_CLASS = "bfp.main.alert.PDWEnterCheck"
SCENE_CLASS = "bfp.tpc.pdw.main.Main"
CASES = {
    "main": ("patches/main.patched.swf", "e4c55b94f75629d605f84f856a0d57f0850b7d89a5eabef578a5fe5a467dd8ed",
             MAIN_CLASS, {"check": 551}),
    "pdw_main": ("dreamworld_assets/shared.pokemon-gl.com/src/swf/pdw/assets/pdw_main.swf",
                 "c30f3cc23134800359e7cfed272af4948b6bcf5abda81580a0ebc013c2b92d2a",
                 SCENE_CLASS, {"chestLoadCompleteHandler": 1261, "changeScene": 1271}),
}


def public(name):
    return f'QName(PackageNamespace(""),"{name}")'


def get(name):
    return "getproperty " + public(name)


def set_property(name):
    return "setproperty " + public(name)


def lexical(package, name):
    return f'getlex QName(PackageNamespace("{package}"),"{name}")'


def call(name, argc, *, returns=False):
    instruction = "callproperty" if returns else "callpropvoid"
    return f"{instruction} {public(name)}, {argc}"


EXTERNAL = lexical("flash.external", "ExternalInterface")
HOME = lexical("bfp", "PDWHomeData")
SCENE = lexical("bfp", "PDWBridge")
GAME = lexical("bfp.common", "PokemonBridge")


def gate_patch():
    # When a paired island is open, go straight to the movie. The next patched
    # method starts its read-only friend scene, without calling the play-start APIs.
    return [EXTERNAL, get("available"), "iffalse originalGate",
            EXTERNAL, 'pushstring "dwVisitIsOpen"', call("call", 1, returns=True), "iffalse originalGate",
            GAME, GAME, get("SITE_PDW"), call("siteChange", 1), "returnvoid", "originalGate:"]


def bootstrap_patch():
    # Same home state and destination as the original Dream Pal Map's island button.
    # local2 is new; local0 and local1 remain the original player and loader event.
    code = [EXTERNAL, get("available"), "iffalse originalStart", EXTERNAL, 'pushstring "dwVisitTarget"',
            call("call", 1, returns=True), "setlocal2", "getlocal2", "iffalse originalStart",
            HOME, "pushfalse", set_property("isMyHome"), HOME, HOME, get("HOME_FRIEND"), set_property("currentHomeType")]
    for field, source in (("anotherPGLName", "pgl_name"), ("anotherMemberId", "member_savedata_id"),
                          ("anotherMemberSaveDataId", "member_savedata_id"), ("anotherCountryId", "country_id"),
                          ("anotherIslandId", "house")):
        code.extend([HOME, "getlocal2", get(source), set_property(field)])
    # Normal game boot first reads the visitor's own garden. Direct visits can
    # initialize the same real sleeper fields without starting a play session.
    code.extend(["getlocal2", get("visitor_pokemon"), "iffalse noSleeper"])
    for field, source in (("No", "pokemon_no"), ("FormNo", "form_no"), ("Name", "pokemon_name"),
                          ("NickName", "pokemon_nickname"), ("Type1", "type1"), ("Type2", "type2"),
                          ("OyaName", "oyaname"), ("Level", "level"), ("Sex", "sex"),
                          ("Personality", "personality"), ("Ball", "ball_name"), ("Shiny", "shiny")):
        code.extend([HOME, "getlocal2", get("visitor_pokemon"), get(source), set_property("myPokemon" + field)])
    code.append("noSleeper:")
    # Even original game buttons cannot change inventory or prepare a wake on this tab.
    for endpoint in ("PDW_API", "PDW_API_SSL", "API", "API_SSL"):
        code.extend([GAME, "getlocal2", get("api_url"), set_property(endpoint)])
    event = 'QName(PackageNamespace("flash.events"),"Event")'
    code.extend([GAME, "findpropstrict "+event, GAME, get("FOOTER_ON"), "constructprop "+event+", 1",
                 call("dispatchEvent", 1), "getlocal0", SCENE, get("SCENE_HOME"), call("changeScene", 1),
                 "returnvoid", "originalStart:"])
    return code


def navigate_patch():
    # "Go to my home" returns through the normal game's checks on a new page.
    return [EXTERNAL, get("available"), "iffalse normalScene", EXTERNAL, 'pushstring "dwVisitScene"',
            "getlocal1", HOME, get("isMyHome"), call("call", 3, returns=True),
            "iffalse normalScene", "returnvoid", "normalScene:"]


def patched_method(source, name):
    block = re.search(r"function " + name + r"\([^\n]*\n\{\n(.*?)\nend ; method", source, re.S)
    if not block:
        raise ValueError(f"Missing method {name}")
    body = block.group(1)
    body = body[body.index("method\n"):] + "\nend ; method\n"
    if name == "chestLoadCompleteHandler":
        anchor = GAME + "\n" + get("first_flag")
        if body.count("localcount 2") != 1 or body.count(anchor) != 2:
            raise ValueError(f"Unexpected start branch in {name}")
        body = body.replace("localcount 2", "localcount 3")
        return body.replace(anchor, "\n".join(bootstrap_patch())+"\n"+anchor, 1)
    if body.count("pushscope\n") != 1:
        raise ValueError(f"Unexpected scope for {name}")
    inserted = gate_patch() if name == "check" else navigate_patch()
    return body.replace("pushscope\n", "pushscope\n"+"\n".join(inserted)+"\n", 1)


def raw(path):
    data = path.read_bytes()
    if data[:3] not in (b"CWS", b"FWS"):
        raise ValueError(f"Invalid movie: {path}")
    return data[:8] + (zlib.decompress(data[8:]) if data[:3] == b"CWS" else data[8:])


def spans(source, result):
    """Represent unchanged ranges as [offset,length] and inserted bytes as hex."""
    block = 16
    index = {}
    for cursor in range(0, len(source)-block+1, block):
        index.setdefault(source[cursor:cursor+block], []).append(cursor)
    out = []
    cursor = end = previous = 0
    while cursor <= len(result)-block:
        matches = index.get(result[cursor:cursor+block])
        if not matches:
            cursor += 1
            continue
        near = bisect(matches, previous)
        candidates = set(matches[max(0,near-2):near+2] + matches[:1] + matches[-1:])
        # Prefer a nearby match when two repeating parts have equal lengths.
        length, offset = 0, 0
        for match in sorted(candidates, key=lambda p: abs(p-previous)):
            count = block
            while (cursor+count+256 <= len(result) and match+count+256 <= len(source) and
                   result[cursor+count:cursor+count+256] == source[match+count:match+count+256]):
                count += 256
            while cursor+count < len(result) and match+count < len(source) and result[cursor+count] == source[match+count]:
                count += 1
            if count > length:
                length, offset = count, match
        while cursor > end and offset and result[cursor-1] == source[offset-1]:
            cursor, offset, length = cursor-1, offset-1, length+1
        if cursor > end:
            out.append(result[end:cursor].hex())
        out.append([offset, length])
        cursor += length
        end, previous = cursor, offset+length
    if end < len(result):
        out.append(result[end:].hex())
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    parser.add_argument("--ffdec", type=Path, required=True, help="Path to ffdec.jar (26.4.0)")
    parser.add_argument("--output", type=Path, help="Defaults to the runtime's json_data/island_movie_patch.json")
    args = parser.parse_args()
    run = ["java", "-jar", str(args.ffdec.resolve(strict=True))]
    records = {}
    for movie, (name, digest, class_name, methods) in CASES.items():
        source = (args.runtime/name).resolve(strict=True)
        original = raw(source)
        if hashlib.sha256(original).hexdigest() != digest:
            raise ValueError(f"Unknown movie version: {source}")
        with TemporaryDirectory() as scratch:
            folder = Path(scratch)
            subprocess.run(run+["-format", "script:pcode", "-selectclass", class_name,
                               "-export", "script", str(folder), str(source)], check=True)
            script = folder/"scripts"/Path(*(class_name.split("."))).with_suffix(".pcode")
            pcode = "\n".join(line.strip() for line in script.read_text("utf8").splitlines())
            destination = folder/f"{movie}.swf"
            replace = run+["-replace", str(source), str(destination)]
            for method, body_index in methods.items():
                assembly = folder/f"{method}.pcode"
                assembly.write_text(patched_method(pcode, method), encoding="utf8")
                replace.extend([class_name, str(assembly), str(body_index)])
            subprocess.run(replace, check=True)
            compiled = raw(destination)
            records[movie] = {"input": digest, "output": hashlib.sha256(compiled).hexdigest(),
                              "spans": spans(original, compiled)}
    output = args.output or args.runtime/"json_data/island_movie_patch.json"
    output.write_text(json.dumps(records, indent=2)+"\n", encoding="utf8")


if __name__ == "__main__":
    main()
