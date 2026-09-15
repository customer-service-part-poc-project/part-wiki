#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`data/profiles/*.json` 과 `data/projects/*.json` 으로 정적 파트 사이트를 만든다.

표준 라이브러리만 쓴다 (Python 3.9+). 외부 패키지·CDN·네트워크를 쓰지 않으며,
생성한 HTML 은 CSS 를 인라인으로 품고 있어 file:// 로 열어도 그대로 보인다.

    python3 scripts/build_site.py --out _site
    python3 scripts/build_site.py --out _site --data data/profiles --projects data/projects

빌드는 프로필·프로젝트를 한 건씩 검증한다. 어긋난 파일은 **그 파일만 건너뛰고** 이유를 stderr 에 남긴다.
한 사람의 실수로 다른 사람 페이지까지 막지 않기 위해서다.
유효한 프로필이 하나도 없을 때만 종료 코드 1 로 실패한다. 프로젝트는 0건이어도 된다 (섹션만 빠진다).

정본 스키마: docs/PROFILE_SCHEMA.md · docs/PROJECT_SCHEMA.md
공개 범위·금지 패턴: docs/PRIVACY.md
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
DEFAULT_PART = "고객서비스파트"
KST = datetime.timezone(datetime.timedelta(hours=9), "KST")

# 사이트 어디에나 붙는 고정 문구. 추측을 사실처럼 읽지 않게 하는 장치다.
BANNER = "MBTI·나이대는 추측이다. 말투 뱃지와 받은 반응은 관측값이다."

# ── 검증 규칙 (docs/PROFILE_SCHEMA.md · docs/PRIVACY.md) ──────────────────────
# 중첩 어디에 있어도 거부하는 키. 원문 인용과 성별 추정을 막는다.
FORBIDDEN_KEY_EXACT = ("raw_quote", "quotes", "gender", "성별")
FORBIDDEN_KEY_PREFIX = ("samples_",)

# JSON 전체를 문자열로 훑어 찾는 금지 패턴.
FORBIDDEN_PATTERNS = (
    ("사내 URL", re.compile(
        r"sharepoint\.com|hanwhalifem365|docs\.google\.com|notion\.com|app\.notion", re.I)),
    ("임원·타부서 실명", re.compile(r"이창희|조정연|강정민|박기우|김상혁")),
    ("전화번호", re.compile(r"01[016-9][-\s]?\d{3,4}[-\s]?\d{4}")),
    ("이메일", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("주민등록번호 형태", re.compile(r"\d{6}[-\s]?[1-4]\d{6}")),
)

# 파일 경로로 새어 나가면 곤란한 문자를 이름에서 막는다.
UNSAFE_NAME = re.compile(r"[/\\:*?\"<>|\x00-\x1f]")

FUN_KEYS = (("mbti", "MBTI"), ("age_band", "나이대"), ("speech_badge", "말투 뱃지"))

# 근거가 0인 항목은 싣지 않는다. 혈액형은 그래서 2026-09-15 에 뺐다.
RETIRED_FUN_KEYS = ("blood_type",)

AXIS_ORDER = ["delegation", "verification", "planning", "thoroughness", "exploration"]
AXIS_KO = {"delegation": "위임", "verification": "검증", "planning": "계획",
           "thoroughness": "집요함", "exploration": "탐색"}
AXIS_POLE = {
    "delegation": ("직접 처리", "위임·분담"),
    "verification": ("결과를 그대로 수용", "검증·팩트체크"),
    "planning": ("즉흥", "계획 우선"),
    "thoroughness": ("요점만", "끝까지 파고듦"),
    "exploration": ("단정형", "탐색·제안형"),
}

# 표에 찍는 순서. 없는 키는 조용히 건너뛴다 (구버전 JSON 호환).
# chat_chars·avg_chat_chars 는 첨부 문서·인용문을 뺀 '순수 대화' 값이라
# 바로 위의 total_chars·avg_chars 와 나란히 두어 대비가 보이게 한다.
SIGNAL_ROWS = (
    ("utterances", "발화 수", "건"),
    ("total_chars", "총 글자 수", "자"),
    ("chat_chars", "대화만 글자 수", "자"),
    ("avg_chars", "평균 길이", "자"),
    ("avg_chat_chars", "평균 대화 길이", "자"),
    ("artifacts", "산출물 언급", "건"),
    ("active_hours", "활동 시간대", ""),
    ("confidence", "신뢰도", ""),
)

# 평균 길이가 평균 대화 길이의 이 배수 이상이면 대비를 배지로 표시한다.
CHAT_GAP_RATIO = 2.0

# ── 프로젝트 (docs/PROJECT_SCHEMA.md) ─────────────────────────────────────────
# 과제 상태. 이 넷 밖의 값은 거부한다 — 카드 색과 정렬이 여기에 묶여 있다.
PROJECT_STATUSES = ("준비", "진행중", "보류", "완료")
PROJECT_STATUS_CLASS = {"준비": "ps-todo", "진행중": "ps-doing", "보류": "ps-hold", "완료": "ps-done"}
# 목록에서 진행 중인 과제가 먼저 오게 한다.
PROJECT_STATUS_ORDER = {"진행중": 0, "준비": 1, "보류": 2, "완료": 3}
MILESTONE_STATES = ("done", "doing", "todo")
MILESTONE_KO = {"done": "완료", "doing": "진행 중", "todo": "예정"}
# 영역별 현황의 state 는 자유 텍스트다. 색만 낱말로 추정한다.
WORK_STATE_HINTS = (("완료", "ws-done"), ("진행", "ws-doing"), ("검토", "ws-doing"),
                    ("대기", "ws-todo"), ("보류", "ws-hold"), ("미착수", "ws-todo"))
# 과제 페이지 상단 고정 문구. 위키 요약을 확정 계획으로 읽지 않게 하는 장치다.
PROJECT_BANNER = "과제 페이지는 위키 요약이다. 일정·범위는 데이터 기준일 시점의 상태이며 확정이 아니다."


# ══════════════════════════════════════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════════════════════════════════════
def esc(v) -> str:
    """모든 사용자 입력은 여기를 반드시 거친다. 이름에 '<' 가 있어도 깨지지 않게."""
    return html.escape("" if v is None else str(v), quote=True)


def num(v, d=0):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def fmt_int(v) -> str:
    n = num(v)
    if isinstance(n, float) and not n.is_integer():
        return f"{n:,.1f}"
    return f"{int(n):,}"


def g(d, path, default=None):
    """'fun.mbti.value' 처럼 점 경로로 꺼낸다. 중간이 없으면 default."""
    cur = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return default if cur is None else cur


def text(v) -> str:
    return str(v).strip() if isinstance(v, (str, int, float)) else ""


def str_list(v, limit=None):
    if not isinstance(v, (list, tuple)):
        return []
    out = [text(x) for x in v if text(x)]
    return out[:limit] if limit else out


def mask(s: str) -> str:
    """금지 패턴이 걸렸을 때 로그로 원문을 그대로 흘리지 않는다."""
    s = str(s)
    if len(s) <= 2:
        return "*" * len(s)
    return s[0] + "*" * (len(s) - 2) + s[-1]


def warn(msg: str) -> None:
    print(msg, file=sys.stderr)


# ══════════════════════════════════════════════════════════════════════════════
# 검증 — 어긋난 파일만 건너뛴다
# ══════════════════════════════════════════════════════════════════════════════
def scan_forbidden_keys(node, path="$"):
    """중첩 dict/list 를 끝까지 내려가며 금지 키를 모은다."""
    hits = []
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}"
            ks = str(k)
            if ks in FORBIDDEN_KEY_EXACT or ks.startswith(FORBIDDEN_KEY_PREFIX):
                hits.append(p)
            hits.extend(scan_forbidden_keys(v, p))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            hits.extend(scan_forbidden_keys(v, f"{path}[{i}]"))
    return hits


