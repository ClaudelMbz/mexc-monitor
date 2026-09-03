"""Daemon : verifie chaque minute la liste des paires spot MEXC et, des qu'une
nouvelle paire apparait, lance en parallele un suivi de prix sur 5 minutes.

  python monitor.py

Ctrl+C pour arreter (les suivis en cours se terminent proprement).
"""
import json
import signal
import threading
import time
from datetime import datetime, timezone

from config import (
    CHECK_INTERVAL_SECONDS,
    DETECTIONS_LOG,
    KNOWN_SYMBOLS_FILE,
    QUOTE_FILTER,
)
from dashboard import build_dashboard
from mexc_client import MexcClient
from tracker import track_symbol


def _ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def load_known():
    if KNOWN_SYMBOLS_FILE.exists():
        try:
            return json.loads(KNOWN_SYMBOLS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_known(symbols):
    tmp = KNOWN_SYMBOLS_FILE.with_name(KNOWN_SYMBOLS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(symbols, indent=2), encoding="utf-8")
    tmp.replace(KNOWN_SYMBOLS_FILE)


def log_detection(entry):
    with open(DETECTIONS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def main():
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
