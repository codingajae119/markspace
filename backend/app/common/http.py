"""공용 HTTP 응답 헬퍼 (교차 관심사 단일 소유 — s12 첨부 서빙·s14 링크 경유 서빙 공유).

첨부 바이너리를 스트리밍하는 라우터가 여럿(s12 인증 서빙·s14 공개 서빙)이며, 모두 원본
파일명을 ``Content-Disposition`` 헤더에 담아야 한다. 이 헤더 값 구성 로직을 각 라우터가
개별 복제하면(과거 s14 가 그러했듯) 한쪽만 안전 인코딩을 갖고 다른 쪽은 500 을 내는 divergence
가 발생한다. 그래서 안전 인코딩을 이 공용 모듈 한 곳에서 소유하고 모든 서빙 라우터가 소비한다.
"""

from urllib.parse import quote

__all__ = ["content_disposition_inline"]


def content_disposition_inline(filename: str) -> str:
    """비-ASCII 파일명도 안전한 inline ``Content-Disposition`` 헤더 값을 만든다(RFC 6266/5987).

    Starlette 는 응답 헤더 값을 **latin-1** 로 인코딩한다. 한글 등 비-latin-1 원본명을 그대로
    ``filename="..."`` 에 넣으면 전송 시 ``UnicodeEncodeError`` 로 500 이 난다(이미지가 무사한
    이유는 붙여넣기 이미지의 원본명이 통상 ASCII 라서일 뿐, kind 무관 파일명 인코딩 문제다).

    RFC 5987 ``filename*=UTF-8''`` 파라미터로 원본명을 UTF-8 percent-encoding 하고, 이 파라미터를
    모르는 구형 클라이언트를 위한 ASCII 폴백 ``filename="..."`` 을 함께 제공한다. 폴백은 비-ASCII·
    헤더를 깨뜨리는 문자(제어문자·``"``·``\\``)를 ``_`` 로 치환해 latin-1 안전성을 보장한다.
    """
    ascii_fallback = (
        "".join(c if (32 < ord(c) < 127 and c not in '"\\') else "_" for c in filename)
        or "download"
    )
    encoded = quote(filename, safe="")
    return f"inline; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"
