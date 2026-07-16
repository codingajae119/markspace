"""비밀번호 해싱 공용 헬퍼 단위 테스트 (Requirement 4.3, Security Considerations).

- ``hash_password`` 는 평문을 저장하지 않고 Argon2id 해시 문자열을 반환한다.
- ``verify_password`` 는 일치 시 True, 불일치 시 False 를 반환한다.
- 동일 평문이라도 매 해시마다 랜덤 salt 로 서로 다른 결과를 낸다.
- 잘못된 형식의 해시에 대해서도 예외 없이 False 를 반환한다.
"""

from app.common.security import hash_password, verify_password


def test_hash_password_returns_argon2_hash_not_plaintext():
    """평문을 저장하지 않고 Argon2id 식별자를 가진 해시 문자열을 반환한다 (4.3)."""
    hashed = hash_password("s3cret")
    assert isinstance(hashed, str)
    assert hashed != "s3cret"
    assert "argon2" in hashed
    assert hashed.startswith("$argon2")


def test_verify_password_roundtrip_true():
    """hash→verify 왕복은 True 를 반환한다."""
    assert verify_password("s3cret", hash_password("s3cret")) is True


def test_verify_password_wrong_password_false():
    """잘못된 비밀번호는 False 를 반환한다."""
    assert verify_password("wrong", hash_password("s3cret")) is False


def test_hash_password_uses_random_salt():
    """동일 평문의 두 해시는 랜덤 salt 로 서로 다르다."""
    assert hash_password("x") != hash_password("x")


def test_verify_password_malformed_hash_returns_false():
    """잘못된 형식의 해시는 예외 없이 False 를 반환한다."""
    assert verify_password("x", "not-a-valid-hash") is False
