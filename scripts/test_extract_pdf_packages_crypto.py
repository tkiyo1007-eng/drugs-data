"""Real AES support, using generated ASCII fixtures and mocked HTTP only."""
import contextlib
from datetime import date
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

try:
    import pypdf
except ModuleNotFoundError as error:
    if error.name != "pypdf":
        raise
    pypdf = None

try:
    from scripts import extract_pdf_packages as packages
except ImportError:
    import extract_pdf_packages as packages


def ascii_package_pdf():
    """Build one plain page from known PDF objects; no manufacturer file or font."""
    stream = b"BT /F1 12 Tf 20 40 Td (PTP100g) Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(body))
        body.extend(str(number).encode() + b" 0 obj\n" + value + b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode())
    body.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(body)


def aes_package_pdf(user_password):
    writer = pypdf.PdfWriter()
    writer.add_page(pypdf.PdfReader(io.BytesIO(ascii_package_pdf())).pages[0])
    writer.encrypt(user_password=user_password, owner_password="fixture-owner-only", algorithm="AES-256")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class PdfResponse(io.BytesIO):
    status = 200
    headers = {"Content-Type": "application/pdf"}


@unittest.skipIf(pypdf is None, "pypdf is not installed; real AES integration tests require the PDF dependency")
class ExtractPdfPackagesCryptoTests(unittest.TestCase):
    def extract(self, body):
        transport = mock.Mock(side_effect=lambda request, timeout: PdfResponse(body))
        with mock.patch.object(packages.urllib.request, "build_opener", return_value=types.SimpleNamespace(open=transport)):
            result = packages.extract_from_pdf("https://maker.example/generated-aes-fixture.pdf")
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(transport.call_args.kwargs, {"timeout": 40})
        return result

    def test_empty_user_password_aes_extracts_the_same_package_as_plain_pdf(self):
        plain = self.extract(ascii_package_pdf())
        encrypted = aes_package_pdf("")
        self.assertTrue(pypdf.PdfReader(io.BytesIO(encrypted)).is_encrypted)
        self.assertEqual(plain, [{"pkg": "PTP100g", "until": ""}])
        self.assertEqual(self.extract(encrypted), plain)

    def test_nonempty_user_password_remains_an_extraction_failure(self):
        encrypted = aes_package_pdf("fixture-user-secret")
        with self.assertRaises(pypdf.errors.FileNotDecryptedError):
            self.extract(encrypted)

    def test_password_failure_is_not_cached_and_preserves_previous_packages(self):
        encrypted = aes_package_pdf("fixture-user-secret")
        previous = {"https://maker.example/old.pdf": [{"pkg": "PTP200g", "until": ""}]}
        failed_url = "https://maker.example/password-protected.pdf"
        announcements = {"既存": {"url": "https://maker.example/old.pdf"}, "要password": {"url": failed_url}}
        transport = mock.Mock(side_effect=lambda request, timeout: PdfResponse(encrypted))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ann, out, cache = root/"ann.json", root/"out.json", root/"cache.json"
            ann.write_text(json.dumps(announcements), encoding="utf-8")
            cache.write_text(json.dumps(previous), encoding="utf-8")
            error_log = io.StringIO()
            with mock.patch.object(sys, "argv", ["extract_pdf_packages", str(ann), str(out), "60"]), \
                    mock.patch.object(packages, "CACHE_FILE", str(cache)), \
                    mock.patch.object(packages.urllib.request, "build_opener", return_value=types.SimpleNamespace(open=transport)), \
                    contextlib.redirect_stderr(error_log):
                packages.main(day=date(2026, 10, 17))
            self.assertEqual(json.loads(cache.read_text()), previous)
            self.assertEqual(json.loads(out.read_text()), {"既存": previous["https://maker.example/old.pdf"]})
            self.assertNotIn(failed_url, json.loads(cache.read_text()))
            self.assertEqual(transport.call_count, 1)
            self.assertEqual(transport.call_args.args[0].full_url, failed_url)
            self.assertIn("取得試行: 1URL / 成功: 0URL / 失敗: 1URL / 上限待ち: 0URL", error_log.getvalue())
            self.assertNotIn("fixture-user-secret", error_log.getvalue())


if __name__ == "__main__":
    unittest.main()
