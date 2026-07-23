"""markdown 안전 렌더 규약 — `MarkdownRenderer`
(design.md §Components and Interfaces #MarkdownRenderer, §Security Considerations).

현재 버전 markdown 본문을 안전 HTML 로 렌더한다(열람 2.2·편집 preview 2.5 공용 단일 규약).
markdown 파싱 후 스크립트·이벤트 핸들러·위험 URL 을 제거하는 새니타이즈를 필수로 적용해
신뢰할 수 없는 본문을 안전 HTML 로 만든다(XSS 방지). 열람 응답의 `content_html` 과 편집 화면
preview 가 동일 규약을 공용하므로 렌더는 순수·결정적이다(2.5).

렌더/새니타이즈는 외부 의존성(markdown-it-py + mdit-py-plugins + nh3)을 사용한다. markdown-it 는
원시 인라인/블록 HTML 을 그대로 통과시키므로(commonmark 프리셋 `html=True`) 렌더 escaping 에만
의존하지 않고, 렌더 산출 HTML 을 nh3 새니타이저 allowlist 로 한 번 더 통과시키는 2단계
파이프라인으로 방어한다. **실질적 XSS 방어선은 nh3 새니타이즈**이며, 규약 자체는 특정 라이브러리에
종속되지 않는다.

GFM 확장(에디터가 소비하는 Toast UI Editor 와의 렌더 정합): 기본 commonmark 프리셋은 표·취소선·
작업 목록을 파싱하지 않으므로 게스트 공개 뷰(`content_html` 소비)에서 표가 리터럴 텍스트로,
`[ ]`/`[x]` 가 원문 그대로 노출됐다. 이를 해소하기 위해 표(`table`)·취소선(`strikethrough`) 규칙을
켜고 작업 목록(`tasklists_plugin`)을 활성화한다. 작업 목록 체크박스(`<input type=checkbox>`)는
nh3 기본 allowlist 가 제거하므로 아래에서 `<input>` 을 무력(inert) 속성만으로 허용 확장한다.

이 모듈은 순수 렌더 규약만 소유한다(preview UI·본문 저장 s09 는 범위 밖, 신규 엔드포인트 없음).
"""

from __future__ import annotations

import nh3
from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin

# nh3 기본 allowlist 를 확장한 GFM 렌더용 allowlist.
#
# 표(table/thead/tbody/tr/th/td)는 nh3 기본 allowlist 에 이미 포함되므로 파서 규칙만 켜면 되고,
# 취소선(`<s>`)도 기본 허용 태그다. 유일한 확장 지점은 GFM 작업 목록 체크박스다: markdown-it 의
# tasklists 플러그인이 `<input type=checkbox disabled>` 로 렌더하는데 nh3 기본 allowlist 가 이를
# 제거해 체크 상태가 사라진다. 렌더러가 생성한 읽기 전용 체크박스를 살리기 위해 `<input>` 을
# `type/checked/disabled/class` 속성으로만 허용한다.
#
# SECURITY: 허용 속성에 이벤트 핸들러·`name`·`value` 가 없으므로, 사용자가 markdown 본문에 raw
# `<input>` 을 주입해도 폼 전송 대상·JS 실행 어포던스 없는 무력(inert) 태그로만 남는다(표시상
# 이슈일 뿐 실행 위험 없음). 스크립트·이벤트 핸들러·위험 URL 제거라는 실질적 XSS 방어는 nh3
# 기본 정책을 그대로 승계한다(아래 세트는 기본 allowlist 를 복제해 확장한 것).
_ALLOWED_TAGS: set[str] = set(nh3.ALLOWED_TAGS) | {"input"}
_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    tag: set(attrs) for tag, attrs in nh3.ALLOWED_ATTRIBUTES.items()
}
_ALLOWED_ATTRIBUTES["input"] = {"type", "checked", "disabled", "class"}
# 작업 목록 컨테이너/아이템의 클래스(`contains-task-list`·`task-list-item`)를 보존해
# prose.css 가 기본 디스크 불릿을 숨기고 체크박스를 정렬할 수 있게 한다.
_ALLOWED_ATTRIBUTES.setdefault("ul", set()).add("class")
_ALLOWED_ATTRIBUTES.setdefault("li", set()).add("class")


class MarkdownRenderer:
    """markdown 본문을 새니타이즈된 안전 HTML 로 렌더하는 단일 규약.

    2단계 파이프라인:
    1. markdown-it-py 로 markdown → HTML 렌더. GFM 정합을 위해 표·취소선 규칙을 켜고 작업
       목록 플러그인을 활성화한다(에디터 Toast UI 와 동일 문법 지원).
    2. nh3 새니타이저 allowlist 로 산출 HTML 을 통과시켜 `<script>` 태그·`onerror` 등 이벤트
       핸들러 속성·`javascript:` 등 위험 URL 스킴을 제거한다(실질적 XSS 방어선). 작업 목록
       체크박스(`<input>`)만 무력 속성으로 허용 확장한다.
    """

    def __init__(self) -> None:
        # commonmark 기반에 GFM 확장을 얹는다: 표·취소선 규칙 활성화 + 작업 목록 플러그인.
        # (linkify 를 켜는 `gfm-like` 프리셋은 linkify-it-py 추가 의존성을 요구하므로 회피.)
        #
        # breaks=True: 소프트 줄바꿈(`\n`)을 `<br>` 로 렌더한다. 에디터 읽기 뷰(Toast Viewer)와의
        # 렌더 정합을 위한 것이다 — Toast 는 문단 내 소프트 줄바꿈을 `<br>` 로 렌더하는데,
        # markdown-it 기본값(breaks=False)은 공백으로 병합해 한 줄로 붙여 버린다. 특히 사용자가
        # `2. 항목` 아래에 `    2.1. 하위` 처럼 손으로 번호를 매긴 유사 중첩 목록은 CommonMark 상
        # `2.` 마커가 문단을 중단할 수 없어(오직 `1.` 만 가능) item 2 문단의 연속 줄이 되는데,
        # breaks=False 면 이 줄들이 공백으로 병합돼 한 줄로 표시된다. breaks=True 로 Toast 와 동일
        # 하게 각 줄을 `<br>` 로 분리한다(진짜 중첩은 표준 CommonMark 들여쓰기·마커로 써야 하며,
        # 그 경우 양쪽 파서가 동일하게 `<ol>` 중첩으로 렌더한다).
        self._md = (
            MarkdownIt("commonmark", {"breaks": True})
            .enable("table")
            .enable("strikethrough")
            .use(tasklists_plugin)
        )

    def render(self, markdown_text: str) -> str:
        """markdown 텍스트를 새니타이즈된 HTML 로 렌더한다.

        빈/공백 입력은 예외 없이 빈/안전 HTML 을 반환한다(2.3). 반환 HTML 에는 실행 가능한
        스크립트·이벤트 핸들러·위험 URL 이 남지 않는다(§Security).
        """
        if not markdown_text:
            return ""
        rendered = self._md.render(markdown_text)
        # 확장 allowlist: 기본 정책(위험 태그·핸들러·URL 제거)에 GFM 작업 목록 체크박스만 가산.
        return nh3.clean(
            rendered,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRIBUTES,
        )
