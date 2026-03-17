"""
Crypto Daily Assistant
每日自动抓取加密货币行情 + 推特博主动态，通过 Claude AI 总结后推送飞书
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from anthropic import Anthropic

# ─── 配置区 ───────────────────────────────────────────────────────────────────

FEISHU_WEBHOOK = os.environ["FEISHU_WEBHOOK"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# 你在 Twitter 上关注的加密博主账号列表（填 username，不含 @）
TWITTER_ACCOUNTS = [
    "cz_binance",
    "VitalikButerin",
    "saylor",
    "CryptoCobain",
    "lookonchain",
    # 在这里继续添加你关注的博主
]

# Nitter 实例（如果某个挂了可以换备用）
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
]

# 要查询价格的代币（CoinGecko ID）
COIN_IDS = {
    "ETH":  "ethereum",
    "BNB":  "binancecoin",
    "ADA":  "cardano",
    "ZAMA": "zama",       # 若 CoinGecko 无此 ID 会自动跳过
}

# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def get_working_nitter() -> str | None:
    """找到当前可用的 nitter 实例"""
    for instance in NITTER_INSTANCES:
        try:
            r = requests.get(f"{instance}/bitcoin", timeout=8)
            if r.status_code == 200:
                return instance
        except Exception:
            continue
    return None


def fetch_btc_data() -> dict:
    """从 fuckbtc.com 抓取 BTC 行情数据"""
    result = {
        "price": "N/A",
        "fear_greed": "N/A",
        "ma200w": "N/A",
        "raw_text": "",
    }
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; CryptoBot/1.0)"}
        r = requests.get("https://fuckbtc.com", headers=headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # 提取页面所有文本，交给后续 AI 解析
        result["raw_text"] = soup.get_text(separator="\n", strip=True)[:3000]

        # 尝试直接抓常见字段（若 DOM 变化则 AI 从 raw_text 兜底）
        for tag in soup.find_all(True):
            text = tag.get_text(strip=True)
            if "$" in text and any(c.isdigit() for c in text) and len(text) < 30:
                if "price" in (tag.get("class") or []) or "btc" in (tag.get("id") or "").lower():
                    result["price"] = text
                    break

        print(f"[BTC] 原始文本获取成功，长度 {len(result['raw_text'])}")
    except Exception as e:
        print(f"[BTC] 抓取失败: {e}")
    return result


def fetch_altcoin_prices() -> dict:
    """从 CoinGecko 免费 API 获取山寨币价格"""
    prices = {}
    ids_str = ",".join(COIN_IDS.values())
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids_str}&vs_currencies=usd&include_24hr_change=true"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        for symbol, coin_id in COIN_IDS.items():
            if coin_id in data:
                price = data[coin_id].get("usd", "N/A")
                change = data[coin_id].get("usd_24h_change", 0)
                sign = "+" if change >= 0 else ""
                prices[symbol] = f"${price:,.4f}  ({sign}{change:.2f}%)"
            else:
                prices[symbol] = "暂无数据"
        print(f"[价格] 获取成功: {list(prices.keys())}")
    except Exception as e:
        print(f"[价格] CoinGecko 请求失败: {e}")
        for symbol in COIN_IDS:
            prices[symbol] = "请求失败"
    return prices


def fetch_tweets(nitter_base: str, username: str, max_tweets: int = 5) -> list[str]:
    """抓取指定博主的最新推文"""
    tweets = []
    try:
        url = f"{nitter_base}/{username}"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; CryptoBot/1.0)"}
        r = requests.get(url, headers=headers, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Nitter 推文通常在 .tweet-content 或 .timeline-item
        for item in soup.select(".tweet-content, .timeline-item .content")[:max_tweets]:
            text = item.get_text(separator=" ", strip=True)
            if text and len(text) > 10:
                tweets.append(text[:400])
    except Exception as e:
        print(f"[推特] 抓取 @{username} 失败: {e}")
    return tweets


def collect_all_tweets(nitter_base: str) -> dict[str, list[str]]:
    """并行采集所有博主推文"""
    all_tweets = {}
    for account in TWITTER_ACCOUNTS:
        tweets = fetch_tweets(nitter_base, account)
        if tweets:
            all_tweets[account] = tweets
            print(f"[推特] @{account}: 获取 {len(tweets)} 条")
        else:
            print(f"[推特] @{account}: 无内容（可能账号不存在或 nitter 屏蔽）")
    return all_tweets


# ─── AI 分析 ──────────────────────────────────────────────────────────────────

def ai_analyze(btc_raw: str, altcoin_prices: dict, tweets: dict[str, list[str]]) -> str:
    """调用 Claude API 做综合分析总结"""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    tweets_text = ""
    for account, posts in tweets.items():
        tweets_text += f"\n@{account}:\n"
        for i, t in enumerate(posts, 1):
            tweets_text += f"  {i}. {t}\n"

    altcoin_text = "\n".join([f"  {sym}: {price}" for sym, price in altcoin_prices.items()])

    prompt = f"""你是一位专业的加密货币分析师。请根据以下原始数据，生成一份今日加密货币早报摘要。

## BTC 数据页面原始文本（来自 fuckbtc.com）：
{btc_raw[:2000]}

## 山寨币价格（来自 CoinGecko）：
{altcoin_text}

## 加密博主最新推文：
{tweets_text[:3000] if tweets_text else "今日未获取到推文数据"}

请生成一份结构清晰的中文日报，包含：
1. **BTC 行情**：从原始文本中提取并汇报 BTC 当前价格、恐惧&贪婪指数、200周均线（及 BTC 是否在均线上方/下方的判断）
2. **山寨币行情**：列出各币种价格和涨跌情况，并给出简短市场情绪判断
3. **博主动态摘要**：对各博主推文进行要点提炼，重点关注市场判断、重要新闻、值得关注的链上数据
4. **综合观点**：2-3句话的市场总结，指出当前最值得关注的信号

输出格式要适合飞书消息阅读，用 emoji 增强可读性，保持简洁。不要输出 Markdown 标题符号(#)。"""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ─── 飞书推送 ─────────────────────────────────────────────────────────────────

def send_feishu(content: str, altcoin_prices: dict):
    """发送富文本卡片到飞书"""
    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")

    # 构造飞书消息卡片
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
                {
                    "tag": "hr"
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "数据来源：fuckbtc.com · CoinGecko · nitter  |  AI分析：Claude"
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

    # 1. 获取 BTC 数据
    print("\n[1/4] 抓取 BTC 行情...")
    btc = fetch_btc_data()

    # 2. 获取山寨币价格
    print("\n[2/4] 获取山寨币价格...")
    altcoins = fetch_altcoin_prices()

    # 3. 抓取推特
    print("\n[3/4] 抓取推特博主动态...")
    nitter = get_working_nitter()
    tweets = {}
    if nitter:
        print(f"  使用 nitter 实例: {nitter}")
        tweets = collect_all_tweets(nitter)
    else:
        print("  ⚠️  所有 nitter 实例均不可用，跳过推特数据")

    # 4. AI 分析
    print("\n[4/4] 调用 Claude AI 分析...")
    report = ai_analyze(btc["raw_text"], altcoins, tweets)

    # 5. 推送飞书
    print("\n[5/5] 推送到飞书...")
    send_feishu(report, altcoins)

    print("\n✅ 日报发送完成！")


if __name__ == "__main__":
    main()

