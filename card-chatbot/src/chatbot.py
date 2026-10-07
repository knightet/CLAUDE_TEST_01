"""문장으로 물어보면 답하는 카드 혜택 챗봇

흐름: 질문 -> (1) 질문 해석 -> (2) 엔진 계산(src/engine.py) -> (3) 설명 문장
- 조건 확인과 금액 계산은 항상 엔진(코드)이 해요.
- (1) 질문 칸(가맹점·금액·수량·시간 등)과 질문 종류는 코드 규칙이 채워요. LLM은 코드가 못 찾은 가맹점 이름만
  제안하고, 그 이름이 질문에 그대로 있을 때만 써요.
- (3) 답변은 코드가 만든 문장만 써요 (EXPLAIN_WITH_LLM = False).
  켜면 LLM이 계산 결과를 문장으로 다듬되, 계산 결과에 없는 숫자나 카드가 섞이면 버리고 코드 문장을 써요.
- OPENAI_API_KEY가 .env에 없으면 (1)(3)도 키워드 규칙과 정해진 문장으로 대신해요.

실행: python src/chatbot.py
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.engine import (CARDS, Profile, Tx, rank, evaluate_card, benefit_status, classify, match,
                        current_tier)
from src.card_summary import reward_text, condition_text, limit_text
from src.normalizer import ALIASES, CATEGORY, normalize

ROOT = Path(__file__).resolve().parent.parent
TOP_N = 3
MAX_AMOUNT = 100_000_000    # 이보다 큰 결제는 금액을 잘못 읽었을 가능성이 커서 되물어요
# 답변은 코드가 만든 문장만 써요. True로 바꾸면 LLM이 계산 결과를 문장으로 다듬되,
# 계산 결과에 없는 숫자·카드가 섞이면 버리고 코드 문장을 써요.
EXPLAIN_WITH_LLM = False

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
USE_LLM = API_KEY.startswith("sk-")
if USE_LLM:
    from openai import OpenAI
    client = OpenAI(api_key=API_KEY)

CARD_KEYWORDS = {
    "kb_nori_check": ["노리", "nori"],
    "shinhan_heyyoung_check": ["헤이영", "hey young", "heyyoung", "헤이 영"],
    "kb_kpass": ["k패스", "k-패스", "케이패스", "kpass", "k-pass", "패스카드"],
    "kb_goodday": ["굿데이", "goodday", "good day"],
    "kb_youth_club_check": ["유스클럽", "youth club", "youthclub", "유스 클럽"],
    "lotte_loca_likit_1_5": ["로카", "loca", "라이킷", "likit"],
    "nh_allbareun_flex": ["올바른", "flex", "플렉스", "nh카드", "농협카드", "nh농협"],
    "samsung_and_mileage_platinum_skypass": ["스카이패스", "skypass", "삼성카드", "마일리지 플래티넘", "&mileage"],
    "shinhan_mr_life": ["미스터라이프", "미스터 라이프", "mr.life", "mrlife", "mr life"],
}
PAY_KEYWORDS = {
    "KB Pay": ["kb pay", "kbpay", "kb페이", "케이비페이"],
    "신한PayFAN": ["페이판", "payfan", "신한pay"],
    "삼성페이": ["삼성페이"],
    "NH pay": ["nh pay", "nhpay", "nh페이", "올원페이"],
    "네이버페이": ["네이버페이", "네페"],
    "스마일페이": ["스마일페이"],
    "카카오페이": ["카카오페이", "카카오 페이"],
}
PREV_ITEMS = ["아파트관리비", "관리비", "상품권", "선불카드", "해외", "세금", "국세", "지방세",
              "공과금", "전기요금", "도시가스", "등록금", "학교납입금", "4대", "보험", "연회비",
              "수수료", "현금서비스", "카드론", "취소", "교통", "후불교통", "tmoney", "티머니"]
DAY_WORDS = {"월요일": "월", "화요일": "화", "수요일": "수", "목요일": "목", "금요일": "금",
             "토요일": "토", "토욜": "토", "일요일": "일", "일욜": "일", "주말": "토", "평일": "수"}
# "신한카드로", "국민카드 중에"처럼 카드사로 묶어 물을 때 (특정 카드 이름이 없을 때만)
ISSUER_KEYWORDS = {
    "KB국민카드": ["국민카드", "kb카드", "kb국민카드"],
    "신한카드": ["신한카드"],
    "롯데카드": ["롯데카드"],
    "NH농협카드": ["농협카드", "nh농협카드"],
    "삼성카드": ["삼성카드"],
}
# "현대카드", "딥드림카드"처럼 자료에 없는 카드: 'X카드'의 X가 아래 낱말이 아니면 모르는 카드로 봐요
NOT_CARD_NAMES = {"체크", "신용", "직불", "선불", "기프트", "교통", "후불교통", "다른", "모든", "어떤", "무슨", "아무",
                  "이", "그", "저", "내", "제", "이번", "전체", "보유", "가진", "새", "신규", "실물", "플라스틱", "모바일",
                  "주", "메인", "서브", "가족", "법인", "하이패스", "멤버십", "포인트", "상품권", "해외", "국내",
                  "마스터", "master", "비자", "visa", "아멕스", "amex", "유니온페이", "jcb", "국내전용", "해외겸용",
                  "한", "두", "세", "몇", "여러", "각", "모바일단독",
                  "최고", "제일", "가장", "인기", "추천", "혜택", "할인", "적립", "캐시백", "마일리지", "연회비", "무료"}


def _modifier(word: str) -> bool:
    """'싼 카드', '좋은 카드', '이득인 카드'처럼 받침 ㄴ으로 끝나는 꾸미는 말은 카드 이름이 아니에요"""
    ch = ord(word[-1]) - 0xAC00
    return 0 <= ch < 11172 and ch % 28 == 4
KNOWN_CARD_WORDS = ({k.replace(" ", "") for kws in CARD_KEYWORDS.values() for k in kws}
                    | {k for kws in PAY_KEYWORDS.values() for k in kws}
                    | {"국민", "kb", "신한", "롯데", "농협", "nh", "삼성", "kb국민", "nh농협", "올바른flex"})
CARD_WORD = re.compile(r"([0-9a-z가-힣+&.\-]+)\s?카드")


def unknown_card(q: str) -> str | None:
    """질문에 나온 카드 이름 중 등록된 9장에 없는 것 ('현대카드로 스벅' → '현대카드')"""
    for m in CARD_WORD.finditer(NEGATION.sub(" ", q).lower()):
        word = m.group(1)
        if (not word or word in NOT_CARD_NAMES or _modifier(word) or any(k in word for k in KNOWN_CARD_WORDS)
                or word in ALIASES or word in CATEGORY):        # '스타벅스 카드 충전'의 스타벅스는 가게
            continue
        return word + "카드"
    return None


# '해외'라는 말 없이 해외 결제를 뜻하는 말
OVERSEAS_WORDS = ["해외", "직구", "아마존", "알리익스프레스", "일본", "도쿄", "오사카", "후쿠오카", "미국", "뉴욕", "중국",
                  "유럽", "파리", "런던", "베트남", "다낭", "태국", "방콕", "싱가포르", "홍콩", "대만", "괌", "하와이", "호주"]
# "KB Pay 말고", "해외 아니고", "백화점 빼고" → 앞 낱말은 해석에서 빼요
NEGATION = re.compile(r"(\S+)\s*(말고|아니고|아닌|빼고|제외하고)")
# 대부분의 카드가 할인에서 빼는 결제 종류
PURCHASE_WORDS = {"선불충전": ["충전", "선불"], "상품권": ["상품권", "기프티콘", "기프트카드", "모바일쿠폰", "e쿠폰"]}
# 일부 카드가 혜택에서 빼는 결제 방식과 연료 종류 (설명서의 제외 문구와 같은 낱말)
PAY_TYPE_WORDS = {"인앱결제": ["인앱결제", "인앱"], "만나서결제": ["만나서결제", "만나서", "현장결제"]}
FUEL_WORDS = {"LPG": ["lpg", "엘피지"], "경유": ["경유", "디젤"], "등유": ["등유"], "휘발유": ["휘발유", "가솔린"]}
# 통신사 이름이 들어가도 통신요금이 아닌 결제 (KT 위즈파크 야구 티켓 등)
NOT_TELECOM = ["야구", "티켓", "경기", "위즈", "트윈스", "랜더스", "구장", "파크", "매장", "대리점", "아트홀"]
TELECOM = {"SKT", "KT", "LG U+", "LiivM"}
STORE_NAMES = set(ALIASES.values())     # 가게 이름 (이 밖의 말은 "편의점", "카페"처럼 업종)
# 가게별 혜택을 덧붙일 넓은 업종 낱말. '중국집'·'일식'처럼 좁은 말에는 VIPS·아웃백을 권하지 않아요
BROAD_WORDS = set(CATEGORY.values()) | {"카페", "커피전문점", "주유소", "충전소", "마트", "대형마트", "식당", "햄버거",
                                        "영화관", "극장", "배달", "ott"}
# 원화가 아닌 금액 ("2000엔", "50달러", "1만엔"). 카드 혜택은 원화 청구금액으로 계산하니 원화로 되물어요
CURRENCY = re.compile(r"(?:\d|[십백천만])\s*(엔|달러|불|유로|위안|파운드|바트)(?![가-힣a-z])")
CURRENCY_NAMES = {"불": "달러"}


def card_names() -> str:
    return " | ".join(f'"{cid}"({c["card_name"]})' for cid, c in CARDS.items())


# ---------- (1) 질문 해석 ----------
PARSE_PROMPT = """너는 카드 혜택 질문을 JSON으로 바꾸는 파서야. 설명 없이 JSON만 출력해.
- 가맹점과 금액만 적혀 있어도(예: "스타벅스 15000원", "편의점 5천원") 어떤 카드가 이득인지 묻는 것이니 intent는 "benefit".
- 가맹점·업종(버스, 지하철, 커피 등)에서 쓸 때의 할인을 물으면 금액이 없어도 merchant를 채우고 intent는 "benefit".
- 카드의 혜택·조건·연회비·할인한도처럼 카드 자체를 묻는 질문은 "card_info". 특정 카드를 말하면 card도 채워.
- "prev_month"는 어떤 지출(관리비, 해외 결제, 상품권 등)이 전월 실적으로 '인정되는지'를 물을 때만 써. item에 그 지출을 넣어.
- "전월 25만원 썼는데 지하철 할인 받을 수 있어?"처럼 자기 전월 실적을 말하면서 할인을 받을 수 있는지 물으면
  prev_month가 아니라 benefit 또는 card_info야. 말한 전월 실적은 prev_month_stated에 넣어.
{
 "intent": "benefit" | "prev_month" | "card_info" | "other",
 "merchant": 가맹점 이름 또는 null (예: "스타벅스", "GS25", "지하철", "택시", "주유소", "넷플릭스"),
 "amount": 결제 금액 정수(원) 또는 null ("만오천원" -> 15000),
 "pay_method": "KB Pay" | "신한PayFAN" | "삼성페이" | "NH pay" | "네이버페이" | "스마일페이" | "카카오페이" | null,
 "location": "백화점" | "대형마트" | null (입점 매장일 때),
 "channel": "온라인" | "오프라인" | null,
 "overseas": true/false,
 "card": CARD_IDS 중 하나 또는 null,
 "card_type": "체크" | "신용" | null (특정 카드가 아니라 "체크카드 중에서", "신용카드로만"처럼 종류를 말할 때),
 "issuer": "KB국민카드" | "신한카드" | "롯데카드" | "NH농협카드" | "삼성카드" | null ("신한카드로"처럼 특정 카드 이름 없이 카드사만 말할 때. 이때 card는 null),
 "purchase": "선불충전" | "상품권" | null (선불카드·스타벅스 카드 충전이면 "선불충전", 상품권·기프티콘 구매면 "상품권"),
 "item": 전월 실적 포함 여부를 묻는 항목 (예: "아파트관리비", "상품권", "해외") 또는 null,
 "prev_month_stated": 사용자가 직접 말한 자기 전월 실적 정수(원) 또는 null ("전월 15만원 썼는데" -> 150000, "실적 없어" -> 0),
 "day": "월"|"화"|"수"|"목"|"금"|"토"|"일" 또는 null (결제 요일, "주말"이면 "토"),
 "hour": 0~23 정수 또는 null (결제 시각, "밤 10시" -> 22),
 "liters": 주유량(리터) 숫자 또는 null
}
amount는 이번에 결제할 금액이야. 전월 실적 금액을 amount에 넣지 마. "15000원짜리 2잔"이면 합계 30000.
pay_method는 질문에 결제수단(페이)을 직접 말했을 때만 채워. 카드 이름만 보고 짐작하지 마.
"KB Pay 말고", "해외 말고", "백화점 아니고"처럼 부정한 것은 그 값으로 채우지 마.
"일본 여행 가서", "아마존 직구"처럼 해외 결제가 분명하면 overseas는 true."""


def parse_with_llm(q: str) -> dict:
    res = client.chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": PARSE_PROMPT.replace("CARD_IDS", card_names())},
                  {"role": "user", "content": q}],
        temperature=0,
    )
    return json.loads(res.choices[0].message.content)


KOR_DIGIT = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
KOR_UNIT = {"십": 10, "백": 100, "천": 1000}


def korean_number(s: str) -> int | None:
    """'만오천' -> 15000, '삼만' -> 30000, '1만2천' -> 12000"""
    total = section = num = 0
    prev = ""
    for ch in s:
        if ch.isdigit():
            # '직구5만'의 '구'처럼 한글 숫자 바로 뒤에 아라비아 숫자가 오면 앞 글자는 숫자가 아니에요
            num = int(ch) if prev in KOR_DIGIT else num * 10 + int(ch)
        elif ch in KOR_DIGIT:
            num = KOR_DIGIT[ch]
        elif ch in KOR_UNIT:
            section += (num or 1) * KOR_UNIT[ch]
            num = 0
        elif ch == "만":
            total += (section + num or 1) * 10000
            section = num = 0
        elif ch == "억":
            total = (total + section + num or 1) * 100_000_000
            section = num = 0
        prev = ch
    value = total + section + num
    return value or None


# 숫자가 든 가게 이름: 띄어쓰기를 지우기 전에 빼야 "이마트24 12000원"이 2412000원이 되지 않아요
DIGIT_NAMES = sorted({n.lower() for n in [*ALIASES, *ALIASES.values(), *CATEGORY] if any(ch.isdigit() for ch in n)},
                     key=len, reverse=True)
COUNTS = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5}
# "15000원짜리 2잔", "만원짜리 커피 3잔"처럼 짜리와 수량 사이에 물건 이름이 끼어도 돼요
QUANTITY = re.compile(r"짜리\s*(?:[가-힣a-zA-Z]+\s*)?(\d+|한|두|세|네|다섯)\s*(잔|개|장|권|병|벌|그릇|명분|인분)")


def parse_quantity(q: str) -> int | None:
    m = QUANTITY.search(q)
    if not m:
        return None
    n = m.group(1)
    return int(n) if n.isdigit() else COUNTS[n]


def parse_amount(q: str) -> int | None:
    """결제 총액. 수량이 있으면 단가 × 수량"""
    s = q.lower().replace(",", "")
    for name in DIGIT_NAMES:
        # 'gs 25'처럼 띄어 써도 가게 이름의 숫자를 금액으로 읽지 않게 글자 사이 띄어쓰기를 허용해요
        s = re.sub(r"\s*".join(map(re.escape, name.replace(" ", ""))), " ", s)
    s = re.sub(r"(?<!\d)([01]?\d|2[0-3]):[0-5]\d(?!\d)", " ", s)   # 23:30 같은 시각
    s = re.sub(r"\d+(\.\d+)?\s*(리터|ℓ|l(?![a-z]))", " ", s)   # 주유량
    s = re.sub(r"\d+(\.\d+)?\s*%", " ", s)                      # 할인율
    s = re.sub(r"\d{1,2}\s*시", " ", s)                         # 시각
    s = QUANTITY.sub("짜리 ", s)                                 # 수량 숫자를 금액으로 읽지 않게
    value = _amount_in(s.replace(" ", ""))
    qty = parse_quantity(q)
    if value and qty:
        value *= qty
    return value


def _amount_in(s: str) -> int | None:
    m = re.search(r"(\d+(?:\.\d+)?)억", s)                      # 1억, 1.5억
    if m:
        return int(float(m.group(1)) * 100_000_000)
    m = re.search(r"(\d+\.\d+)만", s)                           # 1.5만
    if m:
        return int(float(m.group(1)) * 10000)
    m = re.search(r"(\d+(?:\.\d+)?)k(?![a-z])", s)              # 15k
    if m:
        return int(float(m.group(1)) * 1000)
    m = re.search(r"([일이삼사오육칠팔구십백천만억\d]*[십백천만억][일이삼사오육칠팔구십백천만억\d]*)원", s)
    if m and not re.fullmatch(r"\d+", m.group(1)):        # 만오천원, 삼만원, 1만2천원
        return korean_number(m.group(1))
    m = re.search(r"(\d+)만(\d+)?천?", s)          # 1만5천, 3만
    if m:
        return int(m.group(1)) * 10000 + (int(m.group(2)) * 1000 if m.group(2) else 0)
    m = re.search(r"(\d+)천", s)                    # 5천원
    if m:
        return int(m.group(1)) * 1000
    m = re.search(r"(\d{3,})", s)                   # 15000
    if m:
        return int(m.group(1))
    # '원' 없는 한글 금액 ("만 오천", "삼만"). '만약'처럼 만 뒤에 숫자가 아닌 글자가 오면 금액이 아니에요
    m = re.search(r"[\d일이삼사오육칠팔구]+만[일이삼사오육칠팔구\d]*천?|만[일이삼사오육칠팔구\d]+천?|[\d일이삼사오육칠팔구]+천", s)
    return korean_number(m.group(0)) if m else None


STATED_PREV = re.compile(r"(전월|지난\s*달)\s*(실적)?\s*(은|이|을|에)?\s*([\d,]+\s*만?\s*[\d,]*\s*천?\s*원?)")


def parse_stated_prev_month(q: str) -> tuple[int | None, str]:
    """'전월 25만원 썼는데' -> (250000, 그 부분을 뺀 질문). 결제 금액과 헷갈리지 않게 빼둬요"""
    m = STATED_PREV.search(q)
    if m:
        return parse_amount(m.group(4)), q[:m.start()] + q[m.end():]
    if re.search(r"실적\s*(이|은)?\s*(없|0원|하나도)", q):
        return 0, q
    return None, q


KOR_HOURS = {"열한": 11, "열두": 12, "한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7,
             "여덟": 8, "아홉": 9, "열": 10}


def parse_time(q: str) -> tuple[str | None, int | None]:
    day = next((v for k, v in DAY_WORDS.items() if k in q), None)
    # '시간'은 시각이 아니에요 ("3시간", "한 시간")
    m = re.search(r"(오전|오후|밤|새벽|아침|저녁)?\s*(\d{1,2}|열한|열두|다섯|여섯|일곱|여덟|아홉|한|두|세|네|열)\s*시(?!간)", q)
    hm = re.search(r"(?<!\d)([01]?\d|2[0-3]):[0-5]\d(?!\d)", q)   # 23:30
    hour = None
    if hm and not m:
        hour = int(hm.group(1))
    elif m and (not m.group(2).isdigit() or int(m.group(2)) <= 24):   # '25시'처럼 없는 시각은 버려요
        h = m.group(2)
        hour = (int(h) if h.isdigit() else KOR_HOURS[h]) % 24
        if m.group(1) in ("오후", "밤", "저녁") and hour < 12:
            hour = (hour + 12) % 24 if not (m.group(1) == "밤" and hour == 12) else 0
        if m.group(1) in ("오전", "새벽", "아침") and hour == 12:
            hour = 0
    elif "자정" in q:
        hour = 0
    elif "정오" in q:
        hour = 12
    elif any(k in q for k in ("밤에", "야간", "늦은 밤", "심야")):
        hour = 23
    elif "새벽" in q:
        hour = 2
    return day, hour


# '중국집'처럼 나라 이름이 든 업종·가게 이름은 해외 결제가 아니에요
OVERSEAS_LOOKALIKES = sorted({w for w in [*CATEGORY, *ALIASES] if any(o in w for o in OVERSEAS_WORDS)}, key=len, reverse=True)


def is_overseas(text: str) -> bool:
    for w in OVERSEAS_LOOKALIKES:
        text = text.replace(w, " ")
    return any(w in text for w in OVERSEAS_WORDS) and "국내" not in text


def parse_with_rules(q: str) -> dict:
    stated, rest = parse_stated_prev_month(q)
    pos = NEGATION.sub(" ", q)                       # "KB Pay 말고" 같은 부정한 말을 뺀 문장
    low = pos.lower().replace(" ", "")
    day, hour = parse_time(q)
    liters = re.search(r"(\d+(?:\.\d+)?)\s*(리터|ℓ|l(?![a-z]))", q, flags=re.I)
    out = {"intent": "benefit", "merchant": None, "amount": parse_amount(rest), "pay_method": None,
           "location": None, "channel": None, "overseas": is_overseas(pos),
           "card": None, "item": None, "prev_month_stated": stated, "day": day, "hour": hour, "card_type": None,
           "issuer": None, "purchase": None, "liters": float(liters.group(1)) if liters else None,
           "quantity": parse_quantity(rest), "cards": [], "exclude_cards": [], "pay_type": None, "fuel": None,
           "currency": None, "unknown_card": unknown_card(q)}
    cur = CURRENCY.search(pos)
    if cur:                                          # "1만엔"을 10,000원으로 계산하지 않게 금액을 비워요
        out["currency"] = CURRENCY_NAMES.get(cur.group(1), cur.group(1))
        out["amount"] = None
        out["overseas"] = True

    named = [cid for cid, kws in CARD_KEYWORDS.items() if any(k.replace(" ", "") in low for k in kws)]
    if len(named) == 1:
        out["card"] = named[0]
    elif len(named) >= 2:
        out["cards"] = named                      # "노리랑 헤이영 중에" → 두 카드만 비교
    negated = " ".join(m.group(1) for m in NEGATION.finditer(q)).lower()
    out["exclude_cards"] = [cid for cid, kws in CARD_KEYWORDS.items()
                            if any(k.replace(" ", "") in negated for k in kws)]   # "K패스 말고 다른 카드"
    for pay, kws in PAY_KEYWORDS.items():
        if any(k.replace(" ", "") in low for k in kws):
            out["pay_method"] = pay
    if not out["card"]:
        out["issuer"] = next((i for i, kws in ISSUER_KEYWORDS.items() if any(k in low for k in kws)), None)
        out["card_type"] = "체크" if "체크" in low else "신용" if "신용" in low else None
    no_station = low.replace("충전소", "")             # 'LPG 충전소'는 주유이지 선불 충전이 아님
    out["purchase"] = next((k for k, ws in PURCHASE_WORDS.items() if any(w in no_station for w in ws)), None)
    out["pay_type"] = next((k for k, ws in PAY_TYPE_WORDS.items() if any(w in low for w in ws)), None)
    out["fuel"] = next((k for k, ws in FUEL_WORDS.items() if any(w in low for w in ws)), None)
    # 긴 이름부터 찾아야 '버스'보다 '고속버스'가 먼저 잡혀요.
    # '백화점 스벅'처럼 입점 위치 낱말이 같이 있으면 위치가 아니라 가게 이름을 가맹점으로 골라요
    # 영문으로 시작하는 이름은 앞에 다른 영문자가 붙으면 안 돼요 ('skt통신'의 'kt통신')
    found = [n for n in sorted(set(ALIASES) | set(CATEGORY), key=lambda n: (-len(n), n))
             if re.search(("(?<![a-z])" if n[:1].isascii() and n[:1].isalpha() else "") + re.escape(n.lower()), low)]
    shops = [n for n in found if n not in ("백화점", "마트", "대형마트")]
    brands = [n for n in shops if n in ALIASES]       # 'SKT 통신요금'은 업종 낱말보다 가게 이름(SKT)
    out["merchant"] = (brands or shops or found or [None])[0]
    if out["merchant"] and normalize(out["merchant"])[0] in TELECOM and any(w in low for w in NOT_TELECOM):
        out["merchant"] = "기타 가맹점"           # KT 위즈파크 야구 티켓은 통신요금이 아님
    if "백화점" in pos and out["merchant"] not in ("백화점",) and CATEGORY.get(out["merchant"] or "") != "백화점":
        out["location"] = "백화점"
    elif ("마트" in pos.replace(out["merchant"] or "\0", "") and CATEGORY.get(out["merchant"] or "") != "할인마트"
          and out["merchant"] not in ("마트", "대형마트")):         # '이마트24'의 '마트'는 입점 위치가 아님
        out["location"] = "대형마트"
    if any(k in pos for k in ["온라인", "인터넷", "앱으로", "어플"]):
        out["channel"] = "온라인"
    elif any(k in pos for k in ["오프라인", "매장에서", "현장"]):
        out["channel"] = "오프라인"
    # "상품권은?"처럼 '실적' 없이 항목만 말하는 후속 질문도 있어서 항상 찾아둬요
    out["item"] = next((i for i in PREV_ITEMS if i in low), None)

    out["intent"] = decide_intent(out, q)
    return out


def decide_intent(p: dict, q: str) -> str:
    """질문 종류는 항상 코드가 정해요 (LLM에 맡기면 같은 질문도 실행마다 달라졌어요)"""
    if "실적" in q and any(k in q for k in ["포함", "들어가", "인정", "잡혀", "쳐"]):
        return "prev_month"
    if not p["merchant"] and not (p["overseas"] and p["amount"]) and (p["card"] or "혜택" in q):
        return "card_info"
    if not p["merchant"] and not p["overseas"] and not p["amount"]:
        return "other"
    return "benefit"                                  # 금액만 말해도 결제 질문 (가맹점은 되물어요)


def _in_question(word: str, q: str) -> bool:
    return bool(word) and word.lower().replace(" ", "") in q.lower().replace(" ", "")


def parse(q: str) -> dict:
    """질문 칸(가맹점·금액·수량·시간·카드·결제수단 등)은 코드 규칙으로 채워요. 같은 질문은 항상 같은 해석이 나와요.
    LLM은 코드가 가맹점을 못 찾았을 때만 가맹점 후보를 받고, 그 이름이 질문에 그대로 있을 때만 써요."""
    p = parse_with_rules(q)
    p["llm_slots"] = []
    if USE_LLM and not p["merchant"] and p["intent"] in ("benefit", "other") and not p["overseas"]:
        try:
            guess = parse_with_llm(q).get("merchant")
            if isinstance(guess, str) and _in_question(guess, q):
                p["merchant"] = guess.strip()[:50]
                p["llm_slots"] = ["merchant"]
                p["intent"] = decide_intent(p, q)
        except Exception as e:
            print(f"  (LLM 가맹점 확인 실패, 코드 해석만 사용: {e})")
    return p


# ---------- (1-b) 후속 질문 이어받기 ----------
# 해석(1)이 LLM이든 키워드든, 이전 질문을 이어받을지는 항상 코드가 정해요 (테스트 가능하게)
SLOT_KEYS = ["merchant", "amount", "pay_method", "location", "channel", "overseas", "card", "card_type", "issuer",
             "purchase", "item", "prev_month_stated", "day", "hour", "liters", "pay_type", "fuel", "cards",
             "exclude_cards"]
FOLLOWUP_START = ("그럼", "그러면", "그렇다면", "만약", "아니면", "그리고", "근데")
FOLLOWUP_END = re.compile(r"(이면|라면|하면|면|는|은|도|로|으로)\s*(요|용)?\s*[?？]?$")
INFO_CUES = ["혜택", "연회비", "알려", "설명", "조건", "한도"]
ALL_CARDS_CUES = ["다른카드", "전체카드", "모든카드", "카드전부", "전체", "다른거"]


def _new_slots(p: dict) -> dict:
    """이번 질문에서 새로 말한 값만 (False/None은 '말 안 함'으로 봐요)"""
    return {k: p.get(k) for k in SLOT_KEYS
            if p.get(k) not in (None, False, "", []) or (k in ("prev_month_stated", "hour") and p.get(k) == 0)}


def _num(v, low, high, cast=int):
    return cast(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and low <= v < high else None


def _clean_context(ctx) -> dict | None:
    """브라우저가 돌려보낸 이전 해석 결과는 믿지 않고 아는 값만 남겨요"""
    if not isinstance(ctx, dict) or ctx.get("intent") not in ("benefit", "prev_month", "card_info"):
        return None
    out = {"intent": ctx["intent"]}
    for k in SLOT_KEYS:
        v = ctx.get(k)
        if k == "amount":
            v = _num(v, 1, 100_000_000)
        elif k == "prev_month_stated":
            v = _num(v, 0, 100_000_000)
        elif k == "hour":
            v = _num(v, 0, 24)
        elif k == "liters":
            v = _num(v, 0.1, 1000, float)
        elif k == "overseas":
            v = bool(v)
        elif k == "card_type":
            v = v if v in ("체크", "신용") else None
        elif k == "issuer":
            v = v if v in ISSUER_KEYWORDS else None
        elif k == "purchase":
            v = v if v in PURCHASE_WORDS else None
        elif k == "pay_type":
            v = v if v in PAY_TYPE_WORDS else None
        elif k == "fuel":
            v = v if v in FUEL_WORDS else None
        elif k in ("cards", "exclude_cards"):
            v = [c for c in v if c in CARDS] if isinstance(v, list) else []
        elif k == "card":
            v = v if v in CARDS else None
        elif k == "channel":
            v = v if v in ("온라인", "오프라인") else None
        elif k == "day":
            v = v if v in ("월", "화", "수", "목", "금", "토", "일") else None
        else:
            v = str(v)[:50] if isinstance(v, str) and v else None
        out[k] = v
    return out


def is_followup(p: dict, q: str, prev: dict | None) -> bool:
    if not prev:
        return False
    new = _new_slots(p)
    compact = q.replace(" ", "")
    if new.get("merchant") and new.get("amount"):
        return False                                   # 가맹점+금액이 다 있으면 새 질문
    if p.get("currency") or p.get("unknown_card"):
        return False                                   # "일본에서 1만엔", "현대카드는?"은 새 질문 (이전 조건을 붙이면 엉뚱한 답)
    if p.get("intent") == "prev_month" and new.get("item") and "실적" in q:
        return False                                   # 실적 질문을 온전히 새로 함
    short = len(compact) <= 15
    cue = compact.startswith(FOLLOWUP_START) or bool(FOLLOWUP_END.search(compact))
    if new.get("merchant") or new.get("amount"):
        if prev["intent"] == "prev_month":
            return False                               # 실적 질문 뒤의 결제 질문은 주제가 바뀐 것
        if new.get("merchant") and not new.get("amount"):
            # 가게만 바꿔 다시 묻는 말은 짧거나 후속 말투예요("GS25는?", "그럼 롯데월드는?").
            # "롯데월드 놀러가려고 하는데 카드 추천"처럼 길게 새로 말하면 이전 금액·요일을 붙이지 않아요
            return short or cue
        return True                                    # "2만원이면?", 되물음에 "15000원"
    if any(k in compact for k in INFO_CUES):
        return False                                   # "노리 혜택 알려줘"는 카드 정보 질문
    if not short:
        return False                                   # 카드만 바꾸는 후속 질문은 짧아요. 길면 새 질문
    return bool(new) or cue or any(k in compact for k in ALL_CARDS_CUES)  # "헤이영이면?", "다른 카드는?"


def merge_followup(prev: dict, p: dict, q: str) -> dict:
    new = _new_slots(p)
    out = dict(prev)
    if new.get("merchant") and new["merchant"] != prev.get("merchant"):
        # 가게가 바뀌면 그 가게에 붙어 있던 조건(입점·온라인·해외·주유량)은 버려요
        out.update(location=None, channel=None, overseas=False, liters=None, purchase=None)
    out.update(new)
    # 카드 범위(특정 카드 / 카드사 / 체크·신용)는 새로 말한 것 하나만 남겨요
    scope = [k for k in ("card", "cards", "issuer", "card_type") if new.get(k)]
    if scope:
        for k in ("card", "cards", "issuer", "card_type"):
            if k not in scope:
                out[k] = [] if k == "cards" else None    # "신용카드는?" → 특정 카드 대신 종류 전체
    if any(k in q.replace(" ", "") for k in ALL_CARDS_CUES) and not scope:
        out["card"] = out["issuer"] = out["card_type"] = None
        out["cards"], out["exclude_cards"] = [], []
    if new.get("merchant") or new.get("amount"):
        out["intent"] = "benefit"
    elif new.get("item") and not new.get("overseas"):   # "해외"는 결제 조건일 수도 있어서 제외
        out["intent"] = "prev_month"
    return out


LINK_MODES = ("auto", "follow", "new")


def resolve(q: str, context: dict | None, link: str = "auto") -> tuple[dict, bool]:
    """질문 해석 + 이전 질문 이어받기. (해석 결과, 이어받았는지)
    link: "auto"는 코드 규칙으로 판단, "follow"는 사용자가 '이어서'를 골라 무조건 이어받기,
    "new"는 '새 질문'을 골라 이전 질문을 보지 않기"""
    p = parse(q)
    prev = _clean_context((context or {}).get("parsed")) if link != "new" else None
    if prev and (link == "follow" or is_followup(p, q, prev)):
        return merge_followup(prev, p, q), True
    return p, False


# ---------- 사용자 상태 ----------
def build_state(payload: dict | None) -> dict:
    """화면에서 보낸 보유 카드·실적·옵션·이번 달 사용 현황 -> {card_id: Profile}. 모르는 값은 버려요"""
    payload = payload if isinstance(payload, dict) else {}
    owned = [c for c in payload.get("owned", []) if c in CARDS] or list(CARDS)
    raw = payload.get("cards") if isinstance(payload.get("cards"), dict) else {}
    out = {}
    for cid in owned:
        d = raw.get(cid) if isinstance(raw.get(cid), dict) else {}
        card = CARDS[cid]
        opts = {o["id"]: d.get("options", {}).get(o["id"]) for o in card["options"]
                if isinstance(d.get("options"), dict) and d["options"].get(o["id"]) in o["choices"]}
        gids = {g["id"] for g in card["limit_groups"]}
        bids = {b["id"] for b in card["benefits"]}
        ug = d.get("used_groups") if isinstance(d.get("used_groups"), dict) else {}
        ub = d.get("used_benefits") if isinstance(d.get("used_benefits"), dict) else {}
        out[cid] = Profile(
            prev_month=_num(d.get("prev_month"), 0, 1_000_000_000) or 0,
            options=opts,
            enrolled=d.get("enrolled") is True,
            in_grace=d.get("in_grace") is True,
            overseas_brand=d.get("overseas_brand") is not False,
            used_groups={g: _num(v, 0, 100_000_000) or 0 for g, v in ug.items() if g in gids},
            used_benefits={b: {k: _num(v.get(k), 0, 100_000_000) or 0 for k in ("amount", "amount_year", "count", "count_today", "eligible")}
                           for b, v in ub.items() if b in bids and isinstance(v, dict)},
        )
    return out


def default_state() -> dict:
    p = ROOT / "data" / "my_profile.json"
    return build_state(json.loads(p.read_text(encoding="utf-8")) if p.exists() else {})


# ---------- (2) 계산: 결과는 사람이 읽는 사실 목록(facts) + 화면용 구조(view) ----------
def is_small_talk(q: str) -> bool:
    """'고마워', '알겠어요'처럼 질문이 아닌 짧은 말"""
    compact = q.replace(" ", "")
    return len(compact) <= 8 and not compact.endswith(("?", "？")) and not any(
        k in compact for k in ("뭐", "어떤", "어느", "얼마", "알려", "추천"))


def top_results(results: list) -> list:
    """원화 혜택이 있는 카드 → 마일리지 카드 → 혜택 없는 카드 순으로 상위 3개"""
    won = [r for r in results if r.unit == "원" and r.value > 0]
    miles = [r for r in results if r.unit == "마일" and r.value > 0]
    zero = [r for r in results if r.value <= 0]
    return (won + miles + zero)[:TOP_N]


def _amount(r) -> str:
    return f"{r.value:,}{r.unit}"


def _why(r) -> str:
    if r.applied:
        return " + ".join(b.name for b in r.applied)
    if r.considered:
        last = r.considered[0].steps[-1]
        return f"{r.considered[0].name}: {last.detail}"
    return r.note or "해당 혜택 없음"


def tx_text(tx: Tx, qty: int | None = None) -> str:
    parts = [f"{normalize(tx.merchant)[0] if tx.merchant else '해외 가맹점'} {tx.amount:,}원"
             + (f" ({tx.amount // qty:,}원 × {qty})" if qty and qty > 1 else "")]
    parts += [f"결제수단 {tx.pay_method}"] if tx.pay_method else []
    parts += [tx.pay_type] if tx.pay_type else []
    parts += [tx.fuel] if tx.fuel else []
    parts += [tx.channel] if tx.channel else []
    parts += [f"{tx.location} 입점"] if tx.location else []
    parts += ["해외"] if tx.overseas else []
    parts += [f"{tx.day}요일"] if tx.day else []
    parts += [f"{tx.hour}시"] if tx.hour is not None else []
    parts += [f"{tx.liters:g}ℓ"] if tx.liters else []
    return ", ".join(parts)


def targets(p: dict, state: dict) -> list:
    """질문이 가리키는 카드: 특정 카드 > 카드사 > 체크/신용 종류 > 보유 카드 전체"""
    if p.get("card") in CARDS:
        return [p["card"]]
    if p.get("cards"):
        return [c for c in p["cards"] if c in CARDS]
    ids = [c for c in state if c not in (p.get("exclude_cards") or [])]
    if p.get("issuer") in ISSUER_KEYWORDS:
        ids = [c for c in ids if CARDS[c]["issuer"] == p["issuer"]]
    if p.get("card_type") in ("체크", "신용"):
        ids = [c for c in ids if CARDS[c]["card_type"] == p["card_type"]]
    return ids


def scope_text(p: dict) -> str | None:
    if p.get("card") in CARDS:
        return None
    if p.get("cards"):
        return " · ".join(CARDS[c]["card_name"] for c in p["cards"] if c in CARDS) + " 중에서"
    parts = [p["issuer"]] if p.get("issuer") in ISSUER_KEYWORDS else []
    parts += [f"{p['card_type']}카드"] if p.get("card_type") in ("체크", "신용") else []
    text = " ".join(parts) + "만" if parts else ""
    if p.get("exclude_cards"):
        text += (" · " if text else "") + ", ".join(CARDS[c]["card_name"] for c in p["exclude_cards"] if c in CARDS) + " 제외"
    return text or None


def benefit_view(tx: Tx, state: dict, ids: list, scope: str | None = None, qty: int | None = None) -> tuple[str, dict]:
    if not ids:
        return f"NEED: 보유 카드 중 {scope or '해당'} 카드가 없어요. 왼쪽 '내 카드'에서 카드를 골라 주세요.", {}
    results = rank(tx, state, ids)
    top = top_results(results)
    lines = [f"[결제] {tx_text(tx, qty)}", f"[결과 상위 {len(top)}개 / 비교한 카드 {len(results)}장"
             + (f", {scope}" if scope else "") + "]"]
    for i, r in enumerate(top, 1):
        lines.append(f"{i}. {r.card_name}: {_amount(r)} — {_why(r)}")
        for b in r.applied:
            calc = [s.detail for s in b.steps if s.label in ("계산", "건당 상한", "한도 초과분") or "남음" in s.detail]
            lines.append(f"   계산: {'; '.join(calc)} (근거 {b.source})")
    # 상위 3개 밖의 카드도 조건만 바꾸면 1위보다 더 받을 때는 알려줘요 (평일 이마트 → '주말이면 Mr.Life 5,000원')
    best_value = top[0].value if top and top[0].unit == "원" else 0
    sugg = [dict(s, card=r.card_name) for r in results for s in r.suggestions
            if r in top or (r.unit == "원" and s["value"] > best_value)]
    sugg = sorted(sugg, key=lambda s: -s["gain"])[:3]
    if sugg:
        lines.append("[개선 제안]")
        lines += [f"- {s['card']}: {s['text']}" for s in sugg]
    by_brand = brand_breakdown(tx, state, ids)
    if by_brand:
        lines.append(f"[가게별] '{tx.merchant}' 전체가 아니라 특정 가게에만 주는 혜택")
        lines += [f"- {x['brand']}: {x['card_name']} {x['value']:,}{x['unit']}" for x in by_brand]
    # 이번 달 사용 기록(한도·횟수 소진) 때문에 빠진 카드가 있으면, 기록이 없을 때 1위보다 더 받았는지 알려줘요.
    # 안 그러면 "왜 이 카드가 추천에 안 나오지?"를 화면에서 알 수 없어요
    used_up = []
    for r in results:
        prof = state.get(r.card_id, Profile())
        if not (prof.used_groups or prof.used_benefits):
            continue
        blocked = [b for b in r.considered if b.stop in ("count", "limit")]
        if not blocked:
            continue
        fresh = evaluate_card(CARDS[r.card_id], tx, Profile(**{**prof.__dict__, "used_groups": {}, "used_benefits": {}}),
                              suggest=False)
        if fresh.unit == "원" and fresh.value > max(r.value, best_value):
            b = next((x for x in blocked if any(a.benefit_id == x.benefit_id for a in fresh.applied)), blocked[0])
            used_up.append({"card": r.card_name, "benefit": b.name, "why": b.steps[-1].detail,
                            "value": fresh.value, "unit": fresh.unit})
    if used_up:
        lines.append("[사용 기록으로 빠짐]")
        lines += [f"- {u['card']}: {u['benefit']} — {u['why']} (기록이 없으면 {u['value']:,}{u['unit']})" for u in used_up]
    # 리터당 할인은 주유량이 있어야 계산돼요. 말없이 0원으로 두지 않고 물어봐요
    need_liters = [r.card_name for r in results if any(b.stop == "liters" for b in r.considered)]
    if need_liters:
        lines.append(f"[주유량 필요] {', '.join(need_liters)}: 리터당 할인이라 주유량(ℓ)을 알려주면 계산할 수 있음")
    # 카드 한 장을 콕 집어 물었는데 혜택이 없으면, 보유 카드 중 이 결제에 가장 이득인 카드를 함께 알려줘요
    alternative = None
    if len(ids) == 1 and (not top or top[0].value <= 0):
        alt = top_results(rank(tx, state, list(state)))
        if alt and alt[0].value > 0:
            alternative = {"card_name": alt[0].card_name, "value": alt[0].value, "unit": alt[0].unit}
            lines.append(f"[다른 카드] 보유 카드 중에서는 {alt[0].card_name} {_amount(alt[0])}")
    view = {"kind": "benefit", "tx": tx_text(tx, qty), "amount": tx.amount, "compared": len(results), "scope": scope,
            "results": [r.to_dict() for r in top], "suggestions": sugg, "by_brand": by_brand,
            "only_card": CARDS[ids[0]]["card_name"] if len(ids) == 1 else None,
            "alternative": alternative, "need_liters": need_liters, "used_up": used_up}
    return "\n".join(lines), view


def brand_breakdown(tx: Tx, state: dict, ids: list) -> list:
    """'편의점'처럼 업종으로 물었을 때 카드에 GS25·CU처럼 특정 가게에만 주는 혜택이 있으면
    가게마다 다시 계산해서 알려줘요 (업종 전체 혜택만 보면 '혜택 없음'으로 잘못 보이니까)"""
    std, cat = classify(tx.merchant)
    if not cat or std in STORE_NAMES or std not in BROAD_WORDS:
        return []                                    # 가게 이름(GS25 등)이나 좁은 업종으로 물었으면 그대로
    brands = sorted({m for cid in ids for b in CARDS[cid]["benefits"] for m in b["merchants"]
                     if CATEGORY.get(m) == cat})
    base = top_results(rank(tx, state, ids))
    base_value = base[0].value if base and base[0].unit == "원" else 0
    out = []
    for brand in brands:
        best = top_results(rank(Tx(**{**tx.__dict__, "merchant": brand}), state, ids))[0]
        if best.unit == "원" and best.value > base_value:   # 업종 전체 혜택보다 더 받는 가게만
            out.append({"brand": brand, "card_id": best.card_id, "card_name": best.card_name,
                        "value": best.value, "unit": best.unit})
    return out


def merchant_info_view(p: dict, state: dict) -> tuple[str, dict]:
    """금액 없이 '스벅 할인 얼마나 돼?' → 보유 카드에서 그 가맹점에 걸리는 혜택과 조건 (계산은 안 함)"""
    tx = Tx(p.get("merchant"), 0, overseas=bool(p.get("overseas")))
    std, cat = classify(tx.merchant)
    ids = targets(p, state)
    rows = []
    broad = bool(cat) and std not in STORE_NAMES and (std in BROAD_WORDS or std.lower() in BROAD_WORDS)
    for cid in ids:
        card, prof = CARDS[cid], state.get(cid, Profile())
        for b in card["benefits"]:
            how = match(b, std, cat, tx)
            # '배달앱', '영화'처럼 업종으로 물으면 그 업종의 특정 가게에만 주는 혜택도 보여줘요
            stores = [m for m in b["merchants"] if CATEGORY.get(m) == cat] if broad and not how else []
            if (how or stores) and "전체" not in b["merchant_categories"] and not b["stacking"]["stacks_on"]:
                ok, why = benefit_status(card, b, prof)
                if stores:
                    why += f" · {'·'.join(stores)} 한정"
                rows.append((ok, card, b, why, bool(how) and how.startswith("가맹점")))
    # 받을 수 있는 것 → 가맹점을 콕 집은 혜택 → 할인율 높은 순
    rows.sort(key=lambda x: (not x[0], not x[4], -(x[2]["reward"]["rate"] or 0)))
    rows = [r[:4] for r in rows[:TOP_N]]
    if not rows:
        return f"NEED: {std or '그 가맹점'}에 따로 걸린 혜택이 보유 카드에 없어요. 금액을 알려주시면 전 가맹점 할인까지 계산해 드릴게요.", {}
    lines = [f"[가맹점] {std} (금액을 알려주면 정확한 할인액을 계산할 수 있음)"]
    for ok, card, b, why in rows:
        lines.append(f"- {card['card_name']} / {b['name']}: {reward_text(b, card['reward_unit'])}, 조건 {condition_text(card, b)}, "
                     f"한도 {limit_text(card, b)} → 지금 {'받을 수 있음' if ok else '받을 수 없음'} ({why}) (근거 {b['source']['file']} {b['source']['page']}p)")
    return "\n".join(lines), {"kind": "info"}


OVERVIEW_CUES = ["연회비", "실적조건", "실적없", "조건없", "마일리지", "마일", "어떤카드", "카드뭐", "카드추천", "제일좋", "뭐가좋"]


def overview_view(p: dict, state: dict, q: str) -> tuple[str, dict]:
    """특정 카드 없이 카드들을 비교해 묻는 질문 (연회비 싼 카드, 실적 조건 없는 카드, 마일리지 카드)"""
    ids = targets(p, state)
    compact = q.replace(" ", "")
    cards = [CARDS[c] for c in ids]
    if "연회비" in compact:
        how = "연회비 낮은 순"
        cards.sort(key=lambda c: c["annual_fee"]["domestic"] or 0)
    elif "실적" in compact:
        how = "전월 실적 조건 낮은 순 (조건 없는 카드 먼저)"
        cards.sort(key=lambda c: c["prev_month"]["required_min"] or 0)
    elif "마일" in compact:
        how = "마일리지 적립 카드 먼저"
        cards.sort(key=lambda c: c["reward_unit"] != "마일")
    else:
        how = "보유 카드 목록"
    lines = [f"[카드 비교] {how} · {len(cards)}장"]
    for c in cards:
        fee, need = c["annual_fee"]["domestic"] or 0, c["prev_month"]["required_min"]
        top = ", ".join(f"{b['name'].split('] ')[-1]} {reward_text(b, c['reward_unit'])}" for b in c["benefits"][:3])
        lines.append(f"- {c['card_name']} ({c['card_type']}) | 연회비 {fee:,}원 | "
                     + (f"전월 {need:,}원 이상" if need else "실적 조건 없음")
                     + (" | 마일리지 적립" if c["reward_unit"] == "마일" else "") + f" | 주요 혜택: {top}")
    lines.append("어디서 얼마를 쓰는지 알려주면 이 카드들로 할인액을 계산해 드려요. (예: '스벅 15000원')")
    return "\n".join(lines), {"kind": "info"}


def card_info_view(p: dict, state: dict, q: str = "") -> tuple[str, dict]:
    if p.get("card") not in CARDS:
        return overview_view(p, state, q)
    card, prof = CARDS[p["card"]], state.get(p["card"], Profile())
    fee = card["annual_fee"]
    tier = current_tier(card, prof.prev_month)
    lines = [f"[카드] {card['card_name']} ({card['card_type']}, 연회비 국내 {fee['domestic'] or 0:,}원"
             + (f" / 해외겸용 {fee['overseas']:,}원" if fee["overseas"] else "") + ")",
             *([f"[연회비 참고] {fee['note']}"] if fee["note"] else []),
             f"[전월 실적] 입력값 {prof.prev_month:,}원" + (f", 구간 {tier}" if tier else "")
             + (f", 최소 조건 {card['prev_month']['required_min']:,}원" if card["prev_month"]["required_min"] else ", 실적 조건 없음")]
    for b in card["benefits"]:
        ok, why = benefit_status(card, b, prof)
        lines.append(f"- {b['name']}: {reward_text(b, card['reward_unit'])} | 조건 {condition_text(card, b)} | "
                     f"한도 {limit_text(card, b)} | 지금 {'받을 수 있음' if ok else '받을 수 없음'} ({why}) | 근거 {b['source']['page']}p")
    if card["perks"]:
        lines.append("[부가서비스] " + ", ".join(x["name"] for x in card["perks"]))
    return "\n".join(lines), {"kind": "info"}


def prev_month_view(p: dict, state: dict) -> tuple[str, dict]:
    item = p.get("item")
    if not item and p.get("merchant"):
        item = normalize(p["merchant"])[0]           # "스벅 15000원 쓰면 실적에 들어가?" → 그 가맹점 결제
    if not item:
        return "NEED: 어떤 항목이 전월 실적에 들어가는지 물어보신 건지 알려주세요. (예: 아파트관리비)", {}
    ids = targets(p, state)
    lines = [f"[질문 항목] {item}"]
    for cid in ids:
        card = CARDS[cid]
        pm = card["prev_month"]
        src = f"{pm['source']['file']} {pm['source']['page']}p" if pm["source"] else "근거 없음"
        if pm["required_min"] is None:
            lines.append(f"- {card['card_name']}: 전월 실적 조건이 없는 카드")
            continue
        hits = [e for e in pm["excluded"] if item in e or e in item]
        if hits:
            lines.append(f"- {card['card_name']}: 전월 실적에서 제외 (근거: {hits[0]}, {src})")
            continue
        # 설명서는 제외 항목을 목록으로 적어요. 목록에 없으면 실적으로 인정돼요
        line = f"- {card['card_name']}: 전월 실적에 포함 (설명서의 실적 제외 목록에 없음, {src})"
        no_benefit = [e for e in card["common_exclusions"] if item in e or e in item]
        if no_benefit:
            line += f" | 단, 할인·적립 대상에서는 제외: {no_benefit[0]}"
        lines.append(line)
    return "\n".join(lines), {"kind": "prev_month"}


def compute(p: dict, state: dict, q: str = "") -> tuple[str, dict]:
    multi = split_payments(q)
    if multi:
        return ("NEED: 결제가 " + str(len(multi)) + "건이네요. 한 번에 하나씩 물어봐 주세요: "
                + ", ".join(f"'{m}'" for m in multi)), {}
    if p.get("unknown_card"):
        names = ", ".join(c["card_name"] for c in CARDS.values())
        return (f"NEED: '{p['unknown_card']}'는 등록된 카드 자료에 없어서 혜택을 알려드릴 수 없어요. "
                f"지금 자료가 있는 카드는 {len(CARDS)}장이에요: {names}. "
                "이 카드들 중에서 물어보시거나, 어디서 얼마 쓰는지 말하면 이 카드들로 계산해 드려요."), {}
    if p["intent"] == "card_info":
        return card_info_view(p, state, q)
    if p["intent"] == "prev_month":
        return prev_month_view(p, state)
    if (p.get("card") not in CARDS and not p.get("merchant") and not p.get("amount")
            and any(k in q.replace(" ", "") for k in OVERVIEW_CUES)):
        return overview_view(p, state, q)
    if p.get("currency"):
        place =normalize(p["merchant"])[0] + " " if p.get("merchant") else ""
        return (f"NEED: 금액을 {p['currency']}(으)로 말씀하셨어요. 카드 혜택은 원화로 청구되는 금액으로 계산해요. "
                f"원화로 얼마인지 알려주세요. (예: '해외 {place}90000원')"), {}
    if p["intent"] == "other" and not _new_slots(p) and is_small_talk(q):
        return "NEED: 네! 다른 결제나 카드가 궁금하면 말씀해 주세요. 예) '스벅 15000원', '노리 혜택 알려줘'", {}
    if (p.get("amount") or 0) > MAX_AMOUNT:
        return (f"NEED: 결제 금액이 {int(p['amount']):,}원으로 읽혔어요. 너무 큰 금액이라 계산하지 않았어요. "
                "금액을 다시 확인해 주세요."), {}
    if p.get("amount") and not p.get("merchant") and not p.get("overseas"):
        return f"NEED: {int(p['amount']):,}원을 어디서 결제하는지 알려주세요. (예: 스벅, GS25, 지하철)", {}
    if p["intent"] != "benefit" or (not p.get("merchant") and not p.get("overseas")):
        return ("NEED: 어디서 얼마를 결제하는지 알려주세요. 예) '스벅 15000원', '토요일 이마트 6만원', "
                "'주유소 8만원 50리터', '아파트관리비 실적에 들어가?'"), {}
    if not p.get("amount"):
        return merchant_info_view(p, state)
    tx = Tx(p.get("merchant"), int(p["amount"]), pay_method=p.get("pay_method"), channel=p.get("channel"),
            location=p.get("location"), overseas=bool(p.get("overseas")), day=p.get("day"),
            hour=p.get("hour"), liters=p.get("liters"), purchase=p.get("purchase"),
            pay_type=p.get("pay_type"), fuel=p.get("fuel"))
    return benefit_view(tx, state, targets(p, state), scope_text(p), p.get("quantity"))


# '원' 뒤에서 끊으면 연결어 없이 나열한 결제도 나눠요 ("버스 1250원 지하철 1400원", "스벅 15000원에 GS25 3000원")
PAYMENT_SPLIT = re.compile(r"이랑|랑|하고|그리고|,(?!\d{3})|및|\s와\s|\s과\s|(?<=원)에?\s+")


def split_payments(q: str) -> list:
    """'스벅 15000원이랑 CU 5000원' → 결제가 여러 건이면 건별 문장 목록 (한 건이면 빈 목록)"""
    parts = [s.strip() for s in PAYMENT_SPLIT.split(q) if s.strip()]
    pays = []
    for s in parts:
        r = parse_with_rules(s)
        if r["merchant"] and r["amount"]:
            pays.append(f"{normalize(r['merchant'])[0]} {r['amount']:,}원")
    return pays if len(pays) >= 2 else []


# ---------- (3) 설명 ----------
ANSWER_PROMPT = """너는 카드 혜택 계산 결과를 설명하는 도우미야. [계산 결과]는 코드가 이미 계산한 확정값이야.
- 2~4문장으로 짧게. 가장 이득인 카드와 금액을 먼저 말하고, 필요하면 2·3위와 개선 제안 하나를 덧붙여.
- 숫자는 [계산 결과]에 있는 것만 그대로 써. 새로 계산하거나 반올림하거나 합치지 마.
- [계산 결과]에 없는 혜택·조건·의견은 덧붙이지 마. 모르면 모른다고 해.
- "받을 수 있음/없음", "포함/제외"는 결과 그대로 확실하게 말해. "가능성이 높다" 같은 말은 붙이지 마.
- 근거 페이지는 "(설명서 2p)"처럼 괄호로 남겨도 돼.
- 마크다운 기호(**, #, 표) 없이 일반 텍스트로."""

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set:
    return {n.replace(",", "").rstrip(".") for n in NUM.findall(text)}


def numbers_ok(answer: str, facts: str) -> tuple[bool, set]:
    """답변 속 숫자가 모두 계산 결과에 있는지. 순위(1~3) 같은 작은 수는 허용"""
    extra = {n for n in _numbers(answer) - _numbers(facts) if not (n.isdigit() and int(n) <= TOP_N)}
    return not extra, extra


def cards_ok(answer: str, facts: str) -> tuple[bool, set]:
    """답변에 나온 카드가 모두 계산 결과에 있는지 (계산하지 않은 카드를 권하지 않게)"""
    low = answer.lower().replace(" ", "")
    extra = {c["card_name"] for cid, c in CARDS.items() if c["card_name"] not in facts
             and (c["card_name"].replace(" ", "").lower() in low
                  or any(k.replace(" ", "") in low for k in CARD_KEYWORDS[cid] if len(k) >= 3))}
    return not extra, extra


def answer_with_llm(q: str, facts: str, prev_q: str | None = None) -> str:
    before = f"[이전 질문]\n{prev_q}\n\n" if prev_q else ""
    res = client.chat.completions.create(
        model=MODEL, temperature=0,
        messages=[{"role": "system", "content": ANSWER_PROMPT},
                  {"role": "user", "content": f"{before}[질문]\n{q}\n\n[계산 결과]\n{facts}"}],
    )
    text = res.choices[0].message.content.replace("**", "")
    return text.strip()


def answer_with_template(facts: str, view: dict) -> str:
    if facts.startswith("NEED:"):
        return facts[5:].strip()
    if view.get("kind") == "prev_month":
        lines = facts.split("\n")
        return f"'{lines[0].replace('[질문 항목] ', '')}'의 전월 실적 인정 여부예요.\n" + "\n".join(lines[1:])
    if view.get("kind") != "benefit":
        return facts.replace("[카드] ", "■ ").replace("[가맹점] ", "■ ")
    res = view["results"]
    best = res[0] if res else None
    brands = view.get("by_brand") or []
    if (not best or best["value"] <= 0) and brands:
        out = [f"'{view['tx'].split(' ')[0]}' 어디서나 주는 혜택은 없어요. 가게에 따라 달라요."]
    elif (not best or best["value"] <= 0) and view.get("only_card"):
        out = [f"{view['only_card']}는 이 결제({view['tx']})에 받을 수 있는 혜택이 없어요."]
        alt = view.get("alternative")
        if alt:
            out.append(f"보유 카드 중에서는 {alt['card_name']} {alt['value']:,}{alt['unit']}이 가장 이득이에요.")
    elif not best or best["value"] <= 0:
        out = ["이 결제로 혜택을 받을 수 있는 카드가 없어요."]
    else:
        names = " + ".join(b["name"] for b in best["applied"])
        out = [f"👉 가장 이득: {best['card_name']} {best['value']:,}{best['unit']} ({names})"]
        rest = [f"{i}위 {r['card_name']} {r['value']:,}{r['unit']}" for i, r in enumerate(res[1:], 2)]
        if rest:
            out.append(" · ".join(rest))
    if brands:
        out.append("🏪 가게에 따라 더 받아요: " + " · ".join(f"{x['brand']}에서는 {x['card_name']} {x['value']:,}{x['unit']}"
                                                   for x in brands))
    if view.get("scope"):
        out[0] = f"[{view['scope']} 비교] " + out[0]
    if view["suggestions"]:
        s = view["suggestions"][0]
        out.append(f"💡 {s['card']}: {s['text']}")
    for u in view.get("used_up") or []:
        out.append(f"ℹ️ {u['card']}의 {u['benefit']}는 이번 달 기록 때문에 빠졌어요 ({u['why']}). "
                   f"기록이 없으면 {u['value']:,}{u['unit']}이에요.")
    if view.get("need_liters"):
        out.append(f"⛽ 주유량(리터)을 알려주면 {', '.join(view['need_liters'])}의 리터당 할인도 계산해요. "
                   "(예: '주유 5만원 30리터')")
    return "\n".join(out)


INTENT_NAMES = {"benefit": "결제 혜택", "prev_month": "전월 실적 포함 여부", "card_info": "카드 정보"}


def slots_view(p: dict) -> list:
    """화면의 '이렇게 이해했어요' 칸. 코드가 해석한 값을 사람이 읽는 말로"""
    out = []
    add = lambda label, value: out.append({"label": label, "value": value})
    if p.get("intent") in ("prev_month", "card_info"):
        add("질문", INTENT_NAMES[p["intent"]])
    if p.get("item") and p.get("intent") == "prev_month":
        add("항목", p["item"])
    if p.get("merchant"):
        add("가맹점", normalize(p["merchant"])[0])
    elif p.get("overseas") and p.get("intent") == "benefit":
        add("가맹점", "해외 가맹점")
    if p.get("amount"):
        qty = p.get("quantity")
        add("금액", f"{int(p['amount']):,}원" + (f" ({int(p['amount']) // qty:,}원 × {qty})" if qty and qty > 1 else ""))
    if p.get("day"):
        add("요일", f"{p['day']}요일")
    if p.get("hour") is not None:
        h = p["hour"]
        add("시간", "자정" if h == 0 else f"오전 {h}시" if h < 12 else "정오" if h == 12 else f"오후 {h - 12}시")
    if p.get("overseas") and p.get("merchant"):
        add("장소", "해외")
    if p.get("location"):
        add("장소", f"{p['location']} 입점 매장")
    if p.get("liters"):
        add("주유량", f"{p['liters']:g}리터")
    if p.get("fuel"):
        add("연료", p["fuel"])
    if p.get("pay_method"):
        add("결제수단", p["pay_method"])
    if p.get("pay_type"):
        add("결제 방식", p["pay_type"])
    if p.get("purchase"):
        add("구매", p["purchase"])
    if p.get("card") in CARDS:
        add("카드", CARDS[p["card"]]["card_name"])
    elif p.get("cards"):
        add("비교", " · ".join(CARDS[c]["card_name"] for c in p["cards"] if c in CARDS))
    else:
        if p.get("issuer"):
            add("카드사", p["issuer"])
        if p.get("card_type"):
            add("카드 종류", f"{p['card_type']}카드")
    if p.get("exclude_cards"):
        add("제외", ", ".join(CARDS[c]["card_name"] for c in p["exclude_cards"] if c in CARDS))
    if p.get("prev_month_stated") is not None:
        add("전월 실적", f"{int(p['prev_month_stated']):,}원 (말한 값)")
    return out


def ask_turn(q: str, state: dict | None = None, context: dict | None = None, link: str = "auto") -> dict:
    """한 턴 대화. 돌려받은 context를 다음 질문 때 그대로 넘기면 후속 질문을 이어받아요.
    link: "auto" | "follow"(이어서) | "new"(새 질문)
    반환: {answer, context, followup, view, checked}"""
    state = dict(state or default_state())
    link = link if link in LINK_MODES else "auto"
    p, followed = resolve(q, context, link)
    stated = p.get("prev_month_stated")
    if isinstance(stated, int) and not isinstance(stated, bool) and stated >= 0:
        # "전월 15만원 썼는데"처럼 질문에서 말한 실적이 화면 입력값보다 우선
        for cid in targets(p, state):
            prof = state.get(cid, Profile())
            state[cid] = Profile(**{**prof.__dict__, "prev_month": stated})
    facts, view = compute(p, state, q)
    prev_q = (context or {}).get("q") if followed else None
    answer, checked = None, "template"
    # LLM 설명은 결제 순위 설명에만 써요. 실적 포함 여부·카드 정보처럼 카드별 사실을 나열하는 답은
    # LLM이 요약하다 다른 카드의 조건을 섞은 적이 있어서 코드 문장 그대로 보여줘요.
    # '혜택 받을 카드 없음'도 LLM이 없는 권유를 덧붙인 적이 있어서 코드 문장으로.
    explainable = view.get("kind") == "benefit" and any(r["value"] > 0 for r in view["results"])
    if USE_LLM and EXPLAIN_WITH_LLM and explainable:
        try:
            answer = answer_with_llm(q, facts, prev_q)
            ok, extra = numbers_ok(answer, facts)
            ok_cards, extra_cards = cards_ok(answer, facts)
            checked = "llm"
            if not ok or not ok_cards:
                print(f"  (LLM 답변에 계산 결과에 없는 값 {sorted(extra | extra_cards)} → 코드 문장으로 대체)")
                answer, checked = None, "llm_rejected"
        except Exception as e:
            print(f"  (LLM 답변 실패, 기본 형식으로 표시: {e})")
    answer = answer or answer_with_template(facts, view)
    q_text = f"{prev_q} → {q}" if prev_q else q
    return {"answer": answer, "context": {"q": q_text[-200:], "parsed": p}, "followup": followed, "link": link,
            "slots": slots_view(p),
            "view": view, "checked": checked, "facts": facts}


def ask(q: str, state: dict | None = None) -> str:
    return ask_turn(q, state)["answer"]


def main():
    state = default_state()
    mode = f"LLM 모드 ({MODEL})" if USE_LLM else "키워드 모드 (.env에 API 키를 넣으면 LLM 모드)"
    print("=" * 55)
    print(f" 내 카드 혜택 챗봇 - {mode}")
    print(" 보유 카드: " + ", ".join(f"{CARDS[c]['card_name']}(전월 {p.prev_month:,}원)" for c, p in state.items()))
    print(" 종료: q")
    print("=" * 55)
    context = None
    while True:
        q = input("\n나: ").strip()
        if q.lower() in ("q", "quit", "exit", "종료"):
            break
        if q:
            t = ask_turn(q, state, context)
            context = t["context"]
            print("\n챗봇: " + ("(이전 질문에 이어서) " if t["followup"] else "") + t["answer"])


if __name__ == "__main__":
    main()
