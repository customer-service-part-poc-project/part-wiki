# 작업 로그

시간순 append-only 기록. 새 항목은 **맨 아래**에 추가한다.

형식 (고정 — `grep "^## \[" log.md | tail -5` 로 최근 작업 확인):
```
## [YYYY-MM-DD] ingest|query|lint|decision | 제목
- 소스: raw/...
- 생성: wiki/...
- 수정: wiki/...
```

---

## [2026-09-11] decision | 파트 위키 개설
- 생성: CLAUDE.md, README.md, index.md, log.md, wiki/overview.md, templates/
- 결정: llm-wiki 패턴을 CS 파트용으로 인스턴스화. raw 불변 / wiki는 LLM 소유 / 고객 개인정보 마스킹 원칙 확정