def validate(data, json_path: "Path | str"):
    """거부 사유를 한국어 문장 리스트로 돌려준다. 빈 리스트면 통과.

    json_path 는 Path 든 문자열이든 받는다 (진입부에서 Path 로 정규화한다).
    """
    json_path = Path(json_path)
    errors = []
    E = errors.append

    if not isinstance(data, dict):
        return [f"최상위가 객체가 아닙니다 (현재 {type(data).__name__})"]

    # 1) 스키마 버전
    if data.get("schema_version") != SCHEMA_VERSION:
        E(f"schema_version: {SCHEMA_VERSION} 이어야 합니다 (현재 {data.get('schema_version')!r})")

    # 2) 파일명 ↔ name 일치
    name = data.get("name")
    stem = json_path.stem
    if not isinstance(name, str) or not name.strip():
        E("name: 비어 있습니다")
    elif name.strip() != stem:
        E(f"name: 파일명과 다릅니다 (name={name.strip()!r} · 파일={stem!r})")
    elif UNSAFE_NAME.search(name) or name.strip() in (".", ".."):
        E(f"name: 파일 경로로 쓸 수 없는 문자가 있습니다 ({name.strip()!r})")

    # 3) 금지 키 (중첩 포함)
    for p in scan_forbidden_keys(data):
        E(f"금지 키: {p} — 원문 인용·성별 추정은 넣지 않습니다 (docs/PRIVACY.md)")

    # 4) fun 근거 강도 표기 — 없으면 추측이 사실처럼 회람된다
    fun = data.get("fun", None)
    if fun is not None:
        if not isinstance(fun, dict):
            E("fun: 객체이거나 null 이어야 합니다 (재미 코너를 빼려면 null)")
        else:
            for key, ko in FUN_KEYS:
                blk = fun.get(key)
                if not isinstance(blk, dict):
                    E(f"fun.{key}: {{\"value\":…, \"strength\":…, \"basis\":…}} 객체가 필요합니다")
                elif not text(blk.get("strength")):
                    E(f"fun.{key}.strength: 근거 강도 표기가 없습니다 ({ko})")
            for key in RETIRED_FUN_KEYS:
                if key in fun:
                    E(f"fun.{key}: 근거가 없어 폐지된 항목입니다. JSON 에서 지우세요")

    # 5) 금지 패턴 — JSON 전체를 문자열로 훑는다
    blob = json.dumps(data, ensure_ascii=False)
    for label, rx in FORBIDDEN_PATTERNS:
        m = rx.search(blob)
        if m:
            E(f"금지 패턴({label}): {mask(m.group(0))} — docs/PRIVACY.md")

    return errors


def validate_project(data, json_path: "Path | str"):
    """프로젝트 JSON 의 거부 사유를 돌려준다. 빈 리스트면 통과 (docs/PROJECT_SCHEMA.md).

    프로필과 같은 금지 키·금지 패턴을 그대로 적용한다. 과제 페이지도 public 으로 나간다.
    """
    json_path = Path(json_path)
    errors = []
    E = errors.append

    if not isinstance(data, dict):
        return [f"최상위가 객체가 아닙니다 (현재 {type(data).__name__})"]

    if data.get("schema_version") != SCHEMA_VERSION:
        E(f"schema_version: {SCHEMA_VERSION} 이어야 합니다 (현재 {data.get('schema_version')!r})")

    name = data.get("name")
    stem = json_path.stem
    if not isinstance(name, str) or not name.strip():
        E("name: 비어 있습니다")
    elif name.strip() != stem:
        E(f"name: 파일명과 다릅니다 (name={name.strip()!r} · 파일={stem!r})")
    elif UNSAFE_NAME.search(name) or name.strip() in (".", ".."):
        E(f"name: 파일 경로로 쓸 수 없는 문자가 있습니다 ({name.strip()!r})")

    if not text(data.get("title")):
        E("title: 비어 있습니다 (카드에 표시할 과제명)")

    status = text(data.get("status"))
    if status not in PROJECT_STATUSES:
        E(f"status: {' | '.join(PROJECT_STATUSES)} 중 하나여야 합니다 (현재 {status!r})")

    ms = data.get("milestones", [])
    if ms is not None and not isinstance(ms, list):
        E("milestones: 배열이어야 합니다")
    else:
        for i, m in enumerate(ms or []):
            if not isinstance(m, dict) or not text(m.get("label")):
                E(f"milestones[{i}]: {{\"label\":…, \"date\":…, \"state\":…}} 객체가 필요합니다")
            elif text(m.get("state")) not in MILESTONE_STATES:
                E(f"milestones[{i}].state: {' | '.join(MILESTONE_STATES)} 중 하나여야 합니다 "
                  f"(현재 {text(m.get('state'))!r})")

    for key in ("workstreams", "members", "recent"):
        v = data.get(key, [])
        if v is not None and not isinstance(v, list):
            E(f"{key}: 배열이어야 합니다")
    for i, m in enumerate(data.get("members") or []):
        if not isinstance(m, dict) or not text(m.get("name")):
            E(f"members[{i}]: {{\"name\":…, \"role\":…}} 객체가 필요합니다")

    for p in scan_forbidden_keys(data):
        E(f"금지 키: {p} — 원문 인용·성별 추정은 넣지 않습니다 (docs/PRIVACY.md)")

    blob = json.dumps(data, ensure_ascii=False)
    for label, rx in FORBIDDEN_PATTERNS:
        m = rx.search(blob)
        if m:
            E(f"금지 패턴({label}): {mask(m.group(0))} — docs/PRIVACY.md")

    return errors


def project_progress(milestones):
    """(완료 수, 전체 수, 다음 마일스톤 라벨). 진행 중인 것이 있으면 그것이 '다음'이다."""
    items = [m for m in (milestones or []) if isinstance(m, dict) and text(m.get("label"))]
    done = sum(1 for m in items if text(m.get("state")) == "done")
    nxt = ""
    for want in ("doing", "todo"):
        for m in items:
            if text(m.get("state")) == want:
                nxt = text(m.get("label"))
                break
        if nxt:
            break
    return done, len(items), nxt


def load_json(path: Path):
    """(data, 오류문) 을 돌려준다."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as e:
        return None, f"JSON 파싱 실패 — {e.lineno}행 {e.colno}열: {e.msg}"
    except OSError as e:
        return None, f"파일을 읽지 못했습니다 — {e}"


# ══════════════════════════════════════════════════════════════════════════════
# 스타일 — 외부 파일·CDN 없이 인라인으로만 넣는다
# ══════════════════════════════════════════════════════════════════════════════
CSS = """
:root{
  --bg:#F5F2EB; --card:#FFFFFF; --ink:#17140F; --ink2:#4A423A; --muted:#7C7268;
  --line:#E3DBCF; --line2:#F0EBE2; --soft:#FBF8F3; --hero:#17140F; --hero-ink:#F7F3EC;
  --accent:#C8471F; --accent-soft:#FBE9E1;
  --work:#175B63; --work-soft:#E4EFF0;
  --fun:#6D4A9E; --fun-soft:#F0E9FA; --fun-bg:#FAF6FF; --fun-stripe:rgba(109,74,158,.045);
  --talk:#0F6B4F; --talk-soft:#E2F3EC;
  --warn:#98310D; --warn-soft:#FCE6D9; --warn-line:#E9A98C;
  --proj:#1F5A9E; --proj-soft:#E3ECF8; --proj-line:#B9CDEB;
  --shadow:0 1px 2px rgba(23,20,15,.05);
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#131211; --card:#1D1B19; --ink:#EFE9E0; --ink2:#C6BCAF; --muted:#948B80;
    --line:#33302B; --line2:#262421; --soft:#211F1C; --hero:#0C0B0A; --hero-ink:#F3EDE4;
    --accent:#FF8B5E; --accent-soft:#39221A;
    --work:#6FC7CE; --work-soft:#15282A;
    --fun:#C4A4F0; --fun-soft:#251E33; --fun-bg:#1C1826; --fun-stripe:rgba(196,164,240,.06);
    --talk:#6FD3AA; --talk-soft:#12261E;
    --warn:#FFAA82; --warn-soft:#3A2115; --warn-line:#6E4128;
    --proj:#8DB8F2; --proj-soft:#172538; --proj-line:#2C4468;
    --shadow:none;
  }
}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font-size:15px;line-height:1.62;
  letter-spacing:-.01em;-webkit-font-smoothing:antialiased;
  font-family:system-ui,-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard",
    "Noto Sans KR","Malgun Gothic","맑은 고딕",sans-serif}
a{color:var(--accent);text-underline-offset:3px}
h1,h2,h3,h4{margin:0;letter-spacing:-.03em}
p{margin:0 0 10px}
ul{margin:0;padding-left:19px}
li{margin:0 0 6px}
.num{font-variant-numeric:tabular-nums}
.wrap{max-width:1040px;margin:0 auto;padding:0 18px 64px}

