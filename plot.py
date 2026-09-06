"""(Re)genere courbes + analyses a partir des CSV/JSON deja collectes.

  python plot.py                 -> tous les dossiers de data/listings/
  python plot.py NUDESUSDT       -> les dossiers commencant par NUDESUSDT
  python plot.py data/listings/NUDESUSDT_20260903_044110   -> ce dossier precis
  python plot.py --backfill      -> re-telecharge les bougies 1m manquantes via l'API
                                    (ne marche que si le listing date de < ~8 h)

Puis ouvre data/dashboard.html et data/aggregate.html.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from aggregate import build_aggregate
from config import LISTINGS_DIR
from dashboard import build_dashboard
from tracker import _fetch_klines, _write_klines_csv, render_from_csv


def _targets(args):
    args = [a for a in args if not a.startswith("--")]
    if not args:
        return [d for d in sorted(LISTINGS_DIR.iterdir()) if d.is_dir()]
    out = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            out.append(p)
        else:
            out += [d for d in sorted(LISTINGS_DIR.iterdir())
                    if d.is_dir() and d.name.startswith(a)]
    return out


def _backfill(d):
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    symbol = meta["symbol"]
    t0 = datetime.fromisoformat(meta["detected_at"])
    t0_ms = int(t0.timestamp() * 1000)
    from mexc_client import MexcClient
    kl = _fetch_klines(MexcClient(), symbol, start_ms=t0_ms)
    if kl and (kl[0]["open_time"] - t0_ms) / 60000 <= 3:
        _write_klines_csv(d, kl, t0_ms)
        print(f"  [backfill] {symbol}: {len(kl)} bougies")
    else:
        print(f"  [backfill] {symbol}: historique 1m indisponible (listing trop ancien)")


if __name__ == "__main__":
    do_backfill = "--backfill" in sys.argv
    targets = _targets(sys.argv[1:])
    if not targets:
        print("Aucun dossier dans data/listings/.")
        sys.exit(1)
    for d in targets:
        if do_backfill and (d / "meta.json").exists():
            try:
                _backfill(d)
            except Exception as e:
                print(f"  [backfill] {d.name}: {e}")
        try:
            render_from_csv(d)
        except Exception as e:
            print(f"[ERREUR] {d}: {e}")
    print("dashboard:", build_dashboard())
    build_aggregate()
