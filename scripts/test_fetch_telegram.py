#!/usr/bin/env python3
"""fetch_telegram.py 가 내는 형식을 extract_signals.py 가 그대로 읽는지 검증한다.

telethon 없이 돈다. 렌더링 함수만 쓰고 네트워크는 타지 않는다.
이 테스트가 깨지면 수집 결과가 프로필 신호 집계에서 통째로 누락된다.

    python3 scripts/test_fetch_telegram.py
"""
from __future__ import annotations

import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import extract_signals as sig  # noqa: E402
import fetch_telegram as ft  # noqa: E402

KST = timezone(timedelta(hours=9))


def at(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=KST)


class 형식(unittest.TestCase):
    def test_날짜_구분선(self):
        self.assertEqual(ft.fmt_date(at(11, 14, 29)), "11 September 2026")
        self.assertEqual(ft.fmt_time(at(11, 9, 5)), "09:05")

    def test_날짜줄은_잡음으로_걸러진다(self):
        self.assertTrue(sig.is_noise(ft.fmt_date(at(11, 0, 0))))

    def test_시각줄과_화자줄이_파서_패턴과_맞는다(self):
        self.assertTrue(sig.TIME_ONLY.match(ft.fmt_time(at(11, 14, 29))))
        self.assertTrue(sig.SPEAKER_LINE.match("김동준"))
        self.assertTrue(sig.SPEAKER_LINE.match("정은 한화생명 이"))

    def test_리액션은_잡음으로_걸러진다(self):
        line = ft.render_message(when=at(11, 14, 29), sender="전승찬",
                                 text="네", reactions=[("🎄", 4)])[-1]
        self.assertEqual(line, "🎄4")
        self.assertTrue(sig.is_noise(line))

    def test_인용_머리말은_잡음으로_걸러진다(self):
        lines = ft.render_message(when=at(11, 10, 57), sender="김동준",
                                  text="네", reply=True)
        self.assertIn("In reply to this message", lines)
        self.assertTrue(sig.is_noise("In reply to this message"))


class 마스킹(unittest.TestCase):
    def test_초대링크를_가린다(self):
        got = ft.mask("들어오세요 https://t.me/+hTTNnHndDnNmNmI1 여기로")
        self.assertNotIn("hTTNnHndDnNmNmI1", got)
        self.assertIn("초대링크 생략", got)

    def test_joinchat_형식도_가린다(self):
        self.assertNotIn("AbCdEf", ft.mask("https://t.me/joinchat/AbCdEf"))

    def test_일반_링크는_그대로_둔다(self):
        url = "https://customer-service-part-poc-project.github.io/part-wiki/"
        self.assertIn(url, ft.mask(f"사이트 {url} 입니다"))

    def test_투표_본문도_마스킹을_탄다(self):
        lines = ft.render_poll("https://t.me/+secret123 봐주세요", [("예", 1)], 1)
        self.assertNotIn("secret123", "\n".join(lines))


