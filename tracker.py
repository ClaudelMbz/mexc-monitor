"""Suivi d'un nouveau listing en 3 phases, + graphiques + analyse d'entree.

Phase 1 (T2 -> T3) : la paire est visible mais ne trade pas encore.
    On interroge le prix toutes les `wait_poll` s jusqu'au premier prix reel.
Phase 2 (tick)     : a partir du premier prix, echantillonnage fin (2 s)
    pendant `duration` s -> microstructure du demarrage.
Phase 3 (bougies)  : on recupere les bougies 1m toutes les `kline_poll` s
    pendant `follow_minutes` min -> on voit spike / repli / stabilisation,
    et on calcule des points d'entree theoriques.

Sortie par listing : prices.csv (tick), klines.csv (1m), summary.json,
chart.png / chart.html (bougies), chart_ticks.png / chart_ticks.html.
"""
import csv
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import (
    KLINE_FOLLOW_MINUTES,
    KLINE_POLL_SECONDS,
    LISTINGS_DIR,
    PRICE_WAIT_POLL_SECONDS,
    PRICE_WAIT_TIMEOUT_SECONDS,
    TRACK_DURATION_SECONDS,
    TRACK_SAMPLE_INTERVAL_SECONDS,
    atomic_write,
)
from dashboard import build_dashboard

TICK_CSV_HEADER = ["timestamp_utc", "phase", "t_since_detection_s",
                   "t_since_first_price_s", "price", "bid", "ask", "spread_pct"]
KLINE_CSV_HEADER = ["open_time_utc", "minute", "open", "high", "low", "close",
                    "volume", "quote_volume"]

PULLBACK_THRESHOLDS = (10, 20, 30, 40, 50)
FIXED_ENTRY_MINUTES = (1, 2, 3, 5, 10)
SNAPSHOT_MINUTES = (1, 2, 3, 5, 10, 15, 30, 60)


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


def _fetch_klines(client, symbol, start_ms=None):
    raw = client.klines(symbol, "1m", limit=1000, start_time=start_ms)
    out = []
    for k in raw:
        out.append({
            "open_time": int(k[0]),
            "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]),
            "volume": float(k[5]),
            "quote_volume": float(k[7]) if len(k) > 7 and k[7] not in (None, "") else None,
        })
    out.sort(key=lambda x: x["open_time"])
    return out


