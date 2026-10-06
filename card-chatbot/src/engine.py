"""계산 엔진 v2: 카드 데이터(data/cards) + 결제 상황 + 사용자 상태 -> 혜택 금액과 판정 근거

원칙: 조건 확인과 금액 계산은 전부 여기서 해요. 답변 문장(LLM)은 이 결과를 설명만 해요.
모든 판정은 Step으로 남겨서 화면에 '계산 근거'로 그대로 보여줘요.
"""
from __future__ import annotations

import copy
import datetime as dt
import re
from dataclasses import dataclass, field, asdict

try:
    from src.card_schema import load_all
    from src.normalizer import normalize
except ImportError:
    from card_schema import load_all
    from normalizer import normalize

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
THIRD_PARTY_PAY = ["네이버페이", "카카오페이", "스마일페이", "페이코", "토스페이"]


@dataclass
class Tx:
    merchant: str | None
    amount: int
    pay_method: str | None = None
    channel: str | None = None      # "온라인" | "오프라인" | None(모름)
    location: str | None = None     # "백화점" | "대형마트" 입점 매장
    overseas: bool = False
    day: str | None = None          # "월"~"일", None이면 오늘
    hour: int | None = None         # 0~23, None이면 지금
    liters: float | None = None     # 주유량
    purchase: str | None = None     # "선불충전" | "상품권": 대부분의 카드가 할인에서 빼는 결제
    pay_type: str | None = None     # "인앱결제" | "만나서결제" 같은 결제 방식
    fuel: str | None = None         # "LPG" | "휘발유" | "경유" | "등유"


@dataclass
class Profile:
    prev_month: int = 0
    options: dict = field(default_factory=dict)       # {"pack": "A"}
    enrolled: bool = False                             # 프로모션·멤버십 가입
    in_grace: bool = False                             # 신규 발급 특례 기간
    overseas_brand: bool = True                        # 해외겸용 카드인지
    used_groups: dict = field(default_factory=dict)    # {group_id: 이번 달 사용액(할인액·이용금액·마일)}
    used_benefits: dict = field(default_factory=dict)  # {benefit_id: {"amount": 월 할인액, "count": 월 횟수, "count_today": 오늘 횟수}}
    today: dt.date | None = None


@dataclass
class Step:
    label: str
    detail: str
    ok: bool | None = None          # True 통과 / False 탈락 / None 정보
    source: str | None = None


@dataclass
class BenefitResult:
    benefit_id: str
    name: str
    value: int = 0
    unit: str = "원"
    ok: bool = False
    stop: str | None = None         # 탈락 사유 코드 (개선 제안에 씀)
    steps: list = field(default_factory=list)
    source: str | None = None
    used_groups: dict = field(default_factory=dict)  # 이 결제로 그룹 한도를 얼마나 쓰는지
    usage: dict = field(default_factory=dict)        # 이 결제를 하면 혜택별 사용량에 더할 값 (금액·횟수·대상금액)


@dataclass
class CardResult:
    card_id: str
    card_name: str
    unit: str
    value: int
    applied: list                   # 실제 적용된 BenefitResult
    considered: list                # 대상이었지만 탈락한 BenefitResult
    note: str | None = None
    suggestions: list = field(default_factory=list)
    # "이 카드를 썼어요"를 누르면 이번 달 사용량에 더할 값. 화면은 계산하지 않고 이 값을 그대로 더해요
    usage: dict = field(default_factory=dict)       # {"used_groups": {id: 값}, "used_benefits": {id: {...}}}

    def to_dict(self) -> dict:
        return asdict(self)


CARDS = load_all()


def _src(card: dict, ref: dict | None) -> str | None:
    if not ref:
        return None
    return f"{ref['file']} {ref['page']}p" if ref.get("page") else ref["file"]


def _won(n, unit="원") -> str:
    return f"{n:,}{unit}"


# ---------- 매칭 ----------
def classify(merchant: str | None) -> tuple[str | None, str | None]:
    return normalize(merchant) if merchant else (None, None)


