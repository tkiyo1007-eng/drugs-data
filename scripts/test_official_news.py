import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from build_official_news import build, maker_news
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

    def test_package_status_summary_can_use_a_general_maker_label(self):
        url = "https://www.nichiiko.co.jp/medicine/files/supply-matrix.pdf"
        notice = {"maker": "日医工", "title": "包装別の供給状況", "url": url,
                  "event_type": "limited", "listed_at": "2026-11-20"}
        summary = "PTP100錠は通常出荷、PTP1000錠は供給停止です。"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "maker_announcement_events.json").write_text("{}", encoding="utf-8")
            (root / "manufacturer_notices.json").write_text(
                json.dumps({"notices": [notice]}), encoding="utf-8")
            original, = maker_news(root, {})
            editorial, = maker_news(root, {url: {"event_type": "supply", "summary": summary}})
        self.assertEqual(original["tag"], "限定出荷の案内")
        self.assertEqual(editorial, {**original, "tag": "供給に関する案内", "summary": summary})

    def test_shared_maker_source_can_name_both_products_on_one_card(self):
        url = "https://medical.kyowakirin.co.jp/druginfo/drgdiscon/index.html"
        base = {"maker": "協和キリン", "url": url, "event_type": "discontinued", "listed_at": "2026-11-16"}
        notices = [{**base, "title": title} for title in ("アレロックの販売中止", "オングリザの販売中止")]
        title = "アレロックとオングリザの販売中止予定"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "maker_announcement_events.json").write_text("{}", encoding="utf-8")
            (root / "manufacturer_notices.json").write_text(json.dumps({"notices": notices}), encoding="utf-8")
            original, = maker_news(root, {})
            shared, = maker_news(root, {url: {"title": title}})
        self.assertEqual(original["title"], notices[0]["title"])
        self.assertEqual(shared, {**original, "title": title})

    def test_verified_reprint_is_optional_and_preserves_manufacturer_source(self):
        original = "https://www.takata-seiyaku.co.jp/medical/topics/notice.pdf"
        notice = {"maker": "高田製薬", "title": "供給のお知らせ", "url": original,
                  "event_type": "stopped", "listed_at": "2026-11-20"}
        reprint = "https://pbs.twimg.com/media/PublishedDocument?format=png&name=large"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "maker_announcement_events.json").write_text(
                json.dumps({"品目": [notice]}), encoding="utf-8")
            (root / "manufacturer_notices.json").write_text('{"notices":[]}', encoding="utf-8")
            baseline, = maker_news(root, {})
            with_reprint, = maker_news(root, {original: {"reprint_url": reprint}})
            unsafe, = maker_news(root, {original: {"reprint_url": "http://example.invalid/notice.pdf"}})
        self.assertEqual(with_reprint, {**baseline, "reprint_url": reprint})
        self.assertEqual(unsafe, baseline)

    def test_maker_dates_use_announcement_day_when_title_confirms_it(self):
        source = "https://www.hisamitsu-pharm.jp/product/whatsnew/pdf/"
        cases = [
            ("2026.07.16 製品の供給に関する案内", "2026-07-16", "2026-07-16", "案内"),
            ("2026年11月9日 製品の供給に関する案内", "2026-11-09", "2026-11-09", "案内"),
            ("製品の供給に関する案内", "2026-07-16", "2026-11-15", "確認"),
            ("2026/11/09 製品の供給に関する案内", "2026-11-08", "2026-11-15", "確認"),
        ]
        rows = [{"maker": "久光製薬", "event_type": "limited", "url": source + f"{i}.pdf",
                 "title": title, "announced_at": published, "first_seen": "2026-11-15"}
                for i, (title, published, _, _) in enumerate(cases)]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "maker_announcement_events.json").write_text(
                json.dumps({"品目": rows}), encoding="utf-8")
            (root / "manufacturer_notices.json").write_text('{"notices":[]}', encoding="utf-8")
            result = list(maker_news(root, {}))
        self.assertEqual([(r["date"], r["date_label"]) for r in result],
                         [(expected, label) for _, _, expected, label in cases])

    def test_maker_feed_hides_only_reviewed_duplicates_with_matching_metadata(self):
        base = "https://www.takata-seiyaku.co.jp/medical/topics/"
        original_url = base + "old-att/Procaterol.pdf"
        duplicate_url = base + "new-att/Procaterol.pdf"
        separate_url = base + "other-att/Procaterol.pdf"
        revised_url = base + "followup-att/Procaterol.pdf"
        orphan_url = base + "move-att/Procaterol.pdf"
        notice = {"maker": "高田製薬", "event_type": "supply", "announced_at": "2026-11-18",
                  "title": "2026/11/18 プロカテロールの供給に関するお知らせ"}
        rows = [{**notice, "url": url} for url in (original_url, duplicate_url, separate_url, orphan_url)]
        rows.append({**notice, "url": revised_url, "event_type": "stopped"})
        explanations = {
            original_url: {"summary": "バラ100gが限定出荷です。"},
            duplicate_url: {"duplicate_of": original_url},
            revised_url: {"duplicate_of": original_url},
            orphan_url: {"duplicate_of": base + "missing-att/Procaterol.pdf"},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "maker_announcement_events.json").write_text(
                json.dumps({"品目": rows}), encoding="utf-8")
            (root / "manufacturer_notices.json").write_text('{"notices":[]}', encoding="utf-8")
            result = {row["url"]: row for row in maker_news(root, explanations)}
        self.assertEqual(set(result), {original_url, separate_url, revised_url, orphan_url})
        self.assertEqual(result[original_url]["summary"], explanations[original_url]["summary"])


if __name__ == "__main__":
    unittest.main()
