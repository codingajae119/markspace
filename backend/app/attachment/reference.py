"""참조 판정 — `ReferenceScanner`
(design.md §Components and Interfaces #ReferenceScanner, Feature/Service).

문서 현재 버전 본문(markdown)에 첨부 참조 URL 규약(`/attachments/{id}`, `AttachmentRead.url`
과 동일)이 등장하는지를 판정하는 **순수 문자열 함수**다. 8.7 참조 소멸 아카이브 판정의 근거로만
쓰이며, DB·파일 I/O·모델·서비스에 의존하지 않고 표준 라이브러리(`re`)만 사용한다(Req 5.1·5.2).

규약(design.md §Responsibilities & Constraints):
- 참조 토큰은 `/attachments/{attachment_id}` 이며 본문 내 존재 여부만 판정한다.
- **id 경계 정확성**: `/attachments/12` 스캔이 `/attachments/123` 을 오탐(부분 일치)하지
  않아야 한다. id 뒤에 또 다른 숫자가 바로 이어지면 다른 첨부이므로, id 다음 문자가 숫자가
  아닐 때만(문자열 끝·공백·`)`·`"`·`]`·`?`·`#` 등 비숫자 경계) 매칭한다.
"""

from __future__ import annotations

import re


class ReferenceScanner:
    """현재 버전 본문의 첨부 참조 여부를 판정하는 순수 서비스."""

    def is_referenced(self, content: str, attachment_id: int) -> bool:
        """`content` 에 `/attachments/{attachment_id}` 참조 토큰이 존재하면 True.

        첨부 id 경계는 뒤따르는 숫자를 부정 전방탐색(`(?![0-9])`)으로 배제해
        `/attachments/12` 가 `/attachments/123` 를 오탐하지 않도록 한다. id 는 정수라
        `re.escape` 로 안전하게 이스케이프해 패턴에 삽입한다.
        """
        token = re.escape(f"/attachments/{attachment_id}")
        pattern = f"{token}(?![0-9])"
        return re.search(pattern, content) is not None
