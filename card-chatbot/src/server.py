"""웹 채팅 서버: python src/server.py -> http://localhost:8000

API 키가 브라우저로 새지 않도록 LLM 호출은 이 서버에서만 해요.
서버는 대화나 사용자 정보를 저장하지 않아요. 브라우저가 매번 보유 카드·실적·이전 대화 상태를 같이 보내요.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.chatbot import ask_turn, build_state, USE_LLM, MODEL, CARDS
from src.card_summary import reward_text

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "web" / "chat.html"
PORT = 8000
MAX_BODY = 64 * 1024


def card_meta(c: dict) -> dict:
    """화면이 카드별 입력칸(실적·옵션·이번 달 사용 현황)을 만들 때 쓰는 정보"""
    bs = c["benefits"]
    return {
        "id": c["card_id"], "name": c["card_name"], "issuer": c["issuer"], "type": c["card_type"],
        "unit": c["reward_unit"], "fee": c["annual_fee"]["domestic"],
        "required_min": c["prev_month"]["required_min"],
        # 모든 혜택을 받을 수 있는 실적 (최고 구간 하한). 화면에서 전월 실적 기본값으로 써요
        "full_prev_month": max([t["prev_month_min"] for t in c["tiers"]] + [c["prev_month"]["required_min"] or 0]
                               + [b["requires"]["prev_month_min"] or 0 for b in bs]),
        "has_grace": c["prev_month"]["grace"] is not None,
        "grace": (c["prev_month"]["grace"] or {}).get("description"),
        "options": [{"id": o["id"], "name": o["name"], "choices": o["choices"]} for o in c["options"]],
        "enrollment": next((b["requires"]["enrollment"] for b in bs if b["requires"]["enrollment"]), None),
        "overseas_brand": any(b["requires"]["card_brand"] for b in bs),
        "groups": [{"id": g["id"], "name": g["name"], "unit": "마일" if g["kind"] == "마일리지" else "원",
                    "kind": g["kind"]} for g in c["limit_groups"]],
        "counted": [{"id": b["id"], "name": b["name"], "per_month": b["caps"]["count_per_month"]}
                    for b in bs if b["caps"]["count_per_month"]],
        "capped": [{"id": b["id"], "name": b["name"], "per_month": b["caps"]["benefit_per_month"]}
                   for b in bs if b["caps"]["benefit_per_month"] and not b["groups"]],
        "highlights": [f"{b['name'].split('] ')[-1]} {reward_text(b, c['reward_unit'])}" for b in bs[:3]],
        "review": c["review"]["status"],
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data: dict):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        if self.path in ("/", "/chat.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/info":
            self._json(200, {"mode": f"LLM 모드 ({MODEL})" if USE_LLM else "키워드 모드",
                             "cards": [card_meta(c) for c in CARDS.values()]})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/ask":
            return self._send(404, b"not found", "text/plain")
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                return self._json(413, {"error": "요청이 너무 커요."})
            body = json.loads(self.rfile.read(length) or b"{}")
            q = str(body.get("q", "")).strip()[:300]
            state = build_state(body.get("profile"))
        except (ValueError, TypeError, AttributeError):
            return self._json(400, {"error": "잘못된 요청이에요."})
        if not q:
            return self._json(400, {"error": "질문을 입력해 주세요."})
        try:
            t = ask_turn(q, state, body.get("context"), str(body.get("link", "auto")))
            t.pop("facts", None)
            self._json(200, t)
        except Exception as e:
            self._json(500, {"error": f"답변 중 오류가 났어요: {e}"})


if __name__ == "__main__":
    print(f"웹 채팅: http://localhost:{PORT}  (종료: Ctrl+C)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
