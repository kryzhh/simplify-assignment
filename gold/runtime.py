import os
from pathlib import Path

from .store import Store


def configured_store():
    price = Path(__file__).resolve().parent.parent / "fixtures" / "price.json"
    return Store(os.getenv("GOLD_DB", "data/gold.sqlite3"), os.getenv("GOLD_PRICE_FILE", str(price)))
