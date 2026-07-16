"""도메인 불변식 카탈로그(INV-1~12) 매핑 일관성 검증 (Requirement 7.1~7.7).

이 테스트는 런타임 코드를 검증하지 않는다. `design.md` 의
### Contract / Invariants Catalog (INV-1~12) 마크다운 표를 파싱하여, 카탈로그가

- INV-1~12 12개 불변식을 빠짐없이·중복 없이 열거하고(7.1),
- 각 불변식이 강제 계약 요소와 소유 spec 을 모두 표기하며(7.2, 7.7),
- 권한 불변식 INV-1·2·3 이 권한 resolver/세션 auth 계약과 연결되고(7.3),
- 물리 삭제 없음 INV-4 가 soft-delete 계약과 연결되며(7.4),
- 공유 무효화 INV-8 이 share_link 재발급 계약과 연결되고(7.6),
- bundle·휴지통 INV-10·11·12 가 status/trashed_at 계약과 연결됨(7.5)

을 기계적으로 확인한다. 문서가 회귀(불변식 행 누락·매핑 셀 공란화·권한/soft-delete/
share_link/status 링크 소실)하면 이 테스트가 실패하도록 규칙을 도출해 인코딩한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 카탈로그 위치·파싱
# ---------------------------------------------------------------------------

# backend/tests/test_contract_invariants.py -> parents[2] == repo root
DESIGN_PATH = (
    Path(__file__).resolve().parents[2]
    / ".kiro"
    / "specs"
    / "s01-contract-foundation"
    / "design.md"
)

CATALOG_HEADING = "### Contract / Invariants Catalog"

# 소유 spec 토큰(s01~s14). 매핑 존재 증명의 기준(7.2, 7.7).
OWNER_SPEC_RE = re.compile(r"s(\d{2})")
SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")


@dataclass(frozen=True)
class Invariant:
    num: int
    summary: str  # 요지
    contract: str  # 강제 계약 요소
    owner: str  # 강제/검증 소유

    @property
    def mapping_text(self) -> str:
        """계약 요소 + 소유 셀 결합 텍스트(키워드 매칭용)."""
        return f"{self.contract} || {self.owner}"


def _split_cells(line: str) -> list[str]:
    """`| a | b | c |` -> ['a', 'b', 'c'] (양끝 파이프 제거 후 분할)."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _extract_catalog_lines(text: str) -> list[str]:
    """카탈로그 heading 이후 다음 `### ` heading 전까지의 표 라인만 수집.

    blockquote(`>`) 주석과 소개 문단은 `|` 로 시작하지 않으므로 자동 제외된다.
    """
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


def _parse_catalog(text: str) -> list[Invariant]:
    """불변식 카탈로그를 Invariant 목록으로 파싱(INV 번호가 정수인 데이터 행만)."""
    invariants: list[Invariant] = []

    for line in _extract_catalog_lines(text):
        cells = _split_cells(line)

        # 마크다운 구분선 행: 모든 셀이 `---` 형태.
        if cells and all(SEPARATOR_CELL_RE.match(c) for c in cells if c):
            continue

        # 표 헤더 행: 첫 셀이 'INV'.
        if cells and cells[0] == "INV":
            continue

        # 불변식 데이터 행: 4개 셀, 첫 셀이 숫자.
        if len(cells) == 4 and cells[0].isdigit():
            invariants.append(
                Invariant(
                    num=int(cells[0]),
                    summary=cells[1],
                    contract=cells[2],
                    owner=cells[3],
                )
            )

    return invariants


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(kw.lower() in low for kw in keywords)


# ---------------------------------------------------------------------------
# 파싱 픽스처 (모듈 스코프 1회 파싱)
# ---------------------------------------------------------------------------

_TEXT = DESIGN_PATH.read_text(encoding="utf-8") if DESIGN_PATH.exists() else ""
_INVARIANTS = _parse_catalog(_TEXT) if _TEXT else []
_BY_NUM = {inv.num: inv for inv in _INVARIANTS}


# ---------------------------------------------------------------------------
# 테스트
# ---------------------------------------------------------------------------


def test_design_document_exists() -> None:
    """계약 소스 design.md 가 예상 경로에 존재한다."""
    assert DESIGN_PATH.exists(), f"design.md 를 찾지 못했다: {DESIGN_PATH}"


