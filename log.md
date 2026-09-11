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

## [2026-09-11] lint | 누락 점검 후 보강
- 점검: 원본 대비 위키 커버리지 확인 (외부 서비스 언급 25종 대조, 빈 카테고리 확인)
- 생성: wiki/domain/경쟁-서비스 — 시그널 스노우볼·뱅크샐러드 등 9종
- 생성: wiki/glossary/{연금-용어, 사내-용어} — 빈 카테고리였음
- 생성: wiki/decisions/{결정-이력, 사실과-계획-분리} — 빈 카테고리였음
- 생성: wiki/systems/디자인-산출물, wiki/notes/파트-타임라인
- 수정: wiki/projects/평생보장소득-PRD — 컨셉 5축·온보딩·화면상세·게이미피케이션 추가
- 수정: wiki/notes/확인필요-목록 — 모순·공백 6건 신규 기록
- 수정: wiki/overview.md, index.md
- 발견: 세후/세전 표기 기준 충돌, 위험방어 설계 누락, R1~R5 미상, KPI 부재
- 미해결: 창립기념품 PDF를 이 환경에서 열 수 없음 (poppler 미설치)

## [2026-09-11] ingest | 멤버 프로필 사이트 구축 (team)
- 참조: ../members 프로젝트 규약 이식 (재미/업무 분리, 근거 강도 필수 표기)
- 생성: docs/PROFILE_SCHEMA.md, docs/PRIVACY.md
- 생성: scripts/{extract_signals,build_site,test_build_site}.py
- 생성: data/signals.json, data/profiles/*.json 7명분
- 생성: .github/workflows/pages.yml — 매일 09:00 KST 자동 갱신
- 생성: wiki/systems/프로필-사이트.md
- 수정: wiki/people/*.md 7개에 프로필 링크, overview.md, index.md, CLAUDE.md
- 수정: extract_signals.py 버그 2건 — 텔레그램 미파싱, 첨부파일명·인용문 오염
- 확인: 저장소가 public 이며 파트가 인지하고 공개 유지하기로 결정

## [2026-09-11] ingest | 파트 회의록 3세션 (클로바 노트)
- 소스: raw/meetings/2026-09-파트회의-클로바노트-3세션.md (화자 익명, 날짜 추정)
- 생성: wiki/sources/2026-09-파트회의-클로바노트-3세션, wiki/domain/키워드-검색-조사
- 수정: 마이데이터-연금정보 — "예상수령액 안 온다" → 국민연금은 쿠콘 스크래핑으로 가능 (정정 표시)
- 수정: 통합연금포털, 경쟁-서비스, 주택연금, 규제-법무-검토항목(+3건)
- 수정: 평생보장소득(벽 2건 추가), PRD(용어·탭 변천·여유층), 개발범위(인출 2차·소셜로그인)
- 수정: 결정-이력(+6건), 고객서비스파트(리정=이정은 추정, 정미·은영·본부장), 용어집 2종
- 수정: 이정은·이강민·전승찬 이력, 확인필요-목록, overview, index
- 발견: 전사 오류 정정표 (하나생명→한화생명, 이정민/리정→이정은, 정우→한정은)
