"""公的資料で確認した承認承継を、品目とメーカーの取り違えなく維持する。"""
import csv
import sys
import unittest
import tempfile
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

class ManufacturerTransfers(unittest.TestCase):
    def assert_field_if_present(self, rows, code, field, expected, *, unequal=False):
        # 原表から削除された品目は日次CSVから除かれる。残存品目の検査は続ける。
        if code not in rows:
            return
        if unequal:
            self.assertNotEqual(rows[code][field], expected, code)
        else:
            self.assertEqual(rows[code][field], expected, code)

    def test_nine_verified_products_keep_the_new_manufacturer(self):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        # PMDA電子添文：ユリス・トピロリックは持田製薬、ラジカット3剤形は塩野義製薬。
        for code in ('3949005F1022','3949005F2029','3949005F3025',
                     '3949004F1036','3949004F2032','3949004F3039'):
            self.assert_field_if_present(rows, code, '製造メーカー', '持田製薬')
        for code in ('1190032S1021','1190401A1023','1190401G1026'):
            self.assert_field_if_present(rows, code, '製造メーカー', '塩野義製薬')
        # 承継前の会社を現在の販売元と再び表示しない。確認済み情報の追加は許容する。
        for code in ('3949004F1036','3949004F2032','3949004F3039'):
            self.assert_field_if_present(rows, code, '販売メーカー', '富士薬品', unequal=True)
        for code in ('1190032S1021','1190401A1023','1190401G1026'):
            self.assert_field_if_present(rows, code, '販売メーカー', '田辺ファーマ', unequal=True)

    def test_ohara_transfer_for_permax_and_apokyn(self):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        # 2026年7月1日承継。旧会社の包装も当面流通する旨は原文参照。
        for code in ('1169008F1026', '1169008F2022', '1169400G1028'):
            self.assert_field_if_present(rows, code, '製造メーカー', '大原薬品工業')
            self.assert_field_if_present(rows, code, '販売メーカー', '大原薬品工業')

    def test_verified_manufacturer_renames_and_transfers(self):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        for code in ('2646713N1182', '2646730M1075', '2646730Q1050'):
            self.assert_field_if_present(rows, code, '製造メーカー', 'ＭＡＥ')
        for code in ('2190005F1284', '2190005F2183', '1339005F1482', '1339005F2250'):
            self.assert_field_if_present(rows, code, '製造メーカー', '日医工岐阜工場')
        self.assert_field_if_present(rows, '4490038F1020', '製造メーカー', 'キエジ・ファーマ・ジャパン')

    def test_takasago_and_emec_manufacturer(self):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        for code in ('5100081A1080', '5100081X1082'):
            self.assert_field_if_present(rows, code, '製造メーカー', '高砂薬業')
            self.assert_field_if_present(rows, code, '販売メーカー', '砂薬業', unequal=True)
        self.assert_field_if_present(rows, '1149019F1480', '製造メーカー', '日医工岐阜工場')

    def test_individual_liquid_gas_manufacturers(self):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        self.assert_field_if_present(rows, '799070BX1042', '製造メーカー', '日本エア・リキード合同会社')
        self.assert_field_if_present(rows, '799070CX1020', '製造メーカー', 'エア・ウォーター')
        for code in ('799070BX1042', '799070CX1020'):
            self.assert_field_if_present(rows, code, '販売メーカー', '')

    def test_generic_products_use_yj_specific_manufacturer(self):
        # 厚労省原表とPMDA添文／山善製薬公表資料を、YJコードごとに照合。
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        expected = {'2344004X1267': '山善製薬', '7131400A9026': '日新製薬',
                    '7131400H1023': '日新製薬', '7131400A2110': '日新製薬'}
        for code, manufacturer in expected.items():
            self.assert_field_if_present(rows, code, '製造メーカー', manufacturer)
            # 同名品目をまとめた旧販売元リストは、対象品目に紐づく根拠がない。
            self.assert_field_if_present(rows, code, '販売メーカー', '')

    def test_yj_specific_manufacturer_sources_20261110(self):
        # PMDA品目別情報とサノフィの承継案内をYJコードごとに確認。
        # https://www.pmda.go.jp/PmdaSearch/rdDetail/iyaku/6419400D1037_2?user=1
        # https://pro.campus.sanofi/jp/products/benan
        # https://www.pmda.go.jp/PmdaSearch/rdDetail/iyaku/2710806U1030_3?user=1
        # https://www.pmda.go.jp/PmdaSearch/rdDetail/iyaku/7112004X1079_1?user=1
        # https://www.pmda.go.jp/PmdaSearch/rdDetail/iyaku/7122702X1065_1?user=1
        # https://www.pmda.go.jp/PmdaSearch/rdDetail/iyaku/7121706X1023_1?user=1
        # https://www.pmda.go.jp/PmdaSearch/rdDetail/iyaku/7121704X1300_1?user=1
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        expected = {
            '6419400D1037': ('Medical Parkland', 'Medical Parkland'),
            '2710806U1030': ('白水貿易', ''),
            '7112004X1079': ('小堺製薬', ''),
            '7122702X1065': ('小堺製薬', ''),
            '7121706X1023': ('小堺製薬', ''),
            '7121704X1300': ('丸石製薬', ''),
        }
        for code, (manufacturer, sales) in expected.items():
            self.assert_field_if_present(rows, code, '製造メーカー', manufacturer)
            self.assert_field_if_present(rows, code, '販売メーカー', sales)

    def test_perisate_duplicated_vendor_is_not_reintroduced(self):
        # メーカー案内ではN/NL両製品群の販売元はジェイ・エム・エス。
        # https://medical.jms.cc/pdf/customer_information_372.pdf
        # https://medical.jms.cc/pdf/customer_information_301.pdf
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        prefixes = ('3420415', '3420416', '3420426', '3420427')
        for row in rows:
            if row['YJコード'].startswith(prefixes) and row['商品名'].startswith('ペリセート'):
                self.assertEqual(row['製造メーカー'], 'ジェイ・エム・エス')
                self.assertEqual(row['販売メーカー'], 'ジェイ・エム・エス')

    def test_syrup_sugar_manufacturers_are_yj_specific(self):
        # PMDAのYJ別添付文書、厚労省原表、吉田製薬の製品情報で確認。
        # https://www.pmda.go.jp/PmdaSearch/iyakuDetail/730119_7142001X1171_1_10
        # https://www.pmda.go.jp/PmdaSearch/iyakuDetail/510022_7142001X1120_1_09
        # https://www.yamazen-pharm.co.jp/?products=単シロップ
        # https://www.yoshida-pharm.co.jp/files/interview/1034.pdf
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        for code, maker, sales in (
            ('7142001X1171', '丸石製薬', ''), ('7142001X1120', '中北薬品', ''),
            ('7142001X1180', '山善製薬', ''), ('7149002X1037', '小堺製薬', '吉田製薬'),
        ):
            self.assert_field_if_present(rows, code, '製造メーカー', maker)
            self.assert_field_if_present(rows, code, '販売メーカー', sales)

    def test_reviewed_generic_manufacturers_20261110(self):
        # YJ別PMDA添文・厚労省原表・中北薬品の製品情報を確認。
        # https://www.pmda.go.jp/PmdaSearch/iyakuDetail/270108_2356001X1051_1_04
        # https://www.nakakita.co.jp/product/iryokankei/pro/021793-2-2.html
        # https://www.pmda.go.jp/PmdaSearch/iyakuDetail/270108_2619705X1068_1_06
        # https://www.mhlw.go.jp/topics/2024/04/dl/tp20250319-01_03.pdf
        # https://www.pmda.go.jp/PmdaSearch/rdDetail/iyaku/2661702X1238_1?user=1
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        for code, maker, sales in (
            ('2356001X1051', '小堺製薬', ''), ('2614700X1093', '小堺製薬', '中北薬品'),
            ('2619705X1068', '小堺製薬', ''), ('2612703X1254', '山善製薬', ''),
            ('2612700X1250', '山善製薬', ''), ('2661702X1238', '山善製薬', ''),
        ):
            self.assert_field_if_present(rows, code, '製造メーカー', maker)
            self.assert_field_if_present(rows, code, '販売メーカー', sales)

    def test_honey_and_three_generic_manufacturers(self):
        # 各YJについて、厚労省原表・PMDA・メーカーの原文を確認。
        # https://www.pmda.go.jp/PmdaSearch/rdDetail/iyaku/7149003X1333_1?user=1
        # https://www.maruishi-pharm.co.jp/medical/media/keikasotikikan_entyou_20260317.pdf
        # https://www.mhlw.go.jp/topics/2017/06/dl/tp20170616-01_1.pdf
        # https://www.nikko-pharm.co.jp/medicine/
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        for code, maker, sales in (
            ('7149003X1333', '秋田屋本店', '丸石製薬'),
            ('7112004X1206', '山善製薬', ''),
            ('7139700X1039', '日興製薬', ''),
            ('7131700X1022', '共栄製薬', ''),
        ):
            self.assert_field_if_present(rows, code, '製造メーカー', maker)
            self.assert_field_if_present(rows, code, '販売メーカー', sales)

    def test_nikp_transfer_keeps_old_and_new_yj_distinct(self):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        if '7131001X1453' not in rows and '7131001X1461' not in rows:
            self.skipTest('原表から対象コードが削除されたため、この確認を適用しない')
        self.assert_field_if_present(rows, '7131001X1453', '商品名', '精製水「ＮｉｋＰ」')
        self.assert_field_if_present(rows, '7131001X1461', '商品名', '精製水「ヤクハン」')
        self.assert_field_if_present(rows, '7131001X1453', '製造メーカー', 'ヤクハン製薬')
        self.assert_field_if_present(rows, '7131001X1453', '販売メーカー', '岩城製薬')

    def test_absent_row_does_not_block_other_rows(self):
        rows = {'present': {'製造メーカー': '正しい会社'}}
        self.assert_field_if_present(rows, 'removed', '製造メーカー', '旧会社')
        with self.assertRaises(AssertionError):
            self.assert_field_if_present(rows, 'present', '製造メーカー', '別会社')

    def test_old_nikp_removal_still_checks_remaining_successor(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'drugs_app_ready.csv'
            with path.open('w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=['YJコード', '商品名'])
                writer.writeheader()
                writer.writerow({'YJコード': '7131001X1461', '商品名': '別の製品'})
            with mock.patch.object(sys.modules[__name__], 'ROOT', Path(temp)):
                with self.assertRaises(AssertionError):
                    self.test_nikp_transfer_keeps_old_and_new_yj_distinct()

if __name__ == '__main__':
    unittest.main()
