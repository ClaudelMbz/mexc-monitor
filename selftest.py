"""Verifie toute la chaine (API -> CSV -> resume -> PNG -> HTML -> dashboard)
sans attendre un vrai listing : suit BTCUSDT pendant ~20 secondes.

  python selftest.py
"""
from mexc_client import MexcClient
from tracker import track_symbol

if __name__ == "__main__":
    client = MexcClient()
    syms = client.list_symbols()
    print(f"exchangeInfo OK : {len(syms)} paires spot")
    meta = syms.get("BTCUSDT", {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"})
    summary = track_symbol(client, "BTCUSDT", meta, duration=20, interval=5)
    print("resume:", summary)
    print("Ouvre data/dashboard.html et data/listings/BTCUSDT_*/chart.html")
