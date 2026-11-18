import unittest,json,csv,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ReasonOnlyTests(unittest.TestCase):
 def test_exact_scopes_without_alternative_or_supply_override(self):
  notices=json.loads((ROOT/'manufacturer_notices.json').read_text())['notices']
  for nid,yj,pack,code in [('maruishi-kcl-reason-202610','3229002S1026','500mL\uff08\u74f6\uff09','211304935'),('nipro-ascorbic1g-reason-202611','3140400A5072','5mL\u00d750\u7ba1','190040022')]:
   matches=[n for n in notices if n['id']==nid];self.assertEqual(len(matches),1);n=matches[0]
   self.assertEqual(n['alternatives'],[]);self.assertEqual(len(n['targets']),1);t=n['targets'][0]
   self.assertEqual(t['yj_code'],yj);self.assertEqual(t['scope'],'package');self.assertEqual(t['packages'],[{'package':pack,'unified_product_code':code}])
   self.assertEqual(n['collection_mode'],'manual');self.assertRegex(n['announced_at'],r'^2026-\d{2}$');self.assertGreaterEqual(len(n['cautions']),4)
   self.assertNotIn('resumption',n);self.assertNotIn('maker_supply_status',n)
 def test_static_details_preserve_official_status_and_source(self):
  for yj,url in [('3229002S1026','K.C.L.ELIXIR_syukkateisi_20261016.pdf'),('3140400A5072','068Q800001Uj4aLIAR')]:
   page = (ROOT / 'items' / f'{yj}.html').read_text()
   self.assertIn(url, page)
   with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
    status = next(r['供給状況'] for r in csv.DictReader(f) if r['YJコード'] == yj)
   if '限定出荷' in status:
    self.assertIn(f'<strong class="status limited">{status}</strong>', page)
   else:
    self.assertNotIn('<strong class="status limited">', page)
    self.assertIn(f'<td>{status}</td>', page)
