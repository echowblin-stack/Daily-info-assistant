"""
Crypto Daily Assistant
每日自动抓取加密货币行情，通过 DeepSeek AI 总结后推送飞书（分区卡片版）
"""

import os
import time
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup

# ─── 配置区 ───────────────────────────────────────────────────────────────────

FEISHU_WEBHOOK = os.environ["FEISHU_WEBHOOK"]
DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]

TWITTER_ACCOUNTS = [
    "cz_binance",
    "VitalikButerin",
    "saylor",
    "CryptoCobain",
    "lookonchain",
]

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
]

COIN_IDS = {
    "ETH":  "ethereum",
    "BNB":  "binancecoin",
    "ADA":  "cardano",
    "ZAMA": "zama",
}

# 下次减半预估（2028年4月）
NEXT_HALVING = datetime(2028, 4, 12, tzinfo=timezone.utc)

# ─── 数据采集 ─────────────────────────────────────────────────────────────────

def fetch_btc_full() -> dict:
    """获取 BTC 完整行情数据"""
    data = {
        "price": 0,
        "change_24h": 0,
        "ath": 0,
        "ath_date": "",
        "ath_change": 0,
        "ma200w": 0,
        "ma120": 0,
    }
    try:
        # 当前价格 + ATH
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin"
            "?localization=false&tickers=false&community_data=false&developer_data=false",
            timeout=15
        )
        r.raise_for_status()
        d = r.json()
        data["price"] = d["market_data"]["current_price"]["usd"]
        data["change_24h"] = d["market_data"]["price_change_percentage_24h"]
        data["ath"] = d["market_data"]["ath"]["usd"]
        data["ath_date"] = d["market_data"]["ath_date"]["usd"][:10]
        data["ath_change"] = d["market_data"]["ath_change_percentage"]["usd"]
        print(f"[BTC] 价格: ${data['price']:,.0f}  ATH: ${data['ath']:,.0f}")

        time.sleep(3)

        # 历史数据：用于计算 MA200W 和 MA120
        r2 = requests.get(
            "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
            "?vs_currency=usd&days=1400&interval=daily",
            timeout=30
        )
        r2.raise_for_status()
        prices_list = r2.json().get("prices", [])

        # MA120（最近120天日线均值）
        if len(prices_list) >= 120:
            data["ma120"] = sum(p[1] for p in prices_list[-120:]) / 120

        # MA200W（每7天采样一次，取最近200个点）
        weekly = [prices_list[i][1] for i in range(0, len(prices_list), 7)]
        if len(weekly) >= 200:
            data["ma200w"] = sum(weekly[-200:]) / 200
        elif len(weekly) >= 50:
            # 数据不足200周时用实际可用周数
            data["ma200w"] = sum(weekly) / len(weekly)

        print(f"[BTC] MA200W: ${data['ma200w']:,.0f}  MA120: ${data['ma120']:,.0f}")

    except Exception as e:
        print(f"[BTC] 获取失败: {e}")
    return data


def fetch_fear_greed() -> dict:
    """恐惧贪婪指数"""
    try:
        time.sleep(2)
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        r.raise_for_status()
        d = r.json()["data"][0]
        return {"value": int(d["value"]), "label": d["value_classification"]}
    except Exception as e:
        print(f"[恐惧贪婪] 获取失败: {e}")
        return {"value": 0, "label": "N/A"}


def fetch_ahr999() -> str:
    """ahr999 定投指数（从 btc.com 或计算）"""
    try:
        time.sleep(2)
        r = requests.get(
            "https://data.btc.com/btc/ahr999",
            timeout=10
        )
        r.raise_for_status()
        val = r.json().get("data", {}).get("ahr999", None)
        if val:
            return f"{float(val):.2f}"
    except Exception:
        pass

    # 备用：直接返回 N/A，不影响主流程
    return "N/A"


def fetch_altcoin_prices() -> dict:
    """山寨币价格"""
    prices = {}
    ids_str = ",".join(COIN_IDS.values())
    try:
        time.sleep(2)
        url = (
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={ids_str}&vs_currencies=usd&include_24hr_change=true"
        )
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        for symbol, coin_id in COIN_IDS.items():
            if coin_id in data:
                price = data[coin_id].get("usd", 0)
                change = data[coin_id].get("usd_24h_change", 0)
                sign = "+" if change >= 0 else ""
                prices[symbol] = {"price": price, "change": change, "sign": sign}
            else:
                prices[symbol] = None
        print(f"[山寨币] 获取成功")
    except Exception as e:
        print(f"[山寨币] 获取失败: {e}")
    return prices


def get_halving_countdown() -> str:
    """距下次减半天数"""
    now = datetime.now(timezone.utc)
    delta = NEXT_HALVING - now
    days = delta.days
    if days > 0:
        return f"{days} 天（预计 {NEXT_HALVING.strftime('%Y-%m-%d')}）"
    return "已减半"


def get_working_nitter() -> str | None:
    for instance in NITTER_INSTANCES:
        try:
            r = requests.get(f"{instance}/bitcoin", timeout=8)
            if r.status_code == 200:
                return instance
        except Exception:
            continue
    return None


def fetch_tweets(nitter_base: str, username: str, max_tweets: int = 5) -> list[str]:
    tweets = []
    try:
        url = f"{nitter_base}/{username}"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; CryptoBot/1.0)"}
        r = requests.get(url, headers=headers, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".tweet-content, .timeline-item .content")[:max_tweets]:
            text = item.get_text(separator=" ", strip=True)
            if text and len(text) > 10:
                tweets.append(text[:400])
    except Exception as e:
        print(f"[推特] @{username} 失败: {e}")
    return tweets


