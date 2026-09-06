"""Petit client HTTP pour l'API spot MEXC (v3).

Les endpoints utilises ici (exchangeInfo, ticker/price, ticker/bookTicker,
ticker/24hr) sont publics : aucune signature requise. La signature HMAC est
quand meme implementee pour un usage futur (endpoints prives).
"""
import hashlib
import hmac
import time
from urllib.parse import urlencode

import requests

from config import MEXC_API_KEY, MEXC_API_SECRET, MEXC_BASE_URL


class MexcClient:
    def __init__(self, base_url=MEXC_BASE_URL, api_key=MEXC_API_KEY,
                 api_secret=MEXC_API_SECRET, timeout=15):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "mexc-new-listing-monitor/1.0"})
        if api_key:
            self.session.headers.update({"X-MEXC-APIKEY": api_key})

    def _get(self, path, params=None, signed=False):
        params = dict(params or {})
        if signed:
            if not (self.api_key and self.api_secret):
                raise RuntimeError("Endpoint signe demande mais MEXC_API_KEY/SECRET absents")
            params["timestamp"] = int(time.time() * 1000)
            query = urlencode(params)
            params["signature"] = hmac.new(
                self.api_secret.encode(), query.encode(), hashlib.sha256
            ).hexdigest()
        resp = self.session.get(self.base_url + path, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    # --- marche (public) ---------------------------------------------------
    def exchange_info(self):
        return self._get("/api/v3/exchangeInfo")

    def list_symbols(self):
        """Renvoie {symbol: {infos utiles}} pour toutes les paires spot."""
        info = self.exchange_info()
        out = {}
        for s in info.get("symbols", []):
            sym = s.get("symbol")
            if not sym:
                continue
            out[sym] = {
                "symbol": sym,
                "baseAsset": s.get("baseAsset"),
                "quoteAsset": s.get("quoteAsset"),
                "status": s.get("status"),
                "isSpotTradingAllowed": s.get("isSpotTradingAllowed"),
                "fullName": s.get("fullName"),
            }
        return out

    def klines(self, symbol, interval="1m", limit=1000, start_time=None, end_time=None):
        """Bougies OHLCV. Renvoie une liste de listes :
        [open_time_ms, open, high, low, close, volume, close_time_ms, quote_volume].
        Marche meme si on interroge longtemps apres le listing : on recupere
        tout l'historique depuis la 1ere bougie (limit=1000 -> ~16 h en 1m)."""
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time is not None:
            params["startTime"] = int(start_time)
        if end_time is not None:
            params["endTime"] = int(end_time)
        return self._get("/api/v3/klines", params)

    def book_ticker(self, symbol):
        return self._get("/api/v3/ticker/bookTicker", {"symbol": symbol})

    def price(self, symbol):
        return self._get("/api/v3/ticker/price", {"symbol": symbol})

    def ticker_24h(self, symbol):
        return self._get("/api/v3/ticker/24hr", {"symbol": symbol})