def _write_klines_csv(outdir, klines, t0_ms):
    with open(outdir / "klines.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(KLINE_CSV_HEADER)
        for k in klines:
            minute = round((k["open_time"] - t0_ms) / 60000, 2)
            w.writerow([
                datetime.fromtimestamp(k["open_time"] / 1000, timezone.utc).isoformat(),
                minute, k["open"], k["high"], k["low"], k["close"],
                k["volume"], k["quote_volume"],
            ])
    atomic_write(outdir / "klines.json", json.dumps(klines, indent=1))


# --------------------------------------------------------------------------- #
#  Analyse                                                                     #
# --------------------------------------------------------------------------- #
def _summarize_ticks(symbol, detected_at, meta, samples, first_price_at, wait_seconds, status):
    base = {
        "symbol": symbol,
        "status": status,
        "detected_at": detected_at.isoformat(),
        "first_price_at": first_price_at.isoformat() if first_price_at else None,
        "wait_seconds": round(wait_seconds, 1) if wait_seconds is not None else None,
        "full_name": meta.get("fullName"),
        "base_asset": meta.get("baseAsset"),
        "quote_asset": meta.get("quoteAsset"),
        "tick_samples": len(samples),
        "tick_open": None, "tick_last": None, "tick_min": None, "tick_max": None,
        "tick_change_pct": None, "tick_runup_pct": None, "tick_drawdown_pct": None,
    }
    prices = [p for _, p in samples if p and p > 0]
    if prices and prices[0] > 0:
        op, last, mn, mx = prices[0], prices[-1], min(prices), max(prices)
        base.update(
            tick_open=op, tick_last=last, tick_min=mn, tick_max=mx,
            tick_change_pct=round((last - op) / op * 100, 3),
            tick_runup_pct=round((mx - op) / op * 100, 3),
            tick_drawdown_pct=round((mn - op) / op * 100, 3),
        )
    return base


def _analyze_klines(klines, t0_ms, detected_at):
    """Stats de listing + points d'entree theoriques a partir des bougies 1m."""
    if not klines:
        return {"kline_minutes": 0}

    first = klines[0]
    # La 1ere bougie retournee est-elle vraiment la bougie d'ouverture ?
    gap_min = (first["open_time"] - int(detected_at.timestamp() * 1000)) / 60000
    floor_reliable = gap_min <= 3  # sinon MEXC n'a pas garde l'historique complet

    floor = first["low"]
    first_min_high = first["high"]
    ref = first["close"]  # prix "de marche" apres le spike de la 1ere minute
    spike_pct = (first_min_high / floor - 1) * 100 if floor > 0 else None

    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]
    closes = [k["close"] for k in klines]

    span_min = round((klines[-1]["open_time"] - klines[0]["open_time"]) / 60000)
    peak = max(highs)
    peak_idx = highs.index(peak)
    settle = closes[-1]
    post = lows[peak_idx:]
    post_low = min(post)
    post_low_idx = peak_idx + post.index(post_low)
    drawdown_from_peak = (post_low / peak - 1) * 100 if peak > 0 else None

    def at(minute):
        return closes[minute] if 0 <= minute < len(closes) else None

    # A quelle minute le plus haut est-il atteint, selon la fenetre consideree ?
    peak_timing = {}
    for win in (15, 30, 60, 120):
        sub = highs[:win]
        if sub:
            mx = max(sub)
            peak_timing[f"peak_in_{win}m"] = {
                "price": mx, "at_min": sub.index(mx),
                "vs_ref_pct": round((mx / ref - 1) * 100, 2) if ref > 0 else None,
            }

    out = {
        "kline_minutes": len(klines),
        "analysis_span_min": span_min,
        "peak_timing": peak_timing,
        "floor_reliable": floor_reliable,
        "listing_floor": floor,
        "first_minute_high": first_min_high,
        "first_minute_spike_pct": round(spike_pct, 1) if spike_pct else None,
        "reference_price": ref,
        "peak_price": peak,
        "peak_at_min": peak_idx,
        "peak_vs_ref_pct": round((peak / ref - 1) * 100, 2) if ref > 0 else None,
        "post_spike_low": post_low,
        "post_spike_low_at_min": post_low_idx,
        "drawdown_from_peak_pct": round(drawdown_from_peak, 2) if drawdown_from_peak is not None else None,
        "settle_price": settle,
        "settle_vs_ref_pct": round((settle / ref - 1) * 100, 2) if ref > 0 else None,
        "settle_vs_floor_pct": round((settle / floor - 1) * 100, 2) if floor > 0 else None,
    }
    for m in SNAPSHOT_MINUTES:
        out[f"close_{m}m"] = at(m)

    # --- Strategie A : acheter au close de la minute N -------------------
    fixed = {}
    for m in FIXED_ENTRY_MINUTES:
        p = at(m)
        if p and p > 0 and m < len(closes):
            best = max(highs[m:])
            fixed[f"buy_at_{m}m"] = {
                "entry": p,
                "ret_end_pct": round((settle / p - 1) * 100, 2),
                "best_ret_pct": round((best / p - 1) * 100, 2),
            }

    # --- Strategie B : ordre limite a -X% du plus haut glissant ---------
    pullback = {}
    running_peak = ref
    for i in range(1, len(klines)):
        running_peak = max(running_peak, highs[i])
        for thr in PULLBACK_THRESHOLDS:
            key = f"dip_{thr}pct"
            if key in pullback or running_peak <= 0:
                continue
            if (running_peak - lows[i]) / running_peak * 100 >= thr:
                entry = running_peak * (1 - thr / 100)
                best = max(highs[i:])
                pullback[key] = {
                    "entry": round(entry, 12),
                    "at_min": i,
                    "ret_end_pct": round((settle / entry - 1) * 100, 2),
                    "best_ret_pct": round((best / entry - 1) * 100, 2),
                }

    out["entry_buy_at_minute"] = fixed
    out["entry_limit_after_pullback"] = pullback
    return out