def test_all_twelve_invariants_enumerated() -> None:
    """INV-1~12 가 빠짐없이·중복 없이 정확히 12개 열거된다 (7.1).

    행이 누락되면 집합이 {1..12} 와 달라져 실패한다. 중복이 있으면
    파싱 개수(12)와 고유 번호 집합 크기가 어긋나 실패한다.
    """
    nums = [inv.num for inv in _INVARIANTS]
    assert len(nums) == 12, (
        f"불변식 데이터 행이 정확히 12개가 아니다({len(nums)}개). 파싱 절단·행 누락·중복 의심."
    )
    assert set(nums) == set(range(1, 13)), (
        f"INV 번호 집합이 {{1..12}} 와 다르다: {sorted(nums)}"
    )
    assert len(set(nums)) == 12, f"INV 번호에 중복이 있다: {sorted(nums)}"


@pytest.mark.parametrize("num", range(1, 13))
def test_each_invariant_maps_contract_element_and_owner(num: int) -> None:
    """각 불변식이 강제 계약 요소와 소유 spec 을 모두(비공란) 표기한다 (7.2, 7.7).

    강제 계약 요소 셀 또는 소유 셀이 공란화되면 실패한다. 소유 셀은
    최소 하나의 s\\d\\d 토큰(소유 spec)을 포함해야 한다(매핑 존재 증명).
    """
    inv = _BY_NUM.get(num)
    assert inv is not None, f"INV-{num} 데이터 행이 카탈로그에 없다."
    assert inv.summary, f"INV-{num}: 요지 셀이 비어 있다."
    assert inv.contract, f"INV-{num}: 강제 계약 요소 셀이 비어 있다."
    assert inv.owner, f"INV-{num}: 강제/검증 소유 셀이 비어 있다."

    owner_specs = OWNER_SPEC_RE.findall(inv.owner)
    assert owner_specs, (
        f"INV-{num}: 소유 셀에 s\\d\\d 소유 spec 토큰이 없다: '{inv.owner}'"
    )
    for spec in owner_specs:
        idx = int(spec)
        assert 1 <= idx <= 14, (
            f"INV-{num}: 소유 spec s{spec} 가 s01~s14 범위 밖이다."
        )


@pytest.mark.parametrize("num", [1, 2, 3])
def test_permission_invariants_link_resolver_or_auth(num: int) -> None:
    """권한 불변식 INV-1·2·3 이 권한 resolver·세션 auth 계약과 연결된다 (7.3).

    s01 은 모든 행에 등장하므로(자명) 키워드에서 제외한다. resolver /
    require_ws_role / AuthContext / is_admin / auth 등 실제 권한·인증 계약
    토큰을 요구하여, 링크가 소실되면(예: 계약 셀을 스키마 컬럼만으로 교체)
    실패하도록 한다.
    """
    inv = _BY_NUM[num]
    permission_tokens = (
        "resolver",
        "PermissionResolver",
        "require_ws_role",
        "AuthContext",
        "is_admin",
        "auth",
    )
    assert _has_keyword(inv.mapping_text, permission_tokens), (
        f"INV-{num}: 권한 resolver/auth 계약 링크를 찾지 못했다. "
        f"계약='{inv.contract}' 소유='{inv.owner}'"
    )


def test_inv4_links_soft_delete() -> None:
    """물리 삭제 없음 INV-4 가 soft-delete 상태 컬럼 계약과 연결된다 (7.4)."""
    inv = _BY_NUM[4]
    soft_delete_tokens = ("soft-delete", "is_deleted", "status", "is_archived")
    assert _has_keyword(inv.mapping_text, soft_delete_tokens), (
        f"INV-4: soft-delete 계약 링크를 찾지 못했다. "
        f"계약='{inv.contract}' 소유='{inv.owner}'"
    )


def test_inv8_links_share_link() -> None:
    """공유 무효화 INV-8 이 share_link·재발급 계약과 연결된다 (7.6)."""
    inv = _BY_NUM[8]
    share_tokens = ("share_link", "is_enabled", "재발급")
    assert _has_keyword(inv.mapping_text, share_tokens), (
        f"INV-8: share_link 재발급 계약 링크를 찾지 못했다. "
        f"계약='{inv.contract}' 소유='{inv.owner}'"
    )


@pytest.mark.parametrize("num", [10, 11, 12])
def test_bundle_trash_invariants_link_status_trashed_at(num: int) -> None:
    """bundle·휴지통 불변식 INV-10·11·12 가 status/trashed_at 계약과 연결된다 (7.5)."""
    inv = _BY_NUM[num]
    status_tokens = ("status", "trashed_at", "bundle", "묶음")
    assert _has_keyword(inv.mapping_text, status_tokens), (
        f"INV-{num}: status/trashed_at/bundle 계약 링크를 찾지 못했다. "
        f"계약='{inv.contract}' 소유='{inv.owner}'"
    )
