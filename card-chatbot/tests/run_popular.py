"""많이 물을 질문 테스트 (키워드 모드): python tests/run_popular.py  ->  tests/popular_results.txt

화면 기본 상태(카드 9장 보유, 전월 실적 최고 구간)에서 tests/popular_cases.json의 질문을 돌려요.
해석(가맹점·금액·시간·카드)과 동작(결과가 나오는지, 1위 카드, 답변 문구)을 기대값과 비교해요.
"""
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import src.chatbot as bot
from src.normalizer import normalize

DATA = json.loads((ROOT / "tests" / "popular_cases.json").read_text(encoding="utf-8"))
RANK = json.loads((ROOT / "tests" / "rank_cases.json").read_text(encoding="utf-8"))
FULL = {"owned": list(RANK["profile"]), "cards": RANK["profile"]}


def run_case(c: dict) -> tuple[dict, dict, str]:
    ctx, t = None, None
    for q in c.get("turns", [c.get("q")]):
        t = bot.ask_turn(q, bot.build_state(FULL), ctx)
        ctx = t["context"]
    return t["context"]["parsed"], t["view"], t["answer"]


def check(c: dict) -> list[str]:
    p, view, answer = run_case(c)
    e, errs = c["expect"], []
    merchant = p.get("merchant")
    std, cat = normalize(merchant) if merchant else (None, None)
    results = view.get("results", [])
    if "merchant" in e and std != e["merchant"]:
        errs.append(f"가맹점 {std!r} (기대 {e['merchant']!r})")
    if "category" in e and cat != e["category"]:
        errs.append(f"업종 {cat!r} (기대 {e['category']!r}, 가맹점 {merchant!r})")
    if e.get("merchant_found") and not merchant:
        errs.append("가맹점을 못 찾음")
    for k in ("amount", "hour", "day", "intent", "card", "card_type", "pay_method", "item", "overseas"):
        if k in e and p.get(k) != e[k]:
            errs.append(f"{k} {p.get(k)!r} (기대 {e[k]!r})")
    if "not_amount" in e and p.get("amount") == e["not_amount"]:
        errs.append(f"금액을 {p.get('amount')}원으로 읽음 (통화 단위 무시)")
    if e.get("has_results") and not results:
        errs.append("결과 없음: " + answer.splitlines()[0][:60])
    if "top1" in e and (not results or results[0]["card_id"] != e["top1"]):
        errs.append(f"1위 {results[0]['card_id'] if results else None} (기대 {e['top1']})")
    if "result_count" in e and len(results) != e["result_count"]:
        errs.append(f"결과 {len(results)}개 (기대 {e['result_count']}개)")
    for s in e.get("answer_contains", []):
        if s not in answer:
            errs.append(f"답변에 '{s}' 없음: " + answer.splitlines()[0][:60])
    for s in e.get("answer_not_contains", []):
        if s in answer:
            errs.append(f"답변에 '{s}'가 나옴")
    return errs


def main():
    bot.USE_LLM = False
    lines, by_area, fails = [], defaultdict(lambda: [0, 0]), 0
    for c in DATA["cases"]:
        try:
            errs = check(c)
        except Exception as ex:
            errs = [f"오류 {type(ex).__name__}: {ex}"]
        by_area[c["area"]][1] += 1
        if not errs:
            by_area[c["area"]][0] += 1
        fails += bool(errs)
        q = " → ".join(c["turns"]) if "turns" in c else c["q"]
        lines.append(f"[{'O' if not errs else 'X'}] {c['id']} ({c['area']}) {q}" + ("" if not errs else "\n      " + " / ".join(errs)))
    n = len(DATA["cases"])
    head = [f"많이 물을 질문 테스트 (키워드 모드) - {dt.datetime.now():%Y-%m-%d %H:%M}",
            f"통과 {n - fails}/{n}",
            "영역별: " + ", ".join(f"{a} {ok}/{tot}" for a, (ok, tot) in by_area.items()), "=" * 70]
    out = "\n".join(head + lines)
    (ROOT / "tests" / "popular_results.txt").write_text(out + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
