"""Agrege tous les summary.json pour comparer les strategies d'entree.

  python aggregate.py

Ecrit data/aggregate.json + data/aggregate.html et affiche un tableau.
Chaque ligne = une strategie ; on regarde, sur l'ensemble des listings :
  n           nombre de listings ou la strategie s'est declenchee
  hit_rate    % de cas ou best_ret_pct > 0
  median/mean rendement median / moyen (best_ret_pct et ret_end_pct)
"""
import json
import statistics as st
from datetime import datetime, timezone

from config import DATA_DIR, LISTINGS_DIR, atomic_write


def _load_summaries():
    out = []
    if not LISTINGS_DIR.exists():
        return out
    for d in sorted(LISTINGS_DIR.iterdir()):
        s = d / "summary.json"
        if d.is_dir() and s.exists():
            try:
                out.append(json.loads(s.read_text(encoding="utf-8")))
            except Exception:
                pass
    return out


def _collect(summaries):
    """strategie -> {'best': [...], 'end': [...]}"""
    acc = {}
    for s in summaries:
        for group in ("entry_buy_at_minute", "entry_limit_after_pullback"):
            for name, v in (s.get(group) or {}).items():
                key = f"{group.split('_', 1)[1]}:{name}"
                a = acc.setdefault(key, {"best": [], "end": []})
                if v.get("best_ret_pct") is not None:
                    a["best"].append(v["best_ret_pct"])
                if v.get("ret_end_pct") is not None:
                    a["end"].append(v["ret_end_pct"])
    return acc


def _stats(values):
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "hit_rate_pct": round(100 * sum(1 for x in values if x > 0) / len(values), 1),
        "median": round(st.median(values), 2),
        "mean": round(st.fmean(values), 2),
        "p25": round(sorted(values)[len(values) // 4], 2),
        "p75": round(sorted(values)[3 * len(values) // 4], 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def build_aggregate():
    summaries = _load_summaries()
    usable = [s for s in summaries if s.get("kline_minutes")]
    acc = _collect(summaries)

    strategies = {}
    for key, a in sorted(acc.items()):
        end = a["end"]
        strategies[key] = {
            "n": len(end),
            "win_rate_pct": round(100 * sum(1 for x in end if x > 0) / len(end), 1) if end else None,
            "best_ret": _stats(a["best"]),
            "ret_end": _stats(end),
        }

    # quelques chiffres de contexte
    def col(name):
        return [s[name] for s in usable if s.get(name) is not None]

    context = {
        "listings_total": len(summaries),
        "listings_with_klines": len(usable),
        "first_minute_spike_pct": _stats(col("first_minute_spike_pct")),
        "peak_vs_ref_pct": _stats(col("peak_vs_ref_pct")),
        "peak_at_min": _stats(col("peak_at_min")),
        "drawdown_from_peak_pct": _stats(col("drawdown_from_peak_pct")),
        "post_spike_low_at_min": _stats(col("post_spike_low_at_min")),
        "settle_vs_ref_pct": _stats(col("settle_vs_ref_pct")),
        "settle_vs_floor_pct": _stats(col("settle_vs_floor_pct")),
        "analysis_span_min": _stats(col("analysis_span_min")),
    }

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "context": context,
        "strategies": strategies,
    }
    atomic_write(DATA_DIR / "aggregate.json", json.dumps(result, indent=2))
    _write_html(result)
    _print(result)
    return result


def _print(r):
    c = r["context"]
    print(f"\n{c['listings_with_klines']}/{c['listings_total']} listings avec bougies\n")
    for k in ("first_minute_spike_pct", "peak_vs_ref_pct", "peak_at_min",
              "drawdown_from_peak_pct", "post_spike_low_at_min", "settle_vs_ref_pct",
              "settle_vs_floor_pct", "analysis_span_min"):
        s = c[k]
        if s.get("n"):
            unit = "" if k.endswith("_min") else "%"
            print(f"  {k:24} med {s['median']:>8}{unit}  (n={s['n']}, {s['min']}..{s['max']})")
    print(f"\n  {'strategie':32} {'n':>3} {'win%':>6} {'med best':>9} {'med end':>9}")
    print("  (win% / med end = acheter ET tenir jusqu'a la fin de la fenetre)")
    print("  " + "-" * 64)
    for name, s in r["strategies"].items():
        if s.get("n"):
            print(f"  {name:32} {s['n']:>3} {s.get('win_rate_pct') or 0:>6} "
                  f"{s['best_ret'].get('median', 0):>8}% {s['ret_end'].get('median', 0):>8}%")
    print()


def _row(name, s):
    b, e = s["best_ret"], s["ret_end"]
    if not s.get("n"):
        return ""
    return (f"<tr><td>{name}</td><td>{s['n']}</td><td>{s.get('win_rate_pct')}%</td>"
            f"<td>{b.get('median')}%</td><td>{b.get('p25')}% .. {b.get('p75')}%</td>"
            f"<td>{e.get('median')}%</td></tr>")


def _write_html(r):
    c = r["context"]
    ctx_rows = "".join(
        f"<tr><td>{k}</td><td>{c[k].get('median')}%</td><td>{c[k].get('n')}</td>"
        f"<td>{c[k].get('min')}% .. {c[k].get('max')}%</td></tr>"
        for k in ("first_minute_spike_pct", "peak_vs_ref_pct", "peak_at_min",
                  "drawdown_from_peak_pct", "post_spike_low_at_min", "settle_vs_ref_pct",
                  "settle_vs_floor_pct", "analysis_span_min") if c[k].get("n"))
    strat_rows = "".join(_row(n, s) for n, s in r["strategies"].items())
    html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MEXC - stats agregees</title>
<style>
  body{{font-family:system-ui,sans-serif;margin:2rem;background:#0b0f19;color:#e5e7eb}}
  h1{{margin:0 0 .25rem}} p,.muted{{color:#9ca3af}}
  table{{border-collapse:collapse;margin:.5rem 0 2rem;min-width:640px}}
  th,td{{padding:.5rem .8rem;border-bottom:1px solid #1f2937;text-align:left;
        font-variant-numeric:tabular-nums}}
  th{{color:#9ca3af;font-size:.8rem;text-transform:uppercase}}
  a{{color:#60a5fa}}
</style></head><body>
<h1>Stats agregees</h1>
<p>{r['generated_at'][:19]} UTC &middot; {c['listings_with_klines']}/{c['listings_total']}
   listings exploitables &middot; <a href="dashboard.html">&larr; dashboard</a></p>
<p class="muted">Echantillon encore petit : a lire quand n &ge; 20-30.</p>

<h2>Contexte (medianes)</h2>
<table><tr><th>metrique</th><th>mediane</th><th>n</th><th>min .. max</th></tr>
{ctx_rows or "<tr><td colspan=4>-</td></tr>"}</table>

<h2>Strategies d'entree</h2>
<p class="muted">med best = rendement median atteignable apres l'entree &middot;
   fourchette = p25..p75 &middot; med end = rendement median en fin de fenetre</p>
<table><tr><th>strategie</th><th>n</th><th>win rate (tenu)</th><th>med best</th>
<th>p25..p75 (best)</th><th>med end (tenu)</th></tr>
{strat_rows or "<tr><td colspan=6>-</td></tr>"}</table>
</body></html>"""
    atomic_write(DATA_DIR / "aggregate.html", html)


if __name__ == "__main__":
    build_aggregate()
