import unittest

from generate_item_pages import bonzol_strength_selector, page_html, supply_answer_html, product_variants_html


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

    def test_bonzol_strength_switch_links_only_the_verified_published_peer(self):
        low = dict(self.row(), 商品名='ボンゾール錠１００ｍｇ', YJコード='2499007F1021', 一般名='ダナゾール',
                   販売メーカー='田辺ファーマ', 製造メーカー='田辺ファーマ', 供給状況='①通常出荷')
        high = dict(low, 商品名='ボンゾール錠２００ｍｇ', YJコード='2499007F2028')
        keys = {r['YJコード'] for r in (low, high)}
        for row, peer, current, other in ((low, high, '100mg', '200mg'), (high, low, '200mg', '100mg')):
            nav = bonzol_strength_selector(row, [peer], keys)
            self.assertIn(f'aria-current="page">{current}<small>（表示中）', nav)
            self.assertIn(f'href="{peer["YJコード"]}.html" data-dsn-event="related-item-open">{other}</a>', nav)
            self.assertNotIn(f'href="{row["YJコード"]}.html"', nav)
            for status, label, heading in [('ok', '①通常出荷', 'class="stbox status-ok"'),
                                           ('limited', '②限定出荷（自社の事情）', '厚労省の供給状況</h2>')]:
                result = page_html(dict(row, 供給状況=label), row['YJコード'], status, '2026-11-22', [],
                                   keys, product_variants=[peer])
                self.assertLess(result.index(nav), result.index(heading))
                self.assertNotIn('data-spec-note="1"', result)
        for replacement in [dict(high, 販売メーカー='別会社'), dict(high, 商品名=low['商品名']),
                            dict(high, 一般名='別成分'), dict(high, YJコード='0000000F0000')]:
            self.assertEqual('', bonzol_strength_selector(low, [replacement], keys))
        self.assertEqual('', bonzol_strength_selector(low, [high], {low['YJコード']}))