def match(b: dict, std: str | None, cat: str | None, tx: Tx) -> str | None:
    if b["scope"] != "전체" and (b["scope"] == "해외") != tx.overseas:
        return None
    if std and (std in b["merchants"] or std in {normalize(m)[0] for m in b["merchants"]}):
        return f"가맹점 '{std}'"
    if cat and cat in b["merchant_categories"]:
        return f"업종 '{cat}'"
    if "전체" in b["merchant_categories"]:
        return "모든 가맹점" + (" (해외)" if tx.overseas else "")
    return None


def _excluded(texts: list, std: str | None, cat: str | None) -> str | None:
    """제외 문구의 '이름'이 가맹점·업종과 같을 때만 제외.
    '대중교통(시내·광역·시외버스, 지하철)'은 지하철을 제외하지만, '해외 스타벅스'·'스타벅스 카드 충전'은
    국내 스타벅스 결제를 제외하지 않아요."""
    for t in texts:
        head = re.sub(r"\(.*?\)", "", t).strip()
        items = {head} | {x.strip() for inner in re.findall(r"\((.*?)\)", t) for x in re.split(r"[,·/]", inner)}
        if (std and std in items) or (cat and cat in items):
            return t
    return None


# ---------- 실적 구간 ----------
def current_tier(card: dict, prev_month: int) -> str | None:
    best = None
    for t in card["tiers"]:
        if prev_month >= t["prev_month_min"]:
            best = t["id"]
    return best


def _rank(card: dict, tier: str | None) -> int:
    ids = [t["id"] for t in card["tiers"]]
    return ids.index(tier) if tier in ids else -1


def grace_for(card: dict, b: dict, p: Profile) -> dict | None:
    g = card["prev_month"]["grace"]
    if not (p.in_grace and g):
        return None
    if g["only_benefits"] and b["id"] not in g["only_benefits"]:
        return None
    if b["id"] in g["excluded_benefits"]:
        return None
    return g


def effective_tier(card: dict, b: dict, p: Profile) -> str | None:
    tier = current_tier(card, p.prev_month)
    g = grace_for(card, b, p)
    if g and g["effect"] == "tier" and _rank(card, g["tier"]) > _rank(card, tier):
        return g["tier"]
    return tier


def check_prev_month(card: dict, b: dict, p: Profile) -> tuple[bool, str, str | None]:
    """(통과, 설명, 탈락 코드)"""
    pm, req = p.prev_month, b["requires"]
    g = grace_for(card, b, p)
    tier = effective_tier(card, b, p)
    tiers = {t["id"]: t for t in card["tiers"]}
    tier_txt = f" → 구간 {tier}" if tier else ""
    if req["prev_month_min"] == 0:
        return True, "전월 실적 조건 없음", None
    if req["prev_month_min"] == 1:
        if pm > 0 or g:
            return True, f"전월 이용 실적 있음 ({_won(pm)})" if pm > 0 else "신규 발급 특례로 실적 무관", None
        return False, "전월 이용 실적이 있어야 함 (현재 0원)", "prev_month"
    need_tier = req["tier"]
    if need_tier:
        if _rank(card, tier) >= _rank(card, need_tier):
            via = " (신규 발급 특례)" if g and current_tier(card, pm) != tier else ""
            return True, f"전월 {_won(pm)}{tier_txt}, 필요 구간 {need_tier}({_won(tiers[need_tier]['prev_month_min'])} 이상){via}", None
        return False, f"전월 {_won(tiers[need_tier]['prev_month_min'])} 이상({need_tier}) 필요, 현재 {_won(pm)}", "tier"
    need = req["prev_month_min"] if req["prev_month_min"] is not None else card["prev_month"]["required_min"]
    if not need:
        return True, "전월 실적 조건 없음", None
    if pm >= need:
        return True, f"전월 {_won(pm)} ≥ {_won(need)}{tier_txt}", None
    if g and g["effect"] in ("limit_override", "limit_ratio", "tier"):
        if g["effect"] == "tier" and req["prev_month_min"] and req["prev_month_min"] > tiers.get(g["tier"], {}).get("prev_month_min", 0):
            return False, f"전월 {_won(need)} 이상 필요, 현재 {_won(pm)} (특례 구간으로도 부족)", "prev_month"
        return True, f"전월 {_won(pm)} < {_won(need)}이지만 신규 발급 특례 적용 ({g['description']})", None
    return False, f"전월 {_won(need)} 이상 필요, 현재 {_won(pm)}", "prev_month"


