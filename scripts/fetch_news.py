#!/usr/bin/env python3
"""PMDAの新着情報RSSから、医薬品の現場に関係が深いニュースを news.json に書き出す。

対象: 安全対策（回収・使用上の注意改訂・安全性情報）と医薬品の承認関連。
学会・国際活動・基準作成などの専門トピックは除外し、最大10件を保持する。

使い方: python3 scripts/fetch_news.py news.json
"""
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET

RSS_URL = "https://www.pmda.go.jp/rss_015.xml"  # PMDAトップ 新着すべて
NS = {"rss": "http://purl.org/rss/1.0/", "dc": "http://purl.org/dc/elements/1.1/"}

# タイトル先頭の分類タグ→表示用タグ。載せない分類はNoneにせず単に辞書に入れない
CATEGORY_TAGS = {
    "[安全]": "安全対策",
    "[審査]": "承認審査",
}
# 分類タグに関わらず必ず拾いたいキーワード（回収・供給関連）
FORCE_KEYWORDS = ["回収", "供給", "出荷"]
# 医療従事者の日常業務から遠いものを除外するキーワード
EXCLUDE_KEYWORDS = ["国際", "薬局方", "チェックリスト", "プレスリリース", "シンポジウム", "研修", "採用"]


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "news.json"
    req = urllib.request.Request(RSS_URL, headers={"User-Agent": "Mozilla/5.0"})
    xml = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    root = ET.fromstring(xml)
    items = root.findall(".//rss:item", NS) or root.findall(".//item")

    news = []
    for it in items:
        title = (it.findtext("rss:title", "", NS) or it.findtext("title", "")).strip()
        link = (it.findtext("rss:link", "", NS) or it.findtext("link", "")).strip()
        date = (it.findtext("dc:date", "", NS) or it.findtext("pubDate", ""))[:10]
        if not title or not link:
            continue
        tag = None
        for prefix, label in CATEGORY_TAGS.items():
            if title.startswith(prefix):
                tag = label
                title = title[len(prefix):].strip()
                break
        forced = any(k in title for k in FORCE_KEYWORDS)
        if tag is None and not forced:
            continue
        if not forced and any(k in title for k in EXCLUDE_KEYWORDS):
            continue
        if "回収" in title:
            tag = "回収"
        news.append({
            "date": date.replace("-", "/"),
            "title": title,
            "url": link,
            "tag": tag or "新着",
        })
        if len(news) >= 10:
            break

    if len(news) < 3:
        print(f"⚠ 取得件数が少なすぎるため既存のnews.jsonを維持します（{len(news)}件）",
              file=sys.stderr)
        return

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(news, f, ensure_ascii=False, indent=1)
    print(f"✅ news.json 更新: {len(news)}件（出典: PMDA新着情報）", file=sys.stderr)


if __name__ == "__main__":
    main()
