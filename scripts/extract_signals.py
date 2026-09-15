#!/usr/bin/env python3
"""raw/ 의 대화 원문에서 멤버별 말투 신호를 집계한다.

원문 인용은 출력하지 않는다. 집계 수치만 낸다 (docs/PRIVACY.md).
표준 라이브러리만 쓴다. 네트워크 통신 없음. 원본 수정 없음.

두 가지 원문 형식을 읽는다.
  - 슬랙 사본:   "## 이름 HH:MM" 헤더로 블록 분리
  - 텔레그램 사본: "HH:MM" 줄 다음 "이름" 줄, 그 아래가 본문

집계할 때 대화가 아닌 것을 걷어낸다. 이걸 안 하면 첨부파일명·회의록 인용문이
그 사람의 '입버릇'으로 잡힌다 (실제로 그런 일이 있었다).

사용법:
    python3 scripts/extract_signals.py            # data/signals.json 갱신
    python3 scripts/extract_signals.py --print    # 표준출력으로 확인
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW_THREADS = ROOT / "raw" / "threads"
OUT = ROOT / "data" / "signals.json"

# 파트원만 집계한다. 임원·타부서는 대상이 아니다 (docs/PRIVACY.md).
MEMBERS = ["이강민", "이정은", "한정은", "김동준", "한민우", "전승찬", "박정훈", "김민지", "나선영", "이혜진"]

# 텔레그램 표시 이름 → 정규 이름
ALIASES = {
    "정은 한화생명 이": "이정은",
    "Minwoo Han": "한민우",
    "정훈 박": "박정훈",
    "선영 나": "나선영",
}

MARKERS = {
    "웃음ㅋ": r"ㅋㅋ+",
    "웃음ㅎ": r"ㅎㅎ+",
    "물결": r"~",
    "느낌표": r"!",
    "물음표": r"\?",
    "말줄임": r"\.\.+|…",
    "존댓말요": r"요[.\s~!?]|요$",
    "습니다체": r"습니다|입니다",
    "겸양": r"죄송|미안|부탁|감사|고생",
    "확인요구": r"확인|검증|체크|맞는지|팩트",
    "제안형": r"어떨까|어떠|해볼까|같아요|같습니다|좋을것|좋을 것|싶",
    "단정": r"반드시|꼭|무조건|필수|해야",
    "위임분담": r"나눠|분담|맡|담당|선착순",
}

SLACK_HEADER = re.compile(r"^(%s)\s*(\d{1,2}:\d{2})?" % "|".join(MEMBERS))
TIME_ONLY = re.compile(r"^\d{1,2}:\d{2}$")
SPEAKER_LINE = re.compile(r"^(%s)$" % "|".join(MEMBERS + list(ALIASES)))

# 대화가 아닌 줄 — 여기 걸리면 말투 계산에서 뺀다
NOISE = re.compile(
    r"(님이 .*(했습니다|들어왔습니다|초대))"      # 텔레그램 시스템 메시지
    r"|^\d+ members$|^\d{1,2} \w+ \d{4}$"          # 인원수 · 날짜 구분선
    r"|^In reply to"                                # 인용 헤더
    r"|^[^\w\s]{1,3}\d+$"                           # 리액션 집계 (👏1)
    r"|\.(pdf|html|md|mov|png|jpg|xlsx|docx)\b"     # 첨부파일명
    r"|^\d+(\.\d+)? ?(MB|KB)$"                      # 파일 크기
    r"|^https?://"                                  # 링크 단독 줄
)

# 대화체가 아닌 문서 구조 — 말끝(endings) 계산에서만 뺀다
DOCLIKE = re.compile(r"^\s*([-*•]|\||#{1,6}|>|\d+\.|\[)")


def is_noise(line: str) -> bool:
    return bool(NOISE.search(line))


def is_prose(line: str) -> bool:
    """대화체 평문인가. 불릿·표·헤더·인용은 문서체라 입버릇이 아니다."""
    s = line.strip()
    return bool(s) and not is_noise(s) and not DOCLIKE.match(s)


def parse_slack(text: str) -> tuple[dict, dict]:
    utt: dict[str, list[str]] = collections.defaultdict(list)
    times: dict[str, list[str]] = collections.defaultdict(list)
    for block in re.split(r"\n## ", text):
        m = SLACK_HEADER.match(block)
        if not m:
            continue
        body = block[m.end():].strip()
        if body:
            utt[m.group(1)].append(body)
            if m.group(2):
                times[m.group(1)].append(m.group(2))
    return utt, times


def parse_telegram(text: str) -> tuple[dict, dict]:
    """'HH:MM' 줄 → '이름' 줄 → 본문. 다음 화자/시간 줄에서 끊는다."""
    utt: dict[str, list[str]] = collections.defaultdict(list)
    times: dict[str, list[str]] = collections.defaultdict(list)
    lines = text.splitlines()
    speaker: str | None = None
    pending_time: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal speaker, buf
        if speaker and buf:
            body = "\n".join(buf).strip()
            if body:
                utt[speaker].append(body)
        buf = []

    for raw_line in lines:
        line = raw_line.strip()
        if TIME_ONLY.match(line):
            flush()
            pending_time = line
            speaker = None
            continue
        m = SPEAKER_LINE.match(line)
        if m:
            flush()
            speaker = ALIASES.get(m.group(1), m.group(1))
            if pending_time:
                times[speaker].append(pending_time)
                pending_time = None
            continue
        if speaker and line and not is_noise(line):
            buf.append(line)
    flush()
    return utt, times


def collect() -> dict:
    utterances: dict[str, list[str]] = collections.defaultdict(list)
    times: dict[str, list[str]] = collections.defaultdict(list)
    sources: list[str] = []

    files = sorted(p for p in RAW_THREADS.rglob("*")
                   if p.suffix in {".md", ".txt"} and p.is_file()) if RAW_THREADS.exists() else []

    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"건너뜀: {path.name} ({exc})", file=sys.stderr)
            continue
        u, t = parse_slack(text)
        if not u:
            u, t = parse_telegram(text)
        if not u:
            continue
        sources.append(path.relative_to(ROOT).as_posix())
        for name, items in u.items():
            utterances[name].extend(items)
        for name, items in t.items():
            times[name].extend(items)

    result = {}
    for name in MEMBERS:
        texts = utterances.get(name, [])
        n = len(texts)
        joined = " ".join(texts)

        # 대화체 줄만 추려 말끝과 '순수 대화 길이'를 뽑는다
        prose_lines = [ln.strip() for t in texts for ln in t.splitlines() if is_prose(ln)]
        prose = " ".join(prose_lines)

        markers = {}
        for label, pattern in MARKERS.items():
            hits = len(re.findall(pattern, prose))
            if hits:
                markers[label] = hits

        endings = [e for e in re.findall(r"([가-힣]{2,4})[.!?~\n]", prose) if e not in MEMBERS]
        endings_top = [w for w, _ in collections.Counter(e[-3:] for e in endings).most_common(6)]

        hours = sorted({t.split(":")[0].zfill(2) for t in times.get(name, [])})

        if n >= 15:
            confidence = "높음"
        elif n >= 5:
            confidence = "중간"
        else:
            confidence = "낮음"

        total_chars = sum(len(t) for t in texts)
        chat_chars = len(prose)
        result[name] = {
            "utterances": n,
            "total_chars": total_chars,
            "avg_chars": total_chars // n if n else 0,
            # 첨부 문서·인용문을 뺀 순수 대화 길이. 말투 판단은 이쪽을 쓴다
            "chat_chars": chat_chars,
            "avg_chat_chars": chat_chars // n if n else 0,
            "active_hours": f"{hours[0]}~{hours[-1]}" if hours else None,
            "markers": markers,
            "endings_top": endings_top,
            "artifacts": len(re.findall(r"\.md|\.html|\.mov|첨부|공유드|정리해", joined)),
            "confidence": confidence,
        }
    return {"sources": sources, "members": result}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", action="store_true", help="표준출력으로만 보여준다")
    args = ap.parse_args()

    data = collect()
    payload = json.dumps(data, ensure_ascii=False, indent=2)

    if args.print:
        print(payload)
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(payload + "\n", encoding="utf-8")
    counted = sum(1 for v in data["members"].values() if v["utterances"])
    print(f"{OUT.relative_to(ROOT)} 갱신 — 발화가 있는 멤버 {counted}명 / 전체 {len(MEMBERS)}명")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
