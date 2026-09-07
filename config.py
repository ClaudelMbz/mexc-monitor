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

# Phase 2 : fenetre de mesure tick, comptee A PARTIR DU PREMIER PRIX REEL (T3).
TRACK_DURATION_SECONDS = int(os.getenv("TRACK_DURATION_SECONDS", "180"))
# Intervalle d'echantillonnage pendant la mesure tick.
TRACK_SAMPLE_INTERVAL_SECONDS = float(os.getenv("TRACK_SAMPLE_INTERVAL_SECONDS", "2"))

# Phase 3 : suivi des bougies 1m pour voir spike -> repli -> stabilisation.
# Duree totale d'observation en minutes (a partir du premier prix). Le pic
# arrive souvent plusieurs heures apres le listing -> 120 min par defaut.
# (l'API MEXC ne sert que ~500 bougies 1m, soit ~8 h max.)
KLINE_FOLLOW_MINUTES = int(os.getenv("KLINE_FOLLOW_MINUTES", "120"))
# Cadence de rafraichissement des bougies pendant cette phase (secondes).
KLINE_POLL_SECONDS = float(os.getenv("KLINE_POLL_SECONDS", "30"))

# Filtre optionnel sur la devise de cotation. Vide = toutes les paires.
QUOTE_FILTER = os.getenv("QUOTE_FILTER", "").strip().upper()

DATA_DIR.mkdir(parents=True, exist_ok=True)
LISTINGS_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write(path, text, retries=6, delay=0.25):
    """Ecrit via un fichier temporaire + rename : jamais de fichier a moitie
    ecrit, meme si le process est tue ou si deux process ecrivent en meme temps.

    Sous Windows, le rename peut echouer (WinError 5) si la cible est ouverte
    par un autre programme (navigateur, IDE, antivirus) -> on retente."""
    import time as _t

    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(retries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == retries - 1:
                tmp.unlink(missing_ok=True)
                raise
            _t.sleep(delay)

