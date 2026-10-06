"""성질(property) 검사: python tests/run_property.py  ->  tests/property_results.txt

정답을 사람이 하나씩 정하지 않고, "항상 지켜져야 하는 성질"을 수천 개 조합으로 확인해요.
  1. 같은 뜻이면 같은 결과: 금액 표기·가맹점 별칭·시간 표기·어순·꼬리말을 바꿔도 결과가 같아야 함
  2. 카드 데이터의 가맹점은 모두 알아들어야 함: 혜택에 적힌 가맹점 이름으로 물으면 그 가맹점으로 해석
  3. 단조성: 결제 금액·전월 실적이 늘면 같은 카드의 혜택이 줄면 안 됨 / 혜택이 결제 금액보다 크면 안 됨
  4. 범위 일관성: "체크카드 중에 X" = 체크카드만 골랐을 때 X, "노리로 X" = 전체 비교 속 노리 결과
  5. 사용 기록: '썼어요'를 반복해도 받은 금액 합이 혜택 월 한도·횟수를 넘으면 안 됨
키워드 모드로 돌려요 (해석은 코드가 하므로 LLM 모드와 결과가 같아요).
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import src.chatbot as bot
from src.engine import CARDS, Profile, Tx, add_usage, evaluate_card
from src.normalizer import normalize

bot.USE_LLM = False
RANK = json.loads((ROOT / "tests" / "rank_cases.json").read_text(encoding="utf-8"))
FULL = bot.build_state({"owned": [], "cards": RANK["profile"]})
fails = {}


def fail(group, msg):
    fails.setdefault(group, []).append(msg)


def results(q, state=FULL):
    t = bot.ask_turn(q, state)
    return [(r["card_id"], r["value"]) for r in t["view"].get("results", [])], t


# ---------- 1. 같은 뜻이면 같은 결과 ----------
AMOUNTS = {15000: ["15000원", "15,000원", "1만5천원", "1만 5천원", "만오천원", "만 오천원", "일만오천원", "1.5만원", "15k",
                   "₩15,000", "15000", "만오천"],
           12000: ["12000원", "12,000원", "1만2천원", "만이천원", "1.2만원", "12k"],
           60000: ["60000원", "6만원", "육만원", "6만 원", "60,000원"]}
MERCHANTS = {"스타벅스": ["스벅", "스타벅스", "starbucks", "STARBUCKS", "Starbucks", "스타 벅스"],
             "GS25": ["GS25", "gs25", "gs 25", "지에스25", "GS 편의점"],
             "CU": ["CU", "cu", "씨유"],
             "이마트": ["이마트", "emart", "E마트"]}
TIMES = {14: ["오후 2시", "14시", "오후 두시", "14:00", "낮 2시"], 23: ["밤 11시", "23시", "밤 열한시", "23:30", "오후 11시"]}
TAILS = ["", " 결제하면?", " 쓰면 얼마 할인돼?", " 뭐가 이득이야?", " 어떤 카드로 결제할까", "에서 결제"]


def paraphrases():
    groups = []
    for merchant, mws in MERCHANTS.items():
        amount = 60000 if merchant == "이마트" else 15000 if merchant == "스타벅스" else 12000
        for hour, tws in TIMES.items():
            qs = []
            for mw in mws:
                for aw in AMOUNTS[amount]:
                    qs.append(f"{tws[0]} {mw} {aw}")
            for tw in tws:
                qs.append(f"{tw} {mws[0]} {AMOUNTS[amount][0]}")
            for tail in TAILS:
                qs.append(f"{tws[0]} {mws[0]} {AMOUNTS[amount][0]}{tail}")
            qs += [f"{mws[0]} {AMOUNTS[amount][0]} {tws[0]}", f"{mws[0]}에서 {tws[0]}에 {AMOUNTS[amount][0]}"]
            groups.append((f"{merchant} {amount:,}원 {hour}시", qs))
    return groups


for name, qs in paraphrases():
    base, _ = results(qs[0])
    for q in qs[1:]:
        got, t = results(q)
        if got != base:
            p = t["context"]["parsed"]
            fail("1. 같은 뜻 다른 결과", f"[{name}] '{q}' → {got[:3]}  (기준 '{qs[0]}' → {base[:3]})"
                 f"  해석: 가맹점={p.get('merchant')} 금액={p.get('amount')} 시각={p.get('hour')}")

# 1-b. 결제와 상관없는 숫자·말이 섞여도 결과가 같아야 함
NOISE = [("오후 2시 스벅 15000원", ["오후 2시 강남역 2번 출구 스벅 15000원", "오후 2시 스벅 3층 매장 15000원",
                                  "오후 2시 2호선 타고 가서 스벅 15000원", "10월에 오후 2시 스벅 15000원",
                                  "오후 2시 친구 2명이랑 스벅 15000원", "오후 2시 스벅 15000원어치", "오후 2시 스벅에서 15000원 결제했어",
                                  "오후 2시 15000원 스벅", "오후 2시 스벅 15000원 할인 몇 % 돼?", "오후 2시 1층 스벅에서 15000원",
                                  "오늘 오후 2시 스벅 15000원", "오후 2시 스벅 15000원 결제 예정 (3번째 방문)"]),
         ("토요일 이마트 6만원", ["토요일 이마트 성수점 6만원", "토요일 이마트 B1층 6만원", "이번주 토요일 이마트 6만원",
                               "토요일 이마트에서 장보기 6만원", "토요일 이마트 6만원 정도 쓸 듯", "토요일에 이마트 가서 6만원"]),
         ("밤 11시 택시 9000원", ["밤 11시 택시 9000원 나왔어", "밤 11시 택시비 9000원", "밤 11시에 택시 타고 9000원",
                               "밤 11시 강남에서 택시 9000원", "밤 11시 택시 2명 9000원"])]
for base_q, variants in NOISE:
    base, _ = results(base_q)
    for q in variants:
        got, t = results(q)
        if got != base:
            p = t["context"]["parsed"]
            fail("1-b. 상관없는 숫자·말 때문에 결과가 달라짐", f"'{q}' → {got[:3]}  (기준 '{base_q}' → {base[:3]})"
                 f"  해석: 가맹점={p.get('merchant')} 금액={p.get('amount')} 시각={p.get('hour')} 요일={p.get('day')} 해외={p.get('overseas')}")

# ---------- 2. 카드 데이터의 가맹점을 모두 알아듣는지 ----------
seen = set()
for cid, c in CARDS.items():
    for b in c["benefits"]:
        for m in b["merchants"]:
            if m in seen:
                continue
            seen.add(m)
            q = f"{m} 30000원"
            p = bot.parse(q)
            got = normalize(p["merchant"])[0] if p["merchant"] else None
            if got != normalize(m)[0]:
                fail("2. 카드 데이터의 가맹점을 못 알아들음", f"'{q}' → 가맹점 {p['merchant']!r} (표준 {got!r}, 정답 {m!r}, 예: {c['card_name']} '{b['name']}')")

# ---------- 3. 단조성 ----------
MERCH = sorted({m for c in CARDS.values() for b in c["benefits"] for m in b["merchants"]} |
               {"편의점", "커피", "주유소", "대중교통", "택시", "음식점", "할인마트", "통신"})
for cid, c in CARDS.items():
    prof = FULL.get(cid, Profile())
    for m in MERCH:
        prev = None
        for amount in (1000, 5000, 9999, 10000, 15000, 20000, 30000, 50000, 100000, 300000):
            r = evaluate_card(c, Tx(m, amount, hour=14, day="수", liters=amount / 2000), prof, suggest=False)
            if r.unit == "원" and r.value > amount:
                fail("3. 혜택이 결제 금액보다 큼", f"{c['card_name']} {m} {amount:,}원 → {r.value:,}원")
            if prev is not None and r.value < prev[1]:
                fail("3. 금액이 늘었는데 혜택이 줄어듦", f"{c['card_name']} {m}: {prev[0]:,}원 → {prev[1]:,}, {amount:,}원 → {r.value:,}")
            prev = (amount, r.value)
        prev = None
        for pm in (0, 100000, 200000, 300000, 400000, 500000, 600000, 1000000, 1200000, 2000000):
            p2 = Profile(**{**prof.__dict__, "prev_month": pm})
            r = evaluate_card(c, Tx(m, 30000, hour=14, day="수", liters=15), p2, suggest=False)
            if prev is not None and r.value < prev[1]:
                fail("3. 전월 실적이 늘었는데 혜택이 줄어듦", f"{c['card_name']} {m} 30,000원: 전월 {prev[0]:,} → {prev[1]:,}, 전월 {pm:,} → {r.value:,}")
            prev = (pm, r.value)

# ---------- 4. 범위 일관성 ----------
CHECK = [c for c in CARDS if CARDS[c]["card_type"] == "체크"]
CREDIT = [c for c in CARDS if CARDS[c]["card_type"] == "신용"]
WORDS = {c: bot.CARD_KEYWORDS[c][0] for c in CARDS}
for base_q in ["오후 2시 스벅 15000원", "오후 2시 GS25 12000원", "토요일 이마트 6만원", "밤 11시 택시 9000원",
               "주말에 주유소 8만원 50리터", "해외에서 10만원", "넷플릭스 13500원", "오후 2시 편의점 12000원"]:
    for label, ids, prefix in (("체크", CHECK, "체크카드 중에 "), ("신용", CREDIT, "신용카드로 ")):
        a, _ = results(prefix + base_q)
        only = {cid: FULL[cid] for cid in ids}
        b, _ = results(base_q, only)
        if a != b:
            fail("4. 카드 범위 말로 묻기 ≠ 카드 골라서 묻기", f"'{prefix}{base_q}' → {a}  /  {label}카드만 골라서 → {b}")
    for cid in CARDS:
        a, t = results(f"{WORDS[cid]}로 {base_q}")
        alone, _ = results(base_q, {cid: FULL[cid]})
        if a != alone:
            fail("4. 카드 이름 말로 묻기 ≠ 그 카드만 골라서 묻기",
                 f"'{WORDS[cid]}로 {base_q}' → {a}  /  {CARDS[cid]['card_name']}만 골라서 → {alone}  (해석 카드={t['context']['parsed'].get('card')})")

# ---------- 5. 사용 기록 ----------
for cid, c in CARDS.items():
    for b in c["benefits"]:
        caps, ms = b["caps"], (b["merchants"] or b["merchant_categories"] or [None])
        m = ms[0] if ms[0] != "전체" else "다이소"
        tx = Tx(m, 30000, hour=14, day="토" if "토" in b["requires"]["days"] else "수", liters=15,
                overseas=b["scope"] == "해외", pay_method=(b["requires"]["pay_methods"] or [None])[0])
        prof = Profile(**{**FULL.get(cid, Profile()).__dict__, "options": dict(b["requires"]["option"] or {}),
                          "enrolled": True})
        got = []
        for i in range(40):
            r = evaluate_card(c, tx, prof, suggest=False)
            mine = [x for x in r.applied if x.benefit_id == b["id"]]
            got.append(mine[0].value if mine else 0)
            prof = add_usage(prof, r.usage)
            for k in ("count_today",):                              # 매일 새로 쓰는 것으로 (일 횟수 초기화)
                for u in prof.used_benefits.values():
                    u[k] = 0
        cnt = sum(1 for v in got if v > 0)
        if caps["benefit_per_month"] and sum(got) > caps["benefit_per_month"]:
            fail("5. 기록을 반복하면 월 한도를 넘음", f"{c['card_name']} '{b['name']}': 40번 합계 {sum(got):,} > 월 {caps['benefit_per_month']:,}")
        if caps["count_per_month"] and cnt > caps["count_per_month"]:
            fail("5. 기록을 반복하면 월 횟수를 넘음", f"{c['card_name']} '{b['name']}': {cnt}회 > 월 {caps['count_per_month']}회")

# ---------- 6. 이상한 입력에도 멈추지 않음 ----------
ODD = ["", " ", "?", "ㅋㅋㅋㅋ", "😀☕ 15000원", "스벅" * 150, "0", "-1", "1e9원", "NaN원", "스벅 0.0001원", "스벅 99999999999원",
       "스벅 15000원 15000원 15000원", "<b>스벅</b> 15000원", "'; DROP TABLE cards; --", "스벅\n15000원", "스벅\t15000원",
       "스벅 ①②③원", "스벅 15000원??!!", "카드", "혜택", "실적", "전월", "노리 노리 노리", "체크카드 신용카드 스벅 15000원",
       "노리 말고 헤이영 말고 굿데이 말고 스벅 15000원", "만", "억", "천원", "100억원 스벅", "오후 25시 스벅 15000원",
       "32:99 택시 9000원", "토요일 일요일 이마트 6만원", "스벅 15000원짜리 0잔", "스벅 15000원짜리 100잔"]
for q in ODD:
    try:
        t = bot.ask_turn(q, FULL)
        if not t["answer"].strip():
            fail("6. 이상한 입력에 빈 답변", repr(q[:60]))
        for r in t["view"].get("results", []):
            if r["value"] < 0:
                fail("6. 이상한 입력에 음수 혜택", f"{q[:60]!r} → {r['card_id']} {r['value']}")
    except Exception as e:
        fail("6. 이상한 입력에 오류(멈춤)", f"{q[:60]!r} → {e!r}")

for q in ["오후 25시 스벅 15000원", "밤 30시 택시 9000원", "32:99 택시 9000원"]:
    if bot.parse(q)["hour"] is not None:
        fail("6. 없는 시각을 다른 시각으로 바꿔 읽음", f"{q!r} → {bot.parse(q)['hour']}시")
for q in ["100억원 스벅", "스벅 99999999999원", "스벅 2억원"]:
    t = bot.ask_turn(q, FULL)
    if t["view"].get("results"):
        fail("6. 말이 안 되게 큰 금액을 그대로 계산", f"{q!r} → {t['view']['tx']}")

# ---------- 7. 카드 별칭마다 그 카드 정보로 ----------
for cid, kws in bot.CARD_KEYWORDS.items():
    for kw in kws:
        t = bot.ask_turn(f"{kw} 혜택 알려줘", FULL)
        p = t["context"]["parsed"]
        if p.get("card") != cid or CARDS[cid]["card_name"] not in t["answer"]:
            fail("7. 카드 별칭으로 물었는데 다른 답", f"'{kw} 혜택 알려줘' → 해석 카드 {p.get('card')} (정답 {cid}), 종류 {p.get('intent')}")

# ---------- 결과 ----------
total = sum(len(v) for v in fails.values())
head = [f"성질 검사 결과 - {dt.datetime.now():%Y-%m-%d %H:%M}", "=" * 70,
        f"오류 {total}건" + (" (없음)" if not total else "")]
for g, items in fails.items():
    head.append(f"- {g}: {len(items)}건")
body = []
for g, items in fails.items():
    body += ["", f"■ {g} ({len(items)}건)", "-" * 70, *items]
out = ROOT / "tests" / "property_results.txt"
out.write_text("\n".join(head + body) + "\n", encoding="utf-8")
print("\n".join(head))
