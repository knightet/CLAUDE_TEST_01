"""카드 데이터 검사: python -m unittest tests.test_data -v"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.card_schema import CARD_DIR, normalize, load_all

PDFS = {p.name for p in (ROOT / "data" / "pdf").glob("*.pdf")}


class CardData(unittest.TestCase):
    def test_schema_has_no_errors(self):
        for p in sorted(CARD_DIR.glob("*.json")):
            with self.subTest(p.name):
                _, errors = normalize(json.loads(p.read_text(encoding="utf-8")))
                self.assertEqual(errors, [])

    def test_every_benefit_points_to_a_real_pdf_page(self):
        for c in load_all().values():
            for b in c["benefits"]:
                with self.subTest(f"{c['card_id']}.{b['id']}"):
                    self.assertIn(b["source"]["file"], PDFS)
                    self.assertIsInstance(b["source"]["page"], int)

    def test_card_types(self):
        types = {cid: c["card_type"] for cid, c in load_all().items()}
        self.assertEqual(sum(t == "체크" for t in types.values()), 3)
        self.assertEqual(sum(t == "신용" for t in types.values()), 6)


if __name__ == "__main__":
    unittest.main()
