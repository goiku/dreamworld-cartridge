"""The tucked-in Pokémon."""
from dataclasses import dataclass

SHINY_THRESHOLD = 8

# Original Trainer names and public IDs from Generation V Wonder Card 0033.
MOVIE_TRAINERS = {"サトシ": 7161, "지우": 12221, "SPR2012": 3102, "FRÜ2012": 3102, "PRI2012": 3102}


def is_movie_dragon(species: int, trainer: str, ball: int, level: int,
                    trainer_id: int | None = None, secret_id: int | None = None) -> bool:
    """Recognize the movie Reshiram and Zekrom, including sleepers from older uploads."""
    return (species in (643, 644) and ball == 16 and level == 100 and trainer in MOVIE_TRAINERS
            and (trainer_id is None or trainer_id == MOVIE_TRAINERS[trainer]) and secret_id in (None, 0))


def calculate_is_shiny(trainer_id: int, trainer_secret_id: int, personality_value: int) -> bool:
    """Return whether a Pokémon is shiny.

    It is shiny if the trainer ids XORed with both halves of the personality value
    come to less than 8.
    """
    high = (personality_value >> 16) & 0xFFFF
    low = personality_value & 0xFFFF
    return (trainer_id ^ trainer_secret_id ^ high ^ low) < SHINY_THRESHOLD


@dataclass
class PkmnInfo:
    """Field names match the Dream World server."""

    pokemon_no: int  # National Pokédex number
    form_no: int
    type1: int
    type2: int | None
    pokemon_nickname: str
    oyaname: str  # Original Trainer name
    level: int
    sex: int  # 0 = male, 1 = female, 2 = genderless
    personality: int  # nature, 0-24 - NOT the personality value\
    ball_name: int  # the Poké Ball's item id
    is_shiny: bool = False
    movie_dragon: bool | None = None
    nickname_verified: bool = False  # new uploads read the raw nickname before invalid glyphs are replaced
