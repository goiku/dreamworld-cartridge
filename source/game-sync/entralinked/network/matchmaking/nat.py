"""Match two signed-in friends' observed UDP sockets for the private Wi-Fi Club."""
import socket
import struct
from time import monotonic

from .addresses import visible_endpoint
from .directory import GAME_KEYS, Negotiator, Pairing
from .rooms import NAT


def _header(version, op, cookie):
    return NAT + bytes((version, op)) + cookie


def _offer(directory, cookie, pair, now):
    if set(pair.peers) != {0, 1} or now - pair.last_sent < 0.45:
        return
    if not all(p.game_port and p.control_port for p in pair.peers.values()):
        return
    pair.last_sent = now
    for index, player in pair.peers.items():
        if player.acknowledged:
            continue
        address = visible_endpoint(pair.peers[1 - index].game_port)
        listener = directory.nat_sockets.get(player.control_port)
        if address and listener:
            data = _header(pair.version, 5, cookie) + socket.inet_aton(address[0]) + struct.pack(">H", address[1])
            listener.sendto(data + b"\x42\x00", player.control_port)


def retry_pairings(directory):
    with directory.lock:
        directory.expire()
        now = monotonic()
        for cookie, pair in directory.pairings.items():
            if now - pair.touched < 15:
                _offer(directory, cookie, pair, now)


def nat_packet(context, sock, data, peer):
    if not (12 <= len(data) <= 512 and data.startswith(NAT) and data[6] in (2, 3, 4)):
        return
    version, op = data[6:8]
    cookie, body = data[8:12], data[12:]
    def reply(command, payload):
        sock.sendto(_header(version, command, cookie) + payload, peer)
    if op == 10 and len(body) >= 9:
        address = visible_endpoint(peer)
        if address:
            reply(11, body[:3] + socket.inet_aton(address[0]) + struct.pack(">H", address[1]) + body[9:])
        return
    profile = context.user_manager.gts_peer_profile(peer[0])
    if not profile:
        return
    if op == 15 and len(body) == 6:
        reply(16, body[:1] + b"\x02" + body[2:])
        return
    if op == 13 and len(body) >= 3:
        reply(14, body[:2] + b"\0" + body[3:9])
        return
    directory = context.matcher
    with directory.lock:
        directory.expire()
        if op == 6:
            pair = directory.pairings.get(cookie)
            if pair:
                for player in pair.peers.values():
                    if player.profile == profile and player.control_port == peer:
                        player.acknowledged = True
            return
        if op != 0 or len(body) < 10:
            return
        game = body[9:].rstrip(b"\0").decode("ascii")
        if game not in GAME_KEYS:
            return
        port_type, index, use_game = body[:3]
        if index > 1 or port_type > 3 or use_game > 1:
            return
        pair = directory.pairings.setdefault(cookie, Pairing(version=version, game=game))
        if pair.version != version or pair.game != game:
            return
        player = pair.peers.get(index)
        other = pair.peers.get(1 - index)
        if player and player.profile != profile:
            return
        if other and (other.profile == profile or not context.presence.are_buddies(profile, other.profile)):
            return
        if not player:
            player = pair.peers[index] = Negotiator(profile)
        pair.touched = monotonic()
        if port_type == 0 or not use_game:
            player.game_port = peer
        if port_type != 0:
            player.control_port = peer
            directory.nat_sockets[peer] = sock
        reply(1, body[:2] + b"\xff\xff\x6d\x16\xb5\x7d\xea")
        _offer(directory, cookie, pair, pair.touched)
