"""질문 해석·답변 테스트 (키워드 모드 고정): python -m unittest tests.test_chat -v

화면 기본 상태(카드 9장 보유, 전월 실적 최고 구간)에서 실제 질문 문장으로 확인해요.
"""
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import src.chatbot as bot
from src.normalizer import normalize

CASES = json.loads((ROOT / "tests" / "chat_cases.json").read_text(encoding="utf-8"))
RANK = json.loads((ROOT / "tests" / "rank_cases.json").read_text(encoding="utf-8"))
FULL = {"owned": list(RANK["profile"]), "cards": RANK["profile"]}


class ChatCases(unittest.TestCase):
    def setUp(self):
        self._llm, bot.USE_LLM = bot.USE_LLM, False

    def tearDown(self):
        bot.USE_LLM = self._llm

    def test_cases(self):
        for c in CASES:
            with self.subTest(c["id"], q=c["q"]):
                t = bot.ask_turn(c["q"], bot.build_state(FULL))
                p, view = t["context"]["parsed"], t["view"]
                for k, v in c.get("parsed", {}).items():
                    got = p.get(k)
                    if k == "merchant" and v and got:
                        got, v = normalize(got)[0], normalize(v)[0]
                    self.assertEqual(got, v, f"해석 '{k}'")
                results = view.get("results", [])
                if "top_values" in c:
                    self.assertEqual([r["value"] for r in results], c["top_values"], [(r["card_id"], r["value"]) for r in results])
                for i, cid in enumerate(c.get("top_ids", [])):
                    self.assertEqual(results[i]["card_id"], cid)
                if "result_count" in c:
                    self.assertEqual(len(results), c["result_count"])
                text = t["answer"] + "\n" + t["facts"]
                for s in c.get("answer_contains", []):
                    self.assertIn(s, text)
                for s in c.get("answer_not_contains", []):
                    self.assertNotIn(s, t["answer"])

    def test_at_most_three_results(self):
        t = bot.ask_turn("다이소 10000원", bot.build_state(FULL))
        self.assertLessEqual(len(t["view"]["results"]), 3)
        self.assertEqual(t["view"]["compared"], 9)


class NumberGuard(unittest.TestCase):
    """LLM 답변 속 숫자가 계산 결과에 없으면 거부"""
    facts = "1. NH농협 올바른FLEX카드: 5,000원\n2. KB국민 노리 체크카드: 3,000원 (15,000원 × 20%)"

    def test_accepts_numbers_from_facts(self):
        self.assertTrue(bot.numbers_ok("NH가 5,000원, 노리가 3,000원이에요. 2위는 노리예요.", self.facts)[0])

    def test_rejects_invented_number(self):
        ok, extra = bot.numbers_ok("노리는 3,500원 할인돼요", self.facts)
        self.assertFalse(ok)
        self.assertEqual(extra, {"3500"})

    def test_rejects_recalculated_sum(self):
        self.assertFalse(bot.numbers_ok("두 카드를 합치면 8,000원이에요", self.facts)[0])


class StateValidation(unittest.TestCase):
    """화면에서 온 값은 믿지 않고 검사해요"""
    def test_unknown_and_bad_values_dropped(self):
        st = bot.build_state({
            "owned": ["kb_nori_check", "없는카드"],
            "cards": {"kb_nori_check": {"prev_month": -5, "options": {"pack": "Z"},
                                        "used_groups": {"integrated": "많이", "없는그룹": 1},
                                        "used_benefits": {"starbucks": {"count": 2}, "없는혜택": {"count": 1}}}}})
        self.assertEqual(list(st), ["kb_nori_check"])
        p = st["kb_nori_check"]
        self.assertEqual(p.prev_month, 0)
        self.assertEqual(p.options, {})
        self.assertEqual(p.used_groups, {"integrated": 0})
        self.assertEqual(list(p.used_benefits), ["starbucks"])

    def test_option_must_be_valid_choice(self):
        st = bot.build_state({"owned": ["kb_youth_club_check"], "cards": {"kb_youth_club_check": {"options": {"pack": "B"}}}})
        self.assertEqual(st["kb_youth_club_check"].options, {"pack": "B"})

    def test_empty_owned_means_all_cards(self):
        self.assertEqual(len(bot.build_state({})), 9)


