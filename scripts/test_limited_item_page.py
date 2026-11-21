import copy
import tempfile
import unittest
from pathlib import Path
from generate_item_pages import item_key, map_status, page_html, should_generate, strict_status
from limited_item_page import PILOT_KEYS, prepare_assets, write_pilot_links


class LimitedItemPageTests(unittest.TestCase):
    def test_new_limitation_and_recovery_keep_the_item_url_and_switch_layout(self):
        row = {"YJコード": "1234567F9876", "商品名": "テスト薬０．０５％", "規格": "１ｇ"}
        key = item_key(row)
        existing = set()
        for raw in ("①通常出荷", "②限定出荷（自社の事情）", "③限定出荷（他社品の影響）",
                    "④限定出荷（その他）", "①通常出荷", "⑤供給停止", "③限定出荷（他社品の影響）"):
            row["供給状況"] = raw
            if not should_generate(row, key, existing, {}, {}):
                self.assertFalse(existing)
                continue
            existing.add(key)
            page = page_html(row, key, map_status(raw), "", [], existing)
            active = strict_status(raw) == "limited"
            self.assertEqual('class="summary"' in page, active)
            self.assertIn(f'rel="canonical" href="https://kyokyu-navi.jp/items/{key}.html"', page)
            self.assertIn('id="watchButton"', page)
            if active:
                self.assertIn(f'<strong class="status limited">{raw}</strong>', page)
                self.assertIn('<time>確認できません</time>', page)
                self.assertNotIn('href="#trialAlternatives"', page)
                self.assertNotIn('href="#compare"', page)

    def test_dated_existing_package_source_is_promoted_without_live_claim(self):
        fixtures = (
            ("3999001Q6029", "ラグノスＮＦ経口ゼリー分包１２ｇ", "三和化学研究所",
             "https://med.skk-net.com/significant/item/LAGNF2610i.pdf", "2026-10", "2026年10月",
             [("12g×84包", "086220569")]),
            ("3999001Q2058", "モニラック・シロップ６５％", "丸石製薬",
             "https://www.maruishi-pharm.co.jp/medical/media/syukkajokyo_20261116.pdf", "2026-11-16",
             "2026年11月16日付", [("300mL", "211-128302"), ("10mL分包×84包（21包×4）", "211-128319")]),
        )
        for yj, name, maker, url, day, display_day, packages in fixtures:
            with self.subTest(yj=yj):
                row = {"YJコード": yj, "商品名": name, "製造メーカー": maker,
                       "供給状況": "②限定出荷（自社の事情）", "理由": "８．その他の理由"}
                target = {"yj_code": yj, "product_name": name, "maker": maker, "scope": "package",
                          "packages": [{"package": label, "unified_product_code": code}
                                       for label, code in packages]}
                notice = {"id": "test-dated-package", "title": "以前のメーカー案内", "url": url, "maker": maker,
                          "event_type": "limited", "announced_at": day, "verified_at": "2026-11-17",
                          "sha256": "a" * 64, "targets": [target]}
                unchecked = {"items": [{"url": url, "sha256": "a" * 64, "review_status": "needs_review",
                                       "review_reason": "原典hashの今回確認が未完了。前回内容は保持"}]}
                def page(notice=notice, row=row, bulletins=unchecked):
                    return page_html(row, row["YJコード"], map_status(row["供給状況"]), "2026-11-21",
                                     [], {yj}, manufacturer_notices=[notice], manufacturer_bulletins=bulletins)
                exact = "・".join(label for label, _ in packages)
                created = page()
                self.assertIn(f'{maker}の当時の包装別案内（{exact}） <small>文書 {day}</small>', created)
                self.assertIn(f'{display_day}の{maker}の案内は{exact}が対象。', created)
                self.assertIn("当時の案内で、現在の包装別供給や在庫を示しません。", created)
                self.assertIn("最新の原典は再確認待ちです。", created)
                self.assertIn('"dateModified":"2026-11-21"', created)
                self.assertIn(f'rel="canonical" href="https://kyokyu-navi.jp/items/{yj}.html"', created)
                self.assertEqual(created.count('id="manufacturerNoticesTitle"'), 1)

                changed = page(bulletins={"items": [{"url": url, "sha256": "b" * 64}]})
                self.assertIn("更新された原文", changed)
                self.assertIn("原典更新を検出・再確認待ち", changed)
                self.assertNotIn("当時の包装別案内", changed)
                self.assertNotIn("現在の包装別供給や在庫を示しません", changed)

                for field, value in (("scope", "product"), ("product_name", "別製品"),
                                     ("maker", "別製造元"), ("yj_code", "1234567F9876")):
                    bad = copy.deepcopy(notice)
                    bad["targets"][0][field] = value
                    self.assertNotIn("当時の包装別案内", page(bad))
                bad = copy.deepcopy(notice)
                bad["targets"][0]["packages"][0]["unified_product_code"] = "000000000"
                self.assertNotIn("当時の包装別案内", page(bad))
                self.assertNotIn("当時の包装別案内", page(row=dict(row, 供給状況="①通常出荷")))

    def test_pilot_urls_follow_canonical_items_and_retired_products_are_removed(self):
        with tempfile.TemporaryDirectory() as name:
            site = Path(name)
            folder = site / "items" / "trial"
            prepare_assets(site)
            retired = folder / (PILOT_KEYS[1] + ".html")
            retired.touch()
            write_pilot_links(folder, [{"key": PILOT_KEYS[0], "display_name": "テスト錠"}])
            index = (folder / "index.html").read_text()
            self.assertFalse(retired.exists())
            self.assertNotIn(PILOT_KEYS[1], index)
            self.assertIn('noindex,follow', index)
            redirect = (folder / (PILOT_KEYS[0] + ".html")).read_text()
            self.assertIn(f'content="0;url=../{PILOT_KEYS[0]}.html"', redirect)
            self.assertTrue((folder / "trial.js").is_file())
            self.assertTrue((site / "items" / "limited-detail.css").is_file())