# --------------------------------------------------------------------------- #
#  Graphiques                                                                  #
# --------------------------------------------------------------------------- #
def _make_kline_png(outdir, symbol, klines, t0_ms, s):
    if not klines:
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [(k["open_time"] - t0_ms) / 60000 for k in klines]
    close = [k["close"] for k in klines]
    hi = [k["high"] for k in klines]
    lo = [k["low"] for k in klines]

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.fill_between(xs, lo, hi, color="#3b82f6", alpha=0.15, label="range 1m (low-high)")
    ax.plot(xs, close, color="#2563eb", linewidth=1.6, label="close 1m")
    if s.get("reference_price"):
        ax.axhline(s["reference_price"], color="#6b7280", linestyle=":", linewidth=1,
                   label=f"ref {s['reference_price']:.6g}")
    if s.get("peak_at_min") is not None:
        ax.scatter([s["peak_at_min"]], [s["peak_price"]], color="#dc2626", zorder=5,
                   label=f"pic +{s.get('peak_vs_ref_pct')}%")
    if s.get("post_spike_low_at_min") is not None:
        ax.scatter([s["post_spike_low_at_min"]], [s["post_spike_low"]], color="#16a34a",
                   zorder=5, label=f"plus bas post-pic ({s.get('drawdown_from_peak_pct')}%)")
    fl = f" | plancher {s['listing_floor']:.6g} (spike +{s.get('first_minute_spike_pct')}%)" \
        if s.get("floor_reliable") else ""
    ax.set_title(f"{symbol} — {s.get('kline_minutes')} min apres le 1er prix{fl}")
    ax.set_xlabel("minutes depuis le premier prix reel (T3)")
    ax.set_ylabel(f"prix ({s.get('quote_asset')})")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(outdir / "chart.png", dpi=120)
    plt.close(fig)


def _rows_html(d):
    if not d:
        return "<tr><td colspan='4' class='muted'>-</td></tr>"
    out = []
    for k, v in d.items():
        out.append(f"<tr><td>{k}</td><td>{v.get('entry')}</td>"
                   f"<td>{v.get('ret_end_pct')}%</td><td>{v.get('best_ret_pct')}%</td></tr>")
    return "".join(out)


