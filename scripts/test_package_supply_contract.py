"""Package facts remain optional, source-scoped, and separate from dated plans."""
import copy
import json
import unittest
from pathlib import Path

from validate_manufacturer_notices import validate


class PackageSupplyContractTests(unittest.TestCase):
    def fixture(self):
        row = {'YJコード': '1234567F1020', '商品名': '検査用錠１ｍｇ',
               '製造メーカー': 'ファイザー', '販売メーカー': 'ファイザー'}
        document = {'schema_version': 1, 'notices': [{
            'id': 'package-fixture', 'maker': 'ファイザー', 'title': '検査用包装別案内',
            'reason': '検査用理由', 'url': 'https://www.pfizermedicalinformation.jp/fixture.pdf',
            'sha256': 'a' * 64, 'event_type': 'limited', 'announced_at': '2026-09',
            'listed_at': '2026-09-07', 'verified_at': '2026-10-18',
            'targets': [{'yj_code': row['YJコード'], 'product_name': row['商品名'],
                         'scope': 'package', 'packages': [{'package': 'PTP100錠'}]}],
            'alternatives': [], 'cautions': [],
        }]}
        return document, [row]

    def package(self, document):
        return document['notices'][0]['targets'][0]['packages'][0]

    def supply(self):
        return {'status': 'limited', 'status_text': '限定出荷（Aプラス-④）',
                'plans': [{'event': 'stock_depletion', 'timing': '2026年11月'},
                          {'event': 'shipment_resumption', 'timing': '2027年3月頃'}],
                'note': '在庫消尽後に一時供給停止予定。現在の実績は未確認。'}

    def test_legacy_packages_without_supply_remain_valid(self):
        document, rows = self.fixture()
        self.assertEqual(validate(document, rows), [])

    def test_each_known_status_requires_its_source_text(self):
        document, rows = self.fixture()
        for status, text in [('normal', '通常出荷'), ('limited', '限定出荷'), ('stopped', '供給停止')]:
            with self.subTest(status=status):
                self.package(document)['supply'] = {'status': status, 'status_text': text, 'plans': []}
                self.assertEqual(validate(document, rows), [])
                for bad in [None, '', '  ', 1, []]:
                    self.package(document)['supply']['status_text'] = bad
                    self.assertTrue(validate(document, rows))
                self.package(document)['supply'].pop('status_text')
                self.assertTrue(validate(document, rows))

    def test_unconfirmed_omits_potentially_conflicting_source_status(self):
        document, rows = self.fixture()
        self.package(document)['supply'] = {'status': 'unconfirmed', 'plans': []}
        self.assertEqual(validate(document, rows), [])
        for text in ['通常出荷', '供給停止', '', None]:
            self.package(document)['supply']['status_text'] = text
            self.assertTrue(validate(document, rows))

    def test_invalid_supply_shapes_and_unknown_status_fail_closed(self):
        document, rows = self.fixture()
        for value in [None, [], '', True, {}, {'status': 'available', 'plans': []},
                      {'status': [], 'plans': []}, {'status': True, 'plans': []}]:
            with self.subTest(value=value):
                self.package(document)['supply'] = value
                self.assertTrue(validate(document, rows))

    def test_plans_require_known_event_and_nonempty_timing(self):
        document, rows = self.fixture()
        for value in [None, {}, '', [None], [{}],
                      [{'event': 'available', 'timing': '2026年11月'}],
                      [{'event': [], 'timing': '2026年11月'}],
                      [{'event': 'stock_depletion', 'timing': ''}],
                      [{'event': 'stock_depletion', 'timing': ' '}],
                      [{'event': 'stock_depletion', 'timing': 2026}]]:
            with self.subTest(value=value):
                supply = self.supply(); supply['plans'] = value
                self.package(document)['supply'] = supply
                self.assertTrue(validate(document, rows))
        self.package(document)['supply'] = self.supply()
        self.package(document)['supply'].pop('plans')
        self.assertTrue(validate(document, rows))

    def test_all_supported_plan_events_and_optional_note(self):
        document, rows = self.fixture()
        self.package(document)['supply'] = {'status': 'unconfirmed', 'plans': [
            {'event': event, 'timing': 'メーカー公表の予定'} for event in
            ['stock_depletion', 'shipment_resumption', 'normal_shipment', 'discontinuation']]}
        self.assertEqual(validate(document, rows), [])
        for value in [None, '', ' ', 1, []]:
            self.package(document)['supply']['note'] = value
            self.assertTrue(validate(document, rows))

    def test_elapsed_plan_does_not_rewrite_status_or_input(self):
        document, rows = self.fixture()
        supply = self.supply(); supply['plans'][0]['timing'] = '2020年1月'
        self.package(document)['supply'] = supply
        before = copy.deepcopy(document)
        self.assertEqual(validate(document, rows), [])
        self.assertEqual(document, before)
        self.assertEqual(self.package(document)['supply']['status'], 'limited')

    def test_unknown_listing_date_is_omitted_not_inferred_from_document_month(self):
        document, rows = self.fixture()
        document['notices'][0].pop('listed_at')
        before = copy.deepcopy(document)
        self.assertEqual(validate(document, rows), [])
        self.assertEqual(document, before)
        for value in [None, '', '2026-09', '2026-02-30', True]:
            document['notices'][0]['listed_at'] = value
            self.assertTrue(validate(document, rows))

    def test_manual_notice_guides_legacy_clients_to_original_candidate_page(self):
        # Old clients interpret an empty alternatives array as no candidates in the source.
        document = json.loads((Path(__file__).resolve().parents[1] / 'manufacturer_notices.json').read_text())
        notice = next(n for n in document['notices'] if n['id'] == 'amel-hilnamin-tablets-package-plan-202609')
        self.assertTrue(notice['alternatives'])
        self.assertTrue(all(g['products'] == [] for g in notice['alternatives']))
        self.assertIn('原文2ページ', ' '.join(c for g in notice['alternatives'] for c in g['cautions']))

    def test_manual_mode_does_not_relax_source_and_date_validation(self):
        document, rows = self.fixture()
        notice = document['notices'][0]; notice['collection_mode'] = 'manual'
        self.assertEqual(validate(document, rows), [])
        for field, value in [('collection_mode', 'auto'), ('collection_mode', None),
                             ('url', 'https://example.test/fixture.pdf'), ('sha256', 'bad'),
                             ('verified_at', '2026-10')]:
            broken = copy.deepcopy(document); broken['notices'][0][field] = value
            self.assertTrue(validate(broken, rows))

    def test_reviewed_hilnamin_plans_keep_seven_packages_and_three_tablet_strengths(self):
        document = json.loads((Path(__file__).resolve().parents[1] / 'manufacturer_notices.json').read_text())
        notice = next(n for n in document['notices'] if n['id'] == 'amel-hilnamin-tablets-package-plan-202609')
        self.assertEqual(notice['collection_mode'], 'manual')
        self.assertEqual(notice['event_type'], 'resumption_planned')
        self.assertEqual(notice['announced_at'], '2026-09')
        self.assertEqual(notice['verified_at'], '2026-10-18')
        self.assertNotIn('listed_at', notice)
        self.assertEqual(notice['sha256'], '60eada8c9fa8bb7b2f0789758f173ffc52cb88bdfc80c681baadf0e0453de80b')
        self.assertEqual({t['yj_code'] for t in notice['targets']}, {'1172014F1027', '1172014F2139', '1172014F3038'})
        expected = {
            ('1172014F1027', 'PTP100錠'): ('2026年11月', '14987058682033'),
            ('1172014F1027', 'PTP1000錠'): ('2027年1月', '14987058682118'),
            ('1172014F1027', 'バラ1000錠'): ('2026年12月', '14987058682613'),
            ('1172014F2139', 'PTP100錠'): ('2026年10月', '14987058683030'),
            ('1172014F2139', 'バラ1000錠'): ('2026年11月', '14987058683610'),
            ('1172014F3038', 'PTP100錠'): ('2026年11月', '14987058684037'),
            ('1172014F3038', 'バラ1000錠'): ('2027年2月', '14987058684617'),
        }
        observed = {}
        for target in notice['targets']:
            self.assertEqual(target['source_pages'], [1, 2])
            for package in target['packages']:
                supply = package['supply']
                # The narrative schedules a stop, while both tables use stopped codes.
                # Do not resolve that timing ambiguity into a package status.
                self.assertEqual(supply['status'], 'unconfirmed')
                self.assertNotIn('status_text', supply)
                self.assertIn('実際の停止時点は未確認', supply['note'])
                plans = {p['event']: p['timing'] for p in supply['plans']}
                self.assertEqual(plans['shipment_resumption'], '2027年3月頃')
                observed[(target['yj_code'], package['package'])] = (plans['stock_depletion'], package['gs1_sales'])
        self.assertEqual(observed, expected)


if __name__ == '__main__':
    unittest.main()
