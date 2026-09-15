#!/usr/bin/env python3
"""텔레그램 그룹 대화를 raw/threads/ 로 가져온다.

마지막으로 가져온 지점 이후만 받는다(증분). 출력 형식은 Telegram Desktop
내보내기와 같게 맞춰서 scripts/extract_signals.py 가 그대로 파싱한다.

자격증명·세션·수집 지점은 .telegram/ 에 두고 git 에서 제외한다.
이 저장소는 public 이므로 초대 링크는 저장 시점에 마스킹한다.

자격증명은 .env 의 TELEGRAM_API_ID / TELEGRAM_API_HASH 를 읽는다.
없으면 --login 이 물어보고 .telegram/config.json 에 넣는다.

최초 1회 (본인 터미널에서 직접 — 전화번호·인증코드 입력이 필요하다):
    python3 -m venv .venv && .venv/bin/pip install 'telethon>=1.36,<2'
    python3 scripts/fetch_telegram.py --login

방 등록 (한 번씩):
    python3 scripts/fetch_telegram.py --list                    # 이름 확인
    python3 scripts/fetch_telegram.py --add-chat 고객서비스파트

이후 "동기화" 는 이 한 줄이다. 등록된 방을 전부, 마지막 지점 이후만 받는다:
    python3 scripts/fetch_telegram.py
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONF_DIR = ROOT / ".telegram"
CONF_PATH = CONF_DIR / "config.json"
STATE_PATH = CONF_DIR / "state.json"
SESSION_PATH = CONF_DIR / "session"
ENV_PATH = ROOT / ".env"
OUT_ROOT = ROOT / "raw" / "threads"

KST = timezone(timedelta(hours=9))
MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

# 공개 저장소다. 초대 링크는 그대로 두면 아무나 방에 들어올 수 있다.
INVITE_RE = re.compile(r"https?://t\.me/(?:\+|joinchat/)[\w-]+")
INVITE_MASK = "https://t.me/+****(초대링크 생략)"
URL_RE = re.compile(r"https?://\S+")


# ---------------------------------------------------------------- 렌더링
# telethon 없이도 테스트할 수 있도록 순수 함수로 분리한다.

def fmt_date(d: datetime) -> str:
    """'11 September 2026' — 내보내기의 날짜 구분선과 같은 형식."""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def fmt_time(d: datetime) -> str:
    return f"{d.hour:02d}:{d.minute:02d}"


def mask(text: str | None) -> str:
    return INVITE_RE.sub(INVITE_MASK, text or "")


def render_poll(question: str, options: list[tuple[str, int]], total: int) -> list[str]:
    """투표를 텍스트로. 내보내기는 결과를 안 담지만 우리는 담는다."""
    lines = [f"[투표] {mask(question)}"]
    for label, count in options:
        pct = round(count * 100 / total) if total else 0
        lines.append(f"- {mask(label)}: {count}표 ({pct}%)")
    lines.append(f"- 총 {total}표")
    return lines


def render_message(
    *,
    when: datetime,
    sender: str | None,
    text: str = "",
    service: str | None = None,
    reply: bool = False,
    media: list[str] | None = None,
    poll: list[str] | None = None,
    reactions: list[tuple[str, int]] | None = None,
) -> list[str]:
    """메시지 하나를 내보내기 형식의 줄 목록으로.

    형식:  HH:MM / 발신자명 / [In reply to this message] / [첨부경로] /
           [투표블록] / 본문 / [리액션]
    """
    if service:
        return [mask(service)]

    lines = [fmt_time(when), sender or "(알 수 없음)"]
    if reply:
        lines.append("In reply to this message")
    lines.extend(media or [])
    lines.extend(poll or [])
    body = mask(text).strip()
    if body:
        lines.extend(body.splitlines())
    for emoji, count in reactions or []:
        lines.append(f"{emoji}{count}")
    return lines


def render_header(chat_title: str, members: int | None, fetched_at: datetime,
                  first_id: int, last_id: int, chat_key: str = "",
                  last_when: datetime | None = None, notice_only: bool = False,
                  skipped: int = 0) -> list[str]:
    """messages.txt 맨 위 머리말. 화자가 아직 없어 파서가 본문으로 안 센다.

    `대화방 ID … 메시지 ID 범위 …` 줄은 장식이 아니다.
    .telegram/state.json 이 사라졌을 때 어디까지 받았는지 되읽는 근거다.
    형식을 바꾸면 HEADER_RE 도 같이 바꿔야 한다.
    """
    who = "" if notice_only else (f" (텔레그램 그룹, {members}명)" if members else " (텔레그램)")
    tail = f" · 마지막 메시지 {last_when:%Y-%m-%d %H:%M}" if last_when else ""
    lines = [
        f"{chat_title}{who}",
        f"scripts/fetch_telegram.py 로 수집. 기준 {fetched_at:%Y-%m-%d %H:%M} KST.",
        f"대화방 ID {chat_key} · 메시지 ID 범위 {first_id}~{last_id}{tail}",
        "이 범위 앞은 이전 폴더에 있다. 초대 링크는 공개 저장소라 마스킹했다.",
    ]
    if notice_only:
        lines.append(f"공지 전용 방이다. 입·퇴장 등 멤버 기록 {skipped}건은 저장하지 않았다.")
    lines.append("")
    return lines


HEADER_RE = re.compile(r"대화방 ID (\S+) · 메시지 ID 범위 (\d+)~(\d+)")


def scan_collected_max_id(key: str) -> int:
    """이미 raw/ 에 받아 둔 메시지 중 가장 큰 ID. 없으면 0."""
    best = 0
    if not OUT_ROOT.exists():
        return best
    for path in OUT_ROOT.rglob("messages.txt"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for chat_id, _lo, hi in HEADER_RE.findall(text):
            if chat_id == key:
                best = max(best, int(hi))
    return best


def resume_point(key: str, state: dict) -> tuple[int, str]:
    """어디부터 받을지와 그 근거.

    .telegram/ 은 git 에 올라가지 않는다. 다른 기기나 새 클론에서는 비어 있고,
    그때 0 부터 받으면 전체 이력이 raw/ 에 통째로 중복된다.
    그래서 상태 파일이 없으면 이미 받아 둔 머리말에서 마지막 ID 를 되읽는다.
    """
    recorded = int(state.get(key, {}).get("last_id", 0))
    if recorded:
        return recorded, "상태 파일"
    scanned = scan_collected_max_id(key)
    if scanned:
        return scanned, "기존 수집분 머리말 (상태 파일 없음)"
    return 0, "처음부터"


# ---------------------------------------------------------------- 설정·상태

def load_json(path: pathlib.Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(default)


def save_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


LOGIN_HINT = ("먼저 본인 터미널에서 로그인한다:\n"
              "    cd %s\n"
              "    python3 scripts/fetch_telegram.py --login" % ROOT)


def load_env_file(path: pathlib.Path) -> dict:
    """KEY=VALUE 한 줄씩. 주석·따옴표·export 접두어를 걷어낸다.

    python-dotenv 를 쓰지 않는다. 이 저장소는 표준 라이브러리만으로 돈다.
    """
    out: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def load_settings() -> dict:
    """설정을 한곳으로 모은다. 환경변수 > .env > .telegram/config.json 순.

    방 목록은 덮어쓰지 않고 합친다. .env 에 적어 둔 것과 --add-chat 으로
    등록한 것 중 하나가 조용히 사라지면 동기화에서 방이 통째로 빠진다.
    """
    conf = load_json(CONF_PATH, {})
    env = {**load_env_file(ENV_PATH), **os.environ}

    if env.get("TELEGRAM_API_ID"):
        conf["api_id"] = env["TELEGRAM_API_ID"]
    if env.get("TELEGRAM_API_HASH"):
        conf["api_hash"] = env["TELEGRAM_API_HASH"]

    merged = list(registered_chats(conf))
    for name in (c.strip() for c in env.get("TELEGRAM_CHATS", "").split(",")):
        if name and name not in merged:
            merged.append(name)
    conf["chats"] = merged

    notice = list(notice_only_chats(conf))
    for name in (c.strip() for c in env.get("TELEGRAM_NOTICE_ONLY", "").split(",")):
        if name and name not in notice:
            notice.append(name)
    conf["notice_only"] = notice
    return conf


def need_config() -> dict:
    """설정과 세션이 모두 있어야 진행한다.

    세션 확인을 건너뛰면 telethon 이 전화번호를 물으며 멈춘다.
    비대화형으로 돌 때는 그대로 매달리므로 여기서 먼저 끊는다.
    """
    conf = load_settings()
    if not conf.get("api_id") or not conf.get("api_hash"):
        sys.exit(f"api_id/api_hash 가 없다. {ENV_PATH.name} 에 넣거나 " + LOGIN_HINT)
    if not SESSION_PATH.with_suffix(".session").exists():
        sys.exit("세션이 없다. " + LOGIN_HINT)
    return conf


def notice_only_chats(conf: dict) -> list[str]:
    """공지만 받아 오는 방. 입·퇴장 같은 멤버 기록은 저장하지 않는다.

    파트 위 조직 방은 팀 일정과 상황을 알려고 받는다. 거기 누가 들어오고
    나갔는지는 우리가 쌓을 데이터가 아니다. 이 저장소는 public 이기도 해서
    관여한 적 없는 사람 이름을 원본에 남기지 않는다.
    """
    names = conf.get("notice_only") or []
    return [c for c in names if isinstance(c, str) and c.strip()]


def registered_chats(conf: dict) -> list[str]:
    """--chat 없이 부를 때 동기화할 방 목록. 텔레방이 여러 개라 필요하다."""
    chats = conf.get("chats") or []
    return [c for c in chats if isinstance(c, str) and c.strip()]


def add_chat(name: str, *, notice_only: bool = False) -> None:
    """설정 파일을 사람이 직접 열지 않고 방을 등록한다.

    config.json 에는 api_hash 가 함께 있다. 방 하나 추가하자고 그 파일을
    열어 보게 만들지 않는다.
    """
    conf = load_json(CONF_PATH, {})
    if name in registered_chats(load_settings()):
        if notice_only and name not in notice_only_chats(load_settings()):
            conf["notice_only"] = notice_only_chats(conf) + [name]
            save_json(CONF_PATH, conf)
            print(f"공지 전용으로 바꿨다: {name} (멤버 기록 미수집)")
        else:
            print(f"이미 등록돼 있다: {name}")
        return
    chats = registered_chats(conf)
    conf["chats"] = chats + [name]
    if notice_only:
        conf["notice_only"] = notice_only_chats(conf) + [name]
    save_json(CONF_PATH, conf)
    kind = " · 공지 전용(멤버 기록 미수집)" if notice_only else ""
    print(f"등록했다: {name}{kind}  (현재 {len(conf['chats'])}개)")


def slugify(title: str) -> str:
    s = re.sub(r"\s+", "-", title.strip())
    return re.sub(r"[^\w가-힣-]", "", s) or "chat"


# ---------------------------------------------------------------- telethon

VENV_PY = ROOT / ".venv" / "bin" / "python3"
VENV_HINT = ("telethon 이 없다. homebrew 파이썬은 PEP 668 로 설치를 막으므로 가상환경을 쓴다:\n"
             "    cd %s\n"
             "    python3 -m venv .venv && .venv/bin/pip install 'telethon>=1.36,<2'" % ROOT)


REEXEC_GUARD = "PART_WIKI_TELEGRAM_REEXEC"


def reexec_in_venv() -> None:
    """telethon 은 .venv 에만 있다. 없는 인터프리터로 실행되면 갈아탄다.

    인터프리터 경로를 비교하지 않는다. .venv/bin/python3 는 시스템 파이썬을
    가리키는 심볼릭 링크라 resolve() 하면 둘이 같아져 버린다.
    대신 import 가 되는지로 판단하고, 환경변수로 한 번만 전환한다.
    .venv 의 telethon 이 깨져 있어도 무한 재실행에 빠지지 않는다.
    """
    try:
        import telethon  # noqa: F401
        return
    except ImportError:
        pass
    if not VENV_PY.exists() or os.environ.get(REEXEC_GUARD):
        return  # 안내는 get_client() 가 한다
    print(f"[.venv 파이썬으로 전환: {VENV_PY}]", file=sys.stderr)
    os.environ[REEXEC_GUARD] = "1"
    script = str(pathlib.Path(__file__).resolve())
    os.execv(str(VENV_PY), [str(VENV_PY), script, *sys.argv[1:]])


def get_client(conf: dict):
    """telethon.sync 로 받아야 한다.

    `from telethon import TelegramClient` 로 받으면 메서드가 코루틴을 돌려주고,
    await 하지 않은 채 속성을 읽다가 터진다. telethon.sync 를 거치면
    이벤트 루프 밖에서 부를 때 알아서 실행해 결과를 준다.
    """
    try:
        from telethon.sync import TelegramClient
    except ImportError:
        sys.exit(VENV_HINT)
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(SESSION_PATH), int(conf["api_id"]), conf["api_hash"])
    harden_session()
    return client


def harden_session() -> None:
    """세션 파일은 계정 접근 권한 그 자체다. 주인만 읽게 둔다."""
    for path in CONF_DIR.glob("session*"):
        try:
            path.chmod(0o600)
        except OSError:
            pass


def do_login() -> None:
    """최초 1회. 대화형이므로 사용자가 자기 터미널에서 실행해야 한다."""
    if not sys.stdin.isatty():
        sys.exit("--login 은 대화형이다. 터미널에서 직접 실행한다.")

    CONF_DIR.mkdir(parents=True, exist_ok=True)
    conf = load_settings()
    if conf.get("api_id") and conf.get("api_hash"):
        print(f"api_id/api_hash 는 이미 있다 ({ENV_PATH.name}). 전화번호 인증만 진행한다.\n")
    else:
        print("https://my.telegram.org > API development tools 에서 발급한 값을 넣는다.")
        print("입력값은 .telegram/config.json 에만 저장되고 git 에는 올라가지 않는다.\n")
        conf["api_id"] = conf.get("api_id") or input("api_id: ").strip()
        conf["api_hash"] = conf.get("api_hash") or input("api_hash: ").strip()
        save_json(CONF_PATH, {k: v for k, v in conf.items() if k != "chats"})

    client = get_client(conf)
    with client:
        me = client.get_me()
        name = " ".join(filter(None, [me.first_name, me.last_name])) or "(이름 없음)"
        print(f"\n로그인 완료: {name} (@{me.username or '-'})")
    harden_session()
    print("세션은 .telegram/session.session 에 저장됐다. 이 파일은 계정 접근 권한 그 자체다.")


def ensure_authorized(client) -> None:
    if not client.is_user_authorized():
        sys.exit("세션이 만료됐다. " + LOGIN_HINT)


def do_list(conf: dict, limit: int) -> None:
    client = get_client(conf)
    with client:
        ensure_authorized(client)
        print(f"{'ID':>15}  {'종류':4}  이름")
        for dialog in client.iter_dialogs(limit=limit):
            kind = "그룹" if dialog.is_group else ("채널" if dialog.is_channel else "개인")
            print(f"{dialog.id:>15}  {kind:4}  {dialog.name}")


def do_status() -> None:
    """어느 방을 어디까지 받았는지. 상태 파일을 직접 열지 않고 본다."""
    state = load_json(STATE_PATH, {})
    chats = registered_chats(load_settings())
    if not state and not chats:
        print("등록된 방도 수집 기록도 없다. --list 로 이름을 확인하고 --add-chat 으로 등록한다.")
        return
    print(f"{'방':<18}{'마지막 메시지':<20}{'ID':>8}   마지막 수집")
    seen = set()
    for key, row in state.items():
        title = row.get("title") or key
        seen.add(title)
        last_msg = (row.get("last_message_at") or "-")[:16].replace("T", " ")
        fetched = (row.get("fetched_at") or "-")[:16].replace("T", " ")
        print(f"{title:<18}{last_msg:<20}{row.get('last_id', 0):>8}   {fetched}")
    for name in chats:
        if name not in seen:
            print(f"{name:<18}{'아직 수집 안 함':<20}{0:>8}   -")
    missing = [t for t in seen if t not in chats]
    if missing:
        print(f"\n수집 기록은 있으나 등록 목록에 없다: {', '.join(missing)}")
        print("동기화 대상에서 빠진다. 넣으려면 --add-chat 으로 등록한다.")


def resolve_chat(client, chat: str):
    """제목·@username·숫자 ID 중 무엇이든 받는다."""
    if re.fullmatch(r"-?\d+", chat):
        return client.get_entity(int(chat))
    if chat.startswith("@"):
        return client.get_entity(chat)
    for dialog in client.iter_dialogs():
        if dialog.name == chat:
            return dialog.entity
    for dialog in client.iter_dialogs():
        if chat in (dialog.name or ""):
            return dialog.entity
    raise LookupError(f"대화방을 못 찾았다: {chat!r}. `--list` 로 이름을 확인한다.")


def collect(conf: dict, chat: str, *, dry_run: bool, fetch_all: bool,
            limit: int | None, since_id: int | None = None):
    notice_only = chat in notice_only_chats(conf)
    from telethon import utils
    from telethon.tl.types import MessageService

    state = load_json(STATE_PATH, {})
    client = get_client(conf)

    with client:
        ensure_authorized(client)
        entity = resolve_chat(client, chat)
        title = utils.get_display_name(entity)
        key = str(getattr(entity, "id", chat))
        if fetch_all:
            min_id, why = 0, "--all (전체 이력)"
        elif since_id is not None:
            min_id, why = since_id, "--since-id"
        else:
            min_id, why = resume_point(key, state)
        print(f"[{title}] 시작점 {min_id} — 근거: {why}")

        # 시작점을 못 찾았는데 그냥 0 부터 받으면 전체 이력이 raw/ 에 중복된다.
        # 실수로 지나가지 않도록 여기서 끊고 사람이 정하게 한다.
        if min_id == 0 and not fetch_all:
            raise LookupError(
                f"[{title}] 어디부터 받을지 모르겠다. 전체를 받으면 이미 있는 대화가 중복된다.\n"
                f"    처음 받는 방이면   : --chat '{chat}' --all\n"
                f"    이어받는 방이면   : --chat '{chat}' --since-id <마지막 메시지 ID>\n"
                f"    (--status 로 기록을, messages.txt 머리말로 마지막 ID 를 확인한다)")

        members = getattr(getattr(entity, "participants_count", None), "real", None) \
            or getattr(entity, "participants_count", None)

        out_dir = OUT_ROOT / f"{datetime.now(KST):%Y-%m-%d}-텔레그램-{slugify(title)}"
        photos_dir = out_dir / "photos"

        body: list[str] = []
        last_date = None
        last_when: datetime | None = None
        first_id = last_id = 0
        count = 0
        skipped_service = 0
        other_urls: set[str] = set()

        for msg in client.iter_messages(entity, min_id=min_id, reverse=True, limit=limit):
            when = msg.date.astimezone(KST)

            if isinstance(msg, MessageService) and notice_only:
                skipped_service += 1
                continue            # 입·퇴장 기록은 남기지 않는다

            # 날짜 구분선은 실제로 쓸 메시지가 있을 때만 넣는다.
            # 먼저 넣으면 전부 걸러진 날에 빈 날짜 줄만 남는다.
            if last_date != when.date():
                body.append(fmt_date(when))
                last_date = when.date()

            if isinstance(msg, MessageService):
                body.extend(render_message(when=when, sender=None,
                                           service=describe_service(msg)))
            else:
                sender = utils.get_display_name(msg.sender) if msg.sender else None
                media_paths: list[str] = []
                if msg.media and not msg.poll and not dry_run:
                    photos_dir.mkdir(parents=True, exist_ok=True)
                    saved = client.download_media(msg, file=str(photos_dir / str(msg.id)))
                    if saved:
                        media_paths.append(f"photos/{pathlib.Path(saved).name}")
                elif msg.media and not msg.poll:
                    media_paths.append(f"photos/{msg.id}.(첨부 — dry-run 이라 안 받음)")

                body.extend(render_message(
                    when=when,
                    sender=sender,
                    text=msg.message or "",
                    reply=bool(msg.reply_to),
                    media=media_paths,
                    poll=extract_poll(msg),
                    reactions=extract_reactions(msg),
                ))

            for url in URL_RE.findall(msg.message or ""):
                if not INVITE_RE.match(url):
                    other_urls.add(url)

            first_id = first_id or msg.id
            last_id = msg.id
            last_when = when
            count += 1

    if not count:
        print(f"[{title}] 새 메시지 없음.")
        return 0

    header = render_header(title, members, datetime.now(KST), first_id, last_id,
                           chat_key=key, last_when=last_when,
                           notice_only=notice_only, skipped=skipped_service)
    text = "\n".join(header + body) + "\n"

    if dry_run:
        print(text)
        print(f"--- dry-run: [{title}] {count}건, 저장 안 함. 저장하려면 --dry-run 을 뺀다.",
              file=sys.stderr)
        return count

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "messages.txt"
    if target.exists():
        target.write_text(target.read_text(encoding="utf-8") + "\n" + text, encoding="utf-8")
    else:
        target.write_text(text, encoding="utf-8")

    state.setdefault(key, {})
    state[key].update({
        "title": title,
        "last_id": last_id,
        "last_message_at": last_when.isoformat() if last_when else None,
        "fetched_at": datetime.now(KST).isoformat(),
    })
    save_json(STATE_PATH, state)

    print(f"[{title}] {count}건 저장: {target.relative_to(ROOT)}")
    if other_urls:
        print("  공개 전 확인할 링크 (초대 링크 외):")
        for url in sorted(other_urls):
            print(f"    {url}")
    return count


def describe_service(msg) -> str:
    from telethon import utils
    who = utils.get_display_name(msg.sender) if msg.sender else "누군가"
    action = type(msg.action).__name__
    if "JoinedByLink" in action:
        return f"{who}님이 초대 링크를 통해 그룹에 들어왔습니다"
    if "AddUser" in action:
        return f"{who}님이 사용자를 초대했습니다"
    if "DeleteUser" in action:
        return f"{who}님이 나갔습니다"
    if "ChatCreate" in action or "ChannelCreate" in action:
        return f"{who}님이 그룹을 만들었습니다"
    if "EditTitle" in action:
        return f"{who}님이 그룹 이름을 바꿨습니다"
    return f"{who}님의 시스템 메시지 ({action})"


def extract_poll(msg) -> list[str] | None:
    poll = getattr(msg, "poll", None)
    if not poll:
        return None
    question = poll.poll.question
    question = getattr(question, "text", question)
    counts = {}
    total = 0
    if poll.results and poll.results.results:
        for res in poll.results.results:
            counts[res.option] = res.voters
        total = poll.results.total_voters or sum(counts.values())
    options = []
    for answer in poll.poll.answers:
        label = getattr(answer.text, "text", answer.text)
        options.append((label, counts.get(answer.option, 0)))
    return render_poll(question, options, total)


def extract_reactions(msg) -> list[tuple[str, int]]:
    out = []
    reactions = getattr(msg, "reactions", None)
    if reactions and reactions.results:
        for res in reactions.results:
            emoji = getattr(res.reaction, "emoticon", None) or "?"
            out.append((emoji, res.count))
    return out


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--login", action="store_true", help="최초 1회 인증 (대화형)")
    ap.add_argument("--list", action="store_true", help="대화방 목록 출력")
    ap.add_argument("--status", action="store_true", help="방별로 어디까지 받았는지")
    ap.add_argument("--chat", help="대화방 하나만. 생략하면 등록된 방을 전부 동기화한다")
    ap.add_argument("--add-chat", metavar="이름", help="동기화 대상으로 방을 등록한다")
    ap.add_argument("--notice-only", action="store_true",
                    help="--add-chat 과 함께. 공지만 받고 멤버 기록은 저장하지 않는다")
    ap.add_argument("--dry-run", action="store_true", help="저장하지 않고 화면에만")
    ap.add_argument("--all", action="store_true", help="증분 무시하고 전체 이력")
    ap.add_argument("--limit", type=int, help="최대 메시지 수")
    ap.add_argument("--since-id", type=int,
                    help="이 메시지 ID 이후만. 첫 수집에서 기존 내보내기와 겹치는 구간을 자를 때 쓴다")
    args = ap.parse_args()

    reexec_in_venv()

    if args.login:
        do_login()
        return
    if args.add_chat:
        add_chat(args.add_chat, notice_only=args.notice_only)
        return
    if args.status:
        do_status()
        return

    conf = need_config()
    if args.list:
        do_list(conf, args.limit or 50)
        return

    targets = [args.chat] if args.chat else registered_chats(conf)
    if not targets:
        ap.error("동기화할 방이 없다. `--list` 로 이름을 확인한 뒤 "
                 "`--add-chat 이름` 으로 등록한다.")
    if args.since_id is not None and not args.chat:
        ap.error("--since-id 는 방마다 값이 다르다. --chat 과 함께 쓴다.")

    total, failed = 0, []
    for name in targets:
        try:
            total += collect(conf, name, dry_run=args.dry_run, fetch_all=args.all,
                             limit=args.limit, since_id=args.since_id) or 0
        except LookupError as exc:
            failed.append(str(exc))

    if len(targets) > 1 or failed:
        print(f"\n합계 {total}건 / 방 {len(targets)}개")
    for line in failed:
        print(f"  건너뜀 — {line}", file=sys.stderr)
    if failed and not total:
        sys.exit(1)


if __name__ == "__main__":
    main()
