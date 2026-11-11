#!/usr/bin/env python3
"""轮询 Odaily 快讯 RSS，把新快讯推送到 Lark 自定义机器人 webhook。"""
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

RSS_URL = "https://rss.odaily.news/rss/newsflash"
WEBHOOK = os.environ["LARK_WEBHOOK"]
STATE_FILE = Path(__file__).with_name("seen.json")
FIRST_RUN_PUSH = 3  # 首次运行只推最新几条，其余标记为已读，避免刷屏
MAX_SEEN = 500
TZ = timezone(timedelta(hours=8))

# 后台运行时不依赖终端代理
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch_items():
    req = urllib.request.Request(RSS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with opener.open(req, timeout=20) as r:
        root = ET.fromstring(r.read())
    items = []
    for it in root.findall(".//item"):
        desc = re.sub(r"<[^>]+>", "", it.findtext("description") or "")
        desc = html.unescape(desc).replace("Odaily星球日报讯", "").strip()
        try:
            ts = parsedate_to_datetime(it.findtext("pubDate")).astimezone(TZ).strftime("%m-%d %H:%M")
        except Exception:
            ts = ""
        items.append({
            "id": it.findtext("guid") or it.findtext("link"),
            "title": (it.findtext("title") or "").strip(),
            "link": it.findtext("link") or "",
            "desc": desc,
            "time": ts,
        })
    return items  # RSS 中最新的在前


def push(item):
    card = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": item["title"][:100]},
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": item["desc"][:1500]}},
                {"tag": "note", "elements": [
                    {"tag": "lark_md", "content": f"Odaily 快讯 · {item['time']} · [查看原文]({item['link']})"},
                ]},
            ],
        },
    }
    req = urllib.request.Request(
        WEBHOOK,
        data=json.dumps(card).encode(),
        headers={"Content-Type": "application/json"},
    )
    with opener.open(req, timeout=20) as r:
        resp = json.loads(r.read())
    if resp.get("code", 0) != 0:
        raise RuntimeError(f"webhook error: {resp}")


def main():
    first_run = not STATE_FILE.exists()
    seen = [] if first_run else json.loads(STATE_FILE.read_text())
    seen_set = set(seen)

    items = fetch_items()
    new = [i for i in items if i["id"] not in seen_set]
    if first_run:
        to_push = new[:FIRST_RUN_PUSH]
        skipped = new[FIRST_RUN_PUSH:]
    else:
        to_push, skipped = new, []

    for it in skipped:
        seen.append(it["id"])
    # 按时间正序推送
    for it in reversed(to_push):
        try:
            push(it)
            seen.append(it["id"])
            print(f"[{datetime.now(TZ):%F %T}] pushed: {it['title']}")
        except Exception as e:
            print(f"[{datetime.now(TZ):%F %T}] push failed: {it['title']} -> {e}", file=sys.stderr)

    STATE_FILE.write_text(json.dumps(seen[-MAX_SEEN:], ensure_ascii=False))


if __name__ == "__main__":
    main()
