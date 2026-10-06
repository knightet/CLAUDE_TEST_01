"""카드 데이터 표준 구조 (schema v2)

모든 카드 JSON은 같은 키를 갖고, 해당 없는 값은 null / 빈 목록으로 둬요.
필드 설명: data/cards/README.md

사용법
  python src/card_schema.py            # data/cards/*.json 검사만
  python src/card_schema.py --fix      # 빠진 키를 기본값으로 채워서 다시 저장
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARD_DIR = ROOT / "data" / "cards"
SCHEMA_VERSION = "2.0"

CARD = {
    "schema_version": SCHEMA_VERSION,
    "card_id": "",
    "card_name": "",
    "issuer": "",
    "card_type": "",            # "신용" | "체크"
    "reward_unit": "원",         # "원" | "마일"  (마일은 원화 할인과 같은 기준으로 순위를 매기지 않음)
    "sources": [],              # SOURCE 목록
    "annual_fee": {"domestic": None, "overseas": None, "mobile": None, "note": None},
    "issue_notes": [],          # 발급 대상·조건
    "prev_month": {
        "required_min": None,   # 혜택을 받기 위한 최소 전월 실적 (없으면 null)
        "period": None,
        "basis": None,
        "excluded": [],         # 전월 실적에서 빠지는 항목
        "grace": None,          # GRACE 또는 null
        "source": None,         # SOURCE_REF
    },
    "tiers": [],                # TIER 목록 (실적 구간이 없으면 빈 목록)
    "limit_groups": [],         # GROUP 목록 (여러 혜택이 함께 쓰는 한도)
    "options": [],              # OPTION 목록 (사용자가 고르는 선택형 혜택)
    "benefits": [],             # BENEFIT 목록
    "common_exclusions": [],    # 모든 할인·적립에서 빠지는 결제
    "perks": [],                # PERK 목록 (금액으로 계산하지 않는 부가서비스)
    "notes": [],
    "review": {"status": "초안 - 사람 검수 필요", "checked": [], "todo": []},
}

SOURCE = {"file": "", "kind": "", "doc_code": None, "date": None, "note": None}
SOURCE_REF = {"file": "", "page": None}

GRACE = {
    "description": "",
    "period": "",
    "effect": "",               # "tier"(그 구간으로 간주) | "limit_override"(월 한도 고정) | "limit_ratio"(한도의 비율)
    "tier": None,
    "limit": None,
    "limit_ratio": None,
    "only_benefits": [],        # 비어 있으면 모든 혜택
    "excluded_benefits": [],
}

TIER = {"id": "", "prev_month_min": 0, "prev_month_max": None}

GROUP = {
    "id": "",
    "name": "",
    "kind": "할인액",            # "할인액" | "이용금액" | "마일리지"
    "per_day": None,
    "per_month": None,
    "per_year": None,
    "per_month_by_tier": None,  # {"T1": 10000, ...} 구간마다 다를 때
    "note": None,
    "source": None,
}

OPTION = {"id": "", "name": "", "choices": [], "note": None}

BENEFIT = {
    "id": "",
    "name": "",
    "category": "",
    "merchants": [],            # 특정 가맹점 (표준 이름)
    "merchant_categories": [],  # 업종 (README의 업종 목록)
    "scope": "국내",             # "국내" | "해외" | "전체"(국내+해외)
    "reward": {
        "kind": "",             # "정률" | "정액" | "리터당" | "마일리지"
        "rate": None,
        "amount": None,
        "amount_usd": None,
        "per_liter": None,
        "miles_per_1000": None,
        "rounding": None,
    },
    "requires": {
        "tier": None,               # 이 구간 이상일 때만 (예: "T2")
        "prev_month_min": None,     # 혜택 자체의 실적 조건. null이면 카드의 prev_month.required_min, 0이면 조건 없음
        "option": None,             # {"pack": "A"}
        "pay_methods": [],          # 이 결제수단일 때만 (예: ["KB Pay"])
        "channel": None,            # "온라인" | "오프라인"
        "days": [],                 # ["토", "일"]
        "hours": None,              # {"from": "21:00", "to": "09:00"}
        "min_payment_per_txn": None,
        "card_brand": None,         # 예: "해외겸용"
        "enrollment": None,         # 별도 가입·신청이 필요하면 설명
        "valid_period": None,       # {"from": "2026-02-26", "to": "2026-12-31"}
    },
    "caps": {
        "eligible_per_txn": None,   # 건당 할인 대상 금액 상한
        "benefit_per_txn": None,    # 건당 할인액 상한
        "eligible_per_day": None,
        "eligible_per_month": None,
        "benefit_per_month": None,
        "benefit_per_year": None,
        "count_per_day": None,
        "count_per_month": None,
        "count_per_year": None,
        "count_scope": None,        # "혜택" | "가맹점별" | "영역 통합"
    },
    "groups": [],                   # 이 혜택이 함께 쓰는 GROUP id
    "stacking": {
        "stacks_on": None,          # 추가 할인이면 기준 혜택 id ("*"는 어떤 혜택 위에도 더해짐)
        "exclusive_with": [],       # 동시에 받을 수 없는 혜택 id
        "rule": None,               # 중복 규칙 설명
    },
    "exclusions": [],
    "notes": [],
    "source": None,                 # SOURCE_REF
}

PERK = {"id": "", "name": "", "detail": "", "conditions": [], "source": None}

NESTED = {
    ("sources", "*"): SOURCE,
    ("prev_month", "grace"): GRACE,
    ("prev_month", "source"): SOURCE_REF,
    ("tiers", "*"): TIER,
    ("limit_groups", "*"): GROUP,
    ("limit_groups", "*", "source"): SOURCE_REF,
    ("options", "*"): OPTION,
    ("benefits", "*"): BENEFIT,
    ("benefits", "*", "source"): SOURCE_REF,
    ("perks", "*"): PERK,
    ("perks", "*", "source"): SOURCE_REF,
}


def _fill(template: dict, data: dict, path: str, errors: list) -> dict:
    out = copy.deepcopy(template)
    for k, v in data.items():
        if k not in template:
            errors.append(f"{path}.{k}: 정의에 없는 키")
            continue
        if isinstance(template[k], dict) and isinstance(v, dict):
            out[k] = _fill(template[k], v, f"{path}.{k}", errors)
        else:
            out[k] = v
    return out


def normalize(card: dict) -> tuple[dict, list]:
    """빠진 키를 채우고, 모르는 키를 오류로 모아요"""
    errors = []
    out = _fill(CARD, card, card.get("card_id", "?"), errors)
    for (field, *rest), tmpl in NESTED.items():
        if rest == ["*"]:
            out[field] = [_fill(tmpl, x, f"{out['card_id']}.{field}[{i}]", errors)
                          for i, x in enumerate(out[field])]
        elif rest[:1] == ["*"]:
            sub = rest[1]
            for i, x in enumerate(out[field]):
                if x.get(sub) is not None:
                    x[sub] = _fill(tmpl, x[sub], f"{out['card_id']}.{field}[{i}].{sub}", errors)
        elif out[field].get(rest[0]) is not None:
            out[field][rest[0]] = _fill(tmpl, out[field][rest[0]], f"{out['card_id']}.{field}.{rest[0]}", errors)
    errors += check(out)
    return out, errors


def check(card: dict) -> list:
    """값이 서로 맞는지 (참조하는 id가 실제로 있는지 등)"""
    errors, cid = [], card["card_id"]
    tiers = {t["id"] for t in card["tiers"]}
    groups = {g["id"] for g in card["limit_groups"]}
    options = {o["id"]: o["choices"] for o in card["options"]}
    benefit_ids = [b["id"] for b in card["benefits"]]
    if card["card_type"] not in ("신용", "체크"):
        errors.append(f"{cid}: card_type은 '신용' 또는 '체크'")
    if len(set(benefit_ids)) != len(benefit_ids):
        errors.append(f"{cid}: 혜택 id 중복")
    for g in card["limit_groups"]:
        for t in (g["per_month_by_tier"] or {}):
            if t not in tiers:
                errors.append(f"{cid}.{g['id']}: 없는 구간 {t}")
    for b in card["benefits"]:
        where = f"{cid}.{b['id']}"
        r = b["reward"]
        need = {"정률": "rate", "정액": None, "리터당": "per_liter", "마일리지": "miles_per_1000"}
        if r["kind"] not in need:
            errors.append(f"{where}: reward.kind는 {list(need)} 중 하나")
        elif r["kind"] == "정액" and r["amount"] is None and r["amount_usd"] is None:
            errors.append(f"{where}: 정액인데 amount가 없음")
        elif need[r["kind"]] and r[need[r["kind"]]] is None:
            errors.append(f"{where}: {r['kind']}인데 {need[r['kind']]}가 없음")
        if not b["merchants"] and not b["merchant_categories"]:
            errors.append(f"{where}: merchants와 merchant_categories가 모두 비어 있음")
        if b["requires"]["tier"] and b["requires"]["tier"] not in tiers:
            errors.append(f"{where}: 없는 구간 {b['requires']['tier']}")
        for k, v in (b["requires"]["option"] or {}).items():
            if v not in options.get(k, []):
                errors.append(f"{where}: 없는 옵션 {k}={v}")
        for g in b["groups"]:
            if g not in groups:
                errors.append(f"{where}: 없는 한도 그룹 {g}")
        s = b["stacking"]
        for ref in [s["stacks_on"], *s["exclusive_with"]]:
            if ref and ref != "*" and ref not in benefit_ids:
                errors.append(f"{where}: 없는 혜택 {ref}")
        if b["source"] is None:
            errors.append(f"{where}: 근거(source) 없음")
    grace = card["prev_month"]["grace"]
    if grace and grace["effect"] == "tier" and grace["tier"] not in tiers:
        errors.append(f"{cid}: grace.tier {grace['tier']}가 구간 목록에 없음")
    return errors


def load_all() -> dict:
    cards = {}
    for p in sorted(CARD_DIR.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        cards[d["card_id"]] = d
    return cards


def main():
    fix = "--fix" in sys.argv
    total = 0
    for p in sorted(CARD_DIR.glob("*.json")):
        raw = json.loads(p.read_text(encoding="utf-8"))
        card, errors = normalize(raw)
        if fix:
            p.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        status = "OK" if not errors else f"오류 {len(errors)}건"
        print(f"{p.name:45s} 혜택 {len(card['benefits']):2d}개  부가서비스 {len(card['perks']):2d}개  {status}")
        for e in errors:
            print("   -", e)
        total += len(errors)
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
