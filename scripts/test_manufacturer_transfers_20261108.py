"""公的資料で確認した承認承継を、品目とメーカーの取り違えなく維持する。"""
import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

class ManufacturerTransfers(unittest.TestCase):
    def test_nine_verified_products_keep_the_new_manufacturer(self):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        # PMDA電子添文：ユリス・トピロリックは持田製薬、ラジカット3剤形は塩野義製薬。
        for code in ('3949005F1022','3949005F2029','3949005F3025',
                     '3949004F1036','3949004F2032','3949004F3039'):
            self.assertEqual(rows[code]['製造メーカー'], '持田製薬', code)
        for code in ('1190032S1021','1190401A1023','1190401G1026'):
            self.assertEqual(rows[code]['製造メーカー'], '塩野義製薬', code)
        # 承継前の会社を現在の販売元と再び表示しない。確認済み情報の追加は許容する。
        for code in ('3949004F1036','3949004F2032','3949004F3039'):
            self.assertNotEqual(rows[code]['販売メーカー'], '富士薬品', code)
        for code in ('1190032S1021','1190401A1023','1190401G1026'):
            self.assertNotEqual(rows[code]['販売メーカー'], '田辺ファーマ', code)

    def test_ohara_transfer_for_permax_and_apokyn(self):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        # 2026年7月1日承継。旧会社の包装も当面流通する旨は原文参照。
        for code in ('1169008F1026', '1169008F2022', '1169400G1028'):
            self.assertEqual(rows[code]['製造メーカー'], '大原薬品工業', code)
            self.assertEqual(rows[code]['販売メーカー'], '大原薬品工業', code)

    def test_verified_manufacturer_renames_and_transfers(self):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        for code in ('2646713N1182', '2646730M1075', '2646730Q1050'):
            self.assertEqual(rows[code]['製造メーカー'], 'ＭＡＥ', code)
        for code in ('2190005F1284', '2190005F2183', '1339005F1482', '1339005F2250'):
            self.assertEqual(rows[code]['製造メーカー'], '日医工岐阜工場', code)
        self.assertEqual(rows['4490038F1020']['製造メーカー'], 'キエジ・ファーマ・ジャパン')

    def test_takasago_and_emec_manufacturer(self):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        for code in ('5100081A1080', '5100081X1082'):
            self.assertEqual(rows[code]['製造メーカー'], '高砂薬業', code)
            self.assertNotEqual(rows[code]['販売メーカー'], '砂薬業', code)
        self.assertEqual(rows['1149019F1480']['製造メーカー'], '日医工岐阜工場')

    def test_individual_liquid_gas_manufacturers(self):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        self.assertEqual(rows['799070BX1042']['製造メーカー'], '日本エア・リキード合同会社')
        self.assertEqual(rows['799070CX1020']['製造メーカー'], 'エア・ウォーター')
        for code in ('799070BX1042', '799070CX1020'):
            self.assertEqual(rows[code]['販売メーカー'], '', code)

if __name__ == '__main__':
    unittest.main()
