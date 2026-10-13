import copy
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import manufacturer_x_plan as mp
import x_daily_post as xp
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parents[1]

class ManufacturerPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.day = dt.date(2026, 10, 14)
        self.n = {'id': 'reviewed-fixture', 'maker': 'fixture', 'title': 'reviewed notice',
                  'url': 'https://official.test/notice.pdf', 'sha256': 'a'*64,
                  'listed_at': '2026-10-13', 'announced_at': '2026-10', 'verified_at': '2026-10-14',
                  'event_type': 'recall', 'targets': [{'yj_code': '123456789012', 'product_name': 'fixture'}],
                  'x_text': 'Reviewed notice https://official.test/notice.pdf'}
        self.write('manufacturer_posting_policy.json', {'enabled': True, 'max_posts_per_day': 1,
                   'max_attempts_per_month': 31, 'estimated_usd_per_post_with_url': '0.20', 'estimated_monthly_cap_usd': '6.20'})
        self.write('manufacturer_notices.json', {'notices': [self.n]})
        self.b = {'checked_at': '2026-10-14T01:20:00+09:00', 'items': [{'url': self.n['url'], 'sha256': self.n['sha256'], 'review_status': 'confirmed', 'document_checked_at': '2026-10-14T01:20:00+09:00'}]}
        self.write('manufacturer_bulletins.json', self.b)
    def write(self, name, value): (self.base / name).write_text(json.dumps(value), encoding='utf-8')
    def plan(self, log=None): return mp.build(self.base, log or {'posted': []}, self.day, xp.finalize)
    def test_only_current_confirmed_source_can_be_posted(self):
        p = self.plan(); self.assertEqual(p['action'], 'post'); self.assertLessEqual(p['weighted_length'], 280)
        for field, value in [('sha256', '0'*64), ('review_status', 'needs_review'), ('document_checked_at', '2026-10-13T01:00:00+09:00')]:
            b = copy.deepcopy(self.b); b['items'][0][field] = value; self.write('manufacturer_bulletins.json', b)
            self.assertEqual(self.plan()['action'], 'skip')
    def test_daily_monthly_pending_and_document_dedup(self):
        key = self.n['id'] + ':' + self.n['sha256']
        for posted in [
            [{'kind': 'manufacturer', 'post_day': '2026-10-14'}],
            [{'kind': 'manufacturer', 'post_day': '2026-10-13', 'document_key': key}],
            [{'kind': 'manufacturer', 'post_day': '2026-10-01', 'state': 'pending'}],
            [{'kind': 'manufacturer', 'post_day': '2026-10-01'}]*31]:
            self.assertEqual(self.plan({'posted': posted})['action'], 'skip')
    def test_old_or_future_notice_is_not_backfilled(self):
        for date in ['2026-10-01', '2026-10-15']:
            n = copy.deepcopy(self.n); n['listed_at'] = date; self.write('manufacturer_notices.json', {'notices': [n]})
            self.assertEqual(self.plan()['action'], 'skip')
    def test_archived_target_waits_for_a_new_review(self):
        n = copy.deepcopy(self.n); n['targets'][0]['archived_from_csv_at'] = '2026-10-14'
        self.write('manufacturer_notices.json', {'notices': [n]})
        self.assertEqual(self.plan()['action'], 'skip')
    def test_published_page_and_live_source_hash_required(self):
        body = b'%PDF verified'; sha = hashlib.sha256(body).hexdigest()
        item = {'url': 'page', 'source_url': 'source', 'source_sha256': sha}
        registry = b'registry'
        entry = {'sha256': hashlib.sha256(registry).hexdigest(), 'bytes': len(registry)}
        manifest = json.dumps({'files': {name: entry for name in ['manufacturer_notices.json', 'manufacturer_bulletins.json']}}).encode()
        def fetch(page, source): return lambda url: manifest if url.endswith('public-data-manifest.json') else page if url == 'page' else source
        with mock.patch.object(mp.Path, 'read_bytes', return_value=registry):
            mp.verify_published(item, fetch(sha.encode(), body))
            for page, source in [(b'old page', body), (sha.encode(), b'new source')]:
                with self.assertRaises(ValueError): mp.verify_published(item, fetch(page, source))
        with mock.patch.object(mp.Path, 'read_bytes', return_value=b'unpublished'):
            with self.assertRaises(ValueError): mp.verify_published(item, fetch(sha.encode(), body))
    def test_uncertain_post_result_is_saved_and_not_retried(self):
        plan = self.plan(); log_path = self.base / 'x_post_log.json'; plan_path = self.base / 'plan.json'
        plan_path.write_text(json.dumps({'posts': [plan]}))
        with mock.patch.object(xp, 'LOG_PATH', log_path), mock.patch.object(xp, 'jst_today', return_value=self.day), mock.patch.object(mp, 'build', return_value=plan), mock.patch.object(mp, 'verify_published'), mock.patch.object(mp, 'reserve_remote'), mock.patch.dict('os.environ', {n: 'fixture' for n in xp.CREDENTIAL_ENV}), mock.patch.object(xp, 'post_to_x', side_effect=RuntimeError('timeout')):
            with self.assertRaises(RuntimeError): xp.main(['post', '--plan', str(plan_path)])
        log = json.loads(log_path.read_text()); self.assertEqual(log['posted'][0]['state'], 'pending')
        self.assertEqual(self.plan(log)['action'], 'skip')
    def test_reservation_failure_never_sends_a_post(self):
        plan = self.plan(); path = self.base / 'plan.json'; log = self.base / 'log.json'
        path.write_text(json.dumps({'posts': [plan]}))
        with mock.patch.object(xp, 'LOG_PATH', log), mock.patch.object(xp, 'jst_today', return_value=self.day), mock.patch.object(mp, 'build', return_value=plan), mock.patch.object(mp, 'verify_published'), mock.patch.object(mp, 'reserve_remote', side_effect=RuntimeError('push failed')), mock.patch.dict('os.environ', {n: 'fixture' for n in xp.CREDENTIAL_ENV}), mock.patch.object(xp, 'post_to_x') as post:
            with self.assertRaises(RuntimeError): xp.main(['post', '--plan', str(path)])
            post.assert_not_called()

