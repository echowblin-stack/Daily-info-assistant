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
    "KAT":  "katana",   # 新增
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
        r2.raise_for_status()
        prices_list = r2.json().get("prices", [])

        if len(prices_list) >= 120:
            data["ma120"] = sum(p[1] for p in prices_list[-120:]) / 120

        weekly = [prices_list[i][1] for i in range(0, len(prices_list), 7)]
        if len(weekly) >= 200:
            data["ma200w"] = sum(weekly[-200:]) / 200
        elif len(weekly) >= 50:
            data["ma200w"] = sum(weekly) / len(weekly)

        print(f"[BTC] MA200W=${data['ma200w']:,.0f}  MA120=${data['ma120']:,.0f}")
    except Exception as e:
        print(f"[BTC] 失败: {e}")
    return data


def fetch_fear_greed() -> dict:
    try:
        time.sleep(2)
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        r.raise_for_status()
        d = r.json()["data"][0]
        return {"value": int(d["value"]), "label": d["value_classification"]}
    except Exception as e:
        print(f"[恐惧贪婪] 失败: {e}")
        return {"value": 0, "label": "N/A"}


def fetch_altcoin_prices() -> dict:
    prices = {}
    ids_str = ",".join(COIN_IDS.values())
    try:
        time.sleep(2)
        r = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={ids_str}&vs_currencies=usd&include_24hr_change=true",
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        for symbol, coin_id in COIN_IDS.items():
            if coin_id in data:
                prices[symbol] = {
                    "price":  data[coin_id].get("usd", 0),
                    "change": data[coin_id].get("usd_24h_change", 0),
                }
    except Exception as e:
        print(f"[山寨币] 失败: {e}")
    return prices


def get_halving_countdown() -> str:
    now = datetime.now(timezone.utc)
    days = (NEXT_HALVING - now).days
    return f"{days} 天（{NEXT_HALVING.strftime('%Y-%m-%d')}）" if days > 0 else "已减半"


# ─── 飞书卡片 ─────────────────────────────────────────────────────────────────

