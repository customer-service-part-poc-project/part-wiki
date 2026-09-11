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

## [2026-09-11] ingest | 텔레그램 파트방 초기 대화
- 소스: raw/threads/2026-09-10-텔레그램-파트방/
- 생성: wiki/sources/2026-09-10-..., wiki/orgs/고객서비스파트, wiki/people/{이강민,김동준,이정은}
- 생성: wiki/processes/{주간업무-작성,근태-공유}, wiki/systems/텔레그램-파트방
- 생성: wiki/projects/{Direct-변액저축보험, 평생-보장소득-은퇴설계-플랫폼}
- 수정: wiki/overview.md, wiki/notes/확인필요-목록.md, index.md

## [2026-09-11] ingest | 슬랙 proj-평생보장소득 + PRD
- 소스: raw/threads/2026-08-24-슬랙-proj-평생보장소득.md (붙여넣기 사본, 정식 export 아님)
- 소스: raw/docs/2026-09-11-은퇴설계-플랫폼-PRD-스냅샷.md
- 소스: raw/docs/2026-09-01-한화그룹-창립기념품-리스트.pdf
- 생성: wiki/domain/ 신설 — 주택연금, 마이데이터-연금정보, 부부합산-마이데이터-제약, 연금-세제, 통합연금포털
- 생성: wiki/projects/{평생보장소득, 평생보장소득-PRD, 평생보장소득-개발범위}
- 생성: wiki/notes/{평생보장소득-보고-이력, 규제-법무-검토항목}
- 생성: wiki/processes/과제-검토-분담, wiki/systems/협업-도구-현황
- 생성: wiki/people/{한민우,전승찬,박정훈,한정은,김민지}
- 수정: wiki/orgs/고객서비스파트(직무·보고라인 확인), wiki/people/{이강민,이정은,김동준}
- 수정: wiki/overview.md 전면 개편, wiki/notes/확인필요-목록.md, index.md, CLAUDE.md
- 삭제: wiki/projects/평생-보장소득-은퇴설계-플랫폼.md → wiki/projects/평생보장소득.md 로 통합
- 정정: 텔레그램 페이지의 "슬랙→텔레그램 이전" 추론이 틀렸음. 4개 도구 병행이 사실