class Consistency(unittest.TestCase):
    """문항 하나하나가 아니라 여러 조합을 돌려서 '답이 서로 맞는지'를 봐요.
    (업종으로 물으면 '혜택 없음'인데 가게 이름으로 물으면 1,000원 → 사용자에게는 오답)"""

    def setUp(self):
        self._llm, bot.USE_LLM = bot.USE_LLM, False
        self.st = bot.build_state(FULL)

    def tearDown(self):
        bot.USE_LLM = self._llm

    def test_category_answer_mentions_better_brands(self):
        words = sorted(w for w in bot.BROAD_WORDS if w in bot.CATEGORY and w not in bot.STORE_NAMES)
        for word in words:
            for scope in ("", "체크카드 중에 ", "신용카드로 "):
                q = f"{scope}오후 2시 {word} 30000원"
                t = bot.ask_turn(q, self.st)
                res = t["view"].get("results") or []
                if t["view"].get("kind") != "benefit":
                    continue
                best = res[0]["value"] if res and res[0]["unit"] == "원" else 0
                ids = bot.targets(t["context"]["parsed"], self.st)
                cat = normalize(word)[1]
                for brand in {m for cid in ids for b in bot.CARDS[cid]["benefits"] for m in b["merchants"]
                              if bot.CATEGORY.get(m) == cat}:
                    t2 = bot.ask_turn(q.replace(word, brand), self.st)
                    r2 = t2["view"]["results"][0]
                    if r2["unit"] == "원" and r2["value"] > best:
                        with self.subTest(q=q, brand=brand):
                            self.assertIn(brand, t["answer"])
                            self.assertNotIn("혜택을 받을 수 있는 카드가 없어요", t["answer"])

    def test_followup_equals_direct_question(self):
        cases = [
            ("체크카드 중에 편의점 12000원", "gs 25", "체크카드 중에 GS25 12000원"),
            ("토요일 이마트 6만원", "일요일이면?", "일요일 이마트 6만원"),
            ("오후 2시 스벅 15000원", "2만원이면?", "오후 2시 스벅 2만원"),
            ("오후 2시 스벅 15000원", "노리는?", "노리로 오후 2시 스벅 15000원"),
            ("편의점 12000원", "KB Pay로 하면?", "편의점 12000원 KB Pay로"),
            ("밤 11시 택시 9000원", "신용카드는?", "신용카드로 밤 11시 택시 9000원"),
        ]
        for first, second, direct in cases:
            with self.subTest(first=first, second=second):
                ctx = bot.ask_turn(first, self.st)["context"]
                a = bot.ask_turn(second, self.st, ctx, "follow")
                b = bot.ask_turn(direct, self.st)
                self.assertTrue(a["followup"])
                self.assertEqual([(r["card_id"], r["value"]) for r in a["view"]["results"]],
                                 [(r["card_id"], r["value"]) for r in b["view"]["results"]])


class UsageRecords(unittest.TestCase):
    """화면의 '이 카드로 결제했어요' 기록이 반영된 상태 (일 1회 · 월 2회인 NH 스타벅스 50%)"""

    def setUp(self):
        self._llm, bot.USE_LLM = bot.USE_LLM, False
        self.payload = {"owned": list(RANK["profile"]), "cards": json.loads(json.dumps(RANK["profile"]))}

    def tearDown(self):
        bot.USE_LLM = self._llm

    def record(self, r):
        """chat.html applyUsage와 같은 방식으로 사용량을 더해요"""
        st = self.payload["cards"].setdefault(r["card_id"], {})
        for g, v in r["usage"].get("used_groups", {}).items():
            st.setdefault("used_groups", {})[g] = st.get("used_groups", {}).get(g, 0) + v
        for b, d in r["usage"].get("used_benefits", {}).items():
            cur = st.setdefault("used_benefits", {}).setdefault(b, {})
            for k, v in d.items():
                cur[k] = cur.get(k, 0) + v

    def ask(self, q):
        return bot.ask_turn(q, bot.build_state(self.payload))

    def test_daily_limit_counts_only_today(self):
        first = self.ask("스벅 15000원")["view"]["results"][0]
        self.assertEqual((first["card_id"], first["value"]), ("nh_allbareun_flex", 5000))
        self.record(first)
        # 같은 날 다시: 일 1회를 써서 빠지고, 왜 빠졌는지 알려줘요
        again = self.ask("스벅 15000원")
        self.assertNotEqual(again["view"]["results"][0]["card_id"], "nh_allbareun_flex")
        self.assertEqual(again["view"]["used_up"][0]["value"], 5000)
        self.assertIn("기록 때문에 빠졌어요", again["answer"])
        # 오늘이 아닌 요일로 물으면 다른 날 결제라서 일 1회는 다시 쓸 수 있어요
        today = "월화수목금토일"[dt.date.today().weekday()]
        other = next(d for d in "월화수목금토일" if d != today)
        later = self.ask(f"{other}요일 스벅 15000원")["view"]["results"][0]
        self.assertEqual((later["card_id"], later["value"]), ("nh_allbareun_flex", 5000))

    def test_monthly_count_applies_on_any_day(self):
        today = "월화수목금토일"[dt.date.today().weekday()]
        other = next(d for d in "월화수목금토일" if d != today)
        for _ in range(2):   # 월 2회를 다른 날에 모두 사용
            self.record(self.ask(f"{other}요일 스벅 15000원")["view"]["results"][0])
        t = self.ask(f"{other}요일 스벅 15000원")
        self.assertNotEqual(t["view"]["results"][0]["card_id"], "nh_allbareun_flex")
        self.assertIn("월 2회 모두 사용함", t["answer"])


if __name__ == "__main__":
    unittest.main()
