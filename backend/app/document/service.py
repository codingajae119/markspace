"""문서 구조 서비스 — `DocumentService`
(design.md §Components and Interfaces #DocumentService).

문서 생성·조회·목록·제목 수정·이동/재정렬·렌더 오케스트레이션을 소유하며, 상태 전이는
`DocumentStateEngine` 에 위임한다(9.1). 생성 시 부모 존재·active·동일 WS 검증과 형제 마지막
순서 `sort_order` 부여(초기 버전 생성 없음), 조회 응답에 현재 버전 본문(`content`)과
`MarkdownRenderer` 렌더 결과(`content_html`) 포함, 제목 부분 갱신, 이동/재정렬(순환 방지
INV-5·동일 WS INV-6·두 형제 사이 중간값 삽입)을 담당한다. `DocumentRead` 구성은 스키마의
`from_document` 파생 필드 경로를 따른다.

`DocumentService` 의 실제 구현은 후속 task 2.1~2.3 의 소유다. 이 모듈은 현재 import 가능한
골격이며, Service 는 active 구조만 다루고 상태 전이는 엔진만 수행한다.
"""
