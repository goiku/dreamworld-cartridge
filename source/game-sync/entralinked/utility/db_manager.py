"""The database both servers share."""
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from ..model.player.starting_save import STARTING_PLOTS, starting_chest, starting_garden, starting_shelf
from ..paths import SAVE_DIR
from .sqlite_store import SQLiteStore


def _to_json(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


class DBManager(SQLiteStore):
    """Reads and writes player saves (keyed by gscd) and Nintendo WFC users."""

    SCHEMA = (
        """
        CREATE TABLE IF NOT EXISTS player_saves (
            gscd TEXT PRIMARY KEY,
            player_data TEXT,
            sleeping_pokemon TEXT,
            game_sync TEXT,
            crop_data TEXT,
            chest_data TEXT,
            share_data TEXT
        )""",
        """
        CREATE TABLE IF NOT EXISTS wfc_users (
            user_id TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            profiles TEXT
        )""",
        """
        CREATE TABLE IF NOT EXISTS wfc_buddies (
            first_pid INTEGER NOT NULL,
            second_pid INTEGER NOT NULL,
            requester INTEGER NOT NULL,
            signature TEXT NOT NULL,
            reason TEXT NOT NULL,
            requested_at INTEGER NOT NULL,
            accepted INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (first_pid, second_pid),
            CHECK (first_pid < second_pid AND requester IN (first_pid, second_pid))
        )""",
        """
        CREATE TABLE IF NOT EXISTS id_counters (
            name TEXT PRIMARY KEY,
            last_id INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS gts_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner INTEGER NOT NULL UNIQUE,
            state TEXT NOT NULL CHECK(state IN ('draft','listed','reserved','received')),
            record BLOB NOT NULL, origin BLOB NOT NULL, species INTEGER NOT NULL,
            gender INTEGER NOT NULL, level INTEGER NOT NULL, country INTEGER NOT NULL,
            partner INTEGER, partner_key BLOB, incoming BLOB
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS gts_reserved_partner ON gts_slots(partner) WHERE state='reserved'",
        "CREATE INDEX IF NOT EXISTS gts_listing_search ON gts_slots(state,species)",
        "CREATE TABLE IF NOT EXISTS gts_seen(viewer INTEGER,slot INTEGER,PRIMARY KEY(viewer,slot))",
        "CREATE TABLE IF NOT EXISTS gts_last(owner INTEGER PRIMARY KEY,action TEXT NOT NULL)",
        """CREATE TABLE IF NOT EXISTS gts_journal(
            id INTEGER PRIMARY KEY, side_a TEXT NOT NULL, side_b TEXT NOT NULL
        )""",
        "CREATE TABLE IF NOT EXISTS gts_report_epoch(id INTEGER PRIMARY KEY,started_at INTEGER NOT NULL)",
        "INSERT OR IGNORE INTO gts_report_epoch VALUES(1,unixepoch())",
        """CREATE TABLE IF NOT EXISTS gts_offer_activity(
            slot INTEGER PRIMARY KEY,species INTEGER NOT NULL,wanted_le BLOB NOT NULL,
            opened_at INTEGER NOT NULL,closed_at INTEGER)""",
        """INSERT OR IGNORE INTO gts_offer_activity(slot,species,wanted_le,opened_at)
           SELECT id,species,substr(record,241,2),unixepoch() FROM gts_slots WHERE state='listed'""",
        """CREATE TRIGGER IF NOT EXISTS gts_offer_opens AFTER UPDATE OF state ON gts_slots
           WHEN NEW.state='listed' AND OLD.state<>'listed' BEGIN
           INSERT INTO gts_offer_activity(slot,species,wanted_le,opened_at)
           VALUES(NEW.id,NEW.species,substr(NEW.record,241,2),unixepoch()); END""",
        """CREATE TRIGGER IF NOT EXISTS gts_offer_claimed AFTER UPDATE OF state ON gts_slots
           WHEN OLD.state='listed' AND NEW.state<>'listed' BEGIN
           UPDATE gts_offer_activity SET closed_at=unixepoch() WHERE slot=OLD.id; END""",
        """CREATE TRIGGER IF NOT EXISTS gts_offer_returned AFTER DELETE ON gts_slots
           WHEN OLD.state='listed' BEGIN
           UPDATE gts_offer_activity SET closed_at=unixepoch() WHERE slot=OLD.id; END""",
        """CREATE TABLE IF NOT EXISTS wfc_cartridge_keys(
            gscd TEXT NOT NULL, identity BLOB NOT NULL, PRIMARY KEY(gscd,identity))""",
        """CREATE TABLE IF NOT EXISTS wfc_profile_keys(
            pid INTEGER NOT NULL, identity BLOB NOT NULL, PRIMARY KEY(pid,identity))""",
        """CREATE VIEW IF NOT EXISTS wfc_cartridge_profiles AS
            SELECT p.pid, s.gscd FROM wfc_profile_keys p JOIN wfc_cartridge_keys s USING(identity)
            WHERE NOT EXISTS (SELECT 1 FROM wfc_profile_keys b WHERE
              (b.pid=p.pid AND b.identity<>p.identity) OR (b.identity=p.identity AND b.pid<>p.pid))
            AND NOT EXISTS (SELECT 1 FROM wfc_cartridge_keys c WHERE
              (c.gscd=s.gscd AND c.identity<>s.identity) OR (c.identity=s.identity AND c.gscd<>s.gscd))""",
        """CREATE TABLE IF NOT EXISTS gts_profile_events(
            trade_id INTEGER PRIMARY KEY, pid_a INTEGER NOT NULL, pid_b INTEGER NOT NULL,
            key_a BLOB, key_b BLOB, details_a TEXT NOT NULL, details_b TEXT NOT NULL,
            traded_at INTEGER NOT NULL)""",
        "CREATE TABLE IF NOT EXISTS gts_listing_identity(slot INTEGER PRIMARY KEY,identity BLOB NOT NULL)",
        "CREATE INDEX IF NOT EXISTS gts_profile_events_a ON gts_profile_events(pid_a,trade_id)",
        "CREATE INDEX IF NOT EXISTS gts_profile_events_b ON gts_profile_events(pid_b,trade_id)",
        """CREATE TABLE IF NOT EXISTS gts_validation(
            ticket BLOB PRIMARY KEY, pid INTEGER NOT NULL, pokemon BLOB NOT NULL, expires INTEGER NOT NULL
        )""",
        """
        CREATE TABLE IF NOT EXISTS dream_mail (
            id INTEGER PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL,
            sender_name TEXT NOT NULL, recipient_name TEXT NOT NULL, phrase TEXT NOT NULL,
            submission TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sender, submission)
        )""",
        "CREATE INDEX IF NOT EXISTS dream_mail_inbox ON dream_mail(recipient, id)",
        """
        CREATE TABLE IF NOT EXISTS dream_pals (
            left_gscd TEXT NOT NULL,
            right_gscd TEXT NOT NULL,
            requester TEXT NOT NULL,
            accepted INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (left_gscd, right_gscd),
            CHECK (left_gscd < right_gscd AND requester IN (left_gscd, right_gscd))
        )""",
        """
        CREATE TABLE IF NOT EXISTS dream_footprints (
            island TEXT NOT NULL,
            guest TEXT NOT NULL,
            day TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            pokemon TEXT NOT NULL,
            watered INTEGER NOT NULL DEFAULT 0,
            traded INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (island, guest, day)
        )""",
    )
    COLUMNS = frozenset({"player_data", "sleeping_pokemon", "game_sync", "crop_data", "chest_data", "share_data"})

    def _validate_column(self, column: str) -> None:
        if column not in self.COLUMNS:
            raise ValueError(f"Invalid column name: '{column}'")

    def read_rows(self, query: str, *params: object) -> list[sqlite3.Row]:
        """Read a result set through this thread's current connection."""
        return self._conn.execute(query, params).fetchall()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialize a group of save updates and roll it back if any step fails."""
        conn = self._conn
        if conn.in_transaction:
            yield conn
            return
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    # ------------
    # id counters
    # ------------

    def next_id(self, name: str, count: int = 1) -> list[int]:
        """Reserve `count` new ids from the global `name` sequence.

        Ids only ever go up and are never reused. Each name has its own sequence, which
        every player shares.
        """
        with self.transaction() as conn:
            return self._next_id(conn, name, count)

    @staticmethod
    def _next_id(conn: sqlite3.Connection, name: str, count: int) -> list[int]:
        last_id = conn.execute(
            """INSERT INTO id_counters (name, last_id) VALUES (?, ?)
               ON CONFLICT(name) DO UPDATE SET last_id = last_id + excluded.last_id
               RETURNING last_id""",
            (name, count),
        ).fetchone()[0]
        return list(range(last_id - count + 1, last_id + 1))

    # -------------
    # player saves
    # -------------

    def write_gscd(self, gscd: str) -> None:
        """Create the row of a new Game Sync ID, with its starting garden, chest and Share Shelf.

        Do nothing if the row exists.
        """
        with self.transaction() as conn:
            if conn.execute("SELECT 1 FROM player_saves WHERE gscd = ?", (gscd,)).fetchone():
                return
            croft_ids = self._next_id(conn, "my_croft_id", STARTING_PLOTS)
            conn.execute(
                "INSERT INTO player_saves (gscd, crop_data, chest_data, share_data) VALUES (?, ?, ?, ?)",
                (gscd, _to_json(starting_garden(croft_ids)), _to_json(starting_chest()), _to_json(starting_shelf())),
            )

    def gscd_exists(self, gscd: str) -> bool:
        """Whether a Game Sync ID has a row."""
        return self._conn.execute("SELECT 1 FROM player_saves WHERE gscd = ?", (gscd,)).fetchone() is not None

    def find_gscd(self, member_savedata_id: int) -> str | None:
        """The Game Sync ID of the save with this member_savedata_id, if there is one."""
        row = self._conn.execute(
            "SELECT gscd FROM player_saves WHERE json_extract(player_data, '$.member.member_savedata_id') = ?",
            (member_savedata_id,),
        ).fetchone()
        return row["gscd"] if row else None

    def get_all_gscds(self) -> list[str]:
        """Return every Game Sync ID with a row."""
        return [row["gscd"] for row in self._conn.execute("SELECT gscd FROM player_saves")]

    def _upsert(self, conn: sqlite3.Connection, gscd: str, column: str, data: dict | None) -> None:
        query = f"""
            INSERT INTO player_saves (gscd, {column})
            VALUES (?, ?)
            ON CONFLICT(gscd) DO UPDATE SET {column} = excluded.{column};
        """
        conn.execute(query, (gscd, None if data is None else _to_json(data)))

    def read(self, gscd: str, column: str) -> dict | None:
        """One column of a save. None if the row or the column is empty."""
        self._validate_column(column)
        row = self._conn.execute(f"SELECT {column} FROM player_saves WHERE gscd = ?", (gscd,)).fetchone()
        return json.loads(row[column]) if row and row[column] else None

    def update(self, gscd: str, column: str, change: Callable[[dict], None]) -> dict:
        """Read, modify, and write one column in a single write transaction.

        Concurrent updates (other threads, or the other server's process) can't overwrite
        each other. `change` edits the dict in place ({} if the column is empty). The
        dict is returned.
        """
        self._validate_column(column)
        with self.transaction() as conn:
            row = conn.execute(f"SELECT {column} FROM player_saves WHERE gscd = ?", (gscd,)).fetchone()
            data = json.loads(row[column]) if row and row[column] else {}
            change(data)
            self._upsert(conn, gscd, column, data)
        return data

    def write_full_state(self, gscd: str, player_data: dict, game_sync: dict, sleeping_pokemon: dict | None) -> None:
        """Replace the three columns a Game Sync writes in a single transaction."""
        query = """
            INSERT INTO player_saves (gscd, player_data, game_sync, sleeping_pokemon)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(gscd) DO UPDATE SET
                player_data = excluded.player_data,
                game_sync = excluded.game_sync,
                sleeping_pokemon = excluded.sleeping_pokemon
        """
        with self.transaction() as conn:
            conn.execute(query, (gscd, _to_json(player_data), _to_json(game_sync), _to_json(sleeping_pokemon)))

    def read_full_state(self, gscd: str) -> tuple[dict | None, dict | None, dict | None] | None:
        """(player_data, game_sync, sleeping_pokemon) of a save, or None if it has no row."""
        row = self._conn.execute(
            "SELECT player_data, game_sync, sleeping_pokemon FROM player_saves WHERE gscd = ?", (gscd,)
        ).fetchone()
        if row is None:
            return None
        player_data, game_sync, sleeping_pokemon = (json.loads(column) if column else None for column in row)
        return player_data, game_sync, sleeping_pokemon

    # ------------------
    # Nintendo WFC users
    # ------------------

    def save_wfc_user(self, user_id: str, password: str, profiles: dict) -> None:
        """Create or replace a Nintendo WFC user.

        `profiles` maps a branch code to the fields of a GameProfile.
        """
        query = """
            INSERT INTO wfc_users (user_id, password, profiles)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                password = excluded.password,
                profiles = excluded.profiles
        """
        with self._conn:
            self._conn.execute(query, (user_id, password, json.dumps(profiles, ensure_ascii=False)))

    def get_all_wfc_users(self) -> list[dict]:
        """Every Nintendo WFC user, as {"id", "password", "profiles"}."""
        return [
            {
                "id": row["user_id"],
                "password": row["password"],
                "profiles": json.loads(row["profiles"]) if row["profiles"] else {},
            }
            for row in self._conn.execute("SELECT user_id, password, profiles FROM wfc_users")
        ]


db = DBManager(SAVE_DIR / "pokemon_saves.db")