/* 히어로 */
.hero{background:var(--hero);color:var(--hero-ink);padding:34px 0 30px;border-bottom:5px solid var(--accent)}
.hero .in{max-width:1040px;margin:0 auto;padding:0 18px}
.hero-eyebrow{font-size:11.5px;letter-spacing:.17em;color:#A1968A;margin-bottom:10px;font-weight:700}
.hero-title{font-size:clamp(26px,6.4vw,44px);font-weight:800;line-height:1.1}
.hero-sub{font-size:13.5px;color:#B7AC9E;margin-top:12px}
.hero-chips{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px}
.hero-chips .chip{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.16);
  border-radius:999px;padding:5px 12px;font-size:12.5px;color:#E7DED2;max-width:100%}
.hero-chips .chip b{color:#FF9E78;font-weight:700;margin-right:6px;font-size:10.5px;letter-spacing:.08em}
.back{display:inline-block;font-size:12.5px;color:#B7AC9E;text-decoration:none;margin-bottom:14px}
.back:hover{color:var(--hero-ink)}

/* 고정 안내 배너 */
.banner{position:sticky;top:0;z-index:20;background:var(--warn-soft);color:var(--warn);
  border-bottom:1px solid var(--warn-line);padding:9px 18px;font-size:12.5px;font-weight:700;
  text-align:center;line-height:1.45}
.banner span{font-weight:400;display:block;font-size:11.5px;opacity:.85;margin-top:2px}
.banner.proj{background:var(--proj-soft);color:var(--proj);border-bottom-color:var(--proj-line)}

/* 섹션 */
.sec{margin:32px 0 0}
.seclabel{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:14px;
  padding-bottom:8px;border-bottom:2px solid currentColor}
.sectag{font-size:10.5px;font-weight:800;letter-spacing:.11em;padding:3px 9px;border-radius:999px}
.sectitle{font-size:19px;font-weight:800;color:var(--ink)}
.secsub{margin-left:auto;font-size:12px;color:var(--muted);font-weight:400}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:17px;
  box-shadow:var(--shadow)}
.card+.card{margin-top:13px}
.cardtitle{font-size:11px;font-weight:800;color:var(--muted);letter-spacing:.09em;margin-bottom:11px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:13px;align-items:start}
.note{font-size:12.5px;color:var(--muted);margin-top:12px;padding-top:11px;
  border-top:1px dashed var(--line)}
.empty{color:var(--muted);font-size:13px;margin:0}

/* 업무 성향 — 관측 근거 있음 */
.sec-work{color:var(--work)}
.sec-work .card{border-color:var(--work-soft);border-left:4px solid var(--work)}
.sec-work .sectag{background:var(--work-soft);color:var(--work)}

/* 재미 코너 — 추측. 배경·테두리·줄무늬로 업무 성향과 확실히 떼어 놓는다 */
.sec-fun{color:var(--fun);margin-top:40px}
.sec-fun .sectag{background:var(--fun-soft);color:var(--fun)}
.funwrap{background:var(--fun-bg);background-image:repeating-linear-gradient(135deg,
  var(--fun-stripe) 0 9px,transparent 9px 18px);
  border:2px dashed var(--fun);border-radius:18px;padding:16px}
.funwrap .card{background:var(--card);border-color:var(--fun-soft)}
.funhead{font-size:12.5px;color:var(--ink2);margin:0 0 14px;line-height:1.55}
.funhead b{color:var(--fun)}

/* 근거 강도 배지 */
.st{display:inline-block;font-size:10.5px;font-weight:800;padding:3px 9px;border-radius:999px;
  letter-spacing:.02em;white-space:nowrap}
.st-obs{background:var(--work-soft);color:var(--work)}
.st-weak{background:var(--line2);color:var(--muted);border:1px solid var(--line)}
.st-none{background:var(--warn-soft);color:var(--warn)}

/* 5축 막대 (JS·라이브러리 없이 CSS 만) */
.axes{display:flex;flex-direction:column;gap:15px}
.axis-head{display:flex;align-items:baseline;gap:8px;font-size:13px;margin-bottom:5px}
.axis-head b{font-weight:800;font-size:13.5px}
.axis-score{margin-left:auto;font-variant-numeric:tabular-nums;font-weight:800;color:var(--work)}
.axis-score i{font-style:normal;font-weight:400;color:var(--muted);font-size:11.5px}
.axis-track{position:relative;height:13px;border-radius:7px;background:var(--line2);overflow:hidden}
.axis-fill{display:block;height:100%;border-radius:7px;background:var(--work);min-width:5px}
.axis-track::after{content:"";position:absolute;inset:0;pointer-events:none;
  background:repeating-linear-gradient(90deg,transparent 0 calc(20% - 1.5px),
    var(--card) calc(20% - 1.5px) 20%)}
.axis-pole{display:flex;justify-content:space-between;gap:10px;font-size:11px;color:var(--muted);
  margin-top:5px}
.axis-pole span:last-child{text-align:right}

/* 대화 가이드 — 가장 눈에 띄는 카드 */
.talk{background:var(--card);border:2px solid var(--talk);border-radius:16px;padding:19px;
  box-shadow:0 3px 0 var(--talk-soft);margin-bottom:14px}
.talk-h{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:4px}
.talk-h h3{font-size:clamp(17px,3.6vw,21px);font-weight:800;color:var(--talk)}
.talk-lead{font-size:12.5px;color:var(--muted);margin:0 0 15px}
.talk-grid{display:grid;grid-template-columns:1fr 1fr;gap:13px}
.talk-box{background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:13px 14px}
.talk-box.good{border-left:4px solid var(--talk)}
.talk-box.avoid{border-left:4px solid var(--warn-line)}
.talk-k{font-size:11px;font-weight:800;letter-spacing:.08em;margin-bottom:8px}
.talk-box.good .talk-k{color:var(--talk)}
.talk-box.avoid .talk-k{color:var(--warn)}
.talk-box ul{padding-left:17px;font-size:13.5px}
.talk-meta{display:grid;grid-template-columns:1fr 1fr;gap:13px;margin-top:13px}
.talk-time{background:var(--talk-soft);border-radius:12px;padding:13px 14px}
.talk-time .v{font-size:clamp(18px,4vw,24px);font-weight:800;color:var(--talk);
  font-variant-numeric:tabular-nums;line-height:1.2}
.talk-ex{background:var(--soft);border:1px solid var(--line);border-radius:12px;padding:13px 14px}
.talk-ex .q{font-size:13.5px;color:var(--ink);line-height:1.6;margin:0}
.talk-ex .q::before{content:"“"}
.talk-ex .q::after{content:"”"}

/* 재미 코너 3종 */
.fun3{display:grid;grid-template-columns:repeat(2,1fr);gap:13px}
.funcard{background:var(--card);border:1px solid var(--fun-soft);border-radius:14px;padding:16px}
.funk{font-size:11px;color:var(--muted);letter-spacing:.09em;font-weight:800}
.funval{font-size:clamp(24px,5vw,30px);font-weight:800;margin:4px 0 9px;line-height:1.15;
  color:var(--fun)}
.funbasis{font-size:12.5px;color:var(--ink2);margin-top:9px;line-height:1.55}

/* 멤버 카드 그리드 */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,238px),1fr));gap:14px}
.mcard{display:block;background:var(--card);border:1px solid var(--line);border-radius:16px;
  padding:17px;text-decoration:none;color:inherit;box-shadow:var(--shadow)}
