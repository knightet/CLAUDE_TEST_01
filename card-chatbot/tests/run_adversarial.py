"""공격적 테스트: python tests/run_adversarial.py  ->  tests/adversarial_results.txt

일부러 헷갈리게 만든 질문(adversarial_cases.json)을 키워드 모드와 LLM 모드로 돌려서 틀린 것을 모두 뽑아요.
화면 기본 상태(카드 9장, 전월 실적 최고 구간)에서 계산해요. LLM 모드는 질문당 API를 2번 정도 호출해요.
"""
import datetime as dt
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import src.chatbot as bot
from src.normalizer import normalize

CASES = json.loads((ROOT / "tests" / "adversarial_cases.json").read_text(encoding="utf-8"))
FULL = json.loads((ROOT / "tests" / "rank_cases.json").read_text(encoding="utf-8"))["profile"]


def same(k, got, want):
    if k == "merchant" and got and want:
        return normalize(str(got))[0] == normalize(want)[0]
    if k == "liters" and got is not None and want is not None:
        return float(got) == float(want)
    return got == want


def check(c, t) -> list:
    """틀린 점 목록 (비어 있으면 통과)"""
    bad, p, view = [], t["context"]["parsed"], t["view"]
    results = view.get("results", [])
    for k, v in c.get("parsed", {}).items():
        if not same(k, p.get(k), v):
            bad.append(f"해석 {k}={p.get(k)!r} (정답 {v!r})")
    if "followup" in c and t["followup"] != c["followup"]:
        bad.append(f"이어받기={t['followup']} (정답 {c['followup']})")
    for i, (cid, value) in enumerate(c.get("top", [])):
        if i >= len(results):
            bad.append(f"{i + 1}위 없음 (정답 {cid or ''} {value})")
            continue
        r = results[i]
        if r["value"] != value or (cid and r["card_id"] != cid):
            bad.append(f"{i + 1}위 {r['card_id']} {r['value']} (정답 {cid or '아무 카드'} {value})")
    if "compared" in c and view.get("compared") != c["compared"]:
        bad.append(f"비교 카드 {view.get('compared')}장 (정답 {c['compared']}장)")
    if "max_won" in c:
        won = [r["value"] for r in results if r["unit"] == "원"]
        if won and max(won) > c["max_won"]:
            top = next(r for r in results if r["unit"] == "원")
            bad.append(f"할인이 나오면 안 되는데 {top['card_id']} {top['value']}원")
    if c.get("top_benefit_not") and results and results[0]["applied"]:
        name = results[0]["applied"][0]["name"]
        if any(w in name for w in c["top_benefit_not"]):
            bad.append(f"1위 혜택이 '{name}'")
    if c.get("need") and not t["facts"].startswith("NEED:"):
        bad.append("되물어야 하는데 계산함")
    text = t["answer"] + "\n" + t["facts"]
    for s in c.get("answer_contains", []):
        if s not in text:
            bad.append(f"'{s}' 없음")
    for s in c.get("answer_not_contains", []):
        if s in t["answer"]:
            bad.append(f"답변에 '{s}' 있음")
    return bad


def run(c):
    st = bot.build_state({"owned": [], "cards": FULL})
    ctx, t = None, None
    for q in c.get("turns") or [c["q"]]:
        t = bot.ask_turn(q, st, ctx)
        ctx = t["context"]
    return t


def main():
    modes = [("키워드", False)] + ([("LLM", True)] if bot.USE_LLM else [])
    llm_on = bot.USE_LLM
    report, summary = [], []
    for name, use in modes:
        bot.USE_LLM = use and llm_on
        fails = []
        for c in CASES:
            try:
                t = run(c)
                bad = check(c, t)
                answer = t["answer"].replace("\n", " / ")
            except Exception as e:
                bad, answer = [f"오류(예외): {e!r}"], traceback.format_exc().splitlines()[-1]
            if bad:
                q = " → ".join(c.get("turns") or [c["q"]])
                fails.append((c, q, bad, answer))
        summary.append(f"{name} 모드: {len(CASES) - len(fails)}/{len(CASES)} 통과, 오류 {len(fails)}건")
        report += ["", f"■ {name} 모드에서 틀린 문항 ({len(fails)}건)", "-" * 70]
        for c, q, bad, answer in fails:
            report += [f"[{c['id']}] ({c['cat']}) {q}",
                       *[f"    ✗ {b}" for b in bad],
                       *( [f"    왜 오류인가: {c['why']}"] if c.get("why") else []),
                       f"    답변: {answer[:220]}", ""]
    bot.USE_LLM = llm_on
    head = [f"공격적 테스트 결과 - {dt.datetime.now():%Y-%m-%d %H:%M} (문항 {len(CASES)}개)", "=" * 70, *summary]
    out = ROOT / "tests" / "adversarial_results.txt"
    out.write_text("\n".join(head + report) + "\n", encoding="utf-8")
    print("\n".join(head))
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
