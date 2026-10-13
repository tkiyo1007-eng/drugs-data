import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest import mock


class VersionSourceMetadataTests(unittest.TestCase):
    def build_from_real_workflow(self, source):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/update_drugs.yml').read_text()
        step = workflow.split('name: version.json 更新', 1)[1].split('python3 - <<\'EOF\'\n', 1)[1].split('\n          EOF', 1)[0]
        program = textwrap.dedent(step)
        class FixedClock(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 14, 5, 14, tzinfo=tz)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            if source is not None:
                (target / 'mhlw_source.json').write_text(json.dumps(source))
            previous = Path.cwd()
            try:
                os.chdir(target)
                with mock.patch.object(dt, 'datetime', FixedClock), contextlib.redirect_stdout(io.StringIO()) as output:
                    exec(compile(program, '<actual-version-workflow>', 'exec'), {})
                return json.loads((target / 'version.json').read_text()), output.getvalue()
            finally:
                os.chdir(previous)

    def test_real_version_step_preserves_import_and_reads_recorded_source(self):
        source = {'file': '261008iyakuhinkyoukyu.xlsx',
                  'url': 'https://www.mhlw.go.jp/content/10800000/261008iyakuhinkyoukyu.xlsx',
                  'excel_date': '2026-10-08'}
        document, output = self.build_from_real_workflow(source)
        self.assertEqual(document['version'], 202610140514)
        self.assertEqual(document['note'], '2026年10月14日厚労省データ反映')
        self.assertEqual(document['csv_url'], 'https://raw.githubusercontent.com/tkiyo1007-eng/drugs-data/main/drugs_app_ready.csv')
        self.assertEqual(document['mhlw_excel_date'], '2026-10-08')
        self.assertNotIn('::warning::', output)

    def test_absent_or_invalid_metadata_omits_optional_field_and_warns(self):
        for source in [None, {}, {'excel_date': '2026-10-14'}, {'excel_date': '2026-10-15'}]:
            with self.subTest(source=source):
                document, output = self.build_from_real_workflow(source)
                self.assertEqual(document['version'], 202610140514)
                self.assertNotIn('mhlw_excel_date', document)
                self.assertIn('取込日から補完しません', output)


if __name__ == '__main__':
    unittest.main()
