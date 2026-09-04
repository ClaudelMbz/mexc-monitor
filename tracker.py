"""Suivi du prix d'un nouveau listing, en deux phases, + graphiques.

Phase 1 (T2 -> T3) : la paire est visible dans l'API mais ne trade pas encore.
    On interroge le prix toutes les `wait_poll` secondes jusqu'a obtenir un
    premier prix reel (> 0), ou jusqu'a `wait_timeout` (abandon).
Phase 2 (mesure)   : a partir du premier prix reel, on echantillonne toutes
    les `interval` secondes pendant `duration` secondes.

Sortie par listing : prices.csv, summary.json, chart.png, chart.html, et le
dashboard global est regenere.
"""
import csv
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import (
    PRICE_WAIT_POLL_SECONDS,
    PRICE_WAIT_TIMEOUT_SECONDS,
    LISTINGS_DIR,
    TRACK_DURATION_SECONDS,
    TRACK_SAMPLE_INTERVAL_SECONDS,
)
from dashboard import build_dashboard

CSV_HEADER = ["timestamp_utc", "phase", "t_since_detection_s",
              "t_since_first_price_s", "price", "bid", "ask", "spread_pct"]


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


def _spread_pct(bid, ask):
    return round((ask - bid) / bid * 100, 4) if (bid and ask and bid > 0) else None