def _make_kline_html(outdir, symbol, klines, t0_ms, s):
    data = [{"m": round((k["open_time"] - t0_ms) / 60000, 2),
             "c": k["close"], "h": k["high"], "l": k["low"]} for k in klines]
    html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{symbol} - listing</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:2rem;
       background:#0b0f19;color:#e5e7eb}}
  .card{{background:#111827;padding:1.25rem 1.5rem;border-radius:14px;max-width:1000px;
        margin-bottom:1.25rem}}
  h1{{margin:.2rem 0}} .muted{{color:#9ca3af}} b{{color:#fff}}
  .grid{{display:flex;flex-wrap:wrap;gap:1.25rem;margin:.75rem 0}}
  table{{border-collapse:collapse;width:100%;margin-top:.5rem}}
  td,th{{padding:.4rem .7rem;border-bottom:1px solid #1f2937;text-align:left;
        font-variant-numeric:tabular-nums}}
  th{{color:#9ca3af;font-size:.8rem;text-transform:uppercase}}
  a{{color:#60a5fa}}
</style></head><body>
<div class="card">
  <h1>{symbol} <span class="muted">{s.get('full_name') or ''}</span></h1>
  <p class="muted">detecte {s['detected_at']} UTC &middot; 1er prix apres {s.get('wait_seconds')} s
     &middot; {s.get('kline_minutes')} bougies 1m &middot; statut : {s.get('status')}</p>
  <div class="grid">
    <div>plancher <b>{s.get('listing_floor')}</b> {'' if s.get('floor_reliable') else '(incertain)'}</div>
    <div>spike 1re min <b>+{s.get('first_minute_spike_pct')}%</b></div>
    <div>prix ref <b>{s.get('reference_price')}</b></div>
    <div>pic <b>{s.get('peak_price')}</b> (+{s.get('peak_vs_ref_pct')}% / ref, min {s.get('peak_at_min')})</div>
    <div>repli max depuis pic <b>{s.get('drawdown_from_peak_pct')}%</b> (min {s.get('post_spike_low_at_min')})</div>
    <div>fin de fenetre <b>{s.get('settle_price')}</b> ({s.get('settle_vs_ref_pct')}% / ref)</div>
  </div>
  <canvas id="c" height="105"></canvas>
</div>

<div class="card">
  <h2 style="margin:.2rem 0">Points d'entree theoriques</h2>
  <p class="muted">ret_end = rendement jusqu'a la fin de la fenetre &middot;
     best = meilleur rendement atteignable apres l'entree</p>
  <h3>Acheter au close de la minute N</h3>
  <table><tr><th>strategie</th><th>prix d'entree</th><th>ret_end</th><th>best</th></tr>
  {_rows_html(s.get('entry_buy_at_minute'))}</table>
  <h3>Ordre limite a -X% du plus haut glissant</h3>
  <table><tr><th>strategie</th><th>prix d'entree</th><th>ret_end</th><th>best</th></tr>
  {_rows_html(s.get('entry_limit_after_pullback'))}</table>
  <p class="muted" style="margin-top:1rem">
     <a href="../../dashboard.html">&larr; dashboard</a> &middot;
     <a href="chart_ticks.html">zoom tick (3 premieres min)</a> &middot;
     donnees : klines.csv / prices.csv</p>
</div>
<script>
const d = {json.dumps(data)};
new Chart(document.getElementById('c'), {{
  type: 'line',
  data: {{ labels: d.map(x => x.m.toFixed(0)),
    datasets: [
      {{label:'close 1m', data:d.map(x=>x.c), borderColor:'#3b82f6', borderWidth:1.5,
        pointRadius:0, tension:.15}},
      {{label:'high', data:d.map(x=>x.h), borderColor:'#1e3a8a', borderWidth:.5,
        pointRadius:0, fill:'+1', backgroundColor:'rgba(59,130,246,.10)'}},
      {{label:'low', data:d.map(x=>x.l), borderColor:'#1e3a8a', borderWidth:.5, pointRadius:0}}
    ] }},
  options: {{ animation:false, plugins:{{legend:{{labels:{{boxWidth:12}}}}}},
    scales:{{ x:{{title:{{display:true,text:'minutes depuis le premier prix reel (T3)'}}}},
             y:{{title:{{display:true,text:'prix'}}}} }} }}
}});
</script>
</body></html>"""
    atomic_write(outdir / "chart.html", html)


def _make_tick_png(outdir, symbol, samples, s):
    if not samples:
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [t / 60 for t, _ in samples]
    ys = [p for _, p in samples]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(xs, ys, color="#2563eb", linewidth=1.4)
    ax.scatter([xs[0]], [ys[0]], color="#16a34a", zorder=5, label=f"open {ys[0]:.8g}")
    ax.scatter([xs[-1]], [ys[-1]], color="#dc2626", zorder=5, label=f"last {ys[-1]:.8g}")
    ax.set_title(f"{symbol} — zoom tick, {s.get('tick_change_pct')}% sur {xs[-1]:.1f} min")
    ax.set_xlabel("minutes depuis le premier prix reel (T3)")
    ax.set_ylabel("prix (mid bid/ask)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(outdir / "chart_ticks.png", dpi=120)
    plt.close(fig)


def _make_tick_html(outdir, symbol, samples, s):
    data = [{"t": round(t, 2), "p": p} for t, p in samples]
    html = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{symbol} - zoom tick</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>body{{font-family:system-ui,sans-serif;margin:2rem;background:#0b0f19;color:#e5e7eb}}
.card{{background:#111827;padding:1.25rem 1.5rem;border-radius:14px;max-width:960px}}
a{{color:#60a5fa}} .muted{{color:#9ca3af}}</style></head><body>
<div class="card">
  <h1>{symbol} <span class="muted">zoom tick</span></h1>
  <p class="muted">{s.get('tick_samples')} echantillons &middot; open {s.get('tick_open')}
     &middot; last {s.get('tick_last')} &middot; &Delta; {s.get('tick_change_pct')}%
     &middot; run-up {s.get('tick_runup_pct')}% &middot; drawdown {s.get('tick_drawdown_pct')}%</p>
  <canvas id="c" height="110"></canvas>
  <p class="muted"><a href="chart.html">&larr; vue bougies + entrees</a></p>
</div>
<script>
const d = {json.dumps(data)};
new Chart(document.getElementById('c'), {{ type:'line',
  data:{{labels:d.map(x=>(x.t/60).toFixed(2)),
    datasets:[{{label:'{symbol} mid', data:d.map(x=>x.p), borderColor:'#3b82f6',
      borderWidth:1.5, pointRadius:0, tension:.15}}]}},
  options:{{animation:false,
    scales:{{x:{{title:{{display:true,text:'minutes depuis T3'}}}},
            y:{{title:{{display:true,text:'prix'}}}}}}}}}});
</script></body></html>"""
    atomic_write(outdir / "chart_ticks.html", html)


def _finalize(outdir, symbol, detected_at, meta, samples, klines, t0_ms,
              first_price_at, wait_seconds, status, log, dashboard_min_interval=0.0):
    # Ne jamais regresser : si on n'a pas (ou moins) de bougies en memoire mais
    # qu'un klines.json plus complet existe deja sur disque, on le reutilise.
    disk = outdir / "klines.json"
    if disk.exists():
        try:
            saved = json.loads(disk.read_text(encoding="utf-8"))
            if len(saved) > len(klines):
                klines = saved
        except (json.JSONDecodeError, OSError):
            pass
    summary = _summarize_ticks(symbol, detected_at, meta, samples,
                               first_price_at, wait_seconds, status)
    summary.update(_analyze_klines(klines, t0_ms, detected_at))
    atomic_write(outdir / "summary.json", json.dumps(summary, indent=2))
    for fn, args in ((_make_kline_png, (outdir, symbol, klines, t0_ms, summary)),
                     (_make_kline_html, (outdir, symbol, klines, t0_ms, summary)),
                     (_make_tick_png, (outdir, symbol, samples, summary)),
                     (_make_tick_html, (outdir, symbol, samples, summary))):
        try:
            fn(*args)
        except Exception as e:
            log(f"[{symbol}] {fn.__name__}: {e}")
    try:
        build_dashboard(min_interval=dashboard_min_interval)
    except Exception as e:
        log(f"[{symbol}] dashboard: {e}")
    return summary


# --------------------------------------------------------------------------- #
#  Boucle principale de suivi                                                  #
# --------------------------------------------------------------------------- #
def track_symbol(client, symbol, meta, stop_event=None,
                 wait_poll=PRICE_WAIT_POLL_SECONDS,
                 wait_timeout=PRICE_WAIT_TIMEOUT_SECONDS,
                 duration=TRACK_DURATION_SECONDS,
                 interval=TRACK_SAMPLE_INTERVAL_SECONDS,
                 follow_minutes=KLINE_FOLLOW_MINUTES,
                 kline_poll=KLINE_POLL_SECONDS,
                 log=print):

    def _stopped():
        return stop_event is not None and stop_event.is_set()

    def _sleep(seconds):
        if seconds <= 0:
            return _stopped()
        if stop_event is not None:
            return stop_event.wait(seconds)
        time.sleep(seconds)
        return False

    detected_at = _now()
    t0_ms = int(detected_at.timestamp() * 1000)
    outdir = LISTINGS_DIR / f"{symbol}_{detected_at.strftime('%Y%m%d_%H%M%S')}"
    outdir.mkdir(parents=True, exist_ok=True)
    atomic_write(outdir / "meta.json", json.dumps(
        {"symbol": symbol, "detected_at": detected_at.isoformat(), "info": meta,
         "wait_poll_s": wait_poll, "wait_timeout_s": wait_timeout,
         "duration_s": duration, "interval_s": interval,
         "follow_minutes": follow_minutes, "kline_poll_s": kline_poll}, indent=2))

    detect_mono = time.monotonic()
    first_price_mono = None
    samples = []
    klines = []
    status = "ok"

    with open(outdir / "prices.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(TICK_CSV_HEADER)

        # --- Phase 1 : attendre le premier prix reel (T2 -> T3) ------------
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
                log(f"[{symbol}] premier prix {price:.8g} apres {t_det:.0f}s")
                break
            w.writerow([_now().isoformat(), "wait", t_det, "",
                        price or "", bid, ask, _spread_pct(bid, ask)])
            f.flush()
            if _sleep(wait_poll - (time.monotonic() - loop_start)):
                status = "stopped_before_price"
                break

        # --- Phase 2 : capture tick fine ---------------------------------
        if first_price_mono is not None:
            tick_deadline = first_price_mono + duration
            while time.monotonic() < tick_deadline:
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

    # --- Phase 3 : suivi des bougies 1m --------------------------------
    if first_price_mono is not None and status == "ok":
        follow_deadline = first_price_mono + follow_minutes * 60
        while time.monotonic() < follow_deadline:
            if _stopped():
                status = "stopped_during_follow"
                break
            try:
                klines = _fetch_klines(client, symbol, start_ms=t0_ms)
                _write_klines_csv(outdir, klines, t0_ms)
                _finalize(outdir, symbol, detected_at, meta, samples, klines, t0_ms,
                          detected_at + timedelta(seconds=first_price_mono - detect_mono),
                          first_price_mono - detect_mono, "following", log,
                          dashboard_min_interval=20)
            except Exception as e:
                log(f"[{symbol}] klines: {e}")
            if _sleep(kline_poll):
                status = "stopped_during_follow"
                break

    # --- Bilan final -------------------------------------------------
    wait_seconds = first_price_at = None
    if first_price_mono is not None:
        wait_seconds = first_price_mono - detect_mono
        first_price_at = detected_at + timedelta(seconds=wait_seconds)
    if first_price_mono is not None:
        try:
            klines = _fetch_klines(client, symbol, start_ms=t0_ms)
            _write_klines_csv(outdir, klines, t0_ms)
        except Exception as e:
            log(f"[{symbol}] klines (final): {e}")

    summary = _finalize(outdir, symbol, detected_at, meta, samples, klines, t0_ms,
                        first_price_at, wait_seconds, status, log)
    log(f"[OK] {symbol} [{status}] : plancher {summary.get('listing_floor')} "
        f"spike +{summary.get('first_minute_spike_pct')}% / pic +{summary.get('peak_vs_ref_pct')}% "
        f"/ repli {summary.get('drawdown_from_peak_pct')}% / fin {summary.get('settle_vs_ref_pct')}% "
        f"-> {outdir}")
    return summary


# --------------------------------------------------------------------------- #
#  Regeneration hors-ligne depuis les CSV                                      #
# --------------------------------------------------------------------------- #
def render_from_csv(outdir, log=print):
    outdir = Path(outdir)
    meta_file = outdir / "meta.json"
    meta_all = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    meta = meta_all.get("info", {})
    symbol = meta_all.get("symbol") or meta.get("symbol") or outdir.name.split("_")[0]
    try:
        detected_at = datetime.fromisoformat(meta_all["detected_at"])
    except Exception:
        detected_at = _now()
    t0_ms = int(detected_at.timestamp() * 1000)

    # ticks
    samples, wait_seconds = [], None
    tick_csv = outdir / "prices.csv"
    if tick_csv.exists():
        with open(tick_csv, newline="", encoding="utf-8") as f:
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
                elif row.get("elapsed_s") not in (None, ""):
                    t = float(row["elapsed_s"])
                else:
                    continue
                samples.append((t, p))

    # klines
    klines = []
    kfile = outdir / "klines.json"
    if kfile.exists():
        klines = json.loads(kfile.read_text(encoding="utf-8"))
    elif (outdir / "klines.csv").exists():
        with open(outdir / "klines.csv", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                klines.append({
                    "open_time": int(datetime.fromisoformat(row["open_time_utc"]).timestamp() * 1000),
                    "open": float(row["open"]), "high": float(row["high"]),
                    "low": float(row["low"]), "close": float(row["close"]),
                    "volume": float(row["volume"] or 0),
                    "quote_volume": float(row["quote_volume"]) if row.get("quote_volume") else None,
                })

    first_price_at = detected_at + timedelta(seconds=wait_seconds) if wait_seconds else None
    summary = _finalize(outdir, symbol, detected_at, meta, samples, klines, t0_ms,
                        first_price_at, wait_seconds, "rerendered", log)
    log(f"[OK] {symbol}: {summary.get('tick_samples')} ticks, "
        f"{summary.get('kline_minutes')} bougies -> {outdir}")
    return summary
