"""s14-sharing feature 모듈.

문서 단위 읽기 전용 공유 링크(발급·재발급·토글·공개 렌더·링크 경유 첨부 서빙·관측 기반
무효화 조정)를 소유하는 최상위(L6) 도메인이다. s01 공용 계약(`share_link` 모델·Base
Schemas·Settings)·s05 게이트(`is_shareable`)·resolver·s07 문서→WS 어댑터·`DocumentRepository`
·`DocumentStateEngine.active_descendants`·`MarkdownRenderer`·s12 첨부 서빙을 소비하며,
상태 전이·게이트 설정·첨부 저장·렌더 규약을 재구현하지 않는다. s14 는 최상위이므로 어떤
feature 도 s14 를 import 하지 않는다(design.md §Dependency Direction).
"""