.mcard:hover{border-color:var(--accent)}
.mcard.low{border-color:var(--warn-line)}
.mname{font-size:19px;font-weight:800;line-height:1.25}
.mrole{font-size:12px;color:var(--muted);margin-top:3px}
.mnick{font-size:13px;color:var(--accent);margin-top:9px;font-weight:700;line-height:1.45}
.mchips{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.mchip{font-size:11.5px;background:var(--soft);border:1px solid var(--line);border-radius:999px;
  padding:3px 9px;color:var(--ink2)}
.mchip b{font-weight:800;color:var(--fun)}
.mchip.mbti{background:var(--fun-soft);border-color:var(--fun-soft);color:var(--fun);font-weight:800}
.mchip.badge{border-style:dashed;border-color:var(--fun-soft);color:var(--fun)}
.mchip.react{font-size:14px;padding:1px 10px;line-height:1.5}
.lowbadge{display:flex;align-items:center;gap:6px;margin-top:12px;background:var(--warn-soft);
  color:var(--warn);border:1px solid var(--warn-line);border-radius:10px;padding:7px 10px;
  font-size:11.5px;font-weight:800;line-height:1.35}

/* 목록 섹션 라벨 — 멤버는 잉크색, 프로젝트는 파랑 */
.sec-members{color:var(--ink);margin-top:28px}
.sec-members .sectag{background:var(--soft);color:var(--ink2);border:1px solid var(--line)}
.sec-proj{color:var(--proj);margin-top:40px}
.sec-proj .sectag{background:var(--proj-soft);color:var(--proj)}
.sec-proj .card{border-color:var(--proj-soft);border-left:4px solid var(--proj)}

/* 프로젝트 카드 — 동시 진행이 보통 2건이라 한 줄에 하나씩 크게 보여준다 */
.pcards{display:grid;grid-template-columns:1fr;gap:16px}
.pcard{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(220px,1fr);gap:0 28px;
  background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px 24px;
  text-decoration:none;color:inherit;box-shadow:var(--shadow)}
.pcard:hover{border-color:var(--proj)}
.pmain{min-width:0;display:flex;flex-direction:column}
.pside{display:flex;flex-direction:column;justify-content:flex-end;min-width:0;
  border-left:1px solid var(--line);padding-left:24px}
.phead{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.pphase{font-size:12.5px;color:var(--muted)}
.pname{font-size:22px;font-weight:800;line-height:1.3;color:var(--ink);letter-spacing:-.01em}
.pcode{font-size:12px;color:var(--muted);font-weight:700;margin-left:8px;letter-spacing:.06em}
.ptag{font-size:14px;color:var(--proj);font-weight:700;margin-top:6px;line-height:1.5}
.psum{font-size:13.5px;color:var(--ink2);margin-top:8px;line-height:1.6;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.pside .prog{margin-top:0}
.pnext{font-size:13px;color:var(--proj);margin-top:14px;font-weight:700;line-height:1.5}
.pnext i,.ptarget i{font-style:normal;font-weight:800;font-size:10.5px;letter-spacing:.08em;
  color:var(--muted);margin-right:6px}
.ptarget{font-size:12.5px;color:var(--ink2);margin-top:8px;line-height:1.5}
.pcard .mchips{margin-top:auto;padding-top:14px}
.mchip.proj{background:var(--proj-soft);border-color:var(--proj-soft);color:var(--proj);font-weight:700}

/* 과제 상태 배지 */
.ps{display:inline-block;font-size:10.5px;font-weight:800;padding:3px 9px;border-radius:999px;
  letter-spacing:.04em;white-space:nowrap}
.ps-doing{background:var(--proj-soft);color:var(--proj)}
.ps-todo{background:var(--line2);color:var(--muted);border:1px solid var(--line)}
.ps-hold{background:var(--warn-soft);color:var(--warn)}
.ps-done{background:var(--talk-soft);color:var(--talk)}

/* 진행률 — 마일스톤 완료 수 / 전체 수. 지어낸 % 가 아니다 */
.prog{position:relative;height:9px;border-radius:5px;background:var(--line2);overflow:hidden;margin-top:12px}
.prog span{display:block;height:100%;border-radius:5px;background:var(--proj);min-width:3px}
.prog.zero span{display:none}
.progk{display:flex;justify-content:space-between;gap:10px;font-size:11.5px;color:var(--muted);
  margin-top:5px;font-variant-numeric:tabular-nums}
.progk b{color:var(--proj);font-weight:800}

/* 마일스톤 타임라인 */
.ms{list-style:none;padding:0;margin:14px 0 0;position:relative}
.ms::before{content:"";position:absolute;left:7px;top:6px;bottom:6px;width:2px;background:var(--line)}
.ms li{position:relative;padding:0 0 12px 26px;margin:0;font-size:13.5px;line-height:1.45}
.ms li:last-child{padding-bottom:0}
.ms li::before{content:"";position:absolute;left:1px;top:4px;width:14px;height:14px;border-radius:50%;
  background:var(--card);border:2px solid var(--line)}
.ms li.done::before{background:var(--proj);border-color:var(--proj)}
.ms li.done::after{content:"";position:absolute;left:5px;top:7px;width:4px;height:7px;
  border:solid var(--card);border-width:0 2px 2px 0;transform:rotate(45deg)}
.ms li.doing::before{border-color:var(--proj);border-width:3px;background:var(--card)}
.ms li.doing{font-weight:800;color:var(--proj)}
.ms li.todo{color:var(--muted)}
.ms .d{display:inline-block;min-width:88px;font-variant-numeric:tabular-nums;color:var(--muted);
  font-size:12px;font-weight:400;margin-right:6px}
.ms .k{font-size:10.5px;font-weight:800;letter-spacing:.06em;margin-left:8px;color:var(--muted)}

/* 영역별 현황 */
.ws{display:inline-block;font-size:10.5px;font-weight:800;padding:2px 8px;border-radius:999px;
  white-space:nowrap;background:var(--line2);color:var(--ink2);border:1px solid var(--line)}
.ws-done{background:var(--talk-soft);color:var(--talk);border-color:var(--talk-soft)}
.ws-doing{background:var(--proj-soft);color:var(--proj);border-color:var(--proj-soft)}
.ws-todo{background:var(--line2);color:var(--muted)}
.ws-hold{background:var(--warn-soft);color:var(--warn);border-color:var(--warn-line)}
td.area{font-weight:800;white-space:nowrap;color:var(--ink)}

/* 담당 칩 — 프로필이 있으면 링크, 없으면 글자만 */
.mems{display:flex;flex-wrap:wrap;gap:8px}
.mem{display:inline-flex;align-items:baseline;gap:7px;background:var(--soft);border:1px solid var(--line);
  border-radius:12px;padding:8px 12px;text-decoration:none;color:var(--ink);font-size:13.5px;font-weight:800}
a.mem:hover{border-color:var(--proj);color:var(--proj)}
.mem i{font-style:normal;font-weight:400;font-size:12px;color:var(--muted)}
.mem.noprofile{opacity:.75}

/* 최근 변화 */
.recent td.d{white-space:nowrap;font-variant-numeric:tabular-nums;color:var(--muted);width:1%}

/* signals 표 */
details.sig{margin-top:32px;background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:0 17px}
details.sig>summary{cursor:pointer;padding:14px 0;font-size:13.5px;font-weight:800;color:var(--ink2);
  list-style:none}
details.sig>summary::-webkit-details-marker{display:none}
details.sig>summary::before{content:"▸ ";color:var(--muted)}
details.sig[open]>summary::before{content:"▾ "}
details.sig>div{padding-bottom:17px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line2);vertical-align:top}
th{color:var(--muted);font-weight:700;font-size:11.5px;letter-spacing:.05em;white-space:nowrap}
td.n{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
/* 평균 길이 ↔ 평균 대화 길이 대비 */
.gap{display:inline-block;margin-left:8px;font-size:10.5px;font-weight:800;padding:2px 8px;
  border-radius:999px;background:var(--accent-soft);color:var(--accent);white-space:nowrap;
  letter-spacing:0}

/* 표본 부족 경고 · 건너뛴 파일 */
.warnbox{background:var(--warn-soft);border:1px solid var(--warn-line);border-radius:14px;
  padding:16px;color:var(--warn);font-size:13px}
.warnbox h3{font-size:13.5px;margin-bottom:9px}
.warnbox p{margin:0}
.warnbox li{color:var(--warn)}
.lowwarn{margin-top:26px;border-left:5px solid var(--warn)}
.skips{margin-top:36px}

footer{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);font-size:12px;
  color:var(--muted);line-height:1.65}

@media (max-width:720px){
  .grid2,.talk-grid,.talk-meta{grid-template-columns:1fr}
  .fun3{grid-template-columns:1fr}
  .pcard{grid-template-columns:1fr;padding:18px}
  .pside{border-left:0;padding-left:0;border-top:1px solid var(--line);padding-top:14px;margin-top:14px}
  .pcard .mchips{padding-top:12px}
  .pname{font-size:19px}
}
@media (max-width:430px){
  body{font-size:14.5px}
  .wrap{padding:0 14px 48px}
  .hero .in{padding:0 14px}
  .banner{padding:9px 14px;font-size:11.5px}
  .funwrap{padding:12px}
  .card,.talk,.mcard,.pcard{padding:14px}
  .secsub{margin-left:0;width:100%}
  .ms .d{display:block;min-width:0;margin:0}
}
"""


# ══════════════════════════════════════════════════════════════════════════════
# HTML 조각
# ══════════════════════════════════════════════════════════════════════════════
def html_doc(title: str, body: str) -> str:
    return ("<!doctype html>\n<html lang=\"ko\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<meta name=\"robots\" content=\"noindex,nofollow\">\n"
            "<meta name=\"color-scheme\" content=\"light dark\">\n"
            f"<title>{esc(title)}</title>\n<style>{CSS}</style>\n"
            f"</head>\n<body>\n{body}\n</body>\n</html>\n")


def banner_html() -> str:
    return (f'<div class="banner">{esc(BANNER)}'
            '<span>업무 성향만 관측된 행동에 근거한다. 인사 평가나 줄세우기에 쓰지 않는다.</span></div>')


def sec(cls: str, tag: str, title: str, body: str, sub: str = "") -> str:
    subhtml = f'<span class="secsub">{esc(sub)}</span>' if sub else ""
    return (f'<section class="sec {cls}"><div class="seclabel">'
            f'<span class="sectag">{esc(tag)}</span>'
            f'<h2 class="sectitle">{esc(title)}</h2>{subhtml}</div>{body}</section>')


def card(title: str, body: str) -> str:
    head = f'<div class="cardtitle">{esc(title)}</div>' if title else ""
    return f'<div class="card">{head}{body}</div>'


def ul(items, empty="적어 두지 않았습니다") -> str:
    items = str_list(items)
    if not items:
        return f'<p class="empty">{esc(empty)}</p>'
    return "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in items) + "</ul>"


def strength_badge(s: str) -> str:
    """근거 강도 배지. '없음(무작위)' 은 경고색으로 눈에 띄게 둔다."""
    t = text(s)
    flat = re.sub(r"\s+", "", t)
    if "없음" in flat or "무작위" in flat:
        cls = "st-none"
    elif t.startswith("약"):
        cls = "st-weak"
    else:
        cls = "st-obs"
    return f'<span class="st {cls}">근거 강도 · {esc(t or "미기재")}</span>'


def axes_html(axes) -> str:
    """5축을 CSS 막대로. JS·라이브러리를 쓰지 않는다."""
    if not isinstance(axes, dict) or not axes:
        return '<p class="empty">축 데이터가 없습니다</p>'
    rows = []
    for key in AXIS_ORDER:
        if key not in axes:
            continue
        v = num(axes.get(key), 0)
        v = max(1.0, min(5.0, float(v)))
        lo, hi = AXIS_POLE[key]
        pct = (v - 1) / 4 * 100
        rows.append(
            f'<div class="axis"><div class="axis-head"><b>{esc(AXIS_KO[key])}</b>'
            f'<span class="axis-score num">{v:g}<i>/5</i></span></div>'
            f'<div class="axis-track"><span class="axis-fill" style="width:{max(pct, 4):.1f}%"></span></div>'
            f'<div class="axis-pole"><span>1 · {esc(lo)}</span><span>{esc(hi)} · 5</span></div></div>')
    if not rows:
        return '<p class="empty">축 데이터가 없습니다</p>'
    return f'<div class="axes">{"".join(rows)}</div>'


def talk_html(talk) -> str:
    """대화 가이드. 개인 페이지에서 가장 눈에 띄는 카드로 둔다."""
    if not isinstance(talk, dict) or not talk:
        return ""
    good = ul(talk.get("good"), "아직 정리된 요청 방식이 없습니다")
    avoid = ul(talk.get("avoid"), "특별히 피할 방식은 적혀 있지 않습니다")
    best = text(talk.get("best_time"))
    example = text(talk.get("example"))
    meta = ""
    if best or example:
        blocks = []
        if best:
            blocks.append('<div class="talk-time"><div class="talk-k">말 걸기 좋은 시간</div>'
                          f'<div class="v num">{esc(best)}</div></div>')
        if example:
            blocks.append('<div class="talk-ex"><div class="talk-k">이렇게 보내면 된다</div>'
                          f'<p class="q">{esc(example)}</p></div>')
        meta = f'<div class="talk-meta">{"".join(blocks)}</div>'
    return (f'<div class="talk"><div class="talk-h"><h3>이렇게 말 걸면 통한다</h3>'
            f'{strength_badge("관측된 응답 패턴 기반 · 참고용")}</div>'
            '<p class="talk-lead">집계된 말투·활동 시간대에서 뽑았다. 성격 판정이 아니라 요청 방식 제안이다.</p>'
            f'<div class="talk-grid">'
            f'<div class="talk-box good"><div class="talk-k">통하는 방식</div>{good}</div>'
            f'<div class="talk-box avoid"><div class="talk-k">피하면 좋은 방식</div>{avoid}</div>'
            f'</div>{meta}</div>')


def signals_html(sig) -> str:
    """signals 는 집계 수치만 — 원문 인용은 스키마 단계에서 이미 막았다."""
    if not isinstance(sig, dict) or not sig:
        return ""
    # 평균 길이에는 공유한 문서·인용문이 섞여 있다. 대화만 뽑은 값과 차이가 크면
    # "문서는 길게 공유하되 말은 짧게 한다" 가 드러나므로 배지로 짚어 준다.
    badges = {}
    has_chat = sig.get("avg_chat_chars") is not None
    a_all, a_chat = num(sig.get("avg_chars"), 0), num(sig.get("avg_chat_chars"), 0)
    if a_all > 0 and a_chat > 0 and a_all >= a_chat * CHAT_GAP_RATIO:
        badges["avg_chat_chars"] = (f'<span class="gap">문서 빼면 {a_all / a_chat:.1f}배 짧다</span>')

    rows = []
    for key, ko, unit in SIGNAL_ROWS:
        if key not in sig or sig.get(key) is None:
            continue
        v = sig.get(key)
        extra = badges.get(key, "")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            cell = f'<td class="n">{esc(fmt_int(v))}{esc(unit)}{extra}</td>'
        else:
            cell = f"<td>{esc(v)}{extra}</td>"
        rows.append(f"<tr><th>{esc(ko)}</th>{cell}</tr>")

    markers = sig.get("markers")
    if isinstance(markers, dict) and markers:
        pairs = sorted(markers.items(), key=lambda kv: num(kv[1]), reverse=True)
        cells = " · ".join(f"{esc(k)} {esc(fmt_int(v))}" for k, v in pairs)
        rows.append(f'<tr><th>말투 마커</th><td>{cells}</td></tr>')

    endings = str_list(sig.get("endings_top"), 8)
    if endings:
        rows.append(f'<tr><th>자주 쓰는 어미</th><td>{esc(" · ".join(endings))}</td></tr>')

    if not rows:
        return ""
    # 두 평균이 왜 다른지는 값이 실제로 있을 때만 설명한다.
    chat_note = ('<b>평균 길이</b>에는 공유한 문서·인용문이 포함된다. '
                 '<b>평균 대화 길이</b>는 그것을 뺀 값이다. ' if has_chat else "")
    return ('<details class="sig"><summary>관측 신호 (집계 수치)</summary><div>'
            f'<div class="tscroll"><table>{"".join(rows)}</table></div>'
            f'<div class="note">{chat_note}원문 인용은 담지 않는다. '
            '건수·비율 같은 집계값만 남긴다 (docs/PRIVACY.md).</div></div></details>')


def footer_html(part: str, built: str, sources=None) -> str:
    src = ""
    items = str_list(sources)
    if items:
        src = f'<p>출처 — {esc(" · ".join(items))}</p>'
    return (f'<footer><p>{esc(part)} · 빌드 {esc(built)}</p>{src}'
            '<p>표본은 슬랙·텔레그램 2~3주치가 전부다. 발화가 1~2건인 사람의 프로필을 '
            '데이터가 많은 사람과 같은 무게로 비교하지 않는다.</p>'
            '<p>공개 범위와 금지 패턴은 docs/PRIVACY.md · 스키마는 docs/PROFILE_SCHEMA.md 를 따른다. '
            '재미 코너에서 빠지고 싶으면 본인 JSON 의 <code>fun</code> 을 <code>null</code> 로 두면 된다.</p>'
            '</footer>')


# ══════════════════════════════════════════════════════════════════════════════
# 개인 상세 페이지
# ══════════════════════════════════════════════════════════════════════════════
def render_person(data: dict, built: str) -> str:
    name = text(data.get("name"))
    part = text(data.get("part")) or DEFAULT_PART
    role = text(data.get("role"))
    generated = text(data.get("generated"))
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    fun = data.get("fun") if isinstance(data.get("fun"), dict) else None
    sig = data.get("signals") if isinstance(data.get("signals"), dict) else {}

    nick = text(g(fun, "nickname")) if fun else ""
    conf = text(sig.get("confidence"))
    utter = sig.get("utterances")

    # ── 히어로 ──
    chips = []
    if role:
        chips.append(f'<span class="chip"><b>직무</b>{esc(role)}</span>')
    if generated:
        chips.append(f'<span class="chip"><b>데이터 기준</b>{esc(generated)}</span>')
    if conf:
        chips.append(f'<span class="chip"><b>신뢰도</b>{esc(conf)}'
                     + (f' · 발화 {esc(fmt_int(utter))}건' if utter is not None else "")
                     + '</span>')
    hero = ('<header class="hero"><div class="in">'
            '<a class="back" href="../index.html">← 멤버 목록</a>'
            f'<div class="hero-eyebrow">{esc(part)}</div>'
            f'<h1 class="hero-title">{esc(name)}</h1>'
            + (f'<div class="hero-sub">{esc(nick)}</div>' if nick else "")
            + (f'<div class="hero-chips">{"".join(chips)}</div>' if chips else "")
            + '</div></header>')

    # ── 표본이 작으면 숨기지 않고 먼저 말한다 ──
    lowwarn = ""
    if conf == "낮음":
        n = fmt_int(utter) if utter is not None else "?"
        lowwarn = (f'<div class="warnbox lowwarn"><h3>⚠ 표본 {esc(n)}건 — 참고만</h3>'
                   '<p>발화가 적어 아래 내용의 근거가 약하다. '
                   '데이터가 많은 사람과 같은 무게로 읽지 않는다.</p></div>')

    # ── 01 업무 성향 (관측 근거 있음) ──
    work_style = text(g(profile, "work_style"))
    # 5축과 말투 마커는 출처가 다르다. 같은 페이지에 있어서 마커에서 뽑은 것으로
    # 오해하기 쉬운데, 마커가 0이어도 점수가 남는 경우가 실제로 있다.
    axes_note = ""
    if isinstance(profile.get("axes"), dict) and profile.get("axes"):
        axes_note = ('<div class="note">점수는 아래 <b>관측 신호</b>의 말투 마커에서 뽑은 것이 아니다. '
                     '무엇을 먼저 정리했는지, 어떤 산출물을 냈는지 같은 <b>행동</b>을 보고 매겼다. '
                     '그래서 마커 수치가 낮거나 0이어도 점수는 그대로 남아 있을 수 있다.</div>')
    work_body = (card("업무 성향 5축", axes_html(profile.get("axes")) + axes_note)
                 + '<div class="grid2" style="margin-top:13px">'
                 + card("일하는 방식", (f'<p style="margin:0">{esc(work_style)}</p>' if work_style
                                   else '<p class="empty">아직 적혀 있지 않습니다</p>'))
                 + card("강점", ul(profile.get("strengths")))
                 + '</div>')
    # 부제는 '쓸 수 있는 수준' 만 말한다. 출처 설명은 위 axes_note 가 맡는다 (중복 방지).
    s_work = sec("sec-work", "관측 근거 있음", "업무 성향", work_body,
                 "실제 업무 참고에 쓸 수 있는 수준")

    # ── 02 재미 코너 (추측) ── 업무 성향과 섞이지 않게 배경·테두리로 떼어 놓는다
    s_fun = ""
    if fun:
        fcards = []
        for key, ko in FUN_KEYS:
            blk = fun.get(key) if isinstance(fun.get(key), dict) else {}
            fcards.append(
                f'<div class="funcard"><div class="funk">{esc(ko)}</div>'
                f'<div class="funval">{esc(text(blk.get("value")) or "-")}</div>'
                f'{strength_badge(blk.get("strength"))}'
                f'<div class="funbasis">{esc(text(blk.get("basis")) or "근거 메모 없음")}</div></div>')
        top = g(data, "signals.reactions_top") or []
        if isinstance(top, list) and top and isinstance(top[0], (list, tuple)) and top[0]:
            emoji = esc(str(top[0][0]))
            others = " ".join(esc(str(e)) for e, _ in top[1:3] if e)
            fcards.append(
                f'<div class="funcard"><div class="funk">받은 반응</div>'
                f'<div class="funval" style="font-size:34px">{emoji}</div>'
                f'{strength_badge("관측")}'
                f'<div class="funbasis">이 사람 글에 가장 많이 달린 이모지다.'
                + (f' 다음은 {others}.' if others else "")
                + ' 개수는 발화량에 비례해서 적지 않는다.</div></div>')

        fun_body = ('<div class="funwrap">'
                    '<p class="funhead">MBTI·나이대는 <b>추측</b>이다. 위 업무 성향과 같은 근거로 쓰이지 않았다. '
                    '말투 뱃지와 받은 반응은 <b>집계한 관측값</b>이다. '
                    '항목마다 <b>근거 강도</b>를 함께 본다.</p>'
                    + talk_html(fun.get("how_to_talk"))
                    + f'<div class="fun3">{"".join(fcards)}</div></div>')
        s_fun = sec("sec-fun", "추측 · 재미용", "재미 코너", fun_body, "근거 강도를 항목마다 표시한다")
    else:
        s_fun = sec("sec-fun", "비공개", "재미 코너",
                    card("", '<p class="empty" style="margin:0">본인 요청으로 재미 코너를 싣지 않는다. '
                             '업무 성향만 표시한다.</p>'),
                    "")

    body = (hero + banner_html() + '<main class="wrap">' + lowwarn + s_work + s_fun
            + signals_html(sig) + footer_html(part, built, data.get("sources")) + '</main>')
    return html_doc(f"{name} · {part} 프로필", body)


# ══════════════════════════════════════════════════════════════════════════════
# 목록 페이지
# ══════════════════════════════════════════════════════════════════════════════
def badge_short(badge) -> str:
    """말투 뱃지를 칩 한 칸에 들어갈 길이로. '단정 3.5배' / '물결 안 씀'."""
    if not isinstance(badge, dict):
        return ""
    marker = text(badge.get("marker"))
    if not marker:
        return ""
    if badge.get("kind") == "안씀":
        return f"{marker} 안 씀"
    ratio = badge.get("ratio")
    return f"{marker} {ratio}배" if ratio else marker


def member_card(entry: dict) -> str:
    data = entry["data"]
    name = text(data.get("name"))
    role = text(data.get("role"))
    fun = data.get("fun") if isinstance(data.get("fun"), dict) else None
    sig = data.get("signals") if isinstance(data.get("signals"), dict) else {}
    conf = text(sig.get("confidence"))
    low = conf == "낮음"

    nick = text(g(fun, "nickname")) if fun else ""
    mbti = text(g(fun, "mbti.value")) if fun else ""
    age = text(g(fun, "age_band.value")) if fun else ""

    chips = []
    if mbti:
        chips.append(f'<span class="mchip mbti">{esc(mbti)}</span>')
    if age:
        chips.append(f'<span class="mchip">{esc(age)}</span>')

    # 말투 뱃지는 카드에 짧게만 — 긴 이름표는 별명과 겹쳐 보인다.
    # 자세한 이름표와 근거는 개인 페이지에서 본다.
    badge_chip = badge_short(sig.get("badge"))
    if badge_chip:
        label = text(g(fun, "speech_badge.value")) if fun else ""
        chips.append(f'<span class="mchip badge" title="{esc(label)}">{esc(badge_chip)}</span>')

    top = sig.get("reactions_top") or []
    if isinstance(top, list) and top and isinstance(top[0], (list, tuple)) and top[0]:
        chips.append(f'<span class="mchip react" title="가장 많이 받은 반응">'
                     f'{esc(str(top[0][0]))}</span>')

    if not fun:
        chips.append('<span class="mchip">재미 코너 비공개</span>')

    badge = ""
    if low:
        n = fmt_int(sig.get("utterances")) if sig.get("utterances") is not None else "?"
        badge = f'<div class="lowbadge">⚠ 표본 {esc(n)}건 — 참고만</div>'

    return (f'<a class="mcard{" low" if low else ""}" href="{esc(entry["href"])}">'
            f'<div class="mname">{esc(name)}</div>'
            + (f'<div class="mrole">{esc(role)}</div>' if role else "")
            + (f'<div class="mnick">{esc(nick)}</div>' if nick else "")
            + (f'<div class="mchips">{"".join(chips)}</div>' if chips else "")
            + badge + '</a>')


# ══════════════════════════════════════════════════════════════════════════════
# 프로젝트 — 카드와 상세 페이지 (docs/PROJECT_SCHEMA.md)
# ══════════════════════════════════════════════════════════════════════════════
def status_badge(status: str) -> str:
    cls = PROJECT_STATUS_CLASS.get(text(status), "ps-todo")
    return f'<span class="ps {cls}">{esc(status or "상태 미기재")}</span>'


def work_state_chip(state: str) -> str:
    """영역 상태는 자유 텍스트다. 낱말로 색만 고르고 글자는 그대로 둔다."""
    s = text(state)
    if not s:
        return ""
    cls = ""
    for word, c in WORK_STATE_HINTS:
        if word in s:
            cls = c
            break
    return f'<span class="ws {cls}">{esc(s)}</span>'


def progress_html(milestones, compact=False) -> str:
    """마일스톤 완료 수로 막대를 그린다. 임의의 % 를 받지 않는다 — 근거 없는 수치를 싣지 않기 위해서다."""
    done, total, nxt = project_progress(milestones)
    if total == 0:
        return ""
    pct = done / total * 100
    bar = (f'<div class="prog{" zero" if done == 0 else ""}">'
           f'<span style="width:{pct:.1f}%"></span></div>')
    left = f'<b>마일스톤 {done}/{total}</b> 완료'
    right = f'다음 · {esc(nxt)}' if (nxt and not compact) else ""
    return bar + f'<div class="progk"><span>{left}</span><span>{right}</span></div>'


def milestones_html(milestones) -> str:
    items = [m for m in (milestones or []) if isinstance(m, dict) and text(m.get("label"))]
    if not items:
        return '<p class="empty">마일스톤이 아직 없습니다</p>'
    lis = []
    for m in items:
        st = text(m.get("state"))
        st = st if st in MILESTONE_STATES else "todo"
        date = text(m.get("date"))
        lis.append(f'<li class="{st}"><span class="d">{esc(date)}</span>{esc(m.get("label"))}'
                   f'<span class="k">{esc(MILESTONE_KO[st])}</span></li>')
    return f'<ul class="ms">{"".join(lis)}</ul>'


def workstreams_html(rows) -> str:
    rows = [r for r in (rows or []) if isinstance(r, dict) and text(r.get("area"))]
    if not rows:
        return '<p class="empty">영역별 현황이 아직 없습니다</p>'
    trs = "".join(
        f'<tr><td class="area">{esc(r.get("area"))}</td>'
        f'<td>{work_state_chip(r.get("state"))}</td>'
        f'<td>{esc(text(r.get("note")))}</td></tr>' for r in rows)
    return ('<div class="tscroll"><table><thead><tr><th>영역</th><th>상태</th><th>메모</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></div>')


def members_html(members, member_hrefs: dict, prefix: str) -> str:
    """담당자 칩. 프로필 카드가 있는 사람만 링크를 건다. 없는 사람은 이름만 남긴다."""
    items = [m for m in (members or []) if isinstance(m, dict) and text(m.get("name"))]
    if not items:
        return '<p class="empty">담당이 아직 적혀 있지 않습니다</p>'
    chips = []
    for m in items:
        name, role = text(m.get("name")), text(m.get("role"))
        inner = esc(name) + (f'<i>{esc(role)}</i>' if role else "")
        href = member_hrefs.get(name)
        if href:
            chips.append(f'<a class="mem" href="{esc(prefix + href)}">{inner}</a>')
        else:
            chips.append(f'<span class="mem noprofile" title="프로필 카드 없음">{inner}</span>')
    return f'<div class="mems">{"".join(chips)}</div>'


def recent_html(rows) -> str:
    rows = [r for r in (rows or []) if isinstance(r, dict) and text(r.get("note"))]
    if not rows:
        return '<p class="empty">최근 변화가 아직 없습니다</p>'
    trs = "".join(f'<tr><td class="d">{esc(text(r.get("date")))}</td><td>{esc(r.get("note"))}</td></tr>'
                  for r in rows)
    return f'<div class="tscroll"><table class="recent"><tbody>{trs}</tbody></table></div>'


def project_banner_html() -> str:
    return (f'<div class="banner proj">{esc(PROJECT_BANNER)}'
            '<span>상세 근거·검토 항목은 위키 본문에 있고 이 사이트에는 싣지 않는다.</span></div>')


def render_project(data: dict, built: str, member_hrefs: dict) -> str:
    name = text(data.get("name"))
    title = text(data.get("title")) or name
    part = text(data.get("part")) or DEFAULT_PART
    status = text(data.get("status"))
    phase = text(data.get("phase"))
    target = text(data.get("target"))
    codename = text(data.get("codename"))
    generated = text(data.get("generated"))
    summary = text(data.get("summary"))
    tagline = text(data.get("tagline"))
    members = data.get("members") or []

    chips = [f'<span class="chip"><b>상태</b>{esc(status)}</span>']
    if phase:
        chips.append(f'<span class="chip"><b>단계</b>{esc(phase)}</span>')
    if target:
        chips.append(f'<span class="chip"><b>목표</b>{esc(target)}</span>')
    if codename:
        chips.append(f'<span class="chip"><b>코드명</b>{esc(codename)}</span>')
    if members:
        chips.append(f'<span class="chip"><b>담당</b>{len(members)}명</span>')
    if generated:
        chips.append(f'<span class="chip"><b>데이터 기준</b>{esc(generated)}</span>')

    hero = ('<header class="hero"><div class="in">'
            '<a class="back" href="../index.html#projects">← 목록</a>'
            f'<div class="hero-eyebrow">프로젝트 · {esc(part)}</div>'
            f'<h1 class="hero-title">{esc(title)}</h1>'
            + (f'<div class="hero-sub">{esc(tagline or summary)}</div>' if (tagline or summary) else "")
            + f'<div class="hero-chips">{"".join(chips)}</div>'
            '</div></header>')

    intro = ""
    if tagline and summary:
        intro = card("한 줄 정의", f'<p style="margin:0">{esc(summary)}</p>')

    # 01 진행 상황 — 진행률은 마일스톤 완료 수. 사람이 % 를 적는 칸은 없다.
    prog_body = card("진행률", progress_html(data.get("milestones")) or
                     '<p class="empty">마일스톤이 없어 진행률을 계산하지 않는다</p>')
    ms_body = card("마일스톤", milestones_html(data.get("milestones")))
    s_prog = sec("sec-proj", "위키 요약", "진행 상황",
                 prog_body + f'<div style="margin-top:13px">{ms_body}</div>',
                 "완료한 마일스톤 수로만 계산한다")

    s_work = sec("sec-proj", "영역별", "지금 어디까지 왔나",
                 card("", workstreams_html(data.get("workstreams"))),
                 "데이터 기준일 시점")

    s_mem = sec("sec-proj", "담당", "누가 하나",
                card("", members_html(members, member_hrefs, "../")),
                "카드가 있는 사람은 프로필로 이어진다")

    s_next = sec("sec-proj", "다음", "다음 단계",
                 card("", ul(data.get("next"), "다음 단계가 아직 적혀 있지 않습니다")))

    s_recent = sec("sec-proj", "이력", "최근 변화",
                   card("", recent_html(data.get("recent"))),
                   "최신이 위")

    body = (hero + project_banner_html() + '<main class="wrap">'
            + (f'<div style="margin-top:28px">{intro}</div>' if intro else "")
            + s_prog + s_work + s_mem + s_next + s_recent
            + footer_html(part, built, data.get("sources")) + '</main>')
    return html_doc(f"{title} · {part} 과제", body)


def project_card(entry: dict) -> str:
    data = entry["data"]
    title = text(data.get("title")) or text(data.get("name"))
    codename = text(data.get("codename"))
    status = text(data.get("status"))
    phase = text(data.get("phase"))
    summary = text(data.get("summary"))
    tagline = text(data.get("tagline"))
    target = text(data.get("target"))
    members = data.get("members") or []
    _, _, nxt = project_progress(data.get("milestones"))

    chips = [f'<span class="mchip proj">{esc(b)}</span>' for b in str_list(data.get("badges"), 4)]
    if members:
        chips.append(f'<span class="mchip">담당 {len(members)}명</span>')

    # 왼쪽: 무엇인가 (상태·이름·한 줄 소개·요약·배지) / 오른쪽: 어디까지 왔나 (진행·다음·목표)
    main = ('<div class="pmain">'
            f'<div class="phead">{status_badge(status)}'
            + (f'<span class="pphase">{esc(phase)}</span>' if phase else "")
            + '</div>'
            f'<div class="pname">{esc(title)}'
            + (f'<span class="pcode">{esc(codename)}</span>' if codename else "")
            + '</div>'
            + (f'<div class="ptag">{esc(tagline)}</div>' if tagline else "")
            + (f'<div class="psum">{esc(summary)}</div>' if summary else "")
            + (f'<div class="mchips">{"".join(chips)}</div>' if chips else "")
            + '</div>')
    side = ('<div class="pside">'
            + progress_html(data.get("milestones"), compact=True)
            + (f'<div class="pnext"><i>다음</i>{esc(nxt)}</div>' if nxt else "")
            + (f'<div class="ptarget"><i>목표</i>{esc(target)}</div>' if target else "")
            + '</div>')
    return f'<a class="pcard" href="{esc(entry["href"])}">{main}{side}</a>'


def render_index(entries, skipped, part: str, built: str, generated: str, projects=()) -> str:
    chips = [f'<span class="chip"><b>멤버</b>{len(entries)}명</span>']
    if projects:
        chips.append(f'<span class="chip"><b>프로젝트</b>{len(projects)}건</span>')
    chips.append(f'<span class="chip"><b>빌드</b>{esc(built)}</span>')
    if generated:
        chips.append(f'<span class="chip"><b>데이터 기준</b>{esc(generated)}</span>')
    low_n = sum(1 for e in entries
                if text(g(e["data"], "signals.confidence")) == "낮음")
    if low_n:
        chips.append(f'<span class="chip"><b>표본 부족</b>{low_n}명</span>')

    hero = ('<header class="hero"><div class="in">'
            '<div class="hero-eyebrow">멤버 프로필 · 프로젝트</div>'
            f'<h1 class="hero-title">{esc(part)}</h1>'
            '<div class="hero-sub">슬랙·텔레그램에서 집계한 말투 신호로 만든 파트원 카드와 '
            '진행 중인 과제 요약. 위키 본문과 원본 대화는 여기에 실리지 않는다.</div>'
            f'<div class="hero-chips">{"".join(chips)}</div>'
            '</div></header>')

    if entries:
        cards = f'<div class="cards">{"".join(member_card(e) for e in entries)}</div>'
    else:
        cards = card("", '<p class="empty" style="margin:0">표시할 프로필이 없습니다</p>')
    s_members = sec("sec-members", "관측 신호", "멤버", cards, "카드를 누르면 상세로")

    s_projects = ""
    if projects:
        pcards = f'<div class="pcards">{"".join(project_card(p) for p in projects)}</div>'
        s_projects = ('<div id="projects"></div>'
                      + sec("sec-proj", "위키 요약", "프로젝트", pcards,
                            "진행률은 마일스톤 완료 수 · 확정 계획이 아니다"))

    skips = ""
    if skipped:
        items = "".join(f'<li><b>{esc(s["file"])}</b> — {esc(s["reason"])}</li>' for s in skipped)
        skips = ('<div class="warnbox skips"><h3>검증에서 건너뛴 파일 '
                 f'{len(skipped)}건</h3><ul>{items}</ul>'
                 '<p style="margin-top:9px">한 건 때문에 전체가 막히지 않도록 그 파일만 빼고 빌드했다. '
                 'docs/PROFILE_SCHEMA.md · docs/PROJECT_SCHEMA.md 를 확인하고 고치면 다음 빌드에 다시 들어온다.</p></div>')

    body = (hero + banner_html() + '<main class="wrap">'
            + s_members + s_projects
            + skips + footer_html(part, built) + '</main>')
    return html_doc(f"{part} 멤버 프로필", body)


# ══════════════════════════════════════════════════════════════════════════════
# 빌드
# ══════════════════════════════════════════════════════════════════════════════
def load_entries(data_dir: Path, validator, sub: str, label: str):
    """디렉터리의 JSON 을 한 건씩 검증해 (통과 목록, 건너뜀 목록) 을 돌려준다.

    프로필과 프로젝트가 같은 규칙으로 돈다 — 어긋난 파일만 빼고, 이유는 stderr 에 남긴다.
    """
    entries, skipped = [], []
    for jp in sorted(data_dir.glob("*.json")):
        shown = f"{label}/{jp.name}"
        data, err = load_json(jp)
        if err or data is None:
            skipped.append({"file": shown, "reason": err or "빈 파일"})
            warn(f"건너뜀 {shown}: {err}")
            continue
        errors = validator(data, jp)
        if errors:
            head = errors[0] + (f" (외 {len(errors) - 1}건)" if len(errors) > 1 else "")
            skipped.append({"file": shown, "reason": head})
            warn(f"건너뜀 {shown}: 검증 실패 {len(errors)}건")
            for e in errors:
                warn(f"  - {e}")
            continue
        name = text(data.get("name"))
        entries.append({"data": data, "name": name, "href": f"{sub}/{quote(name)}.html"})
    return entries, skipped


def build(data_dir: Path, out_dir: Path, projects_dir: "Path | None" = None) -> int:
    if not data_dir.is_dir():
        warn(f"데이터 디렉터리가 없습니다: {data_dir}")
        return 1

    print(f"데이터: {data_dir} · 프로필 {len(list(data_dir.glob('*.json')))}건")
    entries, skipped = load_entries(data_dir, validate, "m", "profiles")

    if not entries:
        warn("")
        warn(f"유효한 프로필이 0건입니다 — 사이트를 만들지 않습니다 "
             f"(건너뜀 {len(skipped)}건)")
        return 1

    # 프로젝트는 있으면 싣고 없으면 섹션만 빠진다. 프로필과 달리 0건이어도 빌드는 성공이다.
    projects = []
    if projects_dir is not None and projects_dir.is_dir():
        print(f"프로젝트: {projects_dir} · {len(list(projects_dir.glob('*.json')))}건")
        projects, p_skipped = load_entries(projects_dir, validate_project, "p", "projects")
        skipped.extend(p_skipped)
        # 진행 중 → 준비 → 보류 → 완료 순. 같은 상태 안에서는 order(작을수록 앞), 그다음 이름.
        projects.sort(key=lambda e: (PROJECT_STATUS_ORDER.get(text(e["data"].get("status")), 9),
                                     num(e["data"].get("order"), 100), e["name"]))
    elif projects_dir is not None:
        print(f"프로젝트 디렉터리가 없어 건너뜁니다: {projects_dir}")

    entries.sort(key=lambda e: e["name"])
    part = text(entries[0]["data"].get("part")) or DEFAULT_PART
    generated = max((text(e["data"].get("generated")) for e in entries), default="")
    built = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    m_dir = out_dir / "m"
    m_dir.mkdir(parents=True, exist_ok=True)
    for e in entries:
        (m_dir / f"{e['name']}.html").write_text(render_person(e["data"], built), encoding="utf-8")

    if projects:
        member_hrefs = {e["name"]: e["href"] for e in entries}
        p_dir = out_dir / "p"
        p_dir.mkdir(parents=True, exist_ok=True)
        for e in projects:
            (p_dir / f"{e['name']}.html").write_text(
                render_project(e["data"], built, member_hrefs), encoding="utf-8")

    index = out_dir / "index.html"
    index.write_text(render_index(entries, skipped, part, built, generated, projects), encoding="utf-8")
    # GitHub Pages 가 Jekyll 로 후처리하지 않게 한다.
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    print(f"만들었습니다 -> {index} (멤버 {len(entries)}명"
          + (f" · 프로젝트 {len(projects)}건" if projects else "")
          + (f" · 건너뜀 {len(skipped)}건" if skipped else "") + ")")
    if skipped:
        warn("")
        warn(f"건너뛴 파일 {len(skipped)}건 — 고치면 다음 빌드에 들어옵니다:")
        for s in skipped:
            warn(f"  · {s['file']}: {s['reason']}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="build_site.py",
        description="멤버 프로필·프로젝트 JSON 으로 정적 사이트를 만든다 (표준 라이브러리만 사용).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="예)\n  python3 scripts/build_site.py --out _site\n")
    p.add_argument("--out", required=True, metavar="디렉터리",
                   help="빌드 결과를 쓸 위치 (예: _site)")
    p.add_argument("--data", metavar="디렉터리",
                   help="프로필 JSON 디렉터리 (기본: data/profiles)")
    p.add_argument("--projects", metavar="디렉터리",
                   help="프로젝트 JSON 디렉터리 (기본: data/projects · 없으면 섹션 생략)")
    args = p.parse_args(argv)

    data_dir = Path(args.data) if args.data else ROOT / "data" / "profiles"
    projects_dir = Path(args.projects) if args.projects else ROOT / "data" / "projects"
    return build(data_dir, Path(args.out), projects_dir)


if __name__ == "__main__":
    sys.exit(main())