class 파서_왕복(unittest.TestCase):
    """렌더링한 결과를 extract_signals 가 화자별로 되읽는지 본다."""

    def build(self) -> str:
        lines = ft.render_header("고객서비스파트", 10, at(15, 11, 0), 1881, 2021)
        lines.append(ft.fmt_date(at(14, 0, 0)))
        lines += ft.render_message(when=at(14, 9, 48), sender="이강민",
                                   text="스크럼은 10시 반에 진행할게요~")
        lines += ft.render_message(when=at(14, 9, 50), sender="김동준",
                                   text="세일즈에 맞춰달라할게요 ㅋㅋ",
                                   reply=True, reactions=[("🎄", 2)])
        lines += ft.render_message(when=at(14, 15, 37), sender="선영 나",
                                   text="9월 점심회식 날짜를 잡아보시죠~",
                                   poll=ft.render_poll("갈비찜 솥밥?", [("예", 6), ("아니오", 0)], 6))
        lines += ft.render_message(when=at(15, 9, 42), sender="Minwoo Han",
                                   media=["photos/photo_2019.jpg"],
                                   text="네이버 예약을 위한 메뉴 선조사")
        lines.append("정훈 박님이 초대 링크를 통해 그룹에 들어왔습니다")
        return "\n".join(lines) + "\n"

    def test_화자별로_읽힌다(self):
        utt, times = sig.parse_telegram(self.build())
        self.assertEqual(set(utt), {"이강민", "김동준", "나선영", "한민우"})
        self.assertEqual(times["이강민"], ["09:48"])

    def test_별명이_정규이름으로_바뀐다(self):
        utt, _ = sig.parse_telegram(self.build())
        self.assertIn("나선영", utt)      # 선영 나
        self.assertIn("한민우", utt)      # Minwoo Han
        self.assertNotIn("선영 나", utt)

    def test_머리말은_발화로_안_센다(self):
        utt, _ = sig.parse_telegram(self.build())
        joined = " ".join(sum(utt.values(), []))
        self.assertNotIn("fetch_telegram.py 로 수집", joined)

    def test_첨부파일명과_시스템메시지가_본문에_안_섞인다(self):
        utt, _ = sig.parse_telegram(self.build())
        joined = " ".join(sum(utt.values(), []))
        self.assertNotIn("photo_2019", joined)
        self.assertNotIn("초대 링크를 통해", joined)

    def test_슬랙_파서가_먼저_가로채지_않는다(self):
        """collect() 결과는 텔레그램 파서로 가야 한다. 슬랙 파서는 빈손이어야 한다."""
        slack, _ = sig.parse_slack(self.build())
        self.assertEqual(slack, {})


class 격리된_설정(unittest.TestCase):
    """설정 파일과 환경변수를 임시 폴더로 돌린다.

    이걸 안 하면 저장소의 진짜 .env 를 읽어서, 테스트가 로컬 설정에 따라
    붙었다 떨어졌다 한다.
    """

    KEYS = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_CHATS")

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.orig_conf, self.orig_env = ft.CONF_PATH, ft.ENV_PATH
        ft.CONF_PATH = self.tmp / "config.json"
        ft.ENV_PATH = self.tmp / ".env"
        self.saved = {k: os.environ.pop(k) for k in self.KEYS if k in os.environ}

    def tearDown(self):
        ft.CONF_PATH, ft.ENV_PATH = self.orig_conf, self.orig_env
        for k in self.KEYS:
            os.environ.pop(k, None)
        os.environ.update(self.saved)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_env(self, *lines: str):
        ft.ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


class 방_등록(격리된_설정):
    """--chat 없이 부를 때 쓸 방 목록. '동기화' 한 단어가 여기에 기댄다."""

    def test_빈_설정이면_빈_목록(self):
        self.assertEqual(ft.registered_chats({}), [])

    def test_빈_문자열은_걸러낸다(self):
        self.assertEqual(ft.registered_chats({"chats": ["가", "", "  ", None, 3]}), ["가"])

    def test_등록하면_쌓인다(self):
        ft.add_chat("고객서비스파트")
        ft.add_chat("평생보장소득")
        conf = ft.load_json(ft.CONF_PATH, {})
        self.assertEqual(conf["chats"], ["고객서비스파트", "평생보장소득"])

    def test_중복_등록은_무시한다(self):
        ft.add_chat("고객서비스파트")
        ft.add_chat("고객서비스파트")
        self.assertEqual(ft.load_json(ft.CONF_PATH, {})["chats"], ["고객서비스파트"])

    def test_env에_이미_있으면_다시_안_넣는다(self):
        self.write_env("TELEGRAM_CHATS=고객서비스파트")
        ft.add_chat("고객서비스파트")
        self.assertEqual(ft.load_json(ft.CONF_PATH, {}).get("chats"), None)

    def test_기존_설정값을_지우지_않는다(self):
        """api_id·api_hash 가 같은 파일에 있다. 방 추가가 그걸 날리면 안 된다."""
        ft.save_json(ft.CONF_PATH, {"api_id": "123", "api_hash": "deadbeef"})
        ft.add_chat("고객서비스파트")
        conf = ft.load_json(ft.CONF_PATH, {})
        self.assertEqual(conf["api_id"], "123")
        self.assertEqual(conf["api_hash"], "deadbeef")
        self.assertEqual(conf["chats"], ["고객서비스파트"])

    def test_설정파일은_주인만_읽게_둔다(self):
        ft.save_json(ft.CONF_PATH, {"api_hash": "x"})
        self.assertEqual(ft.CONF_PATH.stat().st_mode & 0o077, 0)


