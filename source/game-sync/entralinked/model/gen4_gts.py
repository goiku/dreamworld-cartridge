"""Generation IV's 236-byte party Pokémon and 292-byte exchange records."""
import json
import struct

from .gts import EITHER, GlobalTradeStation
from .save_file import _crypt_array, _decrypt_pkm


class Gen4TradeStation(GlobalTradeStation):
    record_size = 292
    max_species = 493
    country_offset = 0x11e
    traded_offset = 0x121
    search_prefix = b""

    @staticmethod
    def listing_profile(conn, pid, record):
        # Generation IV has no Global Link account or Dream World journal.
        return None

    def _validated_record(self, conn, pid, action, data):
        if len(data) != self.record_size + (4 if action == "exchange" else 0):
            raise ValueError("Invalid Generation IV offer length")
        record = data[:self.record_size]
        core = _decrypt_pkm(record[:136])
        tail = bytearray(record[136:236])
        _crypt_array(tail, int.from_bytes(core[:4], "little"))
        species, gender, level, wanted, sex, low, high = struct.unpack_from("<HBBHBBB", record, 0xec)
        if (sum(struct.unpack_from("<64H", core, 8)) & 0xffff != int.from_bytes(core[6:8], "little")
                or core[4:6] != bytes(2) or core[0x3b] & 0x40 or tail[5] != 0
                or not 1 <= species <= 493 or species != int.from_bytes(core[8:10], "little")
                or not 1 <= level <= 100 or level != tail[4] or gender != 1 + ((core[0x40] >> 1) & 3)
                or not 1 <= wanted <= 493 or sex not in (1, 2, EITHER) or low > (high or 100) or high > 100):
            return None
        return record

    def _log_trade(self, conn, depositor, pid, previous, incoming):
        pairs = [struct.unpack_from("<HBB", row, 0xec) for row in (previous, incoming)]
        conn.execute("INSERT INTO gts_journal(side_a,side_b) VALUES(?,?)", tuple(map(json.dumps, pairs)))
