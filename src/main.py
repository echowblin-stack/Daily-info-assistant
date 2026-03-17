"""
Crypto Daily Assistant
每日自动抓取加密货币行情 + 推特博主动态，通过 DeepSeek AI 总结后推送飞书
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

# CoinGecko ID 映射（BTC 也放进来，统一一次请求）
COIN_IDS = {
    "BTC":  "bitcoin",
    "ETH":  "ethereum",
    "BNB":  "binancecoin",
    "ADA":  "cardano",
    "ZAMA": "zama",
}

# ─── 数据采集 ─────────────────────────────────────────────────────────────────

def fetch_all_prices() -> dict:
    """一次请求获取所有币种价格，包括 BTC"""
    prices = {}
    ids_str = ",".join(COIN_IDS.values())
    try:
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
                if symbol == "BTC":
                    prices[symbol] = f"${price:,.2f}  ({sign}{change:.2f}%)"
                else:
                    prices[symbol] = f"${price:,.4f}  ({sign}{change:.2f}%)"
            else:
                prices[symbol] = "暂无数据"
        print(f"[价格] 获取成功: {list(prices.keys())}")
    except Exception as e:
        print(f"[价格] 请求失败: {e}")
        for symbol in COIN_IDS:
            prices[symbol] = "请求失败"
    return prices


def fetch_fear_greed() -> str:
    """从 alternative.me 获取恐惧贪婪指数"""
    try:
        # 稍作等待，避免连续请求被限速
        time.sleep(2)
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        r.raise_for_status()
        data = r.json()["data"][0]
        value = data["value"]
        label = data["value_classification"]
        print(f"[恐惧贪婪] {value} ({label})")
        return f"{value} ({label})"
    except Exception as e:
        print(f"[恐惧贪婪] 获取失败: {e}")
        return "获取失败"


def fetch_ma200w(btc_price: float) -> str:
    """用 Bybit API 获取 BTC 200周均线"""
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/kline"
            "?category=spot&symbol=BTCUSDT&interval=W&limit=200",
            timeout=15
        )
        r.raise_for_status()
        data = r.json()
        klines = data.get("result", {}).get("list", [])
        if len(klines) >= 200:
            # Bybit 格式：[时间, 开, 高, 低, 收, 成交量, 成交额]，取收盘价
            closes = [float(k[4]) for k in klines]
            ma200w = sum(closes) / 200
            above = "✅ 价格在均线上方" if btc_price > ma200w else "⚠️ 价格在均线下方"
            result = f"${ma200w:,.0f}（200周均线）  {above}"
            print(f"[200WMA] {result}")
            return result
        return "数据不足"
    except Exception as e:
        print(f"[200WMA] 获取失败: {e}")
        return "获取失败"


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
        print(f"[推特] 抓取 @{username} 失败: {e}")
    return tweets


def collect_all_tweets(nitter_base: str) -> dict[str, list[str]]:
    all_tweets = {}
    for account in TWITTER_ACCOUNTS:
        tweets = fetch_tweets(nitter_base, account)
        if tweets:
            all_tweets[account] = tweets
            print(f"[推特] @{account}: 获取 {len(tweets)} 条")
        else:
            print(f"[推特] @{account}: 无内容")
    return all_tweets


# ─── AI 分析 ──────────────────────────────────────────────────────────────────

def ai_analyze(prices: dict, fear_greed: str, ma200w: str, tweets: dict[str, list[str]]) -> str:
    altcoin_text = "\n".join([
        f"  {sym}: {price}" for sym, price in prices.items() if sym != "BTC"
    ])
    tweets_text = ""
    for account, posts in tweets.items():
        tweets_text += f"\n@{account}:\n"
        for i, t in enumerate(posts, 1):
            tweets_text += f"  {i}. {t}\n"

    prompt = f"""你是一位专业的加密货币分析师。请根据以下实时数据，生成一份今日加密货币早报。

## BTC 行情数据：
- 当前价格: {prices.get('BTC', '获取失败')}
- 恐惧与贪婪指数: {fear_greed}
- 200周均线: {ma200w}

## 山寨币价格：
{altcoin_text}

## 加密博主最新推文：
{tweets_text if tweets_text else "今日未获取到推文数据"}

请生成一份结构清晰的中文日报，包含：
1. **BTC 行情**：价格、24h涨跌、恐惧&贪婪指数解读、200周均线位置分析
2. **山寨币行情**：列出各币种价格和涨跌，给出简短市场情绪判断
3. **博主动态摘要**：对各博主推文进行要点提炼
4. **综合观点**：2-3句话的市场总结，指出当前最值得关注的信号

输出格式适合飞书消息阅读，用 emoji 增强可读性，保持简洁。不要输出 Markdown 标题符号(#)。"""

    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1500,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


# ─── 飞书推送 ─────────────────────────────────────────────────────────────────

def send_feishu(content: str):
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"📊 加密日报  {now} (UTC+8)"
                },
                "template": "blue"
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": content
                    }
                },
                {"tag": "hr"},
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

    r = requests.post(FEISHU_WEBHOOK, json=card, timeout=10)
    r.raise_for_status()
    print(f"[飞书] 推送成功，状态码 {r.status_code}")


# ─── 主流程 ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print(f"🚀 开始执行加密日报 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    print("\n[1/5] 获取所有币种价格...")
    prices = fetch_all_prices()

    print("\n[2/5] 获取恐惧贪婪指数...")
    fear_greed = fetch_fear_greed()

    print("\n[3/5] 获取 BTC 200周均线...")
    btc_price = float(prices.get("BTC", "0").replace("$", "").replace(",", "").split()[0]) if prices.get("BTC") != "请求失败" else 0
    ma200w = fetch_ma200w(btc_price)

    print("\n[4/5] 抓取推特博主动态...")
    nitter = get_working_nitter()
    tweets = {}
    if nitter:
        print(f"  使用 nitter 实例: {nitter}")
        tweets = collect_all_tweets(nitter)
    else:
        print("  ⚠️  所有 nitter 实例均不可用，跳过推特数据")

    print("\n[5/5] 调用 DeepSeek AI 分析并推送飞书...")
    report = ai_analyze(prices, fear_greed, ma200w, tweets)
    send_feishu(report)

    print("\n✅ 日报发送完成！")


if __name__ == "__main__":
    main()
