"""markdown 안전 렌더 규약 — `MarkdownRenderer`
(design.md §Components and Interfaces #MarkdownRenderer).

현재 버전 markdown 본문을 안전 HTML 로 렌더한다(열람 4.4·편집 preview 4.5 공용 단일 규약).
markdown 파싱 후 스크립트·이벤트 핸들러·위험 URL 을 제거하는 새니타이즈를 필수로 적용해
신뢰할 수 없는 본문을 안전 HTML 로 만든다(XSS 방지). 렌더/새니타이즈는 신규 외부 의존성
(markdown-it-py + nh3)을 사용한다.

`MarkdownRenderer.render` 의 실제 구현은 후속 task 1.4 의 소유다. 이 모듈은 현재 import 가능한
골격이며, 순수 렌더 규약만 소유한다(preview UI·본문 저장 s09 는 범위 밖).
"""
