"""후속 질문 이어받기 시나리오 테스트: python -m unittest tests.test_followup -v

키워드 모드로 고정해서 돌려요. LLM 응답은 매번 달라서 여기서 확인하지 않아요.
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import src.chatbot as bot
from src.normalizer import normalize

DIALOGS = json.loads((ROOT / "tests" / "dialog_set.json").read_text(encoding="utf-8"))


class FollowupDialogs(unittest.TestCase):
    def setUp(self):
        self._llm = bot.USE_LLM
        bot.USE_LLM = False

    def tearDown(self):
        bot.USE_LLM = self._llm

    def test_dialogs(self):
        for d in DIALOGS:
            context = None
            for i, t in enumerate(d["turns"], 1):
                with self.subTest(dialog=d["name"], turn=i, q=t["q"]):
                    state = bot.build_state({"cards": {cid: {"prev_month": v} for cid, v in t.get("users", {}).items()}})
                    turn = bot.ask_turn(t["q"], state, context)
                    context, followed = turn["context"], turn["followup"]
                    answer = turn["answer"] + "\n" + turn["facts"]   # 화면에 보이는 답변 + 계산 결과
                    self.assertEqual(followed, t["followup"], "이어받기 여부")
                    for k, v in t.get("expect", {}).items():
                        got = context["parsed"].get(k)
                        if k == "merchant" and v and got:   # 'cu'/'CU'처럼 표기만 다른 건 같게 봐요
                            got, v = normalize(got)[0], normalize(v)[0]
                        self.assertEqual(got, v, f"'{k}' 값")
                    for s in t.get("answer_contains", []):
                        self.assertIn(s, answer)
                    for s in t.get("answer_not_contains", []):
                        self.assertNotIn(s, answer)

    def test_tampered_context_is_ignored(self):
        bad = {"parsed": {"intent": "benefit", "merchant": "스벅", "amount": "1e99", "card": "없는카드"}}
        p, followed = bot.resolve("그럼 GS25는?", bad)
        self.assertTrue(followed)
        self.assertIsNone(p["amount"])
        self.assertIsNone(p["card"])
        self.assertFalse(bot.resolve("2만원이면?", {"parsed": "문자열"})[1])


class LinkChoice(unittest.TestCase):
    """화면의 '질문 연결' 선택: 자동 / 이어서 / 새 질문"""

    def setUp(self):
        self._llm, bot.USE_LLM = bot.USE_LLM, False
        self.prev = bot.ask_turn("토요일 이마트 6만원")["context"]

    def tearDown(self):
        bot.USE_LLM = self._llm

    def test_new_ignores_previous(self):
        p, followed = bot.resolve("그럼 2만원이면?", self.prev, "new")
        self.assertFalse(followed)
        self.assertIsNone(p["merchant"])                 # 가맹점을 되묻게 됨
        self.assertIsNone(p["day"])

    def test_follow_forces_link(self):
        # 자동이면 길고 가게 이름이 있는 새 질문이라 이어받지 않지만, '이어서'를 고르면 빈 칸(요일·금액)을 이어받아요
        q = "롯데월드 놀러가려고 하는데 카드 추천"
        self.assertFalse(bot.resolve(q, self.prev, "auto")[1])
        p, followed = bot.resolve(q, self.prev, "follow")
        self.assertTrue(followed)
        self.assertEqual((p["merchant"], p["amount"], p["day"]), ("롯데월드", 60000, "토"))

    def test_follow_without_previous_is_new(self):
        self.assertFalse(bot.resolve("2만원이면?", None, "follow")[1])

    def test_unknown_mode_is_auto(self):
        t = bot.ask_turn("그럼 2만원이면?", None, self.prev, "이상한값")
        self.assertEqual(t["link"], "auto")
        self.assertTrue(t["followup"])


if __name__ == "__main__":
    unittest.main()
