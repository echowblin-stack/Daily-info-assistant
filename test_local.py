#!/usr/bin/env python3
"""
本地测试脚本 - 不实际发送飞书消息，只打印日报内容到终端
用法：
  export ANTHROPIC_API_KEY="sk-ant-..."
  python test_local.py
"""

import os
import sys

# 注入假的飞书 Webhook（本地测试用，不会实际发送）
os.environ.setdefault("FEISHU_WEBHOOK", "https://example.com/fake-webhook")

# 把 src 目录加到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from main import fetch_btc_data, fetch_altcoin_prices, get_working_nitter, collect_all_tweets, ai_analyze

def main():
    print("🧪 本地测试模式（不推送飞书）\n")

    print("[1/4] 抓取 BTC 数据...")
    btc = fetch_btc_data()
    print(f"  原始文本长度: {len(btc['raw_text'])} 字符")
    print(f"  预览: {btc['raw_text'][:200]}\n")

    print("[2/4] 获取山寨币价格...")
    altcoins = fetch_altcoin_prices()
    for sym, price in altcoins.items():
        print(f"  {sym}: {price}")

    print("\n[3/4] 抓取推特...")
    nitter = get_working_nitter()
    tweets = {}
    if nitter:
        print(f"  nitter 实例: {nitter}")
        tweets = collect_all_tweets(nitter)
    else:
        print("  所有 nitter 实例不可用")

    print("\n[4/4] 调用 Claude AI 分析...")
    if not os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-"):
        print("  ⚠️  未设置 ANTHROPIC_API_KEY，跳过 AI 分析")
        return

    report = ai_analyze(btc["raw_text"], altcoins, tweets)
    print("\n" + "=" * 60)
    print("📊 日报内容预览：")
    print("=" * 60)
    print(report)
    print("=" * 60)
    print("\n✅ 测试完成！如果内容正常，可以部署到 GitHub Actions。")

if __name__ == "__main__":
    main()
