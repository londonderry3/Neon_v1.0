from __future__ import annotations

import time
from dataclasses import dataclass

import requests


BINANCE_SPOT = "https://api.binance.com"
BINANCE_FUTURES = "https://fapi.binance.com"


@dataclass
class AssetSnapshot:
    asset: str
    ts_ms: int
    ohlcv_rows: list[dict]
    funding_rate: float
    last_price: float


class BinanceDataFeed:
    def __init__(self, timeout_sec: float = 10.0):
        self.timeout_sec = timeout_sec

    def _get(self, base: str, path: str, params: dict) -> list | dict:
        resp = requests.get(f"{base}{path}", params=params, timeout=self.timeout_sec)
        resp.raise_for_status()
        return resp.json()

    def fetch_asset(self, asset: str, interval: str, lookback_bars: int) -> AssetSnapshot:
        klines = self._get(
            BINANCE_SPOT,
            "/api/v3/klines",
            {"symbol": asset, "interval": interval, "limit": int(lookback_bars)},
        )
        if not klines:
            raise ValueError(f"No kline data for {asset}")
        ts_ms = int(klines[-1][6])
        ohlcv_rows = [
            {
                "ts_ms": int(k[6]),
                "asset": asset,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "source": "binance_spot",
            }
            for k in klines
        ]
        funding = self._get(
            BINANCE_FUTURES,
            "/fapi/v1/fundingRate",
            {"symbol": asset, "limit": 1},
        )
        funding_rate = 0.0
        if isinstance(funding, list) and funding:
            funding_rate = float(funding[-1]["fundingRate"])
        last_price = float(ohlcv_rows[-1]["close"])
        return AssetSnapshot(
            asset=asset,
            ts_ms=ts_ms or int(time.time() * 1000),
            ohlcv_rows=ohlcv_rows,
            funding_rate=funding_rate,
            last_price=last_price,
        )

    def fetch_all(self, assets: list[str], interval: str, lookback_bars: int) -> dict[str, AssetSnapshot]:
        out: dict[str, AssetSnapshot] = {}
        for asset in assets:
            out[asset] = self.fetch_asset(asset, interval=interval, lookback_bars=lookback_bars)
        return out

