"""최종 재실행 (모든 테스트·측정을 한 번에): python tests/run_final_check.py  ->  tests/final_check_YYYY-MM-DD.txt

2차 동결 코드(79da9f9) 그대로 돌려요. 측정 기록 파일(holdout2_results.txt, baseline_results*.txt 등)은 덮어쓰지 않고,
결과를 날짜별 파일 하나에 모아 둬요. GPT 비교(빈손·고치기 전)는 API 키가 있어야 해서 여기서는 돌리지 않아요.
"""
import ast
import contextlib
import datetime as dt
import io
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import src.chatbot as bot
from run_baseline import grade, parse_hit, rule_hit, ask_engine, LAST

bot.USE_LLM = False
TODAY = dt.date.today().isoformat()
lines = []
say = lambda s="": lines.append(s)


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT.parent, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def holdout(file, recorded=None, section=None):
    cases = json.loads((ROOT / "tests" / file).read_text(encoding="utf-8"))
    rec = {}
    if recorded:
        txt = (ROOT / "tests" / recorded).read_text(encoding="utf-8")
        if section:
            txt = txt.split(section)[1]
        for m in re.finditer(r"\[[OX]\] (h2?-\d+) .*?  답 (\[.*?\])  정답", txt):
            rec.setdefault(m.group(1), [tuple(x) for x in ast.literal_eval(m.group(2))])
    t1 = full = card = cn = ph = rh = same = 0
    for c in cases:
        got = ask_engine(c["q"]); t = LAST["turn"]
        a, f, k = grade(c, got)
        t1 += a; full += f; ph += bool(parse_hit(c, t)); rh += bool(rule_hit(c, t))
        if k is not None:
            cn += 1; card += k
        same += rec.get(c["id"]) == [tuple(x) for x in got]
    n = len(cases)
    return f"1위 금액 {t1}/{n}, 상위 금액 전체 {full}/{n}, 1위 카드 {card}/{cn}, 해석 적중 {ph}/{n}, 근거 적중 {rh}/{n}" + \
           (f", 측정 기록과 같은 답 {same}/{n}" if rec else "")


def dev100():
    cases = json.loads((ROOT / "tests" / "compare_cases.json").read_text(encoding="utf-8"))
    t1 = full = card = cn = 0
    for c in cases:
        a, f, k = grade(c, ask_engine(c["q"]))
        t1 += a; full += f
        if k is not None:
            cn += 1; card += k
    return f"1위 금액 {t1}/{len(cases)}, 상위 금액 전체 {full}/{len(cases)}, 1위 카드 {card}/{cn}"


def quiet(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue()


say(f"최종 재실행 - {dt.datetime.now():%Y-%m-%d %H:%M}")
say("=" * 70)
say(f"코드 기준: HEAD {git('rev-parse', '--short', 'HEAD')} / 2차 동결 79da9f9")
diff = git("diff", "--stat", "79da9f9", "HEAD", "--", "card-chatbot/src", "card-chatbot/web", "card-chatbot/data")
say("2차 동결 이후 src/ · web/ · data/ 변경: " + ("없음" if not diff else "있음\n" + diff))
say()

suite = unittest.defaultTestLoader.loadTestsFromNames(
    ["tests.test_engine", "tests.test_chat", "tests.test_followup", "tests.test_server", "tests.test_data"])
res = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
say(f"[단위 테스트] {res.testsRun}개 실행, 실패 {len(res.failures)}, 오류 {len(res.errors)}, 건너뜀 {len(res.skipped)}"
    + (" (설명서 PDF가 없어 쪽수 검사 건너뜀)" if res.skipped else ""))
engine_n = len(json.loads((ROOT / "tests" / "engine_cases.json").read_text(encoding="utf-8")))
say(f"  - 계산 평가 engine_cases.json {engine_n}문항 포함")

backup = {p: (ROOT / "tests" / p).read_text(encoding="utf-8")
          for p in ["adversarial_results.txt", "property_results.txt", "popular_results.txt"]}
try:
    import run_adversarial, run_popular
    quiet(run_adversarial.main)
    adv = re.search(r"키워드 모드: .*", (ROOT / "tests" / "adversarial_results.txt").read_text(encoding="utf-8"))
    say(f"[공격 테스트] {adv.group(0) if adv else '결과 없음'}")
    quiet(lambda: __import__("run_property"))      # 성질 검사는 불러오는 순간 실행돼요
    prop = (ROOT / "tests" / "property_results.txt").read_text(encoding="utf-8").strip().splitlines()[-1]
    say(f"[성질 검사] {prop}")
    quiet(run_popular.main)
    pop = (ROOT / "tests" / "popular_results.txt").read_text(encoding="utf-8").splitlines()[1]
    say(f"[많이 물을 질문] {pop}")
finally:
    for p, s in backup.items():                     # 측정 기록 파일은 원래대로
        (ROOT / "tests" / p).write_text(s, encoding="utf-8")
say()
say(f"[개발 문항 100] {dev100()}")
say(f"[1차 홀드아웃 재실행] {holdout('holdout_cases.json', 'baseline_results_holdout.txt', '■ C.')}")
say(f"[2차 홀드아웃 재실행] {holdout('holdout2_cases.json', 'holdout2_results.txt')}")
say()
say("참고: 홀드아웃은 이미 측정한 문항이라 이 결과는 재현 확인용입니다. 발표 점수는 각 측정 커밋의 기록입니다.")
say("참고: GPT 빈손·고치기 전 비교는 API 키가 필요해 이번 재실행에 포함하지 않았습니다 (1차 측정 기록 사용).")

out = ROOT / "tests" / f"final_check_{TODAY}.txt"
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
