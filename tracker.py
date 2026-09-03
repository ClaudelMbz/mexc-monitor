"""Suivi du prix d'un nouveau listing sur une fenetre courte, + graphiques.

Un appel a track_symbol() echantillonne le prix toutes les `interval` secondes
pendant `duration` secondes, ecrit un CSV, un resume JSON, un PNG (matplotlib)
et un HTML interactif (Chart.js), puis regenere le dashboard global.
"""
import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from config import LISTINGS_DIR, TRACK_DURATION_SECONDS, TRACK_SAMPLE_INTERVAL_SECONDS
from dashboard import build_dashboard


def _now():
    return datetime.now(timezone.utc)


def _sample(client, symbol):
    """Renvoie (price, bid, ask) au mieux ; price = mid si bid/ask dispo."""
    bid = ask = None
    try:
        bt = client.book_ticker(symbol)
        bp, ap = bt.get("bidPrice"), bt.get("askPrice")
        bid = float(bp) if bp not in (None, "", "0") else None
        ask = float(ap) if ap not in (None, "", "0") else None
    except Exception:
        pass
    if bid and ask:
        return (bid + ask) / 2, bid, ask
    try:
        return float(client.price(symbol)["price"]), bid, ask
    except Exception:
        return None, bid, ask


def _summarize(symbol, start, meta, samples):
    base = {
        "symbol": symbol,
        "detected_at": start.isoformat(),
        "full_name": meta.get("fullName"),
        "base_asset": meta.get("baseAsset"),
        "quote_asset": meta.get("quoteAsset"),
        "samples": len(samples),
        "open": None, "last": None, "min": None, "max": None,
        "change_pct": None, "max_runup_pct": None, "max_drawdown_pct": None,
    }
    if not samples:
        return base
    prices = [p for _, p in samples]
    op, last, mn, mx = prices[0], prices[-1], min(prices), max(prices)
    base.update(
        open=op, last=last, min=mn, max=mx,
        change_pct=round((last - op) / op * 100, 3),
        max_runup_pct=round((mx - op) / op * 100, 3),
        max_drawdown_pct=round((mn - op) / op * 100, 3),
    )
    return base


