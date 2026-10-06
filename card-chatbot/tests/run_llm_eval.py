"""LLM 모드 평가: python tests/run_llm_eval.py  (OpenAI API를 질문당 2번 호출해요)

chat_cases.json의 질문을 실제 LLM으로 해석·설명시키고 정답률을 재요.
- 해석 정확도: LLM이 뽑은 값(금액·요일·카드 등)이 정답과 같은가
- 순위 정확도: 해석 결과로 엔진이 계산한 상위 3개 금액이 정답과 같은가
- 숫자 검증: LLM 설명에 계산 결과에 없는 숫자가 섞였는가 (섞이면 코드 문장으로 대체됨)
결과: tests/llm_eval_results.txt
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import src.chatbot as bot
from src.normalizer import normalize

CASES = json.loads((ROOT / "tests" / "chat_cases.json").read_text(encoding="utf-8"))
RANK = json.loads((ROOT / "tests" / "rank_cases.json").read_text(encoding="utf-8"))
FULL = {"owned": list(RANK["profile"]), "cards": RANK["profile"]}


def same(k, got, want):
    if k == "merchant" and got and want:
        return normalize(str(got))[0] == normalize(want)[0]
    if k == "liters" and got is not None and want is not None:
        return float(got) == float(want)
    return got == want


def main():
    if not bot.USE_LLM:
        print("OPENAI_API_KEY가 없어서 LLM 평가를 할 수 없어요.")
        return
    parse_ok = parse_n = rank_ok = rank_n = 0
    checked = {"llm": 0, "llm_rejected": 0, "template": 0}
    lines = []
    for c in CASES:
        t = bot.ask_turn(c["q"], bot.build_state(FULL))
        p, view = t["context"]["parsed"], t["view"]
        bad = [f"{k}: {p.get(k)!r} (정답 {v!r})" for k, v in c.get("parsed", {}).items() if not same(k, p.get(k), v)]
        parse_n += bool(c.get("parsed"))
        parse_ok += bool(c.get("parsed")) and not bad
        got_values = [r["value"] for r in view.get("results", [])]
        rank_hit = None
        if "top_values" in c:
            rank_n += 1
            rank_hit = got_values == c["top_values"]
            rank_ok += rank_hit
        checked[t["checked"]] += 1
        mark = "O" if not bad and rank_hit in (None, True) else "X"
        lines += [f"[{mark}] {c['id']}  Q: {c['q']}",
                  f"      해석: " + ("정답" if not bad else "틀림 - " + "; ".join(bad)),
                  *( [f"      상위 3개: {got_values} (정답 {c['top_values']})"] if "top_values" in c else []),
                  f"      설명 방식: {t['checked']}",
                  "      답변: " + t["answer"].replace("\n", " / "), ""]
    head = [f"LLM 모드 평가 결과 ({bot.MODEL}) - {dt.datetime.now():%Y-%m-%d %H:%M}", "=" * 70,
            f"해석 정확도: {parse_ok}/{parse_n} ({parse_ok / parse_n:.0%})",
            f"순위 정확도: {rank_ok}/{rank_n} ({rank_ok / rank_n:.0%})",
            f"설명 방식: LLM 설명 통과 {checked['llm']}건, 숫자 불일치로 코드 문장 대체 {checked['llm_rejected']}건, "
            f"처음부터 코드 문장(되물음·혜택 없음·실적 포함 여부·카드 정보) {checked['template']}건", "=" * 70, ""]
    out = ROOT / "tests" / "llm_eval_results.txt"
    out.write_text("\n".join(head + lines) + "\n", encoding="utf-8")
    print("\n".join(head[:5]))
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