# ---------- 혜택 하나 계산 ----------
def _today(p: Profile) -> dt.date:
    return p.today or dt.date.today()


def evaluate_benefit(card: dict, b: dict, tx: Tx, p: Profile, how: str) -> BenefitResult:
    unit = "마일" if b["reward"]["kind"] == "마일리지" else "원"
    r = BenefitResult(b["id"], b["name"], unit=unit, source=_src(card, b["source"]))
    S = r.steps.append
    req, caps = b["requires"], b["caps"]
    std, cat = classify(tx.merchant)

    def fail(code, label, detail):
        S(Step(label, detail, False))
        r.stop = code
        return r

    S(Step("대상", f"{how} → {b['name']}", True, r.source))

    hit = _excluded(b["exclusions"] + card["common_exclusions"], std, cat)
    if hit:
        return fail("excluded", "제외 대상", f"'{hit}'은(는) 이 혜택에서 제외")
    if tx.purchase:
        words = {"선불충전": ("충전", "선불"), "상품권": ("상품권",)}.get(tx.purchase, ())
        hit = next((e for e in b["exclusions"] + card["common_exclusions"] if any(w in e for w in words)), None)
        if hit:
            return fail("excluded", "제외 대상", f"{tx.purchase} 결제는 제외 ('{hit}')")
    for term in (tx.pay_type, tx.fuel):
        if term:
            hit = next((e for e in b["exclusions"] + card["common_exclusions"] if term in e.replace(" ", "")), None)
            if hit:
                return fail("excluded", "제외 대상", f"{term}은(는) 제외 ('{hit}')")
    if tx.location:
        loc_words = ("입점", "임대매장", tx.location, "할인점" if tx.location == "대형마트" else tx.location)
        hit = next((e for e in b["exclusions"] + card["common_exclusions"] if any(w in e for w in loc_words)), None)
        if hit:
            return fail("location", "제외 대상", f"{tx.location} 안 매장은 제외될 수 있음 ('{hit}')")

    if req["option"]:
        for k, v in req["option"].items():
            cur = p.options.get(k)
            if cur != v:
                return fail("option", "선택 옵션", f"'{v}' 선택 시에만 (현재: {cur or '선택 안 함'})")
        S(Step("선택 옵션", f"'{', '.join(req['option'].values())}' 선택함", True))
    if req["valid_period"]:
        today = _today(p).isoformat()
        vp = req["valid_period"]
        if not (vp["from"] <= today <= vp["to"]):
            return fail("period", "적용 기간", f"{vp['from']}~{vp['to']} 기간만 (오늘 {today})")
    if req["enrollment"]:
        if not p.enrolled:
            return fail("enrollment", "가입 조건", f"{req['enrollment']} 필요 (가입 안 함으로 설정됨)")
        S(Step("가입 조건", f"{req['enrollment']} 완료", True))
    if req["card_brand"] and "해외겸용" in req["card_brand"] and not p.overseas_brand:
        return fail("brand", "카드 브랜드", f"{req['card_brand']} 카드만 (국내전용으로 설정됨)")
    if req["pay_methods"]:
        if tx.pay_method not in req["pay_methods"]:
            return fail("pay_method", "결제수단", f"{'/'.join(req['pay_methods'])}로 결제 시에만 (이번 결제: {tx.pay_method or '카드 실물'})")
        S(Step("결제수단", f"{tx.pay_method}로 결제", True))
    elif tx.pay_method in THIRD_PARTY_PAY and any("간편결제" in e for e in card["common_exclusions"]):
        return fail("pay_method", "결제수단", f"{tx.pay_method}처럼 가맹점명이 간편결제사로 승인되면 제외될 수 있음")
    if req["channel"] and tx.channel and tx.channel != req["channel"]:
        return fail("channel", "결제 방식", f"{req['channel']} 결제만 (이번 결제: {tx.channel})")
    if req["days"]:
        day = tx.day or WEEKDAYS[_today(p).weekday()]
        if day not in req["days"]:
            return fail("days", "요일", f"{'·'.join(req['days'])}요일에만 (결제일: {day}요일{'' if tx.day else ', 오늘 기준'})")
        S(Step("요일", f"{day}요일", True))
    if req["hours"]:
        hour = tx.hour if tx.hour is not None else dt.datetime.now().hour
        start, end = int(req["hours"]["from"][:2]), int(req["hours"]["to"][:2])
        inside = start <= hour or hour < end if start > end else start <= hour < end
        if not inside:
            return fail("hours", "시간대", f"{req['hours']['from']}~{req['hours']['to']} 승인 건만 (결제 시각: {hour}시{'' if tx.hour is not None else ', 지금 기준'})")
        S(Step("시간대", f"{hour}시 결제", True))

    ok, detail, code = check_prev_month(card, b, p)
    if not ok:
        return fail(code, "전월 실적", detail)
    S(Step("전월 실적", detail, True, _src(card, card["prev_month"]["source"])))

    minp = req["min_payment_per_txn"]
    if minp:
        if tx.amount < minp:
            return fail("min_payment", "건당 최소 결제", f"{_won(tx.amount)} < {_won(minp)} (부족 {_won(minp - tx.amount)})")
        S(Step("건당 최소 결제", f"{_won(tx.amount)} ≥ {_won(minp)}", True))

    used = p.used_benefits.get(b["id"], {})
    for key, label, used_key in (("count_per_month", "월", "count"), ("count_per_day", "일", "count_today")):
        lim = caps[key]
        if lim:
            left = lim - used.get(used_key, 0)
            if left <= 0:
                return fail("count", "횟수", f"{label} {lim}회 모두 사용함")
            S(Step("횟수", f"{label} {lim}회 중 {left}회 남음", True))

    # 할인 대상 금액
    g = grace_for(card, b, p)
    ratio = g["limit_ratio"] if g and g["effect"] == "limit_ratio" else 1
    base = tx.amount
    if caps["eligible_per_txn"] and base > caps["eligible_per_txn"]:
        base = caps["eligible_per_txn"]
        S(Step("건당 대상금액 상한", f"{_won(tx.amount)} 중 {_won(base)}까지만 할인 대상", None))
    if caps["eligible_per_month"]:
        left = caps["eligible_per_month"] - used.get("eligible", 0)
        if left <= 0:
            return fail("limit", "월 대상금액", f"월 {_won(caps['eligible_per_month'])}까지 모두 사용함")
        if base > left:
            base = left
            S(Step("월 대상금액", f"월 {_won(caps['eligible_per_month'])} 중 {_won(left)} 남음 → {_won(base)}만 대상", None))
    groups = {x["id"]: x for x in card["limit_groups"]}
    tier = effective_tier(card, b, p)
    for gid in b["groups"]:
        grp = groups[gid]
        if grp["kind"] != "이용금액":
            continue
        limit = (grp["per_month_by_tier"] or {}).get(tier) if grp["per_month_by_tier"] else grp["per_month"]
        if limit is not None:
            left = limit - p.used_groups.get(gid, 0)
            if left <= 0:
                return fail("limit", grp["name"], f"월 {_won(limit)} 모두 사용함")
            S(Step(grp["name"], f"월 {_won(limit)} 중 {_won(left)} 남음", True, _src(card, grp["source"])))
            if base > left:
                base = left
        if grp["per_day"] and base > grp["per_day"]:
            base = grp["per_day"]
            S(Step(grp["name"], f"일 {_won(grp['per_day'])}까지만 대상", None))
        r.used_groups[gid] = base

    # 금액 계산
    rw = b["reward"]
    if rw["kind"] == "정률":
        value = int(base * rw["rate"])
        S(Step("계산", f"{_won(base)} × {rw['rate'] * 100:g}% = {_won(value)}", None))
    elif rw["kind"] == "정액":
        if rw["amount_usd"] is not None:
            S(Step("계산", f"건당 US${rw['amount_usd']:g} (원화 환산은 환율에 따라 달라 계산 안 함)", None))
            r.ok, r.value = True, 0
            return r
        value = rw["amount"]
        S(Step("계산", f"정액 {_won(value)}", None))
    elif rw["kind"] == "리터당":
        if not tx.liters:
            return fail("liters", "계산", f"리터당 {rw['per_liter']}원이라 주유량(ℓ)을 알려주면 계산할 수 있음")
        liters = tx.liters * base / tx.amount
        value = int(liters * rw["per_liter"])
        S(Step("계산", f"{liters:g}ℓ × {rw['per_liter']}원 = {_won(value)}"
               + (f" (대상금액 {_won(base)} 비율만큼)" if base < tx.amount else ""), None))
    else:
        value = int(base / 1000 * rw["miles_per_1000"] + 0.5)
        S(Step("계산", f"{_won(base)} ÷ 1,000 × {rw['miles_per_1000']}마일 = {value:,}마일 (반올림)", None))

    if caps["benefit_per_txn"] and value > caps["benefit_per_txn"]:
        value = caps["benefit_per_txn"]
        S(Step("건당 상한", f"건당 최대 {_won(value, unit)}", None))
    for key, label, used_key in (("benefit_per_month", "월", "amount"), ("benefit_per_year", "연", "amount_year")):
        lim = caps[key]
        if lim:
            lim = int(lim * ratio)
            left = lim - used.get(used_key, 0)
            if left <= 0:
                return fail("limit", f"{label} 할인 한도", f"{label} {_won(lim, unit)} 모두 사용함")
            S(Step(f"{label} 할인 한도", f"{label} {_won(lim, unit)}" + (" (특례 50%)" if ratio != 1 else "")
                   + f" 중 {_won(left, unit)} 남음", True))
            value = min(value, left)

    for gid in b["groups"]:
        grp = groups[gid]
        if grp["kind"] == "이용금액":
            continue
        g_unit = "마일" if grp["kind"] == "마일리지" else "원"
        if g and g["effect"] == "limit_override":
            limit = g["limit"]
            S(Step(grp["name"], f"신규 발급 특례로 월 {_won(limit)}", None))
        else:
            limit = (grp["per_month_by_tier"] or {}).get(tier) if grp["per_month_by_tier"] else grp["per_month"]
        charge = None                       # 마일리지 한도를 넘으면 한도에는 특별 적립분만 쌓여요
        if limit is not None:
            left = limit - p.used_groups.get(gid, 0)
            if left <= 0 and grp["kind"] != "마일리지":
                return fail("limit", grp["name"], f"월 {_won(limit, g_unit)} 모두 사용함")
            S(Step(grp["name"], f"월 {_won(limit, g_unit)}" + (f"({tier} 구간)" if grp["per_month_by_tier"] else "")
                   + f" 중 {_won(max(left, 0), g_unit)} 남음", True, _src(card, grp["source"])))
            if value > left:
                if grp["kind"] == "마일리지":
                    charge = max(left, 0)
                    value = _overflow_to_base(card, b, tx, value, charge, S)
                else:
                    value = left
        if grp["per_day"]:
            if value > grp["per_day"]:
                value = grp["per_day"]
                S(Step(grp["name"], f"일 최대 {_won(grp['per_day'], g_unit)}", None))
        r.used_groups[gid] = charge
    for gid in list(r.used_groups):
        if groups[gid]["kind"] != "이용금액":
            # 뒤의 한도에서 금액이 더 줄었을 수 있어서 최종 혜택 금액 기준으로 맞춰요
            r.used_groups[gid] = value if r.used_groups[gid] is None else min(r.used_groups[gid], value)

    r.value, r.ok = value, value > 0
    if r.ok:
        r.usage = {"amount": value, "amount_year": value, "count": 1, "count_today": 1, "eligible": base}
    if value <= 0:
        r.stop = r.stop or "limit"
    return r


