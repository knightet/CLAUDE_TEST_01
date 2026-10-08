"""2차 홀드아웃 측정 (한 번만): python tests/run_holdout2.py  ->  tests/holdout2_results.txt

2차 동결 커밋(79da9f9) 코드로 tests/holdout2_cases.json을 채점해요. 채점 기준은 1차 홀드아웃과 같아요
(tests/run_baseline.py의 grade · parse_hit · rule_hit). API 키 없이 키워드 모드로 돌려요.
GPT 빈손·고치기 전 비교는 API 키가 있어야 해서 여기서는 재지 않아요.
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import src.chatbot as bot
from run_baseline import grade, parse_hit, rule_hit, ask_engine, LAST

CASES = json.loads((ROOT / "tests" / "holdout2_cases.json").read_text(encoding="utf-8"))


def main():
    bot.USE_LLM = False
    n = len(CASES)
    top1 = full = parsed = rules = 0
    cards = card_n = 0
    lines = []
    for c in CASES:
        got = ask_engine(c["q"])
        t = LAST["turn"]
        a, f, k = grade(c, got)
        p, r = parse_hit(c, t), rule_hit(c, t)
        top1 += a; full += f; parsed += bool(p); rules += bool(r)
        if k is not None:
            card_n += 1; cards += k
        lines.append(f"[{'O' if a else 'X'}] {c['id']} {c['q']}  답 {got}  정답 {c['top']}  "
                     f"해석{'O' if p else 'X'}  근거{'O' if r else 'X'}")
    head = [f"2차 홀드아웃 측정 (코드 해석 + 엔진, 키워드 모드) - {dt.datetime.now():%Y-%m-%d %H:%M}, 문항 {n}개",
            f"1위 금액 {top1}/{n}, 상위 금액 전체 {full}/{n}, 1위 카드 {cards}/{card_n}, 해석 적중 {parsed}/{n}, 근거 적중 {rules}/{n}",
            "=" * 70]
    out = "\n".join(head + lines)
    (ROOT / "tests" / "holdout2_results.txt").write_text(out + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
