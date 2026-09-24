import shutil
import tempfile
import unittest
from pathlib import Path

from check_web_client_csv import check

ROOT = Path(__file__).resolve().parents[1]
MISSING_VOLUME_ACCEPTED = '&& metadata[2].trim() !== "－"'


@unittest.skipUnless(shutil.which("node"), "Node.jsが必要")
class WebClientCsvGuardTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

    def write_html(self, html):
        path = Path(self.tempdir.name) / "index.html"
        path.write_text(html, encoding="utf-8")
        return path

    def test_published_web_accepts_current_csv(self):
        error, rows = check(ROOT / "index.html", ROOT / "drugs_app_ready.csv")
        self.assertIsNone(error)
        self.assertGreater(rows, 10000)

    def test_detects_client_that_rejects_new_data_format(self):
        # 2026年9月16〜19日の障害: データは出荷量「－」を許可し、Webは拒否していた。
        self.assertIn(MISSING_VOLUME_ACCEPTED, self.html)
        old_client = self.write_html(self.html.replace(MISSING_VOLUME_ACCEPTED, ""))
        error, _ = check(old_client, ROOT / "drugs_app_ready.csv")
        self.assertIn("出荷量区分", error or "")

    def test_detects_status_the_client_cannot_map(self):
        client = self.write_html(self.html.replace('if(value === "5供給停止" || value === "供給停止") return "stopped";', ""))
        error, _ = check(client, ROOT / "drugs_app_ready.csv")
        self.assertIn("未対応の供給区分", error or "")

    def test_missing_contract_markers_fail_closed(self):
        client = self.write_html(self.html.replace("// ===== End public CSV contract =====", ""))
        with self.assertRaises(ValueError):
            check(client, ROOT / "drugs_app_ready.csv")


if __name__ == "__main__":
    unittest.main()
