"""HTTPの推定encodingに依存せず、原典byteと既存の日付検査を守る。"""
import datetime as dt
from types import SimpleNamespace
import unittest

from mhlw_supply_source import decode_supply_page, supply_source_from_page


class MhlwSourceDecodingTests(unittest.TestCase):
    TODAY = dt.date(2026, 10, 15)
    URL = "https://www.mhlw.go.jp/content/10800000/001758803.xlsx"
    LABEL = "医療用医薬品供給状況（令和８年10月13日現在）"

    def page(self, label=None, href=None):
        return ('<!doctype html><html><head><meta charset="UTF-8"></head>'
                f'<body><a href="{href or self.URL}">{label or self.LABEL}</a></body></html>')

    def source(self, body):
        return supply_source_from_page(decode_supply_page(body), self.TODAY)

    def test_utf8_bytes_keep_the_anchor_date_and_exact_text(self):
        page = self.page()
        self.assertEqual(decode_supply_page(page.encode("utf-8")), page)
        self.assertEqual(self.source(page.encode("utf-8")), {
            "file": "001758803.xlsx", "url": self.URL, "excel_date": "2026-10-13"})

    def test_utf8_bom_is_accepted_without_becoming_text(self):
        page = self.page()
        body = page.encode("utf-8-sig")
        self.assertTrue(body.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(decode_supply_page(body), page)
        self.assertEqual(self.source(body)["excel_date"], "2026-10-13")

    def test_mojibake_text_does_not_override_valid_response_bytes(self):
        body = self.page().encode("utf-8")
        # charset欠落時のRequests 2.34.2実Response対照は独立auditへ保存済み。
        # ここではその公開境界を標準libだけで固定し、requestsをunit依存にしない。
        response = SimpleNamespace(
            content=body, text=body.decode("ISO-8859-1"),
            encoding="ISO-8859-1", headers={"Content-Type": "text/html"})
        self.assertNotEqual(response.text, self.page())
        with self.assertRaisesRegex(ValueError, "不明"):
            supply_source_from_page(response.text, self.TODAY)
        self.assertEqual(self.source(response.content)["excel_date"], "2026-10-13")

    def test_invalid_utf8_is_rejected_even_outside_the_supply_anchor(self):
        valid = self.page().encode("utf-8")
        # bodyの別箇所に破損があっても置換decodeで原典確認済みにしない。
        for body in (b"\xff" + valid, valid + b"\xe3\x81", valid + b"\xc0\xaf",
                     valid.replace("令和".encode(), b"\xff", 1)):
            with self.subTest(body_suffix=body[-12:]), self.assertRaises(ValueError):
                decode_supply_page(body)

    def test_non_utf8_japanese_is_not_guessed_or_replaced(self):
        body = self.page().encode("cp932")
        with self.assertRaises(ValueError):
            decode_supply_page(body)

    def test_empty_and_non_bytes_inputs_are_rejected(self):
        for body in (b"", None, "", self.page(), 0, bytearray(self.page().encode()),
                     memoryview(self.page().encode())):
            with self.subTest(input_type=type(body).__name__), self.assertRaises(ValueError):
                decode_supply_page(body)

    def test_decode_success_does_not_infer_a_missing_anchor_date(self):
        page = ('<p>令和８年10月13日現在</p>'
                + self.page(label="医療用医薬品供給状況"))
        with self.assertRaisesRegex(ValueError, "不明"):
            self.source(page.encode())

    def test_decode_success_does_not_accept_a_future_date(self):
        page = self.page(label="医療用医薬品供給状況（令和８年10月16日現在）")
        with self.assertRaisesRegex(ValueError, "未来"):
            self.source(page.encode())

    def test_decode_success_does_not_choose_between_distinct_workbooks(self):
        page = self.page() + self.page(href=self.URL.replace("001758803", "001758804"))
        with self.assertRaisesRegex(ValueError, "一意"):
            self.source(page.encode())

    def test_decode_success_does_not_relax_the_official_excel_url(self):
        for href in (self.URL.replace("https:", "http:"),
                     self.URL.replace("www.mhlw.go.jp", "example.com"),
                     self.URL + "?file=other"):
            with self.subTest(href=href), self.assertRaises(ValueError):
                self.source(self.page(href=href).encode())


if __name__ == "__main__":
    unittest.main()