def _make_png(outdir, symbol, samples, summary):
    if not samples:
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [s / 60 for s, _ in samples]
    ys = [p for _, p in samples]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(xs, ys, color="#2563eb", linewidth=1.6)
    ax.scatter([xs[0]], [ys[0]], color="#16a34a", zorder=5, label=f"open {ys[0]:.8g}")
    ax.scatter([xs[-1]], [ys[-1]], color="#dc2626", zorder=5, label=f"last {ys[-1]:.8g}")
    ax.set_title(f"{symbol}  |  {summary['change_pct']}% sur {xs[-1]:.1f} min apres listing")
    ax.set_xlabel("minutes depuis la detection")
    ax.set_ylabel("prix (mid bid/ask)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(outdir / "chart.png", dpi=120)
    plt.close(fig)


def _make_html(outdir, symbol, samples, summary):
    data = [{"t": round(s, 2), "p": p} for s, p in samples]
    html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{symbol} - listing</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:2rem;
       background:#0b0f19;color:#e5e7eb}}
  .card{{background:#111827;padding:1.25rem 1.5rem;border-radius:14px;max-width:960px}}
  h1{{margin:.2rem 0}} .muted{{color:#9ca3af}} b{{color:#fff}}
  .grid{{display:flex;flex-wrap:wrap;gap:1.5rem;margin:.75rem 0 1rem}}
</style></head><body>
<div class="card">
  <h1>{symbol} <span class="muted">{summary.get('full_name') or ''}</span></h1>
  <p class="muted">detecte {summary['detected_at']} UTC &middot; {summary['samples']} echantillons</p>
  <div class="grid">
    <div>open <b>{summary['open']}</b></div>
    <div>last <b>{summary['last']}</b></div>
    <div>min {summary['min']}</div>
    <div>max {summary['max']}</div>
    <div>&Delta; <b>{summary['change_pct']}%</b></div>
    <div>run-up {summary['max_runup_pct']}%</div>
    <div>drawdown {summary['max_drawdown_pct']}%</div>
  </div>
  <canvas id="c" height="110"></canvas>
  <p class="muted"><a href="../../dashboard.html" style="color:#60a5fa">&larr; dashboard</a>
     &middot; donnees brutes : prices.csv</p>
</div>
<script>
const d = {json.dumps(data)};
new Chart(document.getElementById('c'), {{
  type: 'line',
  data: {{
    labels: d.map(x => (x.t / 60).toFixed(1)),
    datasets: [{{
      label: '{symbol} mid price',
      data: d.map(x => x.p),
      borderColor: '#3b82f6', borderWidth: 1.5, pointRadius: 0, tension: .15
    }}]
  }},
  options: {{
    animation: false,
    scales: {{
      x: {{ title: {{ display: true, text: 'minutes depuis la detection' }} }},
      y: {{ title: {{ display: true, text: 'prix' }} }}
    }}
  }}
}});
</script>
</body></html>"""
    (outdir / "chart.html").write_text(html, encoding="utf-8")


def render_from_csv(outdir, log=print):
    """(Re)genere summary.json + chart.png + chart.html a partir d'un
    prices.csv deja present. Utile si le suivi a ete coupe avant la fin."""
    outdir = Path(outdir)
    csv_path = outdir / "prices.csv"
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    meta_file = outdir / "meta.json"
    meta_all = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    meta = meta_all.get("info", {})
    symbol = meta_all.get("symbol") or meta.get("symbol") or outdir.name.split("_")[0]
    try:
        start = datetime.fromisoformat(meta_all["detected_at"])
    except Exception:
        start = _now()

    samples = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                p = float(row["price"])
            except (TypeError, ValueError):
                continue
            samples.append((float(row["elapsed_s"]), p))

    summary = _summarize(symbol, start, meta, samples)
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    try:
        _make_png(outdir, symbol, samples, summary)
    except Exception as e:
        log(f"[{symbol}] PNG non genere: {e}")
    _make_html(outdir, symbol, samples, summary)
    log(f"[OK] {symbol}: {summary['samples']} pts, {summary['change_pct']}% -> {outdir}")
    return summary


def track_symbol(client, symbol, meta, stop_event=None,
                 duration=TRACK_DURATION_SECONDS,
                 interval=TRACK_SAMPLE_INTERVAL_SECONDS,
                 log=print):
    start = _now()
    outdir = LISTINGS_DIR / f"{symbol}_{start.strftime('%Y%m%d_%H%M%S')}"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "meta.json").write_text(json.dumps(
        {"symbol": symbol, "detected_at": start.isoformat(), "info": meta,
         "duration_s": duration, "interval_s": interval}, indent=2), encoding="utf-8")

    samples = []
    start_mono = time.monotonic()
    deadline = start_mono + duration

    with open(outdir / "prices.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_utc", "elapsed_s", "price", "bid", "ask", "spread_pct"])
        while time.monotonic() < deadline:
            if stop_event is not None and stop_event.is_set():
                break
            loop_start = time.monotonic()
            price, bid, ask = _sample(client, symbol)
            elapsed = round(time.monotonic() - start_mono, 2)
            spread = round((ask - bid) / bid * 100, 4) if (bid and ask and bid > 0) else None
            w.writerow([_now().isoformat(), elapsed, price, bid, ask, spread])
            f.flush()
            if price is not None:
                samples.append((elapsed, price))
            wait = interval - (time.monotonic() - loop_start)
            if wait > 0:
                if stop_event is not None:
                    if stop_event.wait(wait):
                        break
                else:
                    time.sleep(wait)

    summary = _summarize(symbol, start, meta, samples)
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    try:
        _make_png(outdir, symbol, samples, summary)
    except Exception as e:
        log(f"[{symbol}] PNG non genere: {e}")
    _make_html(outdir, symbol, samples, summary)
    try:
        build_dashboard()
    except Exception as e:
        log(f"[{symbol}] dashboard: {e}")

    log(f"[OK] suivi {symbol} termine : {summary['change_pct']}% "
        f"(min {summary['min']}, max {summary['max']}, {summary['samples']} pts) -> {outdir}")
    return summary
