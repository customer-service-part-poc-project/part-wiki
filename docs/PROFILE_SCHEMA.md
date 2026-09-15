# 멤버 프로필 스키마 (정본)

`data/profiles/{이름}.json` 의 형식. `scripts/build_site.py` 가 빌드 전에 이 스키마를 검증하고,
어긋나면 **해당 파일만 건너뛰고 이유를 출력**한다 (한 사람 때문에 전체가 막히지 않는다).

`../members` 프로젝트의 `SUMMARY_SCHEMA.md` 규약을 이식했다. 특히 **근거 강도 표기는 필수**다.

---

## 전체 구조

```json
{
  "schema_version": 1,
  "name": "김동준",
  "part": "고객서비스파트",
  "role": "BE",
  "generated": "2026-09-11",
  "sources": ["slack:proj-평생보장소득", "telegram:고객서비스파트"],

  "signals": {
    "utterances": 10,
    "total_chars": 3205,
    "avg_chars": 320,
    "active_hours": "07~18",
    "markers": { "존댓말요": 21, "습니다": 7, "확인요구": 4, "제안형": 4, "단정": 3 },
    "endings_top": ["입니다", "같아요", "습니다", "드려요"],
    "artifacts": 7,
    "confidence": "중간"
  },

  "profile": {
    "axes": { "delegation": 3, "verification": 5, "planning": 4, "thoroughness": 5, "exploration": 3 },
    "work_style": "2~3줄. 관측된 행동 근거로만 쓴다",
    "strengths": ["근거 있는 강점 1", "2", "3"]
  },

  "fun": {
    "mbti":       { "value": "INTJ",      "strength": "약함",        "basis": "축별 근거 한 줄" },
    "age_band":   { "value": "30대 중반", "strength": "약함",        "basis": "ㅋㅋ 1건 · 존댓말 21건 · 야간 0%" },
    "speech_badge": { "value": "검증부터 말하는 사람", "strength": "관측", "basis": "확인 표현을 파트 평균의 3.7배로 쓴다 · 관측 5건" },
    "nickname": "한 줄 별명 (호의적으로)",
    "how_to_talk": {
      "good":      ["이 사람에게 통하는 요청 방식 2~4개"],
      "avoid":     ["피하면 좋은 방식 1~3개"],
      "best_time": "07~10시 (가장 먼저 응답하는 시간대)",
      "example":   "실제로 보낼 법한 메시지 한 줄 예시"
    }
  }
}
```

---

## 필드 규칙

### `signals` — 관측값만
원문 인용을 넣지 않는다. **집계 수치만** 넣는다. 이 블록이 `profile` 과 `fun` 의 근거가 된다.

| `confidence` | 기준 |
|---|---|
| `높음` | 발화 15건 이상 |
| `중간` | 발화 5~14건 |
| `낮음` | 발화 5건 미만 — **화면에 경고를 함께 띄운다** |

### `profile` — 근거 있는 것만 (members 8장에 대응)
관측된 행동으로 뒷받침되는 내용만 쓴다. 실제 업무 참고에 쓸 수 있는 수준.

`axes` 는 1~5. 방향은 아래와 같다.

| 축 | 1점 | 5점 |
|---|---|---|
| `delegation` | 직접 처리 | 위임·분담 |
| `verification` | 결과를 그대로 수용 | 검증·팩트체크 집착 |
| `planning` | 즉흥 | 계획 우선 |
| `thoroughness` | 요점만 | 끝까지 파고듦 |
| `exploration` | 단정형 | 탐색·제안형 |

### `fun` — 재미 코너 (members 9장에 대응)
**근거 강도 표기가 없으면 빌드가 거부된다.**

| 항목 | 허용 strength | 무엇으로 찍는가 |
|---|---|---|
| `speech_badge` | `관측` | **파트 평균 대비 두드러진 말투 마커.** 수치는 `extract_signals.py` 가 자동 계산하고(`badge`) 이름표만 사람이 붙인다 |
| `mbti` | `약함` | E/I 발화량·먼저 나서는 빈도 · S/N 구체성 · T/F 겸양·칭찬 마커 · J/P 계획 우선도 |
| `age_band` | `약함` | ㅋㅋ/ㅎㅎ · 이모지 · 말줄임 · 존댓말 습관 · 활동 시간대 |
| `how_to_talk` | (강도 없음) | 관측된 응답 패턴·활동 시간대·말투 |

`signals.reactions_top` 은 **받은 반응** 카드가 읽는다. `[[이모지, 개수], …]` 상위 3종이고
화면에는 **이모지만** 나간다. 개수는 발화량에 비례해 사람 사이 비교가 되므로 싣지 않는다.

> **폐지된 항목**: `blood_type` 은 2026-09-15 에 뺐다. 근거 강도를 "없음(무작위)" 로 밝혀도
> 결국 근거가 0인 값을 사람 카드에 싣는 일이었다. JSON 에 남아 있으면 빌드가 거부한다.
> 재미 요소는 **관측된 신호에서 나오는 것**으로 대체한다.

---

## 검증 — 빌드가 거부하는 조건

`scripts/build_site.py` 가 확인한다.

1. `schema_version == 1`
2. `name` 이 파일명과 일치
3. **금지 키 없음**: `samples_*`, `raw_quote`, `quotes`, `gender`, `성별`
4. **`fun` 의 mbti·age_band·speech_badge 에 `strength` 필드 존재** (폐지 항목 `blood_type` 이 있으면 거부)
5. **금지 패턴 없음** (→ `docs/PRIVACY.md`)

## 관련
- [docs/PRIVACY.md](PRIVACY.md) — 공개 범위와 금지 패턴
- `../members/docs/SUMMARY_SCHEMA.md` — 원본 규약