def build_feishu_card(btc: dict, fg: dict, altcoins: dict, halving: str) -> dict:
    tz = timezone(timedelta(hours=8))
    today = datetime.now(tz).strftime("%Y年%-m月%-d日")

    price     = btc["price"]
    change    = btc["change_24h"]
    ath_date  = btc["ath_date"]
    ath_change = btc["ath_change"]

    # 距顶月数
    try:
        ath_dt = datetime.fromisoformat(ath_date).replace(tzinfo=timezone.utc)
        months_from_ath = (datetime.now(timezone.utc) - ath_dt).days // 30
    except Exception:
        months_from_ath = 0

    # 涨跌颜色
    price_color  = "green" if change >= 0 else "red"
    price_arrow  = "↑" if change >= 0 else "↓"

    # 恐惧贪婪颜色
    fg_val = fg["value"]
    if fg_val <= 25:
        fg_color = "red"
    elif fg_val <= 45:
        fg_color = "orange"
    elif fg_val <= 55:
        fg_color = "grey"
    else:
        fg_color = "green"

    # 均线是否有效
    has_ma = btc["ma200w"] > 0 and btc["ma120"] > 0
    ma200w = btc["ma200w"]
    ma120  = btc["ma120"]
    ma200w_ratio = price / ma200w if ma200w else 0

    # 均线/链上数据说明
    if has_ma:
        valuation_content = (
            f"**200WMA**　　${ma200w:,.0f}　价格/200WMA = **{ma200w_ratio:.2f}x**\n"
            f"**MA120**　　　${ma120:,.0f}　距突破 {((ma120 - price) / price * 100):+.1f}%\n"
            f"**ahr999**　　 暂无　　\n"
            f"**矿机数据**　 暂无\n\n"
            f"更多链上数据 → [fuckbtc.com](https://fuckbtc.com)"
        )
    else:
        valuation_content = (
            f"**200WMA、MA120、ahr999 定投指数、矿机数据**\n"
            f"本次未能获取，请查阅 → [fuckbtc.com](https://fuckbtc.com)"
        )

    # 山寨币行情
    alt_lines = []
    for sym, d in altcoins.items():
        arrow = "↑" if d["change"] >= 0 else "↓"
        color = "green" if d["change"] >= 0 else "red"
        s     = "+" if d["change"] >= 0 else ""
        alt_lines.append(
            f"**{sym}**　${d['price']:,.4f}　"
            f"<font color='{color}'>{arrow} {s}{d['change']:.2f}%</font>"
        )
    alt_text = "\n".join(alt_lines) if alt_lines else "暂无数据"

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"📊 BTC 大周期日报　{today}"},
                "template": "indigo"
            },
            "elements": [

                # ── BTC 主行情 ──────────────────────────────
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"<font color='{price_color}'>**＄{price:,.0f}**</font>　"
                            f"<font color='{price_color}'>{price_arrow} {abs(change):.2f}%</font>\n"
                            f"ATH **${btc['ath']:,.0f}**（{ath_date}）\n"
                            f"距顶已过 **{months_from_ath}** 个月　跌幅 "
                            f"<font color='red'>**{ath_change:.1f}%**</font>"
                        )
                    }
                },
                {"tag": "hr"},

                # ── ① 情绪指标 ──────────────────────────────
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "background_style": "grey",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [{
                                "tag": "div",
                                "text": {
                                    "tag": "lark_md",
                                    "content": "🟠 **情绪指标**"
                                }
                            }]
                        }
                    ]
                },
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"恐慌与贪婪指数　"
                            f"<font color='{fg_color}'>**{fg_val}　{fg['label']}**</font>"
                        )
                    }
                },
                {"tag": "hr"},

                # ── ② 估值 & 均线 ────────────────────────────
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "background_style": "grey",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [{
                                "tag": "div",
                                "text": {
                                    "tag": "lark_md",
                                    "content": "🔵 **估值 & 均线**"
                                }
                            }]
                        }
                    ]
                },
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": valuation_content}
                },
                {"tag": "hr"},

                # ── ③ 减半倒计时 ─────────────────────────────
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "background_style": "grey",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [{
                                "tag": "div",
                                "text": {
                                    "tag": "lark_md",
                                    "content": "⏳ **减半倒计时**"
                                }
                            }]
                        }
                    ]
                },
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"距下次减半　**{halving}**"}
                },
                {"tag": "hr"},

                # ── ④ 山寨币 ─────────────────────────────────
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "background_style": "grey",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [{
                                "tag": "div",
                                "text": {
                                    "tag": "lark_md",
                                    "content": "🌐 **山寨币行情**"
                                }
                            }]
                        }
                    ]
                },
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": alt_text}
                },
                {"tag": "hr"},

                # ── 注脚 ──────────────────────────────────────
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "数据来源：CoinGecko · alternative.me  |  更多链上数据：fuckbtc.com"
                        }
                    ]
                }
            ]
        }
    }
    return card


# ─── 飞书推送 ─────────────────────────────────────────────────────────────────

def send_feishu(card: dict):
    r = requests.post(FEISHU_WEBHOOK, json=card, timeout=10)
    r.raise_for_status()
    print(f"[飞书] 推送成功 {r.status_code}")


# ─── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print(f"🚀 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    print("\n[1/4] BTC 数据...")
    btc = fetch_btc_full()

    print("\n[2/4] 恐惧贪婪指数...")
    fg = fetch_fear_greed()

    print("\n[3/4] 山寨币价格...")
    altcoins = fetch_altcoin_prices()

    halving = get_halving_countdown()

    print("\n[4/4] 推送飞书...")
    card = build_feishu_card(btc, fg, altcoins, halving)
    send_feishu(card)

    print("\n✅ 完成！")


if __name__ == "__main__":
    main()
