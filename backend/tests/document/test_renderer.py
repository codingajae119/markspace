"""MarkdownRenderer 안전 렌더 규약 단위 검증 (s07-document-core task 1.4).

requirements.md 2.2·2.3·2.5, design.md §Components and Interfaces #MarkdownRenderer,
§Security Considerations(markdown 렌더 XSS 방지) 검증:
- 일반 markdown(제목·굵게·목록·링크·코드)이 대응 HTML 로 렌더된다(2.2).
- 스크립트·이벤트 핸들러·위험 URL 을 포함한 입력이 새니타이즈되어 실행 불가 HTML 로
  출력된다(XSS 방지). 열람(2.2)·편집 preview(2.5) 가 공용하는 단일 규약이다.
- 빈/공백 입력은 예외 없이 빈/안전 HTML 을 반환한다(2.3).

DB 미접근 순수 함수 단위 테스트: fixture 없이 `MarkdownRenderer().render(...)` 직접 호출.
"""

import pytest

from app.document.renderer import MarkdownRenderer


@pytest.fixture()
def renderer() -> MarkdownRenderer:
    return MarkdownRenderer()


# --- 일반 markdown 렌더(2.2) ---------------------------------------------


def test_heading_renders_to_h1(renderer: MarkdownRenderer) -> None:
    html = renderer.render("# Title")
    assert "<h1>" in html
    assert "Title" in html


def test_bold_renders_to_strong(renderer: MarkdownRenderer) -> None:
    assert "<strong>" in renderer.render("**bold**")


def test_list_renders_to_list_items(renderer: MarkdownRenderer) -> None:
    html = renderer.render("- a\n- b")
    assert "<ul>" in html
    assert html.count("<li>") == 2


def test_code_renders_to_code_element(renderer: MarkdownRenderer) -> None:
    assert "<code>" in renderer.render("`inline`")


def test_safe_link_is_preserved(renderer: MarkdownRenderer) -> None:
    """안전한 https 링크는 보존되어야 한다(과도한 제거 금지)."""
    html = renderer.render("[ok](https://example.com)")
    assert "<a" in html
    assert 'href="https://example.com"' in html
    assert ">ok</a>" in html


# --- GFM 확장: 표·작업 목록·취소선(게스트 공개 뷰 content_html 렌더 정합) ----------


def test_table_renders_to_table_element(renderer: MarkdownRenderer) -> None:
    """GFM 표는 <table> 요소로 렌더된다(commonmark 기본은 리터럴 <p> 로 남김)."""
    html = renderer.render("| A | B |\n|---|---|\n| 1 | 2 |")
    assert "<table>" in html
    assert "<th>A</th>" in html
    assert "<td>1</td>" in html
    # 회귀 가드: 표가 리터럴 파이프 문단으로 남지 않는다.
    assert "<p>| A | B |" not in html


def test_unchecked_task_list_renders_disabled_checkbox(
    renderer: MarkdownRenderer,
) -> None:
    """미완료 작업 목록 `- [ ]` 은 disabled·unchecked 체크박스로 렌더된다."""
    html = renderer.render("- [ ] todo")
    assert "task-list-item" in html
    assert '<input' in html and 'type="checkbox"' in html
    assert "disabled" in html
    assert "checked" not in html
    # 회귀 가드: `[ ]` 리터럴 텍스트로 남지 않는다.
    assert "[ ] todo" not in html


def test_checked_task_list_renders_checked_checkbox(
    renderer: MarkdownRenderer,
) -> None:
    """완료 작업 목록 `- [x]` 은 checked 체크박스로 렌더된다."""
    html = renderer.render("- [x] done")
    assert "task-list-item" in html
    assert 'type="checkbox"' in html
    assert "checked" in html
    assert "[x] done" not in html


def test_strikethrough_renders_to_s_element(renderer: MarkdownRenderer) -> None:
    """GFM 취소선 `~~x~~` 은 <s> 요소로 렌더된다(에디터 Toast 정합)."""
    assert "<s>" in renderer.render("~~struck~~")


def test_soft_line_break_renders_as_br(renderer: MarkdownRenderer) -> None:
    """문단 내 소프트 줄바꿈은 <br> 로 렌더된다(에디터 Toast Viewer 와 정합, breaks=True)."""
    html = renderer.render("a\nb")
    assert "<br" in html


