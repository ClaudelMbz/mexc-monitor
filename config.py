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

# Frequence de verification de la liste des paires (boucle principale)
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))

# --- Suivi d'un nouveau listing ---------------------------------------------
# Phase 1 (T2 -> T3) : la paire est visible mais ne trade pas encore.
# On interroge le prix rapidement jusqu'a obtenir le premier prix reel.
PRICE_WAIT_POLL_SECONDS = float(os.getenv("PRICE_WAIT_POLL_SECONDS", "3"))
# Au-dela de ce delai sans aucun prix, on abandonne le suivi de cette paire.
PRICE_WAIT_TIMEOUT_SECONDS = int(os.getenv("PRICE_WAIT_TIMEOUT_SECONDS", "7200"))

# Phase 2 : fenetre de mesure, comptee A PARTIR DU PREMIER PRIX REEL (T3).
TRACK_DURATION_SECONDS = int(os.getenv("TRACK_DURATION_SECONDS", "180"))
# Intervalle d'echantillonnage pendant la mesure.
TRACK_SAMPLE_INTERVAL_SECONDS = float(os.getenv("TRACK_SAMPLE_INTERVAL_SECONDS", "2"))

# Filtre optionnel sur la devise de cotation. Vide = toutes les paires.
QUOTE_FILTER = os.getenv("QUOTE_FILTER", "").strip().upper()

DATA_DIR.mkdir(parents=True, exist_ok=True)
LISTINGS_DIR.mkdir(parents=True, exist_ok=True)
