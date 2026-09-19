import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from fetch_headlines import collect, parse_feed, JST


def rss(entries=''):
    return ('<rss><channel>' + entries + '</channel></rss>').encode()


ENTRY = '<item><title>試験記事</title><link>https://www.yakuji.co.jp/entry123.html</link><pubDate>Tue, 15 Sep 2026 21:00:00 +0000</pubDate><category>HEADLINE NEWS</category><description>保存禁止本文</description></item>'


class HeadlineTests(unittest.TestCase):
    def test_metadata_only_and_jst(self):
        data = parse_feed(rss(ENTRY + ENTRY))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['date'], '2026-09-16')
        self.assertNotIn('保存禁止本文', json.dumps(data, ensure_ascii=False))
        self.assertEqual(parse_feed(rss(ENTRY.replace('HEADLINE NEWS', '人事'))), [])

    def test_invalid_feeds_rejected(self):
        for body in [b'{}', b'<html/>', rss(ENTRY.replace('entry123.html', 'file.pdf')), rss(ENTRY.replace('www.yakuji.co.jp', 'evil.example')), rss(ENTRY.replace('Tue, 15 Sep 2026 21:00:00 +0000', 'bad'))]:
            with self.subTest(body=body), self.assertRaises(Exception):
                parse_feed(body)

    def test_failure_retains_success_and_recovery_and_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'headlines.json'
            now = dt.datetime(2026, 9, 16, tzinfo=JST)
            good = collect(path, lambda: rss(ENTRY), now)
            def fail():
                raise TimeoutError()
            failed = collect(path, fail, now + dt.timedelta(days=1))
            self.assertEqual(failed['status'], 'failed')
            self.assertEqual(failed['items'], good['items'])
            self.assertEqual(failed['last_success_at'], good['last_success_at'])
            empty = collect(path, lambda: rss(), now + dt.timedelta(days=2))
            self.assertEqual(empty['status'], 'ok')
            self.assertEqual(empty['items'], [])

    def test_invalid_previous_file_does_not_block_failure_status(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'headlines.json'
            path.write_text('{', encoding='utf-8')
            result = collect(path, lambda: (_ for _ in ()).throw(TimeoutError()), dt.datetime(2026, 9, 16, tzinfo=JST))
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['items'], [])
            self.assertIsNone(result['last_success_at'])