def _summarize(symbol, detected_at, meta, samples, first_price_at=None,
               wait_seconds=None, status="ok"):
    base = {
        "symbol": symbol,
        "status": status,
        "detected_at": detected_at.isoformat(),
        "first_price_at": first_price_at.isoformat() if first_price_at else None,
        "wait_seconds": round(wait_seconds, 1) if wait_seconds is not None else None,
        "full_name": meta.get("fullName"),
        "base_asset": meta.get("baseAsset"),
        "quote_asset": meta.get("quoteAsset"),
        "samples": len(samples),
        "open": None, "last": None, "min": None, "max": None,
        "change_pct": None, "max_runup_pct": None, "max_drawdown_pct": None,
    }
    prices = [p for _, p in samples if p and p > 0]
    if not prices or prices[0] <= 0:
        return base
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
    ax.set_title(f"{symbol}  |  {summary['change_pct']}% sur {xs[-1]:.1f} min "
                 f"apres le premier prix")
    ax.set_xlabel("minutes depuis le premier prix reel (T3)")
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
  <p class="muted">detecte {summary['detected_at']} UTC &middot;
     premier prix apres {summary.get('wait_seconds')} s &middot;
     {summary['samples']} echantillons &middot; statut : {summary.get('status')}</p>
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
    labels: d.map(x => (x.t / 60).toFixed(2)),
    datasets: [{{
      label: '{symbol} mid price',
      data: d.map(x => x.p),
      borderColor: '#3b82f6', borderWidth: 1.5, pointRadius: 0, tension: .15
    }}]
  }},
  options: {{
    animation: false,
    scales: {{
      x: {{ title: {{ display: true, text: 'minutes depuis le premier prix reel (T3)' }} }},
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
        detected_at = datetime.fromisoformat(meta_all["detected_at"])
    except Exception:
        detected_at = _now()

    samples = []
    wait_seconds = None
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        for row in reader:
            if "phase" in cols and row.get("phase") != "track":
                continue
            try:
                p = float(row["price"])
            except (TypeError, ValueError):
                continue
            if p <= 0:
                continue
            if row.get("t_since_first_price_s") not in (None, ""):
                t = float(row["t_since_first_price_s"])
                if wait_seconds is None and row.get("t_since_detection_s") not in (None, ""):
                    wait_seconds = float(row["t_since_detection_s"])
            elif row.get("elapsed_s") not in (None, ""):  # ancien format
                t = float(row["elapsed_s"])
            else:
                continue
            samples.append((t, p))

    first_price_at = detected_at + timedelta(seconds=wait_seconds) if wait_seconds else None
    summary = _summarize(symbol, detected_at, meta, samples,
                         first_price_at=first_price_at, wait_seconds=wait_seconds,
                         status="rerendered")
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    try:
        _make_png(outdir, symbol, samples, summary)
    except Exception as e:
        log(f"[{symbol}] PNG non genere: {e}")
    _make_html(outdir, symbol, samples, summary)
    log(f"[OK] {symbol}: {summary['samples']} pts, {summary['change_pct']}% -> {outdir}")
    return summary


def track_symbol(client, symbol, meta, stop_event=None,
                 wait_poll=PRICE_WAIT_POLL_SECONDS,
                 wait_timeout=PRICE_WAIT_TIMEOUT_SECONDS,
                 duration=TRACK_DURATION_SECONDS,
                 interval=TRACK_SAMPLE_INTERVAL_SECONDS,
                 log=print):

    def _stopped():
        return stop_event is not None and stop_event.is_set()

    def _sleep(seconds):
        """Dort en respectant stop_event. Renvoie True si on doit s'arreter."""
        if seconds <= 0:
            return _stopped()
        if stop_event is not None:
            return stop_event.wait(seconds)
        time.sleep(seconds)
        return False

    detected_at = _now()
    outdir = LISTINGS_DIR / f"{symbol}_{detected_at.strftime('%Y%m%d_%H%M%S')}"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "meta.json").write_text(json.dumps(
        {"symbol": symbol, "detected_at": detected_at.isoformat(), "info": meta,
         "wait_poll_s": wait_poll, "wait_timeout_s": wait_timeout,
         "duration_s": duration, "interval_s": interval}, indent=2), encoding="utf-8")

    detect_mono = time.monotonic()
    first_price_mono = None
    samples = []
    status = "ok"

    with open(outdir / "prices.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)

        # --- Phase 1 : attendre le premier prix reel (T2 -> T3) --------------
        while first_price_mono is None:
            if _stopped():
                status = "stopped_before_price"
                break
            if time.monotonic() - detect_mono > wait_timeout:
                status = "timeout_no_price"
                log(f"[{symbol}] aucun prix apres {wait_timeout}s, abandon")
                break
            loop_start = time.monotonic()
            price, bid, ask = _sample(client, symbol)
            t_det = round(time.monotonic() - detect_mono, 2)
            if price and price > 0:
                first_price_mono = time.monotonic()
                w.writerow([_now().isoformat(), "track", t_det, 0.0,
                            price, bid, ask, _spread_pct(bid, ask)])
                f.flush()
                samples.append((0.0, price))
                log(f"[{symbol}] premier prix {price:.8g} apres {t_det:.0f}s "
                    f"-> mesure sur {duration}s")
                break
            w.writerow([_now().isoformat(), "wait", t_det, "",
                        price or "", bid, ask, _spread_pct(bid, ask)])
            f.flush()
            if _sleep(wait_poll - (time.monotonic() - loop_start)):
                status = "stopped_before_price"
                break

        # --- Phase 2 : mesure a partir du premier prix (T3) -----------------
        if first_price_mono is not None:
            track_deadline = first_price_mono + duration
            while time.monotonic() < track_deadline:
                if _stopped():
                    status = "stopped_during_track"
                    break
                loop_start = time.monotonic()
                price, bid, ask = _sample(client, symbol)
                t_fp = round(time.monotonic() - first_price_mono, 2)
                t_det = round(time.monotonic() - detect_mono, 2)
                w.writerow([_now().isoformat(), "track", t_det, t_fp,
                            price, bid, ask, _spread_pct(bid, ask)])
                f.flush()
                if price and price > 0:
                    samples.append((t_fp, price))
                if _sleep(interval - (time.monotonic() - loop_start)):
                    status = "stopped_during_track"
                    break

    wait_seconds = None
    first_price_at = None
    if first_price_mono is not None:
        wait_seconds = first_price_mono - detect_mono
        first_price_at = detected_at + timedelta(seconds=wait_seconds)

    summary = _summarize(symbol, detected_at, meta, samples,
                         first_price_at=first_price_at, wait_seconds=wait_seconds,
                         status=status)
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

    log(f"[OK] {symbol} [{status}] : {summary['change_pct']}% "
        f"(min {summary['min']}, max {summary['max']}, {summary['samples']} pts, "
        f"attente T2->T3 {summary['wait_seconds']}s) -> {outdir}")
    return summary
