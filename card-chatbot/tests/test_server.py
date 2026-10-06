"""웹 서버 API 테스트: python -m unittest tests.test_server -v

테스트 안에서 실제 서버를 빈 포트에 띄워 HTTP로 요청해요. LLM은 끄고 돌려요.
"""
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import src.chatbot as bot
from src.server import Handler


class ServerAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._llm, bot.USE_LLM = bot.USE_LLM, False
        Handler.log_message = lambda *a: None
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        bot.USE_LLM = cls._llm

    def request(self, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read()) if "json" in r.headers["Content-Type"] else r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            return e.code, json.loads(raw) if "json" in e.headers.get("Content-Type", "") else raw

    def test_page(self):
        status, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b'lang="ko"', body)

    def test_info_lists_cards_by_type(self):
        status, d = self.request("/api/info")
        self.assertEqual(status, 200)
        types = {c["id"]: c["type"] for c in d["cards"]}
        self.assertEqual(len(types), 9)
        self.assertEqual(sorted(k for k, v in types.items() if v == "체크"),
                         ["kb_nori_check", "kb_youth_club_check", "shinhan_heyyoung_check"])
        full = {c["id"]: c["full_prev_month"] for c in d["cards"]}
        self.assertEqual(full["kb_goodday"], 1200000)
        self.assertEqual(full["lotte_loca_likit_1_5"], 0)

    def test_ask_returns_top3_with_steps(self):
        status, d = self.request("/api/ask", {"q": "스벅 15000원", "profile": {"cards": {"nh_allbareun_flex": {"prev_month": 300000}}}})
        self.assertEqual(status, 200)
        self.assertLessEqual(len(d["view"]["results"]), 3)
        best = d["view"]["results"][0]
        self.assertEqual((best["card_id"], best["value"]), ("nh_allbareun_flex", 5000))
        self.assertTrue(best["applied"][0]["steps"])
        self.assertNotIn("facts", d)

    def test_followup_through_context(self):
        _, d1 = self.request("/api/ask", {"q": "스벅 15000원"})
        _, d2 = self.request("/api/ask", {"q": "그럼 9000원이면?", "context": d1["context"]})
        self.assertTrue(d2["followup"])
        self.assertEqual(d2["context"]["parsed"]["amount"], 9000)

    def test_bad_requests(self):
        self.assertEqual(self.request("/api/ask", {"q": "   "})[0], 400)
        self.assertEqual(self.request("/api/ask", raw=b"{not json")[0], 400)
        self.assertEqual(self.request("/api/ask", raw=b"x" * (70 * 1024))[0], 413)
        self.assertEqual(self.request("/api/nope", {"q": "a"})[0], 404)

    def test_tampered_profile_and_context_are_ignored(self):
        status, d = self.request("/api/ask", {
            "q": "그럼 GS25는?",
            "profile": {"owned": ["../../etc"], "cards": {"kb_nori_check": {"prev_month": "999999999999"}}},
            "context": {"parsed": {"intent": "benefit", "merchant": "<script>", "amount": -3, "card": "x"}}})
        self.assertEqual(status, 200)
        self.assertIsNone(d["context"]["parsed"]["amount"])
        self.assertEqual(d["view"].get("compared", 9), 9)


if __name__ == "__main__":
    unittest.main()
