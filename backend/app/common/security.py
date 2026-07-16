"""비밀번호 해싱 공용 헬퍼 (Requirement 4.3).

Argon2id 단일 스킴으로 비밀번호를 해싱·검증한다. s02(비번 변경)·s03(비번 재설정)이
동일 스킴으로 ``user.password_hash`` 를 기록·검증하도록 이 유틸을 재사용한다.

이 모듈은 pwdlib/stdlib 에만 의존하며 db·models·auth 등 상위 계층을 import 하지 않는다.
"""

from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

_hasher = PasswordHash.recommended()  # Argon2id


def hash_password(raw: str) -> str:
    """평문 비밀번호를 Argon2id 해시 문자열로 변환한다 (랜덤 salt 포함)."""
    return _hasher.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    """평문이 해시와 일치하면 True, 불일치·형식 오류면 False 를 반환한다."""
    try:
        return _hasher.verify(raw, hashed)
    except (PwdlibError, ValueError, TypeError):
        return False
