"""전체 자동 테스트 실행 + 결과 저장: python tests/run_all.py  ->  tests/test_report.txt

LLM은 끄고 돌려요 (항상 같은 결과). LLM 모드 평가는 tests/run_llm_eval.py로 따로 돌려요.
"""
import datetime as dt
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import src.chatbot as bot

SUITES = [
    ("① 계산 평가 (설명서 정답과 숫자 일치)", "tests.test_engine", "engine_cases.json"),
    ("② 비슷한 카드 순위 (상위 3개)", "tests.test_engine.EngineCases.test_rank_cases", "rank_cases.json"),
    ("③ 질문 해석·답변", "tests.test_chat", "chat_cases.json"),
    ("③ 후속 질문 대화", "tests.test_followup", "dialog_set.json"),
    ("④ 서버 API", "tests.test_server", None),
    ("카드 데이터 검사", "tests.test_data", None),
]


def count(file):
    if not file:
        return None
    d = json.loads((ROOT / "tests" / file).read_text(encoding="utf-8"))
    if file == "rank_cases.json":
        return len(d["cases"])
    if file == "dialog_set.json":
        return sum(len(x["turns"]) for x in d)
    return len(d)


def main():
    bot.USE_LLM = False
    lines, total_fail = [], 0
    for name, target, file in SUITES:
        suite = unittest.defaultTestLoader.loadTestsFromName(target)
        buf = io.StringIO()
        res = unittest.TextTestRunner(stream=buf, verbosity=0).run(suite)
        fails = res.failures + res.errors
        total_fail += len(fails)
        n = count(file)
        status = "통과" if not fails else f"실패 {len(fails)}건"
        lines.append(f"- {name}: {status}" + (f" (문항 {n}개)" if n else f" (테스트 {res.testsRun}개)"))
        for test, tb in fails:
            lines.append(f"    {test}: {tb.strip().splitlines()[-1]}")
    head = [f"카드 혜택 챗봇 자동 테스트 결과 - {dt.datetime.now():%Y-%m-%d %H:%M}", "=" * 70,
            "전체: " + ("모두 통과" if not total_fail else f"실패 {total_fail}건"), ""]
    report = "\n".join(head + lines) + "\n"
    (ROOT / "tests" / "test_report.txt").write_text(report, encoding="utf-8")
    print(report)
    sys.exit(1 if total_fail else 0)


if __name__ == "__main__":
    main()
