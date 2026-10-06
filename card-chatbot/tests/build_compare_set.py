"""방식 비교용 100문항 만들기: python tests/build_compare_set.py  ->  tests/compare_cases.json

새로 정답을 만들지 않고, 이미 설명서로 계산해 둔 정답이 있는 문항만 모아요.
  - chat_cases.json: 정답 순위가 있는 17문항
  - rank_cases.json: chat과 겹치지 않는 3문항 (문장으로 바꿈)
  - adversarial_cases.json: 한 턴짜리이고 정답 순위가 있는 58문항
  - engine_cases.json: 카드 1장 + 전월 실적만 정한 22문항 (카드 이름과 전월 실적을 문장에 넣음)
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
L = lambda n: json.loads((ROOT / "tests" / f"{n}.json").read_text(encoding="utf-8"))

RANK_IDS = ["rank-01", "rank-02", "rank-03"]       # 나머지 7개는 chat 문항과 같은 결제
ENGINE_IDS = ["nori-01", "nori-02", "nori-03", "nori-06", "nori-12", "nori-13", "hey-02", "hey-07", "hey-12",
              "kpass-04", "kpass-10", "good-02", "good-04", "good-09", "good-10", "loca-01", "nh-01", "nh-07",
              "nh-13", "mr-02", "mr-05", "mr-16"]
CARD_WORD = {"kb_nori_check": "노리 카드로", "shinhan_heyyoung_check": "헤이영 카드로", "kb_kpass": "K패스 카드로",
             "kb_goodday": "굿데이 카드로", "lotte_loca_likit_1_5": "로카 카드로", "nh_allbareun_flex": "농협카드로",
             "shinhan_mr_life": "미스터라이프 카드로"}


def when(t):
    s = []
    if t.get("day"):
        s.append(f"{t['day']}요일")
    h = t.get("hour")
    if h is not None:
        s.append("자정" if h == 0 else f"오전 {h}시" if h < 12 else "정오" if h == 12 else
                 f"오후 {h - 12}시" if h < 18 else f"밤 {h - 12}시")
    return " ".join(s)


def sentence(t, prefix=""):
    parts = [prefix, when(t), "백화점" if t.get("location") == "백화점" else "",
             f"{t['merchant']} {t['amount']}원", f"{t['liters']}리터" if t.get("liters") else ""]
    return " ".join(p for p in parts if p)


def main():
    out = []
    for c in L("chat_cases"):
        if "top_values" in c:
            ids = c.get("top_ids") or []
            top = [[ids[i] if i < len(ids) else None, v] for i, v in enumerate(c["top_values"])]
            out.append({"id": c["id"], "from": "질문 해석", "q": c["q"], "top": top})
    for c in L("rank_cases")["cases"]:
        if c["id"] in RANK_IDS:
            out.append({"id": c["id"], "from": "카드 순위", "q": sentence(c["tx"]), "top": c["top"]})
    for c in L("adversarial_cases"):
        if c.get("top") and not c.get("turns"):
            out.append({"id": c["id"], "from": f"공격·{c['cat']}", "q": c["q"], "top": c["top"]})
    engine = {c["id"]: c for c in L("engine_cases")}
    for i in ENGINE_IDS:
        c = engine[i]
        pm = c["profile"]["prev_month"]
        q = sentence(c["tx"], CARD_WORD[c["card"]]) + (f", 전월 실적 {pm:,}원" if pm else "")
        out.append({"id": i, "from": "계산", "q": q, "top": [[c["card"], c["expect"]]]})
    assert len(out) == 100, len(out)
    path = ROOT / "tests" / "compare_cases.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(out)}문항 -> {path}")


if __name__ == "__main__":
    main()
