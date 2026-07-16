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
