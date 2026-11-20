"""Prepare all Japanese Mystery Gifts for use without an archive connection."""
import argparse
import sys
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import japanese_card_archive as archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="Use a previously downloaded pgf.pkl")
    args = parser.parse_args()
    if args.source:
        source = args.source.open("rb")
    else:
        source = urlopen(archive.PACK_URL, timeout=20)
    with source:
        count = archive.install(source.read(archive.PACK_SIZE + 1))
    print(f"{count} Japanese Wonder Cards verified and ready.")


if __name__ == "__main__":
    main()

