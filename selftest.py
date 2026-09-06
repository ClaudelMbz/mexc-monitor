"""Verifie toute la chaine (API -> tick -> bougies -> analyses -> graphiques
-> dashboard -> agregat) sans attendre un vrai listing : suit BTCUSDT ~1 min.

  python selftest.py
"""
import shutil

from aggregate import build_aggregate
from dashboard import build_dashboard
from mexc_client import MexcClient
from tracker import track_symbol
from config import LISTINGS_DIR

if __name__ == "__main__":
    client = MexcClient()
    syms = client.list_symbols()
    print(f"exchangeInfo OK : {len(syms)} paires spot")
    meta = syms.get("BTCUSDT", {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"})
    before = {p.name for p in LISTINGS_DIR.iterdir()} if LISTINGS_DIR.exists() else set()
    summary = track_symbol(client, "BTCUSDT", meta,
                           duration=12, interval=3, follow_minutes=1, kline_poll=15)
    print("resume:", {k: summary[k] for k in
                      ("status", "tick_samples", "kline_minutes", "reference_price",
                       "peak_vs_ref_pct", "drawdown_from_peak_pct", "settle_vs_ref_pct")
                      if k in summary})

    # nettoyage : le selftest ne doit pas polluer le jeu de donnees reel
    for p in LISTINGS_DIR.iterdir():
        if p.name.startswith("BTCUSDT_") and p.name not in before:
            shutil.rmtree(p, ignore_errors=True)
    build_dashboard()
    build_aggregate()
    print("OK. Le dossier de test a ete supprime ; dashboard/agregat regeneres.")
