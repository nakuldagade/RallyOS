"""CLI:  python -m api.import_match demo/out/<clip>/"""
import sys
from pathlib import Path

from sqlmodel import Session

from api.db import create_all, engine
from api.services.importer import import_folder


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m api.import_match <output-folder>")
    create_all()
    with Session(engine) as s:
        print("imported", import_folder(Path(sys.argv[1]), s))


if __name__ == "__main__":
    main()