class NoticeContractTests(unittest.TestCase):
    def fixture(self):
        row = {'YJコード': '1234567F1020', '商品名': '検査用錠１ｍｇ',
               '製造メーカー': 'ファイザー', '販売メーカー': 'ファイザー'}
        document = {'schema_version': 1, 'notices': [{
            'id': 'fixture-notice', 'maker': 'ファイザー', 'title': '検査用販売中止案内',
            'reason': '検査用理由', 'url': 'https://www.pfizermedicalinformation.jp/sites/default/files/announcement/fixture.pdf',
            'sha256': 'a' * 64, 'event_type': 'discontinued', 'announced_at': '2026-10',
            'listed_at': '2026-10-01', 'verified_at': '2026-10-08',
            'targets': [{'yj_code': row['YJコード'], 'product_name': row['商品名'],
                         'scope': 'product', 'packages': [{'package': '100錠'}]}],
            'alternatives': [], 'cautions': [],
        }]}
        return document, [row]

    def test_repository_registry_keeps_current_or_explicitly_archived_identity(self):
        import csv
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig') as handle:
            rows = list(csv.DictReader(handle))
        document = json.loads((ROOT / 'manufacturer_notices.json').read_text())
        self.assertEqual(validate(document, rows), [])

    def test_source_identity_and_dates_fail_closed(self):
        document, rows = self.fixture()
        self.assertEqual(validate(document, rows), [])
        for field, value in [('verified_at', '2026-10'), ('sha256', 'bad'), ('url', 'https://example.org/fake.pdf')]:
            broken = copy.deepcopy(document); broken['notices'][0][field] = value
            self.assertTrue(validate(broken, rows))
        broken = copy.deepcopy(document); broken['notices'][0]['targets'][0]['yj_code'] = '9999999F1020'
        self.assertTrue(validate(broken, rows))

    def test_missing_targets_require_full_valid_archival_date(self):
        document, rows = self.fixture()
        self.assertTrue(validate(document, []))
        target = document['notices'][0]['targets'][0]
        target['archived_from_csv_at'] = '2026-10-08'
        self.assertEqual(validate(document, []), [])
        future = (dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date() + dt.timedelta(days=1)).isoformat()
        for field, value in [('archived_from_csv_at', '2026-10'), ('archived_from_csv_at', '2026-02-30'),
                             ('archived_from_csv_at', future), ('archived_from_csv_at', True),
                             ('yj_code', []), ('yj_code', 'invalid'), ('product_name', 123), ('scope', [])]:
            broken = copy.deepcopy(document); broken['notices'][0]['targets'][0][field] = value
            self.assertTrue(validate(broken, []), (field, value))

    def test_archive_marker_cannot_mask_current_name_or_maker_mismatch(self):
        document, rows = self.fixture()
        document['notices'][0]['targets'][0]['archived_from_csv_at'] = '2026-10-08'
        for field, value in [('product_name', '別名'), ('maker', '別会社')]:
            broken = copy.deepcopy(document); broken['notices'][0]['targets'][0][field] = value
            self.assertTrue(validate(broken, rows))

    def test_missing_candidates_keep_original_identity_only_with_archival_marker(self):
        document, rows = self.fixture()
        candidate = {'name': '過去候補錠', 'yj_code': '9999999F1020'}
        document['notices'][0]['alternatives'] = [{'products': [candidate]}]
        self.assertTrue(validate(document, rows))
        candidate['archived_from_csv_at'] = '2026-10-08'
        self.assertEqual(validate(document, rows), [])
        for field, value in [('yj_code', 'bad'), ('archived_from_csv_at', None), ('name', {}), ('product_kind', []),
                             ('product_kind', 'medical_device')]:
            broken = copy.deepcopy(document)
            broken['notices'][0]['alternatives'][0]['products'][0][field] = value
            self.assertTrue(validate(broken, rows))

if __name__ == '__main__': unittest.main()
