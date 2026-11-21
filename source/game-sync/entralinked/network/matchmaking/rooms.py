"""The standard QR2 and Server Browser replies used by the fifth-generation Wi-Fi Club."""
import base64
import hmac
import os
import secrets
import socket
import struct
from time import monotonic

from .addresses import rewrite_match_data, visible_endpoint
from .directory import GAME_KEY, GAME_KEYS, Room, room_filter
from .enctypex import EncTypeX

QR = b"\xfe\xfd"
NAT = b"\xfd\xfc\x1e\x66\x6a\xb2"
_MATCH = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
          0x20, 0x40, 0x41, 0x52, 0x53, 0x54, 0x55}


def qr_proof(challenge, game_key=GAME_KEY):
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + game_key[i % len(game_key)]) & 255
        state[i], state[j] = state[j], state[i]
    i = j = 0
    out = bytearray()
    for char in challenge:
        i = (i + 1 + char) & 255
        j = (j + state[i]) & 255
        state[i], state[j] = state[j], state[i]
        out.append(char ^ state[(state[i] + state[j]) & 255])
    return base64.b64encode(out + b"\x00")


def qr_packet(context, sock, data, peer):
    if not 5 <= len(data) <= 4096:
        return
    op, session, body = data[0], data[1:5], data[5:]
    if op == 9 and body.rstrip(b"\x00").decode("ascii") in GAME_KEYS:
        sock.sendto(QR + bytes((9, 0, 0, 0, 0)), peer)
        return
    directory = context.matcher
    with directory.lock:
        directory.expire()
        room = directory.rooms.get(peer)
        if op == 3:
            tokens = body.split(b"\x00")
            fields = {}
            for key, value in zip(tokens[::2], tokens[1::2]):
                if not key:
                    break
                fields[key.decode("ascii")] = value.decode("latin1")
            same_session = room is not None and room.session == session
            game = fields.get("gamename", room.fields["gamename"] if same_session else None)
            if game not in GAME_KEYS or (same_session and game != room.fields["gamename"]):
                return
            live_pid = context.user_manager.gts_peer_profile(peer[0])
            given = fields.get("dwc_pid")
            if given and (not given.isdecimal() or int(given) != live_pid):
                return
            if fields.get("statechanged") == "2":
                if room and room.session == session:
                    directory.rooms.pop(peer, None)
                return
            public = visible_endpoint(peer)
            if public is None:
                return
            if room is None or room.session != session:
                challenge = (secrets.token_hex(3).upper() + "00" + socket.inet_aton(public[0]).hex().upper()
                             + f"{public[1]:04X}").encode("ascii")
                room = Room(peer, session, challenge, fields, live_pid)
                directory.rooms[peer] = room
            room.fields.update(fields)
            room.profile, room.touched = live_pid, monotonic()
            directory.qr_sockets[peer] = sock
            if not room.registered:
                sock.sendto(QR + b"\x01" + session + room.challenge + b"\x00", peer)
        elif room and room.session == session:
            room.touched = monotonic()
            if op == 1 and hmac.compare_digest(body.rstrip(b"\x00"), qr_proof(room.challenge, GAME_KEYS[room.fields["gamename"]])):
                room.registered = True
                sock.sendto(QR + b"\x0a" + session, peer)
            elif op == 7:
                room.outstanding.pop(body[:4], None)
            elif op == 8 and room.registered:
                sock.sendto(QR + b"\x08\x00\x00\x00\x00", peer)
                for packet in room.outstanding.values():
                    sock.sendto(packet, peer)


def _is_visible(context, caller, room):
    return room.registered and room.profile and caller and (
        room.profile == caller or context.presence.are_buddies(caller, room.profile))


def discovery(context, packet, peer):
    if len(packet) < 20:
        return
    query_game, game, rest = packet[9:].split(b"\x00", 2)
    game_name = query_game.decode("ascii")
    if game_name not in GAME_KEYS or game != query_game or len(rest) < 14:
        return
    challenge = rest[:8]
    expression, field_list, tail = rest[8:].split(b"\x00", 2)
    options, = struct.unpack_from(">I", tail)
    limit = min(50, struct.unpack_from(">I", tail, 4)[0]) if options & 128 else 50
    public = visible_endpoint(peer, for_tcp=True)
    if public is None:
        return
    fields = [key.decode("ascii") for key in field_list.split(b"\\") if key and len(key) <= 48
              and key not in (b"publicip", b"publicport", b"localport") and not key.startswith(b"localip")]
    if options & 2:
        fields = []
    if len(fields) > 60:
        return
    out = bytearray(socket.inet_aton(public[0]) + struct.pack(">HB", public[1], len(fields)))
    for key in fields:
        out.extend(b"\0" + key.encode("ascii") + b"\0")
    out.append(0)
    if not options & 2:
        caller = context.user_manager.gts_peer_profile(peer[0])
        predicate = room_filter(expression.decode("ascii"))
        directory = context.matcher
        with directory.lock:
            directory.expire()
            for room in directory.rooms.values():
                if not limit or room.fields["gamename"] != game_name or not _is_visible(context, caller, room) or not predicate(room.fields):
                    continue
                dest = visible_endpoint(room.address)
                if dest is None:
                    continue
                # Advertise the negotiated reachable endpoint on both address fields.
                packed = socket.inet_aton(dest[0]) + struct.pack(">H", dest[1])
                flags = 0x40 | 0x10 | 0x02 | 0x20 | 0x08
                if room.fields.get("natneg") not in (None, "0"):
                    flags |= 0x04
                out.extend(bytes((flags,)) + packed + packed + b"\0" * 4)
                for key in fields:
                    out.extend(b"\xff" + room.fields.get(key, "").encode("latin1") + b"\0")
                limit -= 1
        out.extend(b"\x00\xff\xff\xff\xff")
    return bytes(EncTypeX().encrypt(GAME_KEYS[game_name], challenge, out))


def forward_reservation(context, packet, peer):
    if len(packet) < 19:
        return
    target = (socket.inet_ntoa(packet[3:7]), int.from_bytes(packet[7:9], "big"))
    caller = context.user_manager.gts_peer_profile(peer[0])
    data = packet[9:]
    if not caller:
        return
    cookie = len(data) == 10 and data.startswith(NAT)
    if not cookie:
        if not (20 <= len(data) <= 148 and data[:4] in (b"SBCM", b"\xbbI\xccM")
                and int.from_bytes(data[4:8], "little") in (3, 11, 90)
                and data[8] in _MATCH and data[9] + 20 == len(data)
                and int.from_bytes(data[16:20], "little") == caller):
            return
    directory = context.matcher
    with directory.lock:
        directory.expire()
        rooms = list(directory.rooms.values())
        dest = next((room for room in rooms if visible_endpoint(room.address) == target), None)
        source = next((room for room in rooms if room.profile == caller and room.registered), None)
        if (not source or not dest or source.fields["gamename"] != dest.fields["gamename"]
                or dest.profile == caller or not _is_visible(context, caller, dest)):
            return
        if not cookie:
            public = visible_endpoint(source.address)
            if not public:
                return
            content = rewrite_match_data(source.address[0], int.from_bytes(data[4:8], "little"), data[8], data[20:])
            data = data[:10] + struct.pack("<H", public[1]) + socket.inet_aton(public[0]) + data[16:20] + content
        key = os.urandom(4)
        routed = QR + b"\x06" + dest.session + key + data
        if len(dest.outstanding) < 12:
            dest.outstanding[key] = routed
            directory.qr_sockets[dest.address].sendto(routed, dest.address)
