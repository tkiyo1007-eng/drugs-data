import unittest

from generate_item_pages import manufacturer_auto_check_text


class ManufacturerAutoCheckTest(unittest.TestCase):
    def setUp(self):
        self.notice = {'url': 'https://example.test/source.pdf', 'sha256': 'a' * 64}
        self.item = {'url': self.notice['url'], 'sha256': 'a' * 64, 'review_status': 'confirmed',
                     'hash_status': 'ok', 'document_checked_at': '2020-04-05T23:00:00+09:00'}

    def test_matching_verified_document_shows_actual_check_date(self):
        self.assertEqual('原典の自動再確認日：2020-04-05',
                         manufacturer_auto_check_text(self.notice, {'items': [self.item]}))

    def test_old_registry_or_failed_and_invalid_checks_are_not_confirmation(self):
        for changes in ({'review_status': 'needs_review'}, {'sha256': 'b' * 64},
                        {'hash_status': 'failed'}, {'document_checked_at': '2020-02-30'},
                        {'document_checked_at': '2999-01-01'}, {'url': 'https://example.test/other'}):
            item = dict(self.item, **changes)
            with self.subTest(changes=changes):
                self.assertEqual('原典の自動再確認：未確認',
                                 manufacturer_auto_check_text(self.notice, {'items': [item]}))

    def test_manual_and_missing_source_are_distinct(self):
        self.assertEqual('原典の自動再確認：対象外',
                         manufacturer_auto_check_text(dict(self.notice, collection_mode='manual'), {'items': []}))
        self.assertEqual('', manufacturer_auto_check_text(self.notice, None))


if __name__ == '__main__':
    unittest.main()
