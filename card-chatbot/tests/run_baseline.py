"""방식 비교: python tests/run_baseline.py  ->  tests/baseline_results.txt

compare_cases.json(설명서로 계산한 정답이 있는 100문항, build_compare_set.py로 생성)을 세 방식으로 풀어 같은 기준으로 채점해요.
  A. GPT 빈손: 카드 자료 없이 카드 이름과 전월 실적만 주고 GPT가 답함
  B. 고치기 전: 카드 설명서 요약(data/cards/summary)을 통째로 주고 GPT가 조건 판단·계산까지 함
  C. 고친 후: 지금 구조 (GPT는 해석만, 조건 판단·계산은 엔진)
python tests/run_baseline.py --only C 로 고친 후(C)만 다시 돌릴 수 있어요 (A·B는 코드가 바뀌어도 결과가 같아요).
채점: 1위 금액이 정답과 같은가 / 상위 금액 목록이 정답과 같은가 / (정답 카드가 정해진 문항) 1위 카드가 맞는가
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import src.chatbot as bot

CASES = json.loads((ROOT / "tests" / "compare_cases.json").read_text(encoding="utf-8"))
RANK = json.loads((ROOT / "tests" / "rank_cases.json").read_text(encoding="utf-8"))
FULL = {"owned": list(RANK["profile"]), "cards": RANK["profile"]}
SUMMARY = ROOT / "data" / "cards" / "summary"
CARDS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "data" / "cards").glob("*.json")}
TODAY = "2026-10-02(금)"


def profile_text() -> str:
    lines = []
    for cid, s in RANK["profile"].items():
        c = CARDS[cid]
        pm = f"전월 실적 {s['prev_month']:,}원" if "prev_month" in s else "전월 실적 조건 없음"
        lines.append(f"- {cid}: {c['card_name']} ({c['card_type']}) / {pm}")
    return "\n".join(lines)


RULES = f"""오늘은 {TODAY}입니다. 사용자는 아래 9장의 카드를 모두 가지고 있습니다.
{profile_text()}
선택형 혜택은 기본 선택, 이번 달 한도·횟수는 아직 쓰지 않음, 신규 발급 특례 없음, 간편결제는 질문에 말한 경우만 사용으로 가정하세요.
질문에서 전월 실적을 말하면 그 금액을 따르고, 특정 카드나 카드 종류를 말하면 그 카드만 답하세요.
질문의 결제에 대해 받을 수 있는 혜택(원화 할인·캐시백은 원, 마일리지는 마일)이 큰 카드 순서로 최대 3장을 답하세요.
혜택이 0인 카드만 남으면 0으로 적어도 됩니다. 반드시 JSON만 출력하세요:
{{"top": [{{"card_id": "카드 id", "value": 숫자}}, ...]}}"""


def ask_gpt(q: str, docs: str | None) -> list:
    system = RULES + (f"\n\n아래는 카드 설명서 요약입니다. 이 내용만 근거로 판단하세요.\n\n{docs}" if docs else
                      "\n\n카드 자료는 없습니다. 알고 있는 지식으로 답하세요.")
    res = bot.client.chat.completions.create(
        model=bot.MODEL, temperature=0, response_format={"type": "json_object"},
        messages=[{"role": "system", "content": system}, {"role": "user", "content": q}])
    try:
        top = json.loads(res.choices[0].message.content).get("top", [])
        return [(str(t.get("card_id")), int(round(float(t.get("value") or 0)))) for t in top][:3]
    except (ValueError, TypeError, AttributeError):
        return []


def ask_engine(q: str) -> list:
    t = bot.ask_turn(q, bot.build_state(FULL))
    return [(r["card_id"], r["value"]) for r in t["view"].get("results", [])][:3]


def grade(c, got) -> tuple[bool, bool, bool | None]:
    want = [v for _, v in c["top"]]
    values = [v for _, v in got]
    top1 = bool(values) and values[0] == want[0]
    full = values[:len(want)] == want
    card = None
    if c["top"][0][0]:
        card = bool(got) and got[0][0] == c["top"][0][0]
    return top1, full, card


def main():
    if not bot.USE_LLM:
        print("OPENAI_API_KEY가 없어서 비교할 수 없어요.")
        return
    docs = "\n\n".join(p.read_text(encoding="utf-8") for p in sorted(SUMMARY.glob("*.md")) if p.stem != "_overview")
    modes = [("A. GPT 빈손", lambda q: ask_gpt(q, None)),
             ("B. 고치기 전 (설명서 주고 GPT가 계산)", lambda q: ask_gpt(q, docs)),
             ("C. 고친 후 (코드 해석 + 엔진 계산)", ask_engine)]
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].upper()
        modes = [m for m in modes if m[0].startswith(only)]
    summary, detail = [], []
    for name, fn in modes:
        n_card = sum(bool(c["top"][0][0]) for c in CASES)
        s1 = s2 = s3 = 0
        by_group = {}
        detail += ["", f"■ {name}", "-" * 70]
        for c in CASES:
            got = fn(c["q"])
            top1, full, card = grade(c, got)
            s1, s2, s3 = s1 + top1, s2 + full, s3 + bool(card)
            g = by_group.setdefault(c["from"].split("·")[0], [0, 0])
            g[0], g[1] = g[0] + top1, g[1] + 1
            mark = "O" if full and card in (None, True) else "X"
            detail.append(f"[{mark}] {c['id']} ({c['from']}) {c['q']}  답 {got}  정답 {c['top']}")
        summary.append(f"{name}: 1위 금액 {s1}/{len(CASES)} ({s1 / len(CASES):.0%}), "
                       f"상위 금액 전체 {s2}/{len(CASES)} ({s2 / len(CASES):.0%}), "
                       f"1위 카드 {s3}/{n_card} ({s3 / n_card:.0%})")
        summary.append("    1위 금액 유형별: " + ", ".join(f"{k} {a}/{n}" for k, (a, n) in by_group.items()))
    head = [f"방식 비교 ({bot.MODEL}) - {dt.datetime.now():%Y-%m-%d %H:%M}, 문항 {len(CASES)}개", "=" * 70, *summary]
    out = ROOT / "tests" / ("baseline_results.txt" if "--only" not in sys.argv else f"baseline_results_{only}.txt")
    out.write_text("\n".join(head + detail) + "\n", encoding="utf-8")
    print("\n".join(head))


if __name__ == "__main__":
    main()
