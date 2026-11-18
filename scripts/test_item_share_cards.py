import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import item_share_cards as cards


ROOT = Path(__file__).resolve().parents[1]


class ItemShareCardsTest(unittest.TestCase):
    def test_cache_changes_with_the_public_record_and_never_advertises_a_stale_card(self):
        key = cards.KEYS[0]
        row = {"商品名": "モビコール配合内用剤ＬＤ", "販売メーカー": "EAファーマ", "供給状況": "②限定出荷（自社の事情）"}
        targets = {key: (row, "limited"), "other": (row, "limited")}
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            shutil.copyfile(ROOT / "icon-192.png", site / "icon-192.png")
            with patch.object(cards, "render_card",
                              side_effect=lambda _, dest: shutil.copyfile(ROOT / "items/share-cards" / f"{key}.png", dest)) as render:
                first = cards.prepare(site, targets, "2026-11-16")
                self.assertEqual(set(first), {key})
                self.assertIn("2026年11月16日", first[key][1])
                self.assertEqual(cards.prepare(site, targets, "2026-11-16"), first)
                render.assert_called_once()
                newer = cards.prepare(site, targets, "2026-11-17")
                self.assertNotEqual(newer[key][0], first[key][0])
                row["供給状況"] = "①通常出荷"
                targets[key] = (row, "ok")
                normal = cards.prepare(site, targets, "2026-11-17")
                self.assertNotEqual(normal[key][0], newer[key][0])
                self.assertIn("①通常出荷", normal[key][1])
                self.assertIn('class="status ok"', render.call_args.args[0])
                render.side_effect = OSError("test")
                self.assertEqual(cards.prepare(site, targets, "2026-11-18"), {})
                self.assertEqual(cards.prepare(site, targets, ""), {})
