# 카드 데이터 (schema v2)

카드 상품설명서를 옮긴 데이터입니다. **모든 카드 파일은 같은 키를 갖고**, 해당 없는 값은 `null` 또는 빈 목록으로 둡니다.
구조 정의와 검사는 [`src/card_schema.py`](../../src/card_schema.py) 한 곳에 있습니다.

```
data/pdf/            원본 설명서
data/cards/*.json    카드별 데이터 (이 폴더)
data/cards/summary/  카드별 특징 요약 (JSON에서 자동 생성, 직접 고치지 않음)
```

## 카드 추가·수정 순서

1. `data/pdf/`에 설명서를 넣는다.
2. `data/cards/<card_id>.json`을 작성한다. 필요한 값만 써도 된다.
3. `python src/card_schema.py --fix` → 빠진 키를 채우고 오류(없는 구간·그룹 참조, 근거 누락 등)를 알려준다.
4. `python src/card_summary.py` → `summary/`의 특징 요약을 다시 만든다.
5. 다른 사람이 설명서와 대조해 검수하고 `review.status`를 바꾼다.

## 카드 최상위 필드

| 필드 | 설명 |
|---|---|
| `card_id`, `card_name`, `issuer` | 식별자, 카드 이름, 카드사 |
| `card_type` | `신용` / `체크` |
| `reward_unit` | `원`(할인·캐시백) / `마일`(마일리지). 마일 카드는 원화 할인과 같은 순위로 비교하지 않음 |
| `sources` | 근거 자료 목록. `kind`: 상품설명서 / 홈페이지 / 프로모션 / 브랜드서비스안내 |
| `annual_fee` | `domestic`, `overseas`, `mobile`(원), `note` |
| `issue_notes` | 발급 대상·조건 |
| `prev_month` | 전월 실적: `required_min`(최소 실적, 없으면 null), `basis`, `excluded`(실적 제외 항목), `grace`(신규 발급 특례) |
| `tiers` | 실적 구간 `[{id, prev_month_min, prev_month_max}]` |
| `limit_groups` | 여러 혜택이 함께 쓰는 한도. `kind`: 할인액 / 이용금액 / 마일리지. `per_month_by_tier`는 구간마다 다른 한도 |
| `options` | 사용자가 고르는 선택형 혜택 (예: 서비스팩 A/B) |
| `benefits` | 혜택 목록 (아래) |
| `common_exclusions` | 모든 혜택에서 빠지는 결제 |
| `perks` | 라운지·발렛처럼 금액으로 계산하지 않는 부가서비스 |
| `review` | 검수 상태, 확인한 부분, 남은 일 |

### `grace.effect`

| 값 | 의미 | 예 |
|---|---|---|
| `tier` | 실적 미달이어도 `tier` 구간으로 간주 | 헤이영, K-패스, NH |
| `limit_override` | 월 한도를 `limit`으로 고정 | 노리 (60일간 월 1만원) |
| `limit_ratio` | 혜택별 한도의 `limit_ratio`배 | Youth Club (50%) |

`only_benefits`가 있으면 그 혜택에만, `excluded_benefits`에 있는 혜택은 빼고 적용합니다.

## 혜택(`benefits`) 필드

| 필드 | 설명 |
|---|---|
| `merchants` | 특정 가맹점 이름 (아래 표준 이름) |
| `merchant_categories` | 업종. `전체`는 모든 가맹점 |
| `scope` | `국내` / `해외` / `전체`(국내+해외 모두) |
| `reward.kind` | `정률`(`rate`), `정액`(`amount` 또는 `amount_usd`), `리터당`(`per_liter`), `마일리지`(`miles_per_1000`, `rounding`) |
| `requires.tier` | 이 구간 이상일 때만 |
| `requires.prev_month_min` | 혜택 자체의 실적 조건. `null`이면 카드의 `required_min`을 따르고, `0`이면 조건 없음, `1`이면 "실적 있음" |
| `requires.option` | 선택형 조건 (예: `{"pack": "A"}`) |
| `requires.pay_methods` / `channel` / `days` / `hours` | 결제수단, 온라인·오프라인, 요일, 시간대 |
| `requires.min_payment_per_txn` | 건당 최소 결제금액 |
| `requires.card_brand` / `enrollment` / `valid_period` | 해외겸용 등 브랜드, 별도 가입, 적용 기간 |
| `caps` | 건당 대상금액·할인액 상한, 일/월 대상금액, 월·연 할인액, 일/월/연 횟수. `count_scope`: 혜택 / 가맹점별 / 영역 통합 |
| `groups` | 함께 쓰는 한도 그룹 id |
| `stacking` | `stacks_on`(추가 할인의 기준 혜택), `exclusive_with`(동시에 못 받는 혜택), `rule`(설명) |
| `source` | 근거 `{file, page}` — **모든 혜택에 필수** |

## 표준 이름

업종: 전체, 대중교통, 택시, 철도, 주유, 통신, 커피, 편의점, 약국, 병원, 패스트푸드, 음식점, 할인마트, 백화점, 학원, 피트니스, 세탁소, 노래방, PC방, 전기요금, 도시가스, 해외ATM

결제수단: KB Pay, 신한PayFAN, 삼성페이, NH pay, 네이버페이, 카카오페이, 스마일페이