def _overflow_to_base(card, b, tx, value, left, S) -> int:
    """마일리지 특별 적립 한도를 넘으면 넘은 금액은 기본 적립으로"""
    base_b = next((x for x in card["benefits"] if x["id"] in b["stacking"]["exclusive_with"]
                   and x["reward"]["kind"] == "마일리지"), None)
    rate = b["reward"]["miles_per_1000"]
    covered = left / rate * 1000
    extra = int((tx.amount - covered) / 1000 * base_b["reward"]["miles_per_1000"] + 0.5) if base_b else 0
    S(Step("한도 초과분", f"특별 적립 {left:,}마일까지, 나머지 {_won(int(tx.amount - covered))}은 기본 적립 {extra:,}마일", None))
    return left + extra


# ---------- 카드 하나 ----------
def evaluate_card(card: dict, tx: Tx, p: Profile, suggest: bool = True) -> CardResult:
    std, cat = classify(tx.merchant)
    results = []
    for b in card["benefits"]:
        how = match(b, std, cat, tx)
        if how:
            results.append(evaluate_benefit(card, b, tx, p, how))
    unit = "마일" if card["reward_unit"] == "마일" else "원"
    primaries = [r for r, b in _pairs(card, results) if not b["stacking"]["stacks_on"]]
    winners = [r for r in primaries if r.ok]
    applied = []
    if winners:
        best = max(winners, key=lambda r: r.value)
        applied.append(best)
        for r, b in _pairs(card, results):
            on = b["stacking"]["stacks_on"]
            if r.ok and on and (on == "*" or on == best.benefit_id):
                applied.append(r)
    else:
        for r, b in _pairs(card, results):
            if r.ok and b["stacking"]["stacks_on"] == "*":
                applied.append(r)
    considered = [r for r in results if r not in applied]
    for r in considered:
        if r.ok:   # 받을 수 있지만 더 큰 혜택과 중복이 안 돼서 빠진 경우
            r.steps.append(Step("중복", "같은 결제에 더 큰 혜택이 적용되어 제외", False))
            r.stop = "stacking"
    note = None
    if not results:
        what = std or "이 결제"
        note = f"'{what}'에 해당하는 혜택이 없어요." if not tx.overseas else "해외 결제 혜택이 없어요."
    res = CardResult(card["card_id"], card["card_name"], unit, sum(r.value for r in applied), applied, considered, note)
    res.usage = usage_of(applied)
    if suggest:
        res.suggestions = suggestions(card, tx, p, res)
    return res


