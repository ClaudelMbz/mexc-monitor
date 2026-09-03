"""(Re)genere les courbes a partir des CSV deja collectes.

  python plot.py                 -> tous les dossiers de data/listings/
  python plot.py NUDESUSDT       -> seulement les dossiers commencant par NUDESUSDT
  python plot.py data/listings/NUDESUSDT_20260903_044110   -> ce dossier precis

Puis ouvre data/dashboard.html (ou le chart.html du dossier).
"""
import sys
from pathlib import Path

from config import LISTINGS_DIR
from dashboard import build_dashboard
from tracker import render_from_csv


def _targets(args):
    if not args:
        return [d for d in sorted(LISTINGS_DIR.iterdir()) if (d / "prices.csv").exists()]
    out = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            out.append(p)
            continue
        out += [d for d in sorted(LISTINGS_DIR.iterdir())
                if d.is_dir() and d.name.startswith(a) and (d / "prices.csv").exists()]
    return out


if __name__ == "__main__":
    targets = _targets(sys.argv[1:])
    if not targets:
        print("Aucun dossier avec prices.csv trouve.")
        sys.exit(1)
    for d in targets:
        try:
            render_from_csv(d)
        except Exception as e:
            print(f"[ERREUR] {d}: {e}")
    print("dashboard:", build_dashboard())
