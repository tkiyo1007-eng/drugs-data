import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from build_official_news import build
from fetch_pmda_recalls import collect, parse_index

class OfficialNewsTests(unittest.TestCase):
    def test_recall_table_distinguishes_medicines_and_preserves_official_id(self):
        body = """<table>
          <tr><th>番号</th><th>掲載年月日</th><th>種類</th><th>一般名</th><th>販売名</th></tr>
          <tr><td><img src="notice.gif"><br>1-42</td><td>2026/11/20</td><td>医薬品</td><td>-</td>
            <td><a href="/rgo/MainServlet?recallno=1-42">対象品</a></td><td>製造販売元</td><td>回収終了</td></tr>
          <tr><td>1-41</td><td>2026/11/19</td><td>化粧品</td><td>-</td><td>対象外</td><td>社</td><td></td></tr>
        </table>"""
        result = parse_index(body, 1)
        self.assertEqual([item["id"] for item in result], ["1-42"])
        self.assertEqual(result[0]["date"], "2026-11-20")
        self.assertTrue(result[0]["ended"])
        with self.assertRaises(ValueError):
            parse_index("<p>メンテナンス中</p>", 1)

    def test_failed_class_preserves_last_success_and_other_classes_advance(self):
        previous = {"II": {"status": "ok", "last_success_date": "2026-11-20", "items": [{"id": "2-42"}]}}
        captured = []

        def fetch(year, category):
            captured.append(year)
            if category == 2:
                raise OSError()
            return []

        result = collect(previous, dt.date(2027, 4, 2), fetch)
        self.assertEqual(set(captured), {2026, 2027})
        self.assertEqual(result["I"]["status"], "ok")
        self.assertEqual(result["II"], {**previous["II"], "status": "failed"})

    def test_feed_excludes_future_and_marks_verified_maker_publication_date(self):
        url = "https://www.nichiiko.co.jp/medicine/files/20261118-03-01.pdf"
        recall_url = "https://www.info.pmda.go.jp/rgo/MainServlet?recallno=2-13047"
        notice = {"maker": "日医工", "title": "パロキセチン錠の案内", "url": url,
                  "event_type": "discontinued", "first_seen": "2026-11-20"}
        supply = {"date": "2026/11/21", "from": "①通常出荷", "to": "⑤供給停止"}
        fixtures = {
            "status_changes.json": [supply, {**supply, "date": "2026/11/23"}],
            "official_news_explanations.json": {url: {"posted_at": "2026-11-19", "summary": "PTP100錠"}},
            "manufacturer_notices.json": {"notices": []},
            "maker_announcement_events.json": {"品目A": [notice], "品目B": [notice]},
            "pmda_recalls.json": {"classes": {"II": {"status": "ok", "last_success_date": "2026-11-22",
                "items": [{"id": "2-13047", "date": "2026-11-20", "title": "対象品",
                           "maker": "製造販売元", "url": recall_url, "ended": False}]}}},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, data in fixtures.items():
                (root / name).write_text(json.dumps(data), encoding="utf-8")
            (root / "updates").mkdir()
            for day in ("2026-11-21", "2026-11-23"):
                (root / "updates" / f"{day}.html").touch()
            feed = build(root, dt.date(2026, 11, 22))
        self.assertTrue(all(row["date"] <= "2026-11-22" for row in feed["items"]))
        self.assertEqual({row["kind"] for row in feed["items"]}, {"supply", "maker", "recall"})
        self.assertEqual(feed["pmda_status"], "stale")
        entries = [row for row in feed["items"] if row["url"] == url]
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0]["date"], entries[0]["date_label"]), ("2026-11-19", "掲載"))
        self.assertIn("PTP100錠", entries[0]["summary"])


if __name__ == "__main__":
    unittest.main()