def _pairs(card, results):
    by_id = {b["id"]: b for b in card["benefits"]}
    return [(r, by_id[r.benefit_id]) for r in results]


# ---------- 개선 제안: 조건을 하나씩 바꿔서 다시 계산 ----------
def suggestions(card: dict, tx: Tx, p: Profile, cur: CardResult) -> list:
    out, seen = [], set()

    def add(text_fn, tx2=None, p2=None, key=None):
        r2 = evaluate_card(card, tx2 or tx, p2 or p, suggest=False)
        gain = r2.value - cur.value
        if gain > 0 and key not in seen:
            seen.add(key)
            out.append({"text": text_fn(r2), "gain": gain, "value": r2.value})

    unit = cur.unit
    for r in cur.considered:
        b = next(x for x in card["benefits"] if x["id"] == r.benefit_id)
        req = b["requires"]
        if r.stop == "min_payment":
            need = req["min_payment_per_txn"]
            add(lambda r2, need=need: f"{_won(need - tx.amount)} 더 결제해서 {_won(need)}을 맞추면 {_won(r2.value, unit)}",
                tx2=_with(tx, amount=need), key=("min", need))
        elif r.stop == "pay_method" and req["pay_methods"]:
            for pm in req["pay_methods"]:
                add(lambda r2, pm=pm: f"{pm}로 결제하면 {_won(r2.value, unit)}", tx2=_with(tx, pay_method=pm), key=("pay", pm))
        elif r.stop == "option":
            for k, v in req["option"].items():
                opts = dict(p.options, **{k: v})
                add(lambda r2, v=v: f"선택 옵션을 '{v}'(으)로 바꾸면 {_won(r2.value, unit)} (변경은 보통 다음 달부터 적용)",
                    p2=_with(p, options=opts), key=("opt", k, v))
        elif r.stop == "days":
            add(lambda r2: f"{'·'.join(req['days'])}요일에 결제하면 {_won(r2.value, unit)}",
                tx2=_with(tx, day=req["days"][0]), key=("day",))
        elif r.stop == "hours":
            h = int(req["hours"]["from"][:2])
            add(lambda r2: f"{req['hours']['from']}~{req['hours']['to']} 사이에 결제하면 {_won(r2.value, unit)}",
                tx2=_with(tx, hour=h), key=("hour",))
        elif r.stop in ("tier", "prev_month"):
            need = _needed_prev_month(card, b)
            if need and need > p.prev_month:
                add(lambda r2, need=need: f"전월 실적을 {_won(need)} 이상(지금보다 {_won(need - p.prev_month)} 더) 채우면 다음 달 {_won(r2.value, unit)}",
                    p2=_with(p, prev_month=need), key=("pm", need))
        elif r.stop == "enrollment":
            add(lambda r2: f"'{req['enrollment']}' 조건을 채우면 {_won(r2.value, unit)}", p2=_with(p, enrolled=True), key=("enroll",))
    return sorted(out, key=lambda s: -s["gain"])[:3]


