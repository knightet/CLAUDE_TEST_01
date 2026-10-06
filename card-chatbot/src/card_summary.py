"""카드 JSON -> 카드별 특징 요약 (모든 카드가 같은 목차)

실행: python src/card_summary.py  ->  data/cards/summary/*.md, data/cards/summary/_overview.md
JSON을 고친 뒤 다시 실행하면 요약도 같이 바뀌어요. 요약 파일은 직접 고치지 마세요.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.card_schema import CARD_DIR, load_all

OUT = CARD_DIR / "summary"


def won(n) -> str:
    return "-" if n is None else f"{n:,}원"


def reward_text(b: dict, unit: str) -> str:
    r = b["reward"]
    if r["kind"] == "정률":
        return f"{r['rate'] * 100:g}%"
    if r["kind"] == "정액":
        return f"US${r['amount_usd']:g}" if r["amount_usd"] is not None else won(r["amount"])
    if r["kind"] == "리터당":
        return f"리터당 {r['per_liter']}원"
    return f"1,000원당 {r['miles_per_1000']}마일"


def where_text(b: dict) -> str:
    parts = b["merchants"] + [f"{c} 업종" for c in b["merchant_categories"] if c != "전체"]
    if "전체" in b["merchant_categories"]:
        parts.insert(0, "모든 가맹점")
    return ", ".join(parts) + (" (해외)" if b["scope"] == "해외" else "")


def condition_text(card: dict, b: dict) -> str:
    q, out = b["requires"], []
    tiers = {t["id"]: t for t in card["tiers"]}
    if q["tier"]:
        out.append(f"전월 {tiers[q['tier']]['prev_month_min']:,}원 이상({q['tier']})")
    if q["prev_month_min"] == 0:
        out.append("실적 조건 없음")
    elif q["prev_month_min"] == 1:
        out.append("전월 이용 실적 있음")
    elif q["prev_month_min"]:
        out.append(f"전월 {q['prev_month_min']:,}원 이상")
    if q["min_payment_per_txn"]:
        out.append(f"건당 {q['min_payment_per_txn']:,}원 이상")
    if q["pay_methods"]:
        out.append("/".join(q["pay_methods"]) + " 결제")
    if q["channel"]:
        out.append(q["channel"])
    if q["days"]:
        out.append("·".join(q["days"]) + "요일")
    if q["hours"]:
        out.append(f"{q['hours']['from']}~{q['hours']['to']}")
    if q["option"]:
        out.append(", ".join(f"{v} 선택 시" for v in q["option"].values()))
    if q["card_brand"]:
        out.append(q["card_brand"])
    if q["enrollment"]:
        out.append(q["enrollment"])
    if q["valid_period"]:
        out.append(f"{q['valid_period']['from']}~{q['valid_period']['to']}")
    return ", ".join(out) or "-"


def limit_text(card: dict, b: dict) -> str:
    c, out = b["caps"], []
    labels = [("eligible_per_txn", "건당 대상금액 {}"), ("benefit_per_txn", "건당 최대 {}"),
              ("eligible_per_day", "일 대상금액 {}"), ("eligible_per_month", "월 대상금액 {}"),
              ("benefit_per_month", "월 최대 {}"), ("benefit_per_year", "연 최대 {}")]
    for k, fmt in labels:
        if c[k] is not None:
            out.append(fmt.format(won(c[k])))
    counts = [f"{label} {c[k]}회" for k, label in
              (("count_per_day", "일"), ("count_per_month", "월"), ("count_per_year", "연")) if c[k]]
    if counts:
        out.append("/".join(counts) + (f"({c['count_scope']})" if c["count_scope"] else ""))
    groups = {g["id"]: g["name"] for g in card["limit_groups"]}
    out += [f"[{groups[g]}]" for g in b["groups"]]
    return ", ".join(out) or "없음"


def group_text(card: dict, g: dict) -> str:
    unit = "마일" if g["kind"] == "마일리지" else "원"
    parts = []
    if g["per_month_by_tier"]:
        tiers = {t["id"]: t for t in card["tiers"]}
        parts.append(" / ".join(f"{t}(전월 {tiers[t]['prev_month_min']:,}원↑) {v:,}{unit}"
                                for t, v in g["per_month_by_tier"].items()))
    for k, label in (("per_day", "일"), ("per_month", "월"), ("per_year", "연")):
        if g[k] is not None:
            parts.append(f"{label} {g[k]:,}{unit}")
    return f"{g['name']} ({g['kind']} 기준): " + ", ".join(parts)


def page(src) -> str:
    return f"{src['file']} {src['page']}p" if src and src.get("page") else (src["file"] if src else "-")


def card_md(card: dict) -> str:
    pm, fee = card["prev_month"], card["annual_fee"]
    L = [f"# {card['card_name']}", "",
         "> 이 파일은 `data/cards/" + card["card_id"] + ".json`에서 자동 생성됩니다. 직접 고치지 마세요.", "",
         "## 1. 기본 정보", "",
         "| 항목 | 내용 |", "|---|---|",
         f"| 카드사 | {card['issuer']} |",
         f"| 종류 | {card['card_type']} |",
         f"| 혜택 단위 | {'마일리지 적립' if card['reward_unit'] == '마일' else '원화 할인·캐시백'} |",
         f"| 연회비 | 국내 {won(fee['domestic'])} / 해외겸용 {won(fee['overseas'])}"
         + (f" / 모바일 {won(fee['mobile'])}" if fee["mobile"] is not None else "") + " |",
         f"| 연회비 참고 | {fee['note'] or '-'} |",
         f"| 발급 조건 | {', '.join(card['issue_notes']) or '-'} |",
         f"| 근거 자료 | " + "<br>".join(f"{s['kind']}: {s['file']} ({s['date'] or '날짜 없음'})" for s in card["sources"]) + " |",
         "", "## 2. 전월 실적", "",
         "| 항목 | 내용 |", "|---|---|",
         f"| 최소 전월 실적 | {won(pm['required_min']) if pm['required_min'] else '조건 없음'} |",
         f"| 산정 기준 | {pm['basis'] or '-'} |",
         f"| 신규 발급 특례 | {pm['grace']['description'] if pm['grace'] else '없음'} |",
         f"| 실적 제외 항목 | {', '.join(pm['excluded']) or '-'} |",
         f"| 근거 | {page(pm['source'])} |",
         "", "## 3. 실적 구간과 공유 한도", ""]
    if card["tiers"]:
        L.append("구간: " + " / ".join(
            f"{t['id']} {t['prev_month_min']:,}원 이상" + (f" ~ {t['prev_month_max']:,}원" if t["prev_month_max"] else "")
            for t in card["tiers"]))
        L.append("")
    L += [f"- {group_text(card, g)}" for g in card["limit_groups"]] or ["- 여러 혜택이 함께 쓰는 한도 없음"]
    if card["options"]:
        L += [""] + [f"- 선택형: {o['name']} ({' / '.join(o['choices'])}) — {o['note'] or ''}" for o in card["options"]]
    L += ["", "## 4. 혜택", "",
          "| 혜택 | 대상 | 혜택 | 조건 | 한도·횟수 | 근거 |", "|---|---|---|---|---|---|"]
    for b in card["benefits"]:
        L.append(f"| {b['name']} | {where_text(b)} | {reward_text(b, card['reward_unit'])} | "
                 f"{condition_text(card, b)} | {limit_text(card, b)} | {page(b['source'])} |")
    L += ["", "### 혜택별 제외·주의", ""]
    for b in card["benefits"]:
        extra = b["exclusions"] and [f"제외: {', '.join(b['exclusions'])}"] or []
        if b["stacking"]["rule"]:
            extra.append(f"중복: {b['stacking']['rule']}")
        extra += b["notes"]
        if extra:
            L.append(f"- **{b['name']}**: " + " / ".join(extra))
    L += ["", "## 5. 부가서비스 (금액 계산 안 함)", ""]
    L += [f"- **{p['name']}**: {p['detail']}" + (f" (조건: {'; '.join(p['conditions'])})" if p["conditions"] else "")
          + f" — {page(p['source'])}" for p in card["perks"]] or ["- 없음"]
    L += ["", "## 6. 공통 제외 대상", "", ", ".join(card["common_exclusions"]) or "없음",
          "", "## 7. 참고", ""]
    L += [f"- {n}" for n in card["notes"]] or ["- 없음"]
    rv = card["review"]
    L += ["", "## 8. 검수 상태", "", f"- 상태: {rv['status']}",
          f"- 확인한 부분: {', '.join(rv['checked']) or '-'}",
          f"- 남은 일: {', '.join(rv['todo']) or '-'}", ""]
    return "\n".join(L)


def overview_md(cards: dict) -> str:
    L = ["# 카드 한눈에 보기", "", "> `python src/card_summary.py`로 자동 생성됩니다."]
    for t in ("체크", "신용"):
        group = [c for c in cards.values() if c["card_type"] == t]
        L += ["", f"## {t}카드 ({len(group)}장)", "",
              "| 카드 | 카드사 | 연회비(국내) | 최소 전월 실적 | 혜택 수 | 주요 혜택 | 검수 |", "|---|---|---|---|---|---|---|"]
        for c in group:
            top = ", ".join(f"{b['name'].split('] ')[-1]} {reward_text(b, c['reward_unit'])}" for b in c["benefits"][:3])
            L.append(f"| [{c['card_name']}]({c['card_id']}.md) | {c['issuer']} | {won(c['annual_fee']['domestic'])} | "
                     f"{won(c['prev_month']['required_min']) if c['prev_month']['required_min'] else '조건 없음'} | "
                     f"{len(c['benefits'])} | {top} | {c['review']['status']} |")
    return "\n".join(L) + "\n"


def main():
    OUT.mkdir(exist_ok=True)
    cards = load_all()
    for cid, c in cards.items():
        (OUT / f"{cid}.md").write_text(card_md(c), encoding="utf-8")
    (OUT / "_overview.md").write_text(overview_md(cards), encoding="utf-8")
    print(f"요약 {len(cards)}개 + _overview.md 생성: {OUT}")


if __name__ == "__main__":
    main()
