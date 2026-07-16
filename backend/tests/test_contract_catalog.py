"""API 엔드포인트 카탈로그·스키마 규약 일관성 검증 (Requirement 6.1, 6.3, 6.4, 6.6).

이 테스트는 런타임 코드를 검증하지 않는다. `design.md` 의 "단일 API 계약 소스"인
### Contract / API Endpoint Catalog 마크다운 표를 파싱하여, 카탈로그가

- 8개 도메인(REQ-1~8)을 빠짐없이 열거하고(6.3),
- 각 엔드포인트가 요구 role·요청/응답 스키마·소유 spec(s02~s14)을 표기하며(6.1, 6.4),
- `{Resource}Create/Read/Update`(및 request DTO 규약) 명명 규약을 위반하지 않음(6.6/6.2)

을 기계적으로 확인한다. 문서가 회귀(소유 spec 누락·도메인 누락·규약 위반 스키마 추가)하면
이 테스트가 실패하도록 규칙을 도출해 인코딩한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 카탈로그 위치·파싱
# ---------------------------------------------------------------------------

# backend/tests/test_contract_catalog.py -> parents[2] == repo root
DESIGN_PATH = (
    Path(__file__).resolve().parents[2]
    / ".kiro"
    / "specs"
    / "s01-contract-foundation"
    / "design.md"
)

CATALOG_HEADING = "### Contract / API Endpoint Catalog"

HTTP_METHODS = {"GET", "POST", "PATCH", "DELETE", "PUT"}

# 도메인 그룹 헤더(REQ-1~8) — 8개 도메인이 모두 열거되었음을 증명한다.
EXPECTED_DOMAIN_HEADERS = {
    "인증·계정",       # REQ-1
    "Admin 계정관리",  # REQ-2
    "워크스페이스",     # REQ-3
    "문서 코어",        # REQ-4
    "잠금·버전",        # REQ-5
    "휴지통",           # REQ-6
    "첨부",             # REQ-8
    "공유",             # REQ-7
}

# 각 도메인의 동작을 소유하는 하위 spec(6.4). 이 집합이 모두 등장해야
# 8개 도메인의 엔드포인트가 빠짐없이 열거되었다고 볼 수 있다.
EXPECTED_OWNER_SPECS = {"s02", "s03", "s05", "s07", "s09", "s10", "s12", "s14"}

# 스키마 명명 규약(6.2): 요청 생성/수정/응답 및 request DTO.
ALLOWED_SCHEMA_SUFFIXES = ("Create", "Read", "Update", "Request")

OWNER_SPEC_RE = re.compile(r"^s(\d{2})$")
SCHEMA_TOKEN_RE = re.compile(r"Page\[[A-Za-z0-9]+\]|[A-Z][A-Za-z0-9]*")
SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")


@dataclass(frozen=True)
class Endpoint:
    num: int
    method: str
    path: str
    role: str
    request: str
    response: str
    owner: str
    req: str


def _split_cells(line: str) -> list[str]:
    """`| a | b | c |` -> ['a', 'b', 'c'] (양끝 파이프 제거 후 분할)."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _extract_catalog_lines(text: str) -> list[str]:
    """카탈로그 heading 이후 다음 `### ` heading 전까지의 표 라인만 수집."""
    lines = text.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.strip().startswith(CATALOG_HEADING)),
        None,
    )
    assert start is not None, (
        f"'{CATALOG_HEADING}' 섹션을 design.md 에서 찾지 못했다."
    )
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].lstrip().startswith("### ")
        ),
        len(lines),
    )
    return [ln for ln in lines[start + 1 : end] if ln.lstrip().startswith("|")]


def _parse_catalog(text: str) -> tuple[list[Endpoint], set[str]]:
    """카탈로그를 (엔드포인트 목록, 도메인 그룹 헤더 집합)으로 파싱."""
    endpoints: list[Endpoint] = []
    domain_headers: set[str] = set()

    for line in _extract_catalog_lines(text):
        cells = _split_cells(line)

        # 도메인 그룹 헤더: 단일 셀 행 (예: `| 인증·계정 |`).
        if len(cells) == 1:
            if cells[0]:
                domain_headers.add(cells[0])
            continue

        # 마크다운 구분선 행: 모든 셀이 `---` 형태.
        if all(SEPARATOR_CELL_RE.match(c) for c in cells if c):
            continue

        # 표 헤더 행: 첫 셀이 '#'.
        if cells[0] == "#":
            continue

        # 엔드포인트 데이터 행: 8개 셀, 첫 셀이 숫자.
        if len(cells) == 8 and cells[0].isdigit():
            endpoints.append(
                Endpoint(
                    num=int(cells[0]),
                    method=cells[1],
                    path=cells[2],
                    role=cells[3],
                    request=cells[4],
                    response=cells[5],
                    owner=cells[6],
                    req=cells[7],
                )
            )

    return endpoints, domain_headers


def _schema_tokens(cell: str) -> list[str]:
    """셀에서 sentinel 마커를 제거하고 스키마 식별자만 추출.

    Sentinel: `—`, `(없음)`, `(binary)`, `(multipart) ...`, `(공개)` 등 괄호 마커.
    `(multipart) AttachmentCreate` 처럼 마커와 스키마가 공존하면 스키마만 남긴다.
    """
    cleaned = re.sub(r"\([^)]*\)", "", cell)  # 괄호 마커 제거
    cleaned = cleaned.replace("—", "").strip()
    if not cleaned:
        return []
    return SCHEMA_TOKEN_RE.findall(cleaned)


def _schema_token_ok(token: str) -> bool:
    if token.startswith("Page["):
        inner = token[len("Page[") : -1]
        return inner.endswith("Read")
    return token.endswith(ALLOWED_SCHEMA_SUFFIXES)


