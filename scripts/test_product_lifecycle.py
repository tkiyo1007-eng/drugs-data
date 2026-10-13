import csv
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.build_product_lifecycle import (
    PARTIAL_RE,
    announcement_date,
    announcement_covers_product,
    announcement_identifies_product_as_new_release,
    announcement_targets_product,
    backfill_announcement_dates,
    confirmed_supply_end_fields,
    event_last_checked_by_url,
    existing_record_needs_reverification,
    is_product_wide_discontinuation,
    lifecycle_verified_at,
    verified_group_announcements,
    verified_group_scopes,
)
from scripts.fetch_maker_announcements import match_to_csv
from scripts.validate_product_lifecycle import validate


class ProductLifecycleTests(unittest.TestCase):
    @staticmethod
    def _end_annotation(expected="2027-03"):
        annotation = {
            "target_products_verified": True,
            "target_scope": "product",
            "supply_end_note": "在庫消尽次第。2027年3月頃を予定しています。",
            "supply_end_packages": ["PTP100錠"],
            "supply_end_source_url": "https://med.sawai.co.jp/end.pdf",
            "supply_end_verified_at": "2026-08-28",
        }
        if expected is not None:
            annotation["supply_end_expected"] = expected
        return annotation

    def test_condition_only_is_not_invented_as_an_end_date(self):
        annotation = self._end_annotation(None)
        annotation["supply_end_note"] = "弊社在庫がなくなり次第、販売を中止します。"
        fields = confirmed_supply_end_fields(annotation, {}, annotation["supply_end_source_url"])
        self.assertNotIn("supply_end_expected", fields)
        self.assertEqual(fields["supply_end_note"], annotation["supply_end_note"])

    def test_missing_or_unverified_notice_does_not_erase_recorded_end_information(self):
        current = self._end_annotation()
        current.pop("target_products_verified")
        current.pop("target_scope")
        for announcement in ({}, {"supply_end_expected": "2028-01"}):
            with self.subTest(announcement=announcement):
                self.assertEqual(confirmed_supply_end_fields(
                    announcement, current, "https://med.sawai.co.jp/end.pdf"), current)

    def test_confirmed_condition_without_date_keeps_same_source_date(self):
        current = {"source_url": "https://med.sawai.co.jp/end.pdf", "supply_end_expected": "2027-03"}
        annotation = self._end_annotation(None)
        fields = confirmed_supply_end_fields(annotation, current, current["source_url"])
        self.assertEqual(fields["supply_end_expected"], "2027-03")

    def test_legacy_date_is_bound_to_old_source_before_a_notice_switch(self):
        current = {"source_url": "https://med.sawai.co.jp/old.pdf", "supply_end_expected": "2027-03"}
        fields = confirmed_supply_end_fields({}, current, "https://med.sawai.co.jp/new.pdf")
        self.assertEqual(fields, {"supply_end_expected": "2027-03",
                                  "supply_end_source_url": current["source_url"]})

    def test_end_annotation_cannot_be_attached_to_a_different_source(self):
        with self.assertRaisesRegex(ValueError, "原典URL"):
            confirmed_supply_end_fields(self._end_annotation(), {}, "https://med.sawai.co.jp/other.pdf")

    def test_new_notice_condition_does_not_inherit_old_notice_date(self):
        current = {"source_url": "https://med.sawai.co.jp/old.pdf", "supply_end_expected": "2027-03"}
        annotation = self._end_annotation(None)
        fields = confirmed_supply_end_fields(annotation, current, annotation["supply_end_source_url"])
        self.assertNotIn("supply_end_expected", fields)

    def test_confirmed_end_annotation_rejects_impossible_calendar_date(self):
        for field, value in (("supply_end_expected", "2027-02-30"),
                             ("supply_end_expected", "2027-13"),
                             ("supply_end_verified_at", "2026-08")):
            with self.subTest(field=field, value=value):
                annotation = self._end_annotation()
                annotation[field] = value
                with self.assertRaises(ValueError):
                    confirmed_supply_end_fields(annotation, {}, annotation["supply_end_source_url"])

    def test_per_product_end_conditions_do_not_inherit_group_date(self):
        annotation = self._end_annotation()
        group = {
            "products": ["薬A錠"], "target_products_verified": True,
            "target_scope": "product", "expected_target_count": 2,
            "announcement": {"maker": "沢井製薬", "title": "販売中止", "event_type": "discontinued",
                             "url": annotation["supply_end_source_url"], **annotation},
            "lifecycle_targets": [{"product_name": "薬B錠", "yj_code": "123456789012",
                                   **self._end_annotation(None),
                                   "supply_end_note": "在庫消尽次第"}],
        }
        expanded = verified_group_announcements([group])
        self.assertEqual(expanded["薬A錠"]["supply_end_expected"], "2027-03")
        self.assertNotIn("supply_end_expected", expanded["薬B錠"])

    @staticmethod
    def _same_name_targets():
        name = "ゼルフォーム"
        source = "https://www.pfizermedicalinformation.jp/end.pdf"
        yjs = ("3322701X1020", "3322701X2027")
        rows = [{"商品名": name, "YJコード": yj, "製造メーカー": "ファイザー",
                 "販売メーカー": "ファイザー"} for yj in yjs]
        group = {
            "products": [], "target_products_verified": True,
            "target_scope": "product", "expected_target_count": 2,
            "announcement": {"maker": "ファイザー", "title": "販売中止予定のご案内",
                             "event_type": "discontinued", "url": source,
                             "checked": "2026-10-14", "announced_at": "2026-10"},
            "lifecycle_targets": [
                {"product_name": name, "yj_code": yj,
                 "supply_end_note": "出荷停止中。販売中止日・月の記載はありません",
                 "supply_end_packages": [package], "supply_end_source_url": source,
                 "supply_end_verified_at": "2026-10-14"}
                for yj, package in zip(yjs, ("No.12［4袋］", "No.100［1袋］"))
            ],
        }
        return rows, group

    def _build_target_groups(self, rows, groups, existing=None):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with (base / "drugs.csv").open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["商品名", "YJコード", "製造メーカー", "販売メーカー"])
                writer.writeheader()
                writer.writerows(rows)
            for filename, value in (("announcements.json", {}), ("groups.json", groups),
                                    ("existing.json", existing or {"products": {}})):
                (base / filename).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run([
                sys.executable, str(root / "scripts/build_product_lifecycle.py"),
                "--csv", str(base / "drugs.csv"), "--announcements", str(base / "announcements.json"),
                "--manual-groups", str(base / "groups.json"), "--existing", str(base / "existing.json"),
                "--output", str(base / "output.json"),
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr[-500:])
            return json.loads((base / "output.json").read_text())["products"]

    def test_verified_same_name_targets_keep_both_yjs_and_original_names(self):
        _, group = self._same_name_targets()
        expanded = verified_group_announcements([group])
        self.assertEqual(len(expanded), 2)
        self.assertEqual({info["verified_yj_code"] for info in expanded.values()},
                         {"3322701X1020", "3322701X2027"})
        self.assertEqual({info["verified_product_name"] for info in expanded.values()}, {"ゼルフォーム"})
        # 既存の一意の商品名キーのインターフェースを維持する。
        group["lifecycle_targets"] = group["lifecycle_targets"][:1]
        group["expected_target_count"] = 1
        self.assertEqual(set(verified_group_announcements([group])), {"ゼルフォーム"})

    def test_cli_same_name_explicit_targets_generate_distinct_package_facts(self):
        rows, group = self._same_name_targets()
        products = self._build_target_groups(rows, [group])
        self.assertEqual(set(products), {"3322701X1020", "3322701X2027"})
        for target in group["lifecycle_targets"]:
            item = products[target["yj_code"]]
            self.assertEqual(item["product_name"], target["product_name"])
            self.assertEqual(item["supply_end_packages"], target["supply_end_packages"])
            self.assertEqual(item["supply_end_source_url"], target["supply_end_source_url"])
            self.assertNotIn("supply_end_expected", item)
            self.assertEqual(item["verified_at"], "2026-10-14")

    def test_cli_same_name_target_never_falls_back_after_yj_name_or_maker_mismatch(self):
        for mismatch in ("missing_yj", "name", "maker", "removed_from_csv"):
            with self.subTest(mismatch=mismatch):
                rows, group = self._same_name_targets()
                if mismatch == "missing_yj":
                    group["lifecycle_targets"][1]["yj_code"] = "3322701X9999"
                elif mismatch == "name":
                    rows[1]["商品名"] = "別の製品"
                elif mismatch == "maker":
                    rows[1].update({"製造メーカー": "別製薬", "販売メーカー": "別製薬"})
                else:
                    rows = rows[:1]
                products = self._build_target_groups(rows, [group])
                self.assertEqual(set(products), {"3322701X1020"})
                self.assertEqual(products["3322701X1020"]["supply_end_packages"], ["No.12［4袋］"])

    def test_cli_same_name_target_retains_explicit_active_release(self):
        rows, group = self._same_name_targets()
        active = {"product_name": "ゼルフォーム", "maker": "ファイザー", "state": "active",
                  "source_title": "販売中止予定のご案内", "source_url": group["announcement"]["url"],
                  "verified_at": "2026-10-14"}
        products = self._build_target_groups(rows, [group], {"products": {"3322701X1020": active}})
        self.assertEqual(products["3322701X1020"], active)
        self.assertEqual(products["3322701X2027"]["state"], "discontinuation_announced")

    def test_validator_accepts_legacy_expected_and_verified_optional_evidence(self):
        document, rows = self._lifecycle_fixture(
            "123456789012", "沢井製薬", "https://med.sawai.co.jp/end.pdf")
        item = document["products"]["123456789012"]
        item["supply_end_expected"] = "2027-03"
        self.assertEqual(validate(document, rows), [])
        # 旧予定値に元の出典を付けるだけで、本文の再確認日を捏造しない。
        item["supply_end_source_url"] = "https://med.sawai.co.jp/old.pdf"
        self.assertEqual(validate(document, rows), [])
        item.update({k: v for k, v in self._end_annotation().items() if k.startswith("supply_end_")})
        self.assertEqual(validate(document, rows), [])

    def test_validator_rejects_unverified_pointer_without_a_legacy_date(self):
        document, rows = self._lifecycle_fixture(
            "123456789012", "沢井製薬", "https://med.sawai.co.jp/new.pdf")
        document["products"]["123456789012"]["supply_end_source_url"] = "https://med.sawai.co.jp/old.pdf"
        self.assertTrue(any("supply_end_source_url" in error for error in validate(document, rows)))

    def test_validator_rejects_invalid_end_evidence(self):
        document, rows = self._lifecycle_fixture(
            "123456789012", "沢井製薬", "https://med.sawai.co.jp/end.pdf")
        item = document["products"]["123456789012"]
        item.update({k: v for k, v in self._end_annotation().items() if k.startswith("supply_end_")})
        for field, value in (("supply_end_expected", "2027-02-30"),
                             ("announced_at", "2026-13"),
                             ("verified_at", "2026-02-30"),
                             ("supply_end_verified_at", "2026-08-29"),
                             ("supply_end_source_url", "https://evil-sawai.co.jp/end.pdf"),
                             ("supply_end_note", ""),
                             ("supply_end_packages", ["PTP100錠", "PTP100錠"]),
                             ("supply_end_packages", "PTP100錠")):
            with self.subTest(field=field, value=value):
                invalid = copy.deepcopy(document)
                invalid["products"]["123456789012"][field] = value
                self.assertTrue(any(field in error for error in validate(invalid, rows)))

    def _build_end_fixture(self, directory, groups, existing):
        root = Path(__file__).resolve().parents[1]
        base = Path(directory)
        with (base / "drugs.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["商品名", "YJコード", "製造メーカー", "販売メーカー"])
            writer.writeheader()
            writer.writerow({"商品名": "テスト錠１ｍｇ", "YJコード": "123456789012",
                             "製造メーカー": "沢井製薬", "販売メーカー": "沢井製薬"})
        for filename, value in (("announcements.json", {}), ("groups.json", groups),
                                ("existing.json", existing)):
            (base / filename).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([
            sys.executable, str(root / "scripts/build_product_lifecycle.py"),
            "--csv", str(base / "drugs.csv"), "--announcements", str(base / "announcements.json"),
            "--manual-groups", str(base / "groups.json"), "--existing", str(base / "existing.json"),
            "--output", str(base / "output.json"),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-500:])
        return json.loads((base / "output.json").read_text())["products"]["123456789012"]

    def test_daily_build_retains_missing_end_data_and_does_not_refresh_or_promote_state(self):
        document, _ = self._lifecycle_fixture(
            "123456789012", "沢井製薬", "https://med.sawai.co.jp/end.pdf")
        annotation = self._end_annotation("2020-03")
        group = {"products": ["テスト錠１ｍｇ"], "target_products_verified": True,
                 "target_scope": "product", "expected_target_count": 1,
                 "announcement": {"maker": "沢井製薬", "title": "販売中止のお知らせ",
                                  "event_type": "discontinued", "url": annotation["supply_end_source_url"],
                                  **annotation}}
        with tempfile.TemporaryDirectory() as directory:
            item = self._build_end_fixture(directory, [group], document)
            self.assertEqual(item["state"], "discontinuation_announced")
            self.assertEqual(item["verified_at"], "2026-08-28")
            self.assertEqual(item["supply_end_expected"], "2020-03")
            # 原典取得不能で次回入力が空でも、既存の時期・原典・本文確認日を残す。
            rebuilt = self._build_end_fixture(directory, [], {"products": {"123456789012": item}})
            self.assertEqual(rebuilt, item)

    def test_daily_build_notice_switch_preserves_legacy_date_with_old_source(self):
        old_url, new_url = "https://med.sawai.co.jp/old.pdf", "https://med.sawai.co.jp/new.pdf"
        document, rows = self._lifecycle_fixture("123456789012", "沢井製薬", old_url)
        document["products"]["123456789012"]["supply_end_expected"] = "2027-03"
        group = {"products": ["テスト錠１ｍｇ"], "target_products_verified": True,
                 "target_scope": "product", "expected_target_count": 1,
                 "announcement": {"maker": "沢井製薬", "title": "販売中止のお知らせ",
                                  "event_type": "discontinued", "url": new_url}}
        with tempfile.TemporaryDirectory() as directory:
            item = self._build_end_fixture(directory, [group], document)
            self.assertEqual(item["source_url"], new_url)
            self.assertEqual(item["supply_end_expected"], "2027-03")
            self.assertEqual(item["supply_end_source_url"], old_url)
            self.assertNotIn("supply_end_verified_at", item)
            self.assertNotIn("supply_end_note", item)
            self.assertEqual(item["verified_at"], "2026-08-28")
            document["products"]["123456789012"] = item
            self.assertEqual(validate(document, rows), [])
            rebuilt = self._build_end_fixture(directory, [], document)
            self.assertEqual(rebuilt, item)

    def test_verified_tatsumi_and_maruishi_hosts_are_accepted(self):
        cases = (
            ("2190101F1063", "辰巳化学", "https://www.tatsumi-kagaku.com/notice.pdf"),
            ("2614700X1441", "丸石製薬", "https://www.maruishi-pharm.co.jp/notice.pdf"),
        )
        for yj_code, maker, source_url in cases:
            with self.subTest(maker=maker):
                document, rows = self._lifecycle_fixture(yj_code, maker, source_url)
                self.assertEqual(validate(document, rows), [])

    def test_verified_sumitomo_and_iwaki_hosts_are_accepted(self):
        cases = (
            ("1169006F2023", "住友ファーマ", "https://sumitomo-pharma.jp/notice.pdf"),
            ("261970BQ1140", "岩城製薬", "https://www.iwakiseiyaku.co.jp/notice.pdf"),
        )
        for yj_code, maker, source_url in cases:
            with self.subTest(maker=maker):
                document, rows = self._lifecycle_fixture(yj_code, maker, source_url)
                self.assertEqual(validate(document, rows), [])

    def test_alias_and_delimited_seller_match_through_validator(self):
        cases = (
            (
                "1141007C1148",
                "日本ジェネリック",
                "https://www.nihon-generic.co.jp/notice.pdf",
                "長生堂製薬",
                "長生堂製薬",
            ),
            (
                "2260700F1145",
                "日本ケミファ",
                "https://www.nc-medical.com/notice.pdf",
                "東亜薬品",
                "日本ケミファ・沢井製薬",
            ),
        )
        for yj_code, maker, source_url, manufacturer, seller in cases:
            with self.subTest(maker=maker):
                document, rows = self._lifecycle_fixture(
                    yj_code,
                    maker,
                    source_url,
                    manufacturer,
                    seller,
                )
                self.assertEqual(validate(document, rows), [])

    def test_similar_but_unofficial_host_is_rejected(self):
        document, rows = self._lifecycle_fixture(
            "2190101F1063",
            "辰巳化学",
            "https://evil-tatsumi-kagaku.com/notice.pdf",
        )
        self.assertTrue(any("公式ドメインではありません" in error for error in validate(document, rows)))

    @staticmethod
    def _lifecycle_fixture(yj_code, maker, source_url, manufacturer="", seller=""):
        product_name = "テスト錠１ｍｇ"
        document = {
            "schema_version": 1,
            "generated_at": "2026-08-28T09:00:00+09:00",
            "products": {
                yj_code: {
                    "product_name": product_name,
                    "maker": maker,
                    "state": "discontinuation_announced",
                    "source_title": "販売中止のお知らせ",
                    "source_url": source_url,
                    "verified_at": "2026-08-28",
                }
            },
        }
        rows = {
            yj_code: {
                "商品名": product_name,
                "製造メーカー": manufacturer or maker,
                "販売メーカー": seller or maker,
            }
        }
        return document, rows

    def test_known_package_and_seller_route_false_positives_are_absent(self):
        root = Path(__file__).resolve().parents[1]
        lifecycle = json.loads(
            (root / "product_lifecycle.json").read_text(encoding="utf-8")
        )["products"]
        false_positives = {
            "2344002X1349", "2679701Q1055", "6149004F1036",
            "3969007F3035", "3969007F4031", "2190406A1128", "2190406A2124",
            "1124020F2056", "1124020F4059", "1319710Q2108",
            "2649731S1275", "3231001X1108", "2171017F2156",
        }
        self.assertTrue(false_positives.isdisjoint(lifecycle))

    def test_verified_product_wide_handling_titles_are_readded_safely(self):
        root = Path(__file__).resolve().parents[1]
        lifecycle = json.loads(
            (root / "product_lifecycle.json").read_text(encoding="utf-8")
        )["products"]
        for yj_code in {"2614700X1441", "2649731S1348", "2649731S2077"}:
            with self.subTest(yj_code=yj_code):
                self.assertEqual(
                    lifecycle[yj_code]["state"], "discontinuation_announced"
                )

    def test_amaluet_tracks_manufacturer_discontinuation_while_in_supply_csv(self):
        """対象品がCSVにある間だけ、メーカーの販売中止情報を追跡する。"""
        root = Path(__file__).resolve().parents[1]
        with (root / "drugs_app_ready.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = {row["YJコード"]: row for row in csv.DictReader(handle)}
        lifecycle = json.loads(
            (root / "product_lifecycle.json").read_text(encoding="utf-8")
        )["products"]
        expected = {
            "2190101F1098": "サンド", "2190102F1092": "サンド",
            "2190103F1097": "サンド", "2190104F1091": "サンド",
            "2190101F1063": "辰巳化学", "2190102F1068": "辰巳化学",
            "2190103F1062": "辰巳化学", "2190104F1067": "辰巳化学",
        }
        for yj_code, maker in expected.items():
            with self.subTest(yj_code=yj_code):
                # 厚労省一覧から販売終了品が削除された後は、reconcile処理に
                # 合わせてライフサイクル側にも残さない。正常な将来更新を
                # 固定YJの存在チェックで止めないための条件分岐。
                if yj_code not in rows:
                    self.assertNotIn(yj_code, lifecycle)
                    continue
                self.assertEqual(lifecycle[yj_code]["state"], "discontinuation_announced")
                self.assertEqual(lifecycle[yj_code]["maker"], maker)
                self.assertTrue(lifecycle[yj_code]["source_url"].startswith("https://"))

    def test_announcement_date_uses_pdf_url_when_title_has_no_date(self):
        self.assertEqual(
            announcement_date(
                "販売中止のお知らせ",
                "https://example.test/fileloader.php?f=20260730_notice.pdf",
            ),
            "2026-07-30",
        )

    def test_announcement_date_rejects_impossible_date(self):
        self.assertIsNone(
            announcement_date("販売中止のお知らせ", "https://example.test/20261340.pdf")
        )

    def test_announcement_date_does_not_parse_embedded_identifier(self):
        self.assertIsNone(
            announcement_date(
                "販売中止のお知らせ",
                "https://example.test/documentX20260730Y.pdf",
            )
        )

    def test_existing_lifecycle_date_is_backfilled_from_source_url(self):
        products = {
            "123456789012": {
                "source_title": "販売中止のお知らせ",
                "source_url": "https://example.test/f=20260730_notice.pdf",
            }
        }
        self.assertEqual(backfill_announcement_dates(products), 1)
        self.assertEqual(products["123456789012"]["announced_at"], "2026-07-30")

    def test_existing_lifecycle_date_is_not_overwritten(self):
        products = {
            "123456789012": {
                "announced_at": "2025-01-01",
                "source_url": "https://example.test/f=20260730_notice.pdf",
            }
        }
        self.assertEqual(backfill_announcement_dates(products), 0)
        self.assertEqual(products["123456789012"]["announced_at"], "2025-01-01")

    def test_event_history_last_checked_refreshes_the_same_notice_verification(self):
        source_url = "https://example.test/notice.pdf"
        checks = event_last_checked_by_url({
            "テスト錠": [
                {"url": source_url, "last_checked": "2026-08-20"},
                {"url": source_url, "last_checked": "2026-08-25"},
                {"url": source_url, "last_checked": "2026-99-99"},
                {"url": "https://example.test/other.pdf", "last_checked": "2026-08-26"},
            ],
        })
        self.assertEqual(checks[source_url], "2026-08-25")
        self.assertEqual(
            lifecycle_verified_at(
                {"checked": "2026-08-21"},
                {"verified_at": "2026-08-22"},
                checks,
                source_url,
                "2026-08-26",
            ),
            "2026-08-25",
        )

    def test_event_history_for_another_url_does_not_refresh_lifecycle(self):
        self.assertEqual(
            lifecycle_verified_at(
                {},
                {"verified_at": "2026-08-22"},
                {"https://example.test/other.pdf": "2026-08-26"},
                "https://example.test/notice.pdf",
                "2026-08-26",
            ),
            "2026-08-22",
        )

    def test_normal_supply_discontinuation_is_collected(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "drugs.csv"
            with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["商品名", "製造メーカー", "販売メーカー", "供給状況", "代替候補"],
                )
                writer.writeheader()
                writer.writerow({
                    "商品名": "薬Ａ錠５ｍｇ「サワイ」",
                    "製造メーカー": "沢井製薬",
                    "販売メーカー": "沢井製薬",
                    "供給状況": "①通常出荷",
                    "代替候補": "出荷量状況: A．出荷量通常",
                })
            result = match_to_csv(
                [("沢井製薬", "薬A錠5mg「サワイ」 販売中止のお知らせ", "https://example.test/a.pdf")],
                csv_path,
            )
            self.assertIn("薬Ａ錠５ｍｇ「サワイ」", result)

    def test_strength_does_not_match_decimal_substring(self):
        self.assertFalse(
            announcement_covers_product(
                "薬Ａ錠５ｍｇ「Ａ」",
                "薬A錠2.5mg/10mg「A」 販売中止のお知らせ",
            )
        )

    def test_grouped_strength_is_accepted(self):
        self.assertTrue(
            announcement_covers_product(
                "薬Ａ錠５ｍｇ「Ａ」",
                "薬A錠2.5mg/5mg/10mg「A」 販売中止のお知らせ",
            )
        )

    def test_grouped_numbered_formulation_is_accepted(self):
        self.assertTrue(
            announcement_covers_product(
                "アマルエット配合錠２番「ＴＣＫ」",
                "アマルエット配合錠1番/2番/3番/4番「TCK」 販売中止のお知らせ",
            )
        )

    def test_grouped_numbered_formulation_rejects_missing_number(self):
        self.assertFalse(
            announcement_covers_product(
                "アマルエット配合錠４番「ＴＣＫ」",
                "アマルエット配合錠1番/2番/3番「TCK」 販売中止のお知らせ",
            )
        )

    def test_product_named_as_new_release_is_not_the_discontinued_target(self):
        title = (
            "シルビノール錠5mg販売中止及び"
            "ニコランジル錠5mg「サワイ」新発売に関するお知らせ"
        )
        product = "ニコランジル錠５ｍｇ「サワイ」"
        self.assertTrue(announcement_identifies_product_as_new_release(product, title))
        self.assertFalse(announcement_covers_product(product, title))
        self.assertTrue(existing_record_needs_reverification({
            "product_name": product,
            "source_title": title,
        }))

    def test_verified_manual_group_target_accepts_generic_title(self):
        self.assertTrue(announcement_targets_product(
            "薬Ａ錠５ｍｇ「Ａ」",
            {"title": "販売中止品目のご案内", "target_products_verified": True,
             "target_scope": "product"},
        ))

    def test_only_explicitly_verified_group_is_expanded(self):
        document = [
            {
                "products": ["薬Ａ錠", "薬Ｂ錠"],
                "target_products_verified": True,
                "target_scope": "product",
                "expected_target_count": 2,
                "announcement": {
                    "maker": "Ａ製薬", "title": "販売中止",
                    "url": "https://example.test/a", "event_type": "discontinued",
                },
            },
            {
                "products": ["薬Ｃ錠"],
                "announcement": {"maker": "Ａ製薬", "title": "販売中止", "url": "https://example.test/c"},
            },
        ]
        expanded = verified_group_announcements(document)
        self.assertEqual(set(expanded), {"薬Ａ錠", "薬Ｂ錠"})
        self.assertTrue(expanded["薬Ａ錠"]["target_products_verified"])

    def test_verified_supply_group_does_not_replace_lifecycle_group(self):
        document = [
            {
                "products": ["薬Ａ錠"],
                "target_products_verified": True,
                "target_scope": "product",
                "expected_target_count": 1,
                "announcement": {
                    "maker": "Ａ製薬", "title": "薬A錠 販売中止",
                    "url": "https://example.test/end", "event_type": "discontinued",
                },
            },
            {
                "products": ["薬Ａ錠"],
                "target_products_verified": True,
                "target_scope": "product",
                "expected_target_count": 1,
                "announcement": {
                    "maker": "Ａ製薬", "title": "薬A錠 限定出荷",
                    "url": "https://example.test/supply", "event_type": "limited",
                },
            },
        ]
        expanded = verified_group_announcements(document)
        self.assertEqual(expanded["薬Ａ錠"]["event_type"], "discontinued")

    def test_verified_seller_route_scope_blocks_raw_product_wide_inference(self):
        groups = [{
            "products": ["薬Ａ錠"],
            "target_products_verified": True,
            "target_scope": "seller_route",
            "expected_target_count": 1,
            "announcement": {
                "maker": "Ａ製薬", "title": "販売中止", "url": "https://example.test/a",
            },
        }]
        self.assertEqual(
            verified_group_scopes(groups)[("薬A錠", "https://example.test/a")],
            "seller_route",
        )
        self.assertEqual(verified_group_announcements(groups), {})

    def test_unverified_generic_title_is_rejected(self):
        self.assertFalse(announcement_targets_product(
            "薬Ａ錠５ｍｇ「Ａ」",
            {"title": "販売中止品目のご案内"},
        ))

    def test_partial_package_notice_is_not_product_discontinuation(self):
        self.assertIsNotNone(PARTIAL_RE.search("薬A錠 一部包装販売中止のお知らせ"))

    def test_explicit_package_event_is_not_product_discontinuation(self):
        self.assertFalse(is_product_wide_discontinuation({
            "title": "薬A注 販売中止のご案内",
            "event_type": "package_discontinued",
        }))

    def test_explicit_product_event_is_product_discontinuation(self):
        self.assertTrue(is_product_wide_discontinuation({
            "title": "薬A注 販売中止のご案内",
            "event_type": "discontinued",
        }))

    def test_legacy_handling_only_record_is_not_carried_forward(self):
        self.assertTrue(existing_record_needs_reverification({
            "source_title": "薬A錠 取り扱い中止のご案内",
        }))

    def test_legacy_product_discontinuation_can_be_carried_forward(self):
        self.assertFalse(existing_record_needs_reverification({
            "source_title": "薬A錠 製造販売中止のご案内",
        }))


if __name__ == "__main__":
    unittest.main()
