#!/usr/bin/env python3
"""build_site.py 의 프로필 검증 로직을 테스트한다 (docs/PROFILE_SCHEMA.md, docs/PRIVACY.md).

build_site.py 는 worker-site 가 동시에 작성 중이라 아직 없을 수 있고, 검증 함수의
정확한 이름도 미리 알 수 없다. 그래서 이 파일은:

  1. build_site 모듈을 import 할 수 없으면(파일이 아직 없으면) 건너뛴다.
  2. import 는 됐지만 검증 함수로 보이는 이름을 찾지 못하면 건너뛴다.

두 경우 모두 이유를 표준에러로 출력한 뒤 unittest.SkipTest 를 던진다 — CI 가 빨간불이
되지는 않지만, 조용히 통과하지도 않는다.

표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import copy
import pathlib
import sys
import unittest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# 검증 함수로 추정할 이름들. build_site.py 가 확정되기 전이라 이름이 달라질 수 있어
# 후보를 순서대로 hasattr 로 찾는다. 못 찾으면 이름에 "valid" 가 들어간 첫 callable 을 쓴다.
CANDIDATE_VALIDATOR_NAMES = [
    "validate_profile",
    "validate",
    "check_profile",
    "is_valid_profile",
    "validate_profile_data",
    "profile_is_valid",
]


def _find_validator(module):
    for name in CANDIDATE_VALIDATOR_NAMES:
        if hasattr(module, name):
            candidate = getattr(module, name)
            if callable(candidate):
                return name, candidate
    for name in dir(module):
        if "valid" in name.lower():
            candidate = getattr(module, name)
            if callable(candidate):
                return name, candidate
    return None, None


def _skip(reason: str):
    print(f"[test_build_site] 건너뜀: {reason}", file=sys.stderr)
    raise unittest.SkipTest(reason)


def make_profile(**deep_overrides):
    """docs/PROFILE_SCHEMA.md 기준의 정상 프로필(김동준.json)을 만든다.

    deep_overrides 는 얕은 최상위 키 덮어쓰기만 지원한다. 중첩 필드를 바꿀 때는
    반환값을 직접 수정한다(각 테스트에서 그렇게 한다).
    """
    profile = {
        "schema_version": 1,
        "name": "김동준",
        "part": "고객서비스파트",
        "role": "BE",
        "generated": "2026-09-11",
        "sources": ["slack:proj-평생보장소득"],
        "signals": {
            "utterances": 10,
            "total_chars": 3205,
            "avg_chars": 320,
            "active_hours": "07~18",
            "markers": {"존댓말요": 21, "습니다체": 7, "확인요구": 4},
            "endings_top": ["입니다", "같아요", "습니다"],
            "artifacts": 7,
            "confidence": "중간",
        },
        "profile": {
            "axes": {
                "delegation": 3,
                "verification": 5,
                "planning": 4,
                "thoroughness": 5,
                "exploration": 3,
            },
            "work_style": "관측된 행동 근거로만 쓴 2~3줄짜리 설명이다.",
            "strengths": ["근거 있는 강점 1", "근거 있는 강점 2", "근거 있는 강점 3"],
        },
        "fun": {
            "mbti": {"value": "INTJ", "strength": "약함", "basis": "축별 근거 한 줄"},
            "age_band": {"value": "30대 중반", "strength": "약함", "basis": "ㅋㅋ 1건 · 존댓말 21건"},
            "blood_type": {"value": "A형", "strength": "없음(무작위)", "basis": "데이터 신호 0. 억지 논리 한 줄"},
            "nickname": "한 줄 별명 (호의적으로)",
            "how_to_talk": {
                "good": ["짧고 명확하게 요청"],
                "avoid": ["급박한 재촉"],
                "best_time": "07~10시",
                "example": "확인 부탁드립니다.",
            },
        },
    }
    profile.update(deep_overrides)
    return profile


class ValidateProfileTests(unittest.TestCase):
    """docs/PROFILE_SCHEMA.md · docs/PRIVACY.md 에 정의된 검증 규칙을 확인한다."""

    validator = None
    validator_name = None

    @classmethod
    def setUpClass(cls):
        try:
            import build_site  # type: ignore
        except ImportError as exc:
            _skip(
                "scripts/build_site.py 를 import 할 수 없다 "
                f"(worker-site 가 아직 작성 중일 수 있음): {exc!r}"
            )
            return

        name, fn = _find_validator(build_site)
        if fn is None:
            _skip(
                "build_site.py 에서 검증 함수를 찾지 못했다. "
                f"찾아본 이름: {', '.join(CANDIDATE_VALIDATOR_NAMES)} "
                "(또는 이름에 'valid' 를 포함하는 callable)"
            )
            return

        cls.validator = staticmethod(fn)
        cls.validator_name = name

    # -- 검증 함수 호출 · 결과 해석 헬퍼 --------------------------------------
    #
    # validate_profile(data, filename) 시그니처를 기대하지만, 유사한 함수가
    # 인자를 하나만 받을 수도 있어 TypeError 시 재시도한다.
    # 반환 관례도 확정돼 있지 않으므로(bool / None / 에러 메시지 문자열 / 에러 리스트)
    # 여러 관례를 함께 해석하고, 예외를 던져 거부를 표현하는 관례도 지원한다.

    def _call(self, data, filename):
        # build_site.validate(data, json_path: Path) 는 두 번째 인자에서 .stem 을 쓰므로
        # pathlib.Path 로 넘긴다. 인자를 하나만 받는 구현이면 TypeError 로 걸러 재시도한다.
        path_arg = pathlib.Path(filename)
        try:
            return self.validator(data, path_arg)
        except TypeError:
            return self.validator(data)

    @staticmethod
    def _is_pass(result) -> bool:
        if result is None:
            return True
        if isinstance(result, bool):
            return result
        if isinstance(result, str):
            return result == ""
        if isinstance(result, (list, tuple, set)):
            return len(result) == 0
        return bool(result)

    def assert_profile_valid(self, data, filename="김동준.json"):
        try:
            result = self._call(data, filename)
        except Exception as exc:  # noqa: BLE001 - 예외 자체가 "거부"라는 관례일 수 있다
            self.fail(f"통과해야 하는 프로필이 예외로 거부됨: {exc!r}")
        self.assertTrue(
            self._is_pass(result),
            f"통과해야 하는 프로필이 거부됨 (반환값: {result!r})",
        )

    def assert_profile_invalid(self, data, filename="김동준.json"):
        try:
            result = self._call(data, filename)
        except Exception:
            return  # 예외로 거부를 표현하는 관례 — 통과
        self.assertFalse(
            self._is_pass(result),
            f"거부해야 하는 프로필이 통과함 (반환값: {result!r})",
        )

    # -- 테스트 케이스 --------------------------------------------------------

    def test_valid_profile_passes(self):
        self.assert_profile_valid(make_profile())

    def test_schema_version_mismatch_rejected(self):
        profile = make_profile()
        profile["schema_version"] = 2
        self.assert_profile_invalid(profile)

    def test_filename_name_mismatch_rejected(self):
        profile = make_profile()  # name == "김동준"
        self.assert_profile_invalid(profile, filename="한민우.json")

    def test_forbidden_key_gender_rejected(self):
        profile = make_profile()
        profile["gender"] = "남"
        self.assert_profile_invalid(profile)

    def test_forbidden_key_samples_in_nested_dict_rejected(self):
        profile = make_profile()
        # 최상위가 아니라 중첩된 dict 안에 금지 키를 넣어도 걸려야 한다
        profile["profile"] = copy.deepcopy(profile["profile"])
        profile["profile"]["samples_원문"] = ["실제로 이렇게 말했다"]
        self.assert_profile_invalid(profile)

    def test_mbti_missing_strength_rejected(self):
        profile = make_profile()
        profile["fun"] = copy.deepcopy(profile["fun"])
        del profile["fun"]["mbti"]["strength"]
        self.assert_profile_invalid(profile)

    def test_blood_type_strength_must_be_random_label(self):
        profile = make_profile()
        profile["fun"] = copy.deepcopy(profile["fun"])
        profile["fun"]["blood_type"]["strength"] = "약함"  # "없음(무작위)" 여야 한다
        self.assert_profile_invalid(profile)

    def test_internal_url_rejected(self):
        profile = make_profile()
        profile["profile"] = copy.deepcopy(profile["profile"])
        profile["profile"]["work_style"] = (
            "https://hanwhalifem365.sharepoint.com/sites/abc 문서를 참고해 처리한다."
        )
        self.assert_profile_invalid(profile)

    def test_executive_real_name_rejected(self):
        profile = make_profile()
        profile["profile"] = copy.deepcopy(profile["profile"])
        profile["profile"]["work_style"] = "이창희 상무님 보고 후 처리하는 편이다."
        self.assert_profile_invalid(profile)

    def test_phone_number_rejected(self):
        profile = make_profile()
        profile["profile"] = copy.deepcopy(profile["profile"])
        profile["profile"]["work_style"] = "급할 때는 010-1234-5678 로 연락하면 된다."
        self.assert_profile_invalid(profile)

    def test_fun_null_passes(self):
        profile = make_profile()
        profile["fun"] = None  # 본인이 재미 코너를 뺀 경우 — 통과해야 한다
        self.assert_profile_valid(profile)


if __name__ == "__main__":
    unittest.main()
