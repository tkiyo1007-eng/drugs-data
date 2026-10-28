import unittest

from generate_item_pages import page_html, supply_answer_html, product_variants_html


class ItemAnswerContextTests(unittest.TestCase):
    def row(self):
        return {"商品名": "テスト散１％", "YJコード": "2242001B2335", "一般名": "テスト成分",
                "製造メーカー": "テスト製薬", "供給状況": "⑤供給停止", "理由": "６．薬価削除",
                "代替候補": "出荷量状況: D．薬価削除予定",
                "更新日": "2025/12/02", "ステータス更新日": "2026/06/01"}

    def notice(self):
        return {"maker": "テスト製薬", "title": "販売中止予定のお知らせ", "reason": "諸般の事情",
                "event_type": "discontinued", "id": "test-end", "url": "https://example.com/a.pdf",
                "announced_at": "2025-09", "verified_at": "2026-10-19", "sha256": "a" * 64,
                "targets": [{"yj_code": "2242001B2335", "product_name": "テスト散１％",
                             "maker": "テスト製薬", "scope": "product"}]}

    def test_top_answer_keeps_official_status_reason_and_row_date(self):
        result = page_html(self.row(), "2242001B2335", "stopped", "2099-01-01", [], set())
        top = result.split('class="item-freshness"', 1)[0].split('<main>', 1)[1]
        for value in ['供給停止', '６．薬価削除', '2026-06-01', '具体的な販売終了理由は確認できません']:
            self.assertIn(value, top)
        self.assertNotIn('2099-01-01', top)
        self.assertIn('how-to-check-discontinuation-and-delisting.html', top)
        desc = result.split('<meta name="description" content="', 1)[1].split('">', 1)[0]
        self.assertLess(desc.index('公表理由'), desc.index('原Excel'))

    def test_limited_supply_does_not_become_a_discontinuation(self):
        row = self.row()
        row.update(YJコード="2649805M1026", 供給状況="②限定出荷（自社の事情）", 理由="２．原材料調達上の問題")
        result = supply_answer_html(row, "limited")
        self.assertIn('限定出荷', result)
        self.assertIn('原材料調達上の問題', result)
        self.assertIn('販売中止を示す区分ではありません', result)

    def test_manufacturer_reason_requires_identity_and_product_scope(self):
        notice = self.notice()
        self.assertIn('諸般の事情', supply_answer_html(self.row(), "stopped", [notice]))
        notice['targets'][0]['scope'] = 'package'
        self.assertNotIn('諸般の事情', supply_answer_html(self.row(), "stopped", [notice]))
        notice['targets'][0].update(scope='product', product_name='別の散剤')
        self.assertNotIn('諸般の事情', supply_answer_html(self.row(), "stopped", [notice]))

    def test_changed_original_does_not_reuse_old_reason(self):
        notice = self.notice()
        bulletins = {"items": [{"url": notice['url'], "sha256": "b" * 64}]}
        result = supply_answer_html(self.row(), "stopped", [notice], bulletins=bulletins)
        self.assertNotIn('諸般の事情', result)
        self.assertIn('具体的な販売終了理由は確認できません', result)

    def test_other_products_do_not_get_discontinuation_interpretation(self):
        row = dict(self.row(), YJコード='1141007R1060')
        for status in ['ok', 'limited', 'stopped', 'ended']:
            result = supply_answer_html(row, status)
            self.assertNotIn('具体的な販売終了理由は確認できません', result)
            self.assertNotIn('終了案内と薬価の確認手順', result)
            self.assertNotIn('販売中止を示す区分ではありません', result)

    def test_variants_keep_each_status_and_reject_other_maker_or_ingredient(self):
        row = self.row()
        row.update(商品名='レボトミン錠５０ｍｇ', YJコード='1172014F3070')
        other = dict(row, 商品名='レボトミン錠５ｍｇ', YJコード='1172014F1043', 供給状況='①通常出荷')
        result = product_variants_html(row, [row, other], {'1172014F3070', '1172014F1043'})
        self.assertIn('href="1172014F1043.html"', result)
        self.assertIn('厚労省 通常出荷', result)
        self.assertIn('厚労省 供給停止', result)
        self.assertEqual('', product_variants_html(row, [row, dict(other, 製造メーカー='別会社')], set()))
        self.assertEqual('', product_variants_html(row, [row, dict(other, 一般名='別成分')], set()))
