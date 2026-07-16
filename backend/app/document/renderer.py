"""markdown 안전 렌더 규약 — `MarkdownRenderer`
(design.md §Components and Interfaces #MarkdownRenderer, §Security Considerations).

현재 버전 markdown 본문을 안전 HTML 로 렌더한다(열람 2.2·편집 preview 2.5 공용 단일 규약).
markdown 파싱 후 스크립트·이벤트 핸들러·위험 URL 을 제거하는 새니타이즈를 필수로 적용해
신뢰할 수 없는 본문을 안전 HTML 로 만든다(XSS 방지). 열람 응답의 `content_html` 과 편집 화면
preview 가 동일 규약을 공용하므로 렌더는 순수·결정적이다(2.5).

렌더/새니타이즈는 신규 외부 의존성(markdown-it-py + nh3)을 사용한다. markdown 라이브러리 자체의
escaping 에만 의존하지 않고, 렌더 산출 HTML 을 새니타이저 allowlist 로 한 번 더 통과시키는
2단계 파이프라인으로 이중 방어한다. 규약 자체는 특정 라이브러리에 종속되지 않는다.

이 모듈은 순수 렌더 규약만 소유한다(preview UI·본문 저장 s09 는 범위 밖, 신규 엔드포인트 없음).
"""

from __future__ import annotations

import nh3
from markdown_it import MarkdownIt


class MarkdownRenderer:
    """markdown 본문을 새니타이즈된 안전 HTML 로 렌더하는 단일 규약.

    2단계 파이프라인:
    1. markdown-it-py 로 markdown → HTML 렌더(기본 `html=False`: 원시 인라인 HTML 을
       escape 하고, `javascript:` 등 위험 스킴 링크는 링크로 만들지 않음).
    2. nh3 새니타이저 allowlist 로 산출 HTML 을 통과시켜 `<script>` 태그·`onerror` 등
       이벤트 핸들러 속성·`javascript:` 등 위험 URL 스킴을 제거(이중 방어, XSS 방지).
    """

    def __init__(self) -> None:
        # html=False(기본): 신뢰할 수 없는 원시 HTML 은 렌더 단계에서 escape 한다.
        self._md = MarkdownIt()

    def render(self, markdown_text: str) -> str:
        """markdown 텍스트를 새니타이즈된 HTML 로 렌더한다.

        빈/공백 입력은 예외 없이 빈/안전 HTML 을 반환한다(2.3). 반환 HTML 에는 실행 가능한
        스크립트·이벤트 핸들러·위험 URL 이 남지 않는다(§Security).
        """
        if not markdown_text:
            return ""
        rendered = self._md.render(markdown_text)
        # nh3 기본 allowlist: script/style 등 위험 태그, 이벤트 핸들러 속성, 위험 URL
        # 스킴을 제거하고 안전한 서식 태그(a·strong·h1·ul·code 등)는 보존한다.
        return nh3.clean(rendered)