def collect_all_tweets(nitter_base: str) -> dict[str, list[str]]:
    all_tweets = {}
    for account in TWITTER_ACCOUNTS:
        tweets = fetch_tweets(nitter_base, account)
        if tweets:
            all_tweets[account] = tweets
            print(f"[推特] @{account}: {len(tweets)} 条")
    return all_tweets


# ─── AI 总结 ──────────────────────────────────────────────────────────────────

def ai_summary(tweets: dict[str, list[str]]) -> str:
    """用 DeepSeek 总结推特博主动态"""
    if not tweets:
        return "今日未获取到推文数据。"

    tweets_text = ""
    for account, posts in tweets.items():
        tweets_text += f"\n@{account}:\n"
        for i, t in enumerate(posts, 1):
            tweets_text += f"  {i}. {t}\n"

    prompt = f"""以下是加密货币博主的最新推文，请用2-4句中文总结最重要的观点和信息，
要求简洁、客观，重点提炼市场判断和值得关注的信号：

{tweets_text}"""

    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[AI] 失败: {e}")
        return "AI 分析暂时不可用。"


# ─── 飞书卡片构建 ─────────────────────────────────────────────────────────────

def build_feishu_card(btc: dict, fg: dict, ahr: str, altcoins: dict, halving: str, tweet_summary: str) -> dict:
    tz = timezone(timedelta(hours=8))
    today = datetime.now(tz).strftime("%Y年%-m月%-d日")

    price = btc["price"]
    change = btc["change_24h"]
    sign = "↑" if change >= 0 else "↓"
    change_color = "green" if change >= 0 else "red"

    ath_change = btc["ath_change"]
    ma200w = btc["ma200w"]
    ma120 = btc["ma120"]
    ma200w_ratio = price / ma200w if ma200w else 0

    # 距顶月数
    ath_date = datetime.fromisoformat(btc["ath_date"]).replace(tzinfo=timezone.utc)
    months_from_ath = (datetime.now(timezone.utc) - ath_date).days // 30

    # 恐惧贪婪标签颜色
    fg_val = fg["value"]
    if fg_val <= 25:
        fg_color = "red"
    elif fg_val <= 45:
        fg_color = "orange"
    elif fg_val <= 55:
        fg_color = "grey"
    elif fg_val <= 75:
        fg_color = "green"
    else:
        fg_color = "green"

    # 山寨币行情文字
    alt_lines = []
    for sym, d in altcoins.items():
        if d:
            s = "+" if d["change"] >= 0 else ""
            arrow = "↑" if d["change"] >= 0 else "↓"
            alt_lines.append(f"**{sym}**　${d['price']:,.4f}　{arrow} {s}{d['change']:.2f}%")
        else:
            alt_lines.append(f"**{sym}**　暂无数据")
    alt_text = "\n".join(alt_lines)

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"📊 BTC 大周期日报　{today}"},
                "template": "indigo"
            },
            "elements": [
                # ── BTC 价格主区 ──
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**${price:,.0f}**　"
                            f"<font color='{change_color}'>{sign} {abs(change):.2f}%</font>\n"
                            f"ATH **${btc['ath']:,.0f}**（{btc['ath_date']}）　"
                            f"距顶已过 **{months_from_ath}** 个月　"
                            f"距顶跌幅 **{ath_change:.1f}%**"
                        )
                    }
                },
                {"tag": "hr"},

                # ── ① 情绪指标 ──
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"🟠 **情绪指标**\n"
                            f"恐慌指数　<font color='{fg_color}'>{fg_val}　{fg['label']}</font>"
                        )
                    }
                },
                {"tag": "hr"},

                # ── ② 链上 / 均线估值 ──
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"🔵 **估值指标**\n"
                            f"ahr999 定投指数　**{ahr}**\n"
                            f"200WMA　**${ma200w:,.0f}**　价格/200WMA = **{ma200w_ratio:.2f}x**"
                        )
                    }
                },
                {"tag": "hr"},

                # ── ③ 技术面 ──
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"🟢 **技术面**\n"
                            f"MA120　**${ma120:,.0f}**　"
                            f"距突破 {((ma120 - price) / price * 100):+.1f}%"
                        )
                    }
                },
                {"tag": "hr"},

                # ── ④ 减半倒计时 ──
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"⏳ **减半倒计时**　{halving}"
                    }
                },
                {"tag": "hr"},

                # ── ⑤ 山寨币 ──
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"🌐 **山寨币行情**\n{alt_text}"
                    }
                },
                {"tag": "hr"},

                # ── ⑥ 博主动态 ──
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"📣 **博主动态摘要**\n{tweet_summary}"
                    }
                },
                {"tag": "hr"},

                # ── 来源注脚 ──
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "数据来源：CoinGecko · alternative.me · nitter  |  AI分析：DeepSeek"
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

    print("\n[1/6] BTC 完整数据...")
    btc = fetch_btc_full()

    print("\n[2/6] 恐惧贪婪指数...")
    fg = fetch_fear_greed()

    print("\n[3/6] ahr999 指数...")
    ahr = fetch_ahr999()

    print("\n[4/6] 山寨币价格...")
    altcoins = fetch_altcoin_prices()

    print("\n[5/6] 推特博主动态...")
    nitter = get_working_nitter()
    tweets = {}
    if nitter:
        tweets = collect_all_tweets(nitter)
    else:
        print("  ⚠️ nitter 不可用")
    tweet_summary = ai_summary(tweets)

    halving = get_halving_countdown()

    print("\n[6/6] 构建卡片并推送飞书...")
    card = build_feishu_card(btc, fg, ahr, altcoins, halving, tweet_summary)
    send_feishu(card)

    print("\n✅ 完成！")


if __name__ == "__main__":
    main()