def _with(obj, **kw):
    o = copy.copy(obj)
    for k, v in kw.items():
        setattr(o, k, v)
    return o


def _needed_prev_month(card: dict, b: dict) -> int | None:
    req = b["requires"]
    if req["tier"]:
        return next(t["prev_month_min"] for t in card["tiers"] if t["id"] == req["tier"])
    if req["prev_month_min"] and req["prev_month_min"] > 1:
        return req["prev_month_min"]
    return card["prev_month"]["required_min"]


# ---------- 여러 카드 비교 ----------
def usage_of(applied: list) -> dict:
    """적용된 혜택들이 이번 달 사용량에 더할 값 (같은 한도를 함께 쓰는 혜택은 합쳐요)"""
    groups, benefits = {}, {}
    for r in applied:
        if not r.ok:
            continue
        for gid, v in r.used_groups.items():
            groups[gid] = groups.get(gid, 0) + v
        benefits[r.benefit_id] = dict(r.usage)
    return {"used_groups": groups, "used_benefits": benefits} if (groups or benefits) else {}


def add_usage(p: Profile, usage: dict) -> Profile:
    """사용량을 더한 새 Profile (화면의 '썼어요'와 같은 계산. 테스트에서 씀)"""
    ug = dict(p.used_groups)
    for gid, v in usage.get("used_groups", {}).items():
        ug[gid] = ug.get(gid, 0) + v
    ub = {k: dict(v) for k, v in p.used_benefits.items()}
    for bid, d in usage.get("used_benefits", {}).items():
        cur = ub.setdefault(bid, {})
        for k, v in d.items():
            cur[k] = cur.get(k, 0) + v
    return Profile(**{**p.__dict__, "used_groups": ug, "used_benefits": ub})


