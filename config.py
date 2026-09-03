"""Configuration centrale, chargee depuis l'environnement / le fichier .env."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv non installe : on lit juste os.environ
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LISTINGS_DIR = DATA_DIR / "listings"
KNOWN_SYMBOLS_FILE = DATA_DIR / "known_symbols.json"
DETECTIONS_LOG = DATA_DIR / "detections.jsonl"

MEXC_BASE_URL = os.getenv("MEXC_BASE_URL", "https://api.mexc.com")
MEXC_API_KEY = os.getenv("MEXC_API_KEY", "")
MEXC_API_SECRET = os.getenv("MEXC_API_SECRET", "")

CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
TRACK_DURATION_SECONDS = int(os.getenv("TRACK_DURATION_SECONDS", "300"))
TRACK_SAMPLE_INTERVAL_SECONDS = float(os.getenv("TRACK_SAMPLE_INTERVAL_SECONDS", "7"))
QUOTE_FILTER = os.getenv("QUOTE_FILTER", "").strip().upper()

DATA_DIR.mkdir(parents=True, exist_ok=True)
LISTINGS_DIR.mkdir(parents=True, exist_ok=True)
