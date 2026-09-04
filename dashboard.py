"""Genere data/dashboard.html : tableau recap de tous les listings detectes."""
import json
from datetime import datetime, timezone

from config import DATA_DIR, LISTINGS_DIR


def _fmt(v, suffix=""):
    return "-" if v is None else f"{v}{suffix}"


def build_dashboard():
    rows = []
    for d in sorted(LISTINGS_DIR.iterdir(), reverse=True) if LISTINGS_DIR.exists() else []:
        summary = d / "summary.json"
        if not d.is_dir() or not summary.exists():
            continue
        rows.append((d.name, json.loads(summary.read_text(encoding="utf-8"))))

    cards = []
    for name, i in rows:
        chg = i.get("change_pct")
        color = "#9ca3af" if chg is None else ("#22c55e" if chg >= 0 else "#ef4444")
        cards.append(
            f"<tr>"
            f"<td><a href='listings/{name}/chart.html'>{i.get('symbol')}</a></td>"
            f"<td>{i.get('detected_at')}</td>"
            f"<td>{_fmt(i.get('wait_seconds'), ' s')}</td>"
            f"<td style='color:{color};font-weight:600'>{_fmt(chg, '%')}</td>"
            f"<td>{_fmt(i.get('max_runup_pct'), '%')}</td>"
            f"<td>{_fmt(i.get('max_drawdown_pct'), '%')}</td>"
            f"<td>{_fmt(i.get('open'))}</td>"
            f"<td>{_fmt(i.get('last'))}</td>"
            f"<td>{_fmt(i.get('samples'))}</td>"
            f"<td>{_fmt(i.get('status'))}</td>"
            f"</tr>"
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MEXC - nouveaux listings</title>
<style>
  body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:2rem;
       background:#0b0f19;color:#e5e7eb}}
  h1{{margin:0 0 .25rem}}
  p{{color:#9ca3af;margin:.25rem 0 1.25rem}}
  table{{border-collapse:collapse;width:100%;max-width:1000px}}
  th,td{{padding:.55rem .8rem;border-bottom:1px solid #1f2937;text-align:left;
        font-variant-numeric:tabular-nums}}
  th{{color:#9ca3af;font-weight:600;font-size:.85rem;text-transform:uppercase;letter-spacing:.04em}}
  a{{color:#60a5fa;text-decoration:none}} a:hover{{text-decoration:underline}}
  tr:hover td{{background:#111827}}
</style></head><body>
<h1>MEXC - nouveaux listings detectes</h1>
<p>Genere {now} UTC &middot; {len(rows)} listing(s) &middot; rafraichir la page pour la mise a jour</p>
<table>
<tr><th>Symbole</th><th>Detecte (UTC)</th><th>Attente T2&rarr;T3</th><th>&Delta;%</th>
<th>Run-up</th><th>Drawdown</th><th>Open</th><th>Last</th><th>Samples</th><th>Statut</th></tr>
{''.join(cards) or "<tr><td colspan='10'>Aucun listing detecte pour l'instant.</td></tr>"}
</table>
</body></html>"""
    (DATA_DIR / "dashboard.html").write_text(html, encoding="utf-8")
    return DATA_DIR / "dashboard.html"


if __name__ == "__main__":
    print(build_dashboard())
