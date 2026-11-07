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
