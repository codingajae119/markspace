"""`ReferenceScanner` 단위 테스트 — 현재 버전 본문의 첨부 참조 판정 (Req 5.1·5.2).

`ReferenceScanner.is_referenced(content, attachment_id)` 는 문서 본문에 첨부 참조
URL 규약(`/attachments/{id}`, `AttachmentRead.url` 과 동일)이 등장하는지를 판정하는
순수 문자열 함수다. 핵심 관심사는 **첨부 id 경계 정확성**으로, `/attachments/12` 가
`/attachments/123` 을 오탐(부분 일치)하지 않아야 한다.

DB·파일 I/O·모델 없이 문자열만 다루므로 하네스/픽스처가 필요 없다.
"""

from __future__ import annotations

import pytest

from app.attachment.reference import ReferenceScanner


@pytest.fixture()
def scanner() -> ReferenceScanner:
    return ReferenceScanner()


# --- True: 참조 존재 -------------------------------------------------------


def test_reference_present_returns_true(scanner: ReferenceScanner) -> None:
    """본문에 `/attachments/{id}` 토큰이 있으면 True."""
    content = "본문 이미지: ![img](/attachments/12) 끝"
    assert scanner.is_referenced(content, 12) is True


def test_reference_at_end_of_string_returns_true(scanner: ReferenceScanner) -> None:
    """토큰이 문자열 끝에서 끝나면(뒤에 숫자 없음) True."""
    assert scanner.is_referenced("see /attachments/12", 12) is True


@pytest.mark.parametrize(
    "trailing",
    [" ", ")", '"', "]", "?query=1", "#frag", "\n", "\t", ".png", "/download"],
)
def test_reference_with_non_digit_boundary_returns_true(
    scanner: ReferenceScanner, trailing: str
) -> None:
    """id 뒤가 숫자가 아닌 임의 경계 문자면 True(공백·)·"·]·?·#·비숫자)."""
    content = f"x /attachments/12{trailing} y"
    assert scanner.is_referenced(content, 12) is True


# --- False: 참조 없음 / 경계 오탐 방지 -------------------------------------


def test_empty_content_returns_false(scanner: ReferenceScanner) -> None:
    assert scanner.is_referenced("", 12) is False


def test_no_reference_returns_false(scanner: ReferenceScanner) -> None:
    assert scanner.is_referenced("참조 없는 평범한 본문", 12) is False


def test_longer_id_does_not_match_shorter_scan(scanner: ReferenceScanner) -> None:
    """경계 오탐 방지(정방향): id 12 스캔이 `/attachments/123` 을 오탐하지 않는다."""
    content = "![img](/attachments/123)"
    assert scanner.is_referenced(content, 12) is False


def test_exact_longer_id_matches_itself(scanner: ReferenceScanner) -> None:
    """경계 오탐 방지(역방향): id 123 은 `/attachments/123` 을 정확히 매칭한다."""
    content = "![img](/attachments/123)"
    assert scanner.is_referenced(content, 123) is True


def test_shorter_id_prefix_does_not_match(scanner: ReferenceScanner) -> None:
    """`/attachments/1` 만 있을 때 id 12 스캔은 False(더 짧은 접두 불일치)."""
    content = "/attachments/1"
    assert scanner.is_referenced(content, 12) is False


def test_zero_padded_id_does_not_match(scanner: ReferenceScanner) -> None:
    """`/attachments/012` 는 리터럴 `/attachments/12` 부재이므로 id 12 스캔 False(방어)."""
    content = "/attachments/012"
    assert scanner.is_referenced(content, 12) is False


def test_multiple_references_only_target_id_counts(scanner: ReferenceScanner) -> None:
    """여러 참조가 섞여도 대상 id 경계 매칭만 True/False 를 결정한다."""
    content = "a /attachments/123 b /attachments/45 c /attachments/12 d"
    assert scanner.is_referenced(content, 12) is True
    assert scanner.is_referenced(content, 45) is True
    assert scanner.is_referenced(content, 1) is False
    assert scanner.is_referenced(content, 4) is False