def test_pseudo_nested_list_lines_are_separated(
    renderer: MarkdownRenderer,
) -> None:
    """손번호 유사 중첩 목록(`2. …` 아래 `    2.1. …`)이 한 줄로 병합되지 않는다.

    CommonMark 상 `2.` 마커는 문단을 중단할 수 없어 하위 줄이 item 2 문단의 연속 줄이 되는데,
    breaks=True 로 각 줄이 <br> 로 분리되어 에디터 읽기 뷰와 동일하게 표시된다(회귀 가드).
    """
    html = renderer.render(
        "1. 개발 환경 설정\n"
        "2. 소스 코드 작성\n"
        "    2.1. 기능 구현\n"
        "    2.2. 버그 수정\n"
        "3. 최종 배포"
    )
    # 하위 줄이 <br> 로 분리되어 한 <li> 안에서 공백 병합(한 줄 표시)되지 않는다.
    assert "<br" in html
    assert "2.1. 기능 구현" in html and "2.2. 버그 수정" in html
    # 회귀 가드: 하위 줄이 공백으로 병합돼 "작성 2.1." 처럼 한 줄로 붙지 않는다.
    assert "소스 코드 작성 2.1." not in html


def test_standard_nested_ordered_list_nests(renderer: MarkdownRenderer) -> None:
    """표준 CommonMark 들여쓰기(3칸)·`1.`/`2.` 마커는 <ol> 중첩으로 렌더된다."""
    html = renderer.render(
        "1. 개발 환경 설정\n2. 소스 코드 작성\n   1. 기능 구현\n   2. 버그 수정\n3. 최종 배포"
    )
    # 중첩 <ol> 이 생성된다(바깥 1개 + 안쪽 1개 = 2개 이상).
    assert html.count("<ol>") >= 2


def test_injected_raw_input_is_inert(renderer: MarkdownRenderer) -> None:
    """사용자가 raw <input> 을 주입해도 이벤트 핸들러·name·value 는 제거되어 무력하다.

    작업 목록 체크박스를 위해 <input> 태그 자체는 allowlist 에 추가됐지만, 허용 속성은
    type/checked/disabled/class 뿐이라 폼 전송·JS 실행 어포던스가 없다(표시상 이슈만 가능).
    """
    html = renderer.render('<input type="text" name="x" value="y" onfocus="alert(1)">')
    lowered = html.lower()
    assert "onfocus" not in lowered
    assert 'name="x"' not in lowered
    assert 'value="y"' not in lowered


# --- XSS 새니타이즈(2.2 안전 처리·§Security) ------------------------------


def test_script_tag_is_removed(renderer: MarkdownRenderer) -> None:
    html = renderer.render("<script>alert(1)</script>")
    assert "<script" not in html.lower()
    assert "alert(1)" not in html or "<script" not in html.lower()


def test_script_tag_case_variant_is_removed(renderer: MarkdownRenderer) -> None:
    html = renderer.render("<SCRIPT>alert(1)</SCRIPT>")
    assert "<script" not in html.lower()


def test_event_handler_attribute_is_removed(renderer: MarkdownRenderer) -> None:
    html = renderer.render("<img src=x onerror=alert(1)>")
    assert "onerror" not in html.lower()


def test_javascript_url_in_markdown_link_is_neutralized(
    renderer: MarkdownRenderer,
) -> None:
    """위험 스킴 링크는 무력화된다: 실행 가능한 href 로 렌더되지 않는다."""
    html = renderer.render("[x](javascript:alert(1))")
    lowered = html.lower()
    assert 'href="javascript:' not in lowered
    assert "<a" not in lowered  # 링크로 승격되지 않고 무력화됨


def test_javascript_url_case_variant_is_neutralized(
    renderer: MarkdownRenderer,
) -> None:
    html = renderer.render("[x](JavaScript:alert(1))")
    lowered = html.lower()
    assert 'href="javascript:' not in lowered
    assert "<a" not in lowered


def test_javascript_url_in_inline_html_anchor_is_neutralized(
    renderer: MarkdownRenderer,
) -> None:
    html = renderer.render('<a href="javascript:alert(1)">c</a>')
    assert "javascript:" not in html.lower()


# --- 빈/공백 입력(2.3) ----------------------------------------------------


def test_empty_string_returns_safe_html(renderer: MarkdownRenderer) -> None:
    html = renderer.render("")
    assert isinstance(html, str)
    assert "<script" not in html.lower()


def test_whitespace_only_returns_safe_html(renderer: MarkdownRenderer) -> None:
    html = renderer.render("   \n\t  ")
    assert isinstance(html, str)
    assert "<script" not in html.lower()


# --- 단일 규약(2.5): 동일 입력 → 동일 출력 --------------------------------


def test_render_is_deterministic_shared_contract(
    renderer: MarkdownRenderer,
) -> None:
    """열람·preview 가 공용하는 단일 규약: 같은 입력은 항상 같은 안전 HTML."""
    source = "# H\n\n**b** and [l](https://ok.test)"
    assert renderer.render(source) == renderer.render(source)
