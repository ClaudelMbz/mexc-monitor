"""Daemon : verifie chaque minute la liste des paires spot MEXC et, des qu'une
nouvelle paire apparait, lance en parallele un suivi de prix sur 5 minutes.

  python monitor.py

Ctrl+C pour arreter (les suivis en cours se terminent proprement).
"""
import atexit
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone

from config import (
    CHECK_INTERVAL_SECONDS,
    DATA_DIR,
    DETECTIONS_LOG,
    KNOWN_SYMBOLS_FILE,
    QUOTE_FILTER,
    atomic_write,
)
from dashboard import build_dashboard
from mexc_client import MexcClient
from tracker import track_symbol

LOCK_FILE = DATA_DIR / "monitor.lock"


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        try:
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFO
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        except Exception:
            return True  # dans le doute, on considere qu'il tourne
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def acquire_lock():
    """Empeche deux monitor.py de tourner sur le meme data/ (source de courses
    sur known_symbols.json / dashboard.html / summary.json)."""
    if LOCK_FILE.exists():
        try:
            other = int(LOCK_FILE.read_text().strip() or "0")
        except (ValueError, OSError):
            other = 0
        if other and other != os.getpid() and _pid_alive(other):
            print(f"[{_ts()}] ERREUR : un monitor tourne deja (PID {other}). "
                  f"Arrete-le, ou supprime {LOCK_FILE} s'il est mort.")
            sys.exit(1)
        print(f"[{_ts()}] verrou orphelin (PID {other}) ignore.")
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(lambda: LOCK_FILE.exists() and
                    LOCK_FILE.read_text().strip() == str(os.getpid()) and
                    LOCK_FILE.unlink(missing_ok=True))


def load_known():
    if KNOWN_SYMBOLS_FILE.exists():
        try:
            return json.loads(KNOWN_SYMBOLS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_known(symbols):
    atomic_write(KNOWN_SYMBOLS_FILE, json.dumps(symbols, indent=2))


def log_detection(entry):
    with open(DETECTIONS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def main():
    acquire_lock()
    client = MexcClient()
    stop = threading.Event()

    def handle_sig(*_):
        print(f"\n[{_ts()}] arret demande, on laisse les suivis en cours se terminer...")
        stop.set()

    signal.signal(signal.SIGINT, handle_sig)
    try:
        signal.signal(signal.SIGTERM, handle_sig)
    except (ValueError, AttributeError):
        pass

    known = load_known()
    first_run = known is None
    known = known or {}
    known_bases = {m.get("baseAsset") for m in known.values()}
    trackers = []

    print(f"[{_ts()}] monitor MEXC spot demarre "
          f"(check={CHECK_INTERVAL_SECONDS}s, filtre quote={QUOTE_FILTER or '*'}, "
          f"{'PREMIER LANCEMENT' if first_run else str(len(known)) + ' paires connues'})")

    while not stop.is_set():
        cycle = time.monotonic()
        try:
            current = client.list_symbols()
        except Exception as e:
            print(f"[{_ts()}] erreur API exchangeInfo: {e}")
            stop.wait(CHECK_INTERVAL_SECONDS)
            continue

        if first_run:
            save_known(current)
            known = current
            known_bases = {m.get("baseAsset") for m in current.values()}
            first_run = False
            print(f"[{_ts()}] baseline enregistree : {len(current)} paires. "
                  f"Les nouveautes a partir de maintenant seront suivies.")
        else:
            new_syms = [s for s in current if s not in known]
            if QUOTE_FILTER:
                to_track = [s for s in new_syms if current[s].get("quoteAsset") == QUOTE_FILTER]
            else:
                to_track = list(new_syms)

            for s in new_syms:
                meta = current[s]
                is_new_coin = meta.get("baseAsset") not in known_bases
                will_track = s in to_track
                print(f"[{_ts()}] >>> NOUVEAU LISTING {s} "
                      f"(base={meta.get('baseAsset')}, quote={meta.get('quoteAsset')}, "
                      f"nouveau_coin={is_new_coin}, suivi={'oui' if will_track else 'non/filtre'})")
                log_detection({
                    "symbol": s,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "info": meta,
                    "new_base_asset": is_new_coin,
                    "tracked": will_track,
                })

            for s in to_track:
                t = threading.Thread(
                    target=track_symbol, args=(client, s, current[s]),
                    kwargs={"stop_event": stop}, name=f"track-{s}", daemon=True,
                )
                t.start()
                trackers.append(t)

            if new_syms or set(current) != set(known):
                known = current
                known_bases |= {m.get("baseAsset") for m in current.values()}
                save_known(known)

        trackers = [t for t in trackers if t.is_alive()]
        if not stop.is_set():
            print(f"[{_ts()}] ok - {len(current)} paires, {len(trackers)} suivi(s) actif(s)")
        stop.wait(max(1.0, CHECK_INTERVAL_SECONDS - (time.monotonic() - cycle)))

    if trackers:
        print(f"[{_ts()}] attente de la fin de {len(trackers)} suivi(s)...")
        for t in trackers:
            t.join()
    try:
        build_dashboard()
    except Exception:
        pass
    print(f"[{_ts()}] arrete proprement.")


if __name__ == "__main__":
    main()