def rank(tx: Tx, profiles: dict, card_ids: list | None = None) -> list[CardResult]:
    """원화 카드는 혜택 큰 순, 마일리지 카드는 그 뒤에 (단위가 달라 같은 순위로 비교 안 함)"""
    ids = card_ids or list(profiles) or list(CARDS)
    results = [evaluate_card(CARDS[c], tx, profiles.get(c, Profile())) for c in ids if c in CARDS]
    won = sorted([r for r in results if r.unit == "원"], key=lambda r: -r.value)
    miles = sorted([r for r in results if r.unit == "마일"], key=lambda r: -r.value)
    return won + miles


def benefit_status(card: dict, b: dict, p: Profile) -> tuple[bool, str]:
    """결제 없이 '지금 이 혜택을 받을 수 있는 상태인지' (카드 정보 질문용)"""
    req = b["requires"]
    if req["option"]:
        for k, v in req["option"].items():
            if p.options.get(k) != v:
                return False, f"'{v}' 선택 시에만"
    if req["enrollment"] and not p.enrolled:
        return False, f"{req['enrollment']} 필요"
    if req["valid_period"]:
        today = _today(p).isoformat()
        if not (req["valid_period"]["from"] <= today <= req["valid_period"]["to"]):
            return False, "적용 기간 아님"
    ok, detail, _ = check_prev_month(card, b, p)
    return ok, detail