# ---------------------------------------------------------------------------
# 파싱 픽스처 (모듈 스코프 1회 파싱)
# ---------------------------------------------------------------------------

_TEXT = DESIGN_PATH.read_text(encoding="utf-8") if DESIGN_PATH.exists() else ""
_ENDPOINTS, _DOMAIN_HEADERS = _parse_catalog(_TEXT) if _TEXT else ([], set())


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------


def test_design_document_exists() -> None:
    """계약 소스 design.md 가 예상 경로에 존재한다."""
    assert DESIGN_PATH.exists(), f"design.md 를 찾지 못했다: {DESIGN_PATH}"


def test_catalog_parsed_and_row_count() -> None:
    """카탈로그가 파싱되고 충분한(>=30) 엔드포인트 행을 가진다 (파싱 절단 방지, 6.1)."""
    assert _ENDPOINTS, "카탈로그에서 엔드포인트 행을 하나도 파싱하지 못했다."
    assert len(_ENDPOINTS) >= 30, (
        f"엔드포인트 행이 예상보다 적다({len(_ENDPOINTS)}개). 파싱 절단 또는 카탈로그 축소 의심."
    )


def test_endpoint_numbers_are_contiguous() -> None:
    """엔드포인트 # 가 1..N 연속이다 (중간 누락·중복·파싱 절단 방지)."""
    nums = [e.num for e in _ENDPOINTS]
    assert nums == list(range(1, len(nums) + 1)), (
        f"엔드포인트 번호가 1..N 연속이 아니다: {nums}"
    )


def test_all_eight_domains_are_enumerated() -> None:
    """8개 도메인(REQ-1~8)이 그룹 헤더와 소유 spec 양쪽으로 빠짐없이 열거된다 (6.3, 6.4)."""
    missing_headers = EXPECTED_DOMAIN_HEADERS - _DOMAIN_HEADERS
    assert not missing_headers, (
        f"카탈로그에 누락된 도메인 그룹 헤더: {missing_headers}"
    )

    owner_specs = {e.owner for e in _ENDPOINTS}
    missing_owners = EXPECTED_OWNER_SPECS - owner_specs
    assert not missing_owners, (
        f"카탈로그에 누락된 소유 spec(도메인 미열거): {missing_owners}"
    )


@pytest.mark.parametrize("endpoint", _ENDPOINTS, ids=lambda e: f"{e.num}:{e.method} {e.path}")
def test_every_endpoint_row_is_complete(endpoint: Endpoint) -> None:
    """각 엔드포인트 행이 method·path·role·request·response·소유 spec 을 모두 표기한다 (6.1, 6.4, 6.6)."""
    assert endpoint.method in HTTP_METHODS, (
        f"#{endpoint.num}: 알 수 없는 HTTP 메서드 '{endpoint.method}'"
    )
    assert endpoint.path.startswith("/"), (
        f"#{endpoint.num}: path 가 '/' 로 시작하지 않는다: '{endpoint.path}'"
    )
    assert endpoint.role, f"#{endpoint.num}: 요구 role 이 비어 있다."
    assert endpoint.request, f"#{endpoint.num}: Request 셀이 비어 있다."
    assert endpoint.response, f"#{endpoint.num}: Response 셀이 비어 있다."

    owner_match = OWNER_SPEC_RE.match(endpoint.owner)
    assert owner_match, (
        f"#{endpoint.num}: 소유 spec 형식이 s\\d\\d 가 아니다: '{endpoint.owner}'"
    )
    owner_idx = int(owner_match.group(1))
    assert 2 <= owner_idx <= 14, (
        f"#{endpoint.num}: 소유 spec s{owner_idx:02d} 가 s02~s14 범위 밖이다."
    )


@pytest.mark.parametrize("endpoint", _ENDPOINTS, ids=lambda e: f"{e.num}:{e.method} {e.path}")
def test_schema_names_follow_naming_convention(endpoint: Endpoint) -> None:
    """Request/Response 의 스키마 식별자가 명명 규약을 위반하지 않는다 (6.6/6.2).

    sentinel 마커(`—`, `(없음)`, `(binary)`, `(multipart)`, `(공개)`)는 무시하고,
    남은 PascalCase 식별자는 반드시 Create/Read/Update/Request 로 끝나거나
    `Page[...Read]` 봉투여야 한다. (예: `WorkspaceFoo` 추가 시 실패)
    """
    for cell in (endpoint.request, endpoint.response):
        for token in _schema_tokens(cell):
            assert _schema_token_ok(token), (
                f"#{endpoint.num}: 명명 규약 위반 스키마 '{token}' "
                f"(허용: {ALLOWED_SCHEMA_SUFFIXES} 접미사 또는 Page[...Read])"
            )


def test_convention_families_are_actually_present() -> None:
    """{Resource}Create/Read/Update 3종 규약이 카탈로그에 실제로 존재한다 (규칙 유의미성 보증)."""
    tokens: set[str] = set()
    for e in _ENDPOINTS:
        tokens.update(_schema_tokens(e.request))
        tokens.update(_schema_tokens(e.response))

    plain = {t for t in tokens if not t.startswith("Page[")}
    for suffix in ("Create", "Read", "Update"):
        assert any(t.endswith(suffix) for t in plain), (
            f"명명 규약 검증이 유의미하려면 '{suffix}' 스키마가 최소 1개 존재해야 한다."
        )
    # Page[...Read] 봉투 규약도 사용되고 있음을 확인.
    assert any(t.startswith("Page[") for t in tokens), (
        "목록 응답 Page[...Read] 봉투 규약이 카탈로그에 존재해야 한다."
    )
