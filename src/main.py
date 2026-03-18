"""
Crypto Daily Assistant
每日自动抓取加密货币行情，推送飞书（优化排版版）
"""

import os
import time
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# ─── 配置区 ───────────────────────────────────────────────────────────────────

FEISHU_WEBHOOK = os.environ["FEISHU_WEBHOOK"]
DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]

COIN_IDS = {
    "ETH":  "ethereum",
    "BNB":  "binancecoin",
    "ADA":  "cardano",
    "ZAMA": "zama",
}

NEXT_HALVING = datetime(2028, 4, 12, tzinfo=timezone.utc)

# ─── 数据采集 ─────────────────────────────────────────────────────────────────

def fetch_btc_full() -> dict:
    data = {
        "price": 0, "change_24h": 0,
        "ath": 0, "ath_date": "", "ath_change": 0,
        "ma200w": 0, "ma120": 0,
    }
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin"
            "?localization=false&tickers=false&community_data=false&developer_data=false",
            timeout=15
        )
        r.raise_for_status()
        d = r.json()
        data["price"]      = d["market_data"]["current_price"]["usd"]
        data["change_24h"] = d["market_data"]["price_change_percentage_24h"]
        data["ath"]        = d["market_data"]["ath"]["usd"]
        data["ath_date"]   = d["market_data"]["ath_date"]["usd"][:10]
        data["ath_change"] = d["market_data"]["ath_change_percentage"]["usd"]
        print(f"[BTC] ${data['price']:,.0f}")

        time.sleep(4)

        r2 = requests.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            "?vs_currency=usd&days=1400&interval=daily",
            timeout=30
        )
