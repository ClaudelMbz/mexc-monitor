"""Genere data/dashboard.html : tableau recap de tous les listings detectes."""
import json
from datetime import datetime, timezone

from config import DATA_DIR, LISTINGS_DIR


def _fmt(v, suffix=""):
    return "-" if v is None else f"{v}{suffix}"


def _color(v):
    if v is None:
        return "#9ca3af"
    return "#22c55e" if v >= 0 else "#ef4444"


def build_dashboard():
    rows = []
    dirs = sorted(LISTINGS_DIR.iterdir(), reverse=True) if LISTINGS_DIR.exists() else []
    for d in dirs:
        summary = d / "summary.json"
        if not d.is_dir() or not summary.exists():
            continue
        rows.append((d.name, json.loads(summary.read_text(encoding="utf-8"))))

    cards = []
    for name, i in rows:
        dips = i.get("entry_limit_after_pullback") or {}
        best_dip = max((v.get("best_ret_pct") for v in dips.values()
                        if v.get("best_ret_pct") is not None), default=None)
        floor = _fmt(i.get("listing_floor"))
        if i.get("listing_floor") is not None and not i.get("floor_reliable", True):
            floor += " ?"
        cards.append(
            "<tr>"
            f"<td><a href='listings/{name}/chart.html'>{i.get('symbol')}</a></td>"
            f"<td class='muted'>{(i.get('detected_at') or '')[:19]}</td>"
            f"<td>{_fmt(i.get('wait_seconds'), ' s')}</td>"
            f"<td>{floor}</td>"
            f"<td style='color:{_color(i.get('first_minute_spike_pct'))}'>"
            f"{_fmt(i.get('first_minute_spike_pct'), '%')}</td>"
            f"<td style='color:{_color(i.get('peak_vs_ref_pct'))}'>"
            f"{_fmt(i.get('peak_vs_ref_pct'), '%')}</td>"
            f"<td style='color:{_color(i.get('drawdown_from_peak_pct'))}'>"
            f"{_fmt(i.get('drawdown_from_peak_pct'), '%')}</td>"
            f"<td style='color:{_color(i.get('settle_vs_ref_pct'))}'>"
            f"{_fmt(i.get('settle_vs_ref_pct'), '%')}</td>"
            f"<td style='color:{_color(best_dip)}'>{_fmt(round(best_dip, 1) if best_dip is not None else None, '%')}</td>"
            f"<td>{_fmt(i.get('kline_minutes'))}</td>"
            f"<td class='muted'>{_fmt(i.get('status'))}</td>"
            "</tr>"
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
  .wrap{{overflow-x:auto}}
  table{{border-collapse:collapse;min-width:960px}}
  th,td{{padding:.55rem .8rem;border-bottom:1px solid #1f2937;text-align:left;
        font-variant-numeric:tabular-nums;white-space:nowrap}}
  th{{color:#9ca3af;font-weight:600;font-size:.8rem;text-transform:uppercase;letter-spacing:.03em}}
  a{{color:#60a5fa;text-decoration:none}} a:hover{{text-decoration:underline}}
  .muted{{color:#9ca3af}}
  tr:hover td{{background:#111827}}
</style></head><body>
<h1>MEXC - nouveaux listings detectes</h1>
<p>Genere {now} UTC &middot; {len(rows)} listing(s) &middot;
   <a href="aggregate.html">stats agregees &rarr;</a></p>
<div class="wrap"><table>
<tr>
  <th>Symbole</th><th>Detecte (UTC)</th><th>Attente T2&rarr;T3</th><th>Plancher</th>
  <th>Spike 1re min</th><th>Pic /ref</th><th>Repli max</th><th>Fin /ref</th>
  <th>Best entree repli</th><th>Bougies</th><th>Statut</th>
</tr>
{''.join(cards) or "<tr><td colspan='11'>Aucun listing detecte pour l'instant.</td></tr>"}
</table></div>
</body></html>"""
    (DATA_DIR / "dashboard.html").write_text(html, encoding="utf-8")
    return DATA_DIR / "dashboard.html"


if __name__ == "__main__":
    print(build_dashboard())
