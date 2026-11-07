import unittest
import csv
import json
from pathlib import Path
from check_reviewed_gas_sources import validate


class ReviewedGasSourceTests(unittest.TestCase):
    def setUp(self):
        self.reviewed = {'X00001': {'name': '液化酸素', 'manufacturer': '会社A'}}

    def test_same_identity_and_removed_row(self):
        self.assertEqual([], validate([('X00001', '液化酸素', '会社Ａ')], self.reviewed))
        self.assertEqual([], validate([], self.reviewed))

    def test_changed_name_maker_and_duplicate_stop(self):
        self.assertTrue(validate([('X00001', '液体窒素', '会社A')], self.reviewed))
        self.assertTrue(validate([('X00001', '液化酸素', '会社B')], self.reviewed))
        self.assertTrue(validate([('X00001', '液化酸素', '会社A'), ('X00001', '液化酸素', '会社A')], self.reviewed))

    def test_reviewed_rows_match_published_fields_without_guessing_sellers(self):
        root = Path(__file__).resolve().parent.parent
        reviewed = json.loads((root / 'verified_missing_gas_sellers.json').read_text(encoding='utf-8'))['products']
        self.assertEqual(126, len(reviewed))
        with (root / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {r['YJコード']: r for r in csv.DictReader(f)}
        for code, expected in reviewed.items():
            if code not in rows:  # 原表から消えた製品の削除は許容する。
                continue
            self.assertEqual(rows[code]['商品名'], expected['name'], code)
            self.assertEqual(rows[code]['製造メーカー'], expected['manufacturer'], code)
            self.assertEqual(rows[code]['販売メーカー'], '', code)

    def test_review_evidence_records_source_dates_and_hashes(self):
        root = Path(__file__).resolve().parent.parent
        evidence = json.loads((root / 'verified_missing_gas_sellers.json').read_text(encoding='utf-8'))
        self.assertEqual('2026-11-06', evidence['source_date'])
        self.assertRegex(evidence['source_sha256'], r'^[0-9a-f]{64}$')
        documents = evidence['association_document_evidence']
        self.assertEqual({'液体酸素', '酸素', '窒素', '二酸化炭素', '液体窒素'}, {d['kind'] for d in documents})
        self.assertEqual(5, len(documents))
        for document in documents:
            self.assertRegex(document['document_date'], r'^\d{4}-\d{2}-\d{2}$')
            self.assertTrue(document['url'].startswith('https://www.jimga.or.jp/'))
            self.assertRegex(document['sha256'], r'^[0-9a-f]{64}$')