class 설정_읽기(격리된_설정):
    """.env 를 읽어 자격증명을 채우는 부분. 여기가 비면 매번 다시 입력해야 한다."""

    def test_주석과_빈줄을_건너뛴다(self):
        self.write_env("# 주석", "", "TELEGRAM_API_ID=1")
        self.assertEqual(ft.load_env_file(ft.ENV_PATH), {"TELEGRAM_API_ID": "1"})

    def test_따옴표와_export_를_걷어낸다(self):
        self.write_env("export TELEGRAM_API_HASH='abc'", 'X="y"')
        got = ft.load_env_file(ft.ENV_PATH)
        self.assertEqual(got["TELEGRAM_API_HASH"], "abc")
        self.assertEqual(got["X"], "y")

    def test_등호가_없는_줄은_무시한다(self):
        self.write_env("쓰레기줄", "TELEGRAM_API_ID=7")
        self.assertEqual(ft.load_env_file(ft.ENV_PATH), {"TELEGRAM_API_ID": "7"})

    def test_파일이_없어도_안_터진다(self):
        self.assertEqual(ft.load_env_file(self.tmp / "없음"), {})

    def test_자격증명을_설정으로_옮긴다(self):
        self.write_env("TELEGRAM_API_ID=38185115", "TELEGRAM_API_HASH=deadbeef")
        conf = ft.load_settings()
        self.assertEqual(conf["api_id"], "38185115")
        self.assertEqual(conf["api_hash"], "deadbeef")

    def test_환경변수가_env파일을_이긴다(self):
        self.write_env("TELEGRAM_API_ID=111")
        os.environ["TELEGRAM_API_ID"] = "999"
        self.assertEqual(ft.load_settings()["api_id"], "999")

    def test_방_목록은_덮어쓰지_않고_합친다(self):
        """한쪽만 남으면 그 방이 동기화에서 통째로 빠진다."""
        ft.save_json(ft.CONF_PATH, {"chats": ["과제방"]})
        self.write_env("TELEGRAM_CHATS=고객서비스파트, 법무방")
        self.assertEqual(ft.registered_chats(ft.load_settings()),
                         ["과제방", "고객서비스파트", "법무방"])

    def test_중복된_방은_한_번만(self):
        ft.save_json(ft.CONF_PATH, {"chats": ["고객서비스파트"]})
        self.write_env("TELEGRAM_CHATS=고객서비스파트")
        self.assertEqual(ft.registered_chats(ft.load_settings()), ["고객서비스파트"])

    def test_env만_있어도_동작한다(self):
        self.write_env("TELEGRAM_API_ID=1", "TELEGRAM_API_HASH=h", "TELEGRAM_CHATS=방")
        conf = ft.load_settings()
        self.assertEqual((conf["api_id"], conf["api_hash"], conf["chats"]), ("1", "h", ["방"]))

    def test_env가_비면_config_값을_쓴다(self):
        ft.save_json(ft.CONF_PATH, {"api_id": "5", "api_hash": "z"})
        conf = ft.load_settings()
        self.assertEqual((conf["api_id"], conf["api_hash"]), ("5", "z"))


class 출력경로(unittest.TestCase):
    def test_슬러그가_기존_폴더명_규칙과_같다(self):
        self.assertEqual(ft.slugify("고객서비스파트"), "고객서비스파트")
        self.assertEqual(ft.slugify("Direct 변액 저축"), "Direct-변액-저축")

    def test_수집_경로가_raw_threads_아래다(self):
        self.assertEqual(ft.OUT_ROOT, ft.ROOT / "raw" / "threads")

    def test_비밀은_전부_telegram_폴더에_있다(self):
        for path in (ft.CONF_PATH, ft.STATE_PATH, ft.SESSION_PATH):
            self.assertEqual(path.parent, ft.CONF_DIR)


if __name__ == "__main__":
    unittest.main(verbosity=2)
