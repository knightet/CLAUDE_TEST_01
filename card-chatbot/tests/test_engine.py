"""계산 평가: 설명서를 보고 사람이 정한 정답과 엔진 결과가 숫자로 정확히 같아야 해요.
실행: python -m unittest tests.test_engine -v
"""
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.engine import CARDS, Profile, Tx, add_usage, evaluate_card, rank

CASES = json.loads((ROOT / "tests" / "engine_cases.json").read_text(encoding="utf-8"))
RANK = json.loads((ROOT / "tests" / "rank_cases.json").read_text(encoding="utf-8"))


def profile(d: dict) -> Profile:
    d = dict(d)
    if "today" in d:
        d["today"] = dt.date.fromisoformat(d["today"])
    return Profile(**d)


class EngineCases(unittest.TestCase):
    def test_cases(self):
        for c in CASES:
            with self.subTest(c["id"], why=c["why"]):
                r = evaluate_card(CARDS[c["card"]], Tx(**c["tx"]), profile(c["profile"]))
                self.assertEqual(r.value, c["expect"], [(s.label, s.detail) for b in r.applied + r.considered for s in b.steps])

    def test_rank_cases(self):
        """비슷한 카드 순위: 화면 기본 상태(9장 보유, 최고 구간)에서 상위 3개"""
        from src.chatbot import top_results
        profiles = {cid: profile(p) for cid, p in RANK["profile"].items()}
        for c in RANK["cases"]:
            with self.subTest(c["id"], why=c["why"]):
                top = top_results(rank(Tx(**c["tx"]), profiles))
                got = [(r.card_id, r.value) for r in top]
                for (cid, value), (gid, gvalue) in zip(c["top"], got):
                    self.assertEqual(gvalue, value, got)
                    if cid:
                        self.assertEqual(gid, cid, got)

    def test_every_result_has_steps_and_source(self):
        r = evaluate_card(CARDS["kb_nori_check"], Tx("스벅", 15000), Profile(prev_month=400000))
        self.assertTrue(r.applied[0].steps)
        self.assertEqual(r.applied[0].source, "kb_nori_check.pdf 1p")

    def test_suggestion_min_payment(self):
        r = evaluate_card(CARDS["kb_nori_check"], Tx("스벅", 9000), Profile(prev_month=400000))
        self.assertEqual(r.suggestions[0]["value"], 2000)
        self.assertIn("1,000원 더 결제", r.suggestions[0]["text"])

    def test_suggestion_pay_method(self):
        r = evaluate_card(CARDS["kb_kpass"], Tx("편의점", 12000), Profile(prev_month=350000))
        self.assertEqual(r.value, 600)
        self.assertTrue(any("KB Pay" in s["text"] and s["value"] == 1200 for s in r.suggestions))

    def test_rank_similar_cards(self):
        profiles = {"kb_nori_check": Profile(prev_month=400000), "nh_allbareun_flex": Profile(prev_month=300000),
                    "shinhan_heyyoung_check": Profile(prev_month=600000), "kb_kpass": Profile(prev_month=350000),
                    "samsung_and_mileage_platinum_skypass": Profile(options={"mileage_type": "국내형"})}
        r = rank(Tx("스벅", 15000), profiles)
        self.assertEqual([x.card_id for x in r[:3]], ["nh_allbareun_flex", "kb_nori_check", "shinhan_heyyoung_check"])
        self.assertEqual(r[-1].unit, "마일")


class UsageRecording(unittest.TestCase):
    """'이 카드를 썼어요'로 사용량을 더하면 다음 계산에서 남은 한도·횟수만큼만 나와야 해요"""

    def use(self, card_id, tx, p, times):
        values = []
        for _ in range(times):
            r = evaluate_card(CARDS[card_id], tx, p, suggest=False)
            values.append(r.value)
            p = add_usage(p, r.usage)
        return values, p

    def test_shared_limit_runs_out(self):
        # 노리 T2(전월 40만) 통합한도 월 2만원, 스벅 15,000원 → 3,000원씩 (1p, 2p)
        values, p = self.use("kb_nori_check", Tx("스벅", 15000), Profile(prev_month=400000), 8)
        self.assertEqual(values, [3000] * 6 + [2000, 0])
        self.assertEqual(p.used_groups["integrated"], 20000)
        self.assertEqual(p.used_benefits["starbucks"]["count"], 7)

    def test_daily_and_monthly_count(self):
        # NH 스타벅스 50%: 일 1회 / 월 2회 (2p)
        values, p = self.use("nh_allbareun_flex", Tx("스벅", 15000), Profile(prev_month=300000), 2)
        self.assertEqual(values, [5000, 0])
        p.used_benefits["starbucks"]["count_today"] = 0          # 다음 날 (일 횟수는 화면이 날짜가 바뀌면 0으로)
        p.used_groups["coffee"] = 0                              # 커피 한도는 일 단위
        values, p = self.use("nh_allbareun_flex", Tx("스벅", 15000), p, 1)
        self.assertEqual(values, [5000])
        p.used_benefits["starbucks"]["count_today"] = 0
        p.used_groups["coffee"] = 0
        values, _ = self.use("nh_allbareun_flex", Tx("스벅", 15000), p, 1)
        self.assertEqual(values, [0])                            # 월 2회 소진

    def test_usage_matches_benefit(self):
        # 한도에 쌓이는 값은 받은 혜택보다 클 수 없어요 (할인액·마일리지 한도)
        p = {"samsung_and_mileage_platinum_skypass": Profile(options={"mileage_type": "국내형"}, used_groups={"special": 2000})}
        for cid, tx in [("kb_nori_check", Tx("스벅", 25000)), ("kb_goodday", Tx("주유소", 80000, liters=50)),
                        ("samsung_and_mileage_platinum_skypass", Tx("GS25", 10000))]:
            r = evaluate_card(CARDS[cid], tx, p.get(cid, Profile(prev_month=1200000)), suggest=False)
            for b in r.applied:
                for gid, v in b.used_groups.items():
                    if next(g for g in CARDS[cid]["limit_groups"] if g["id"] == gid)["kind"] != "이용금액":
                        self.assertLessEqual(v, b.value, (cid, gid))


if __name__ == "__main__":
    unittest.main()
