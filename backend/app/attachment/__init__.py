"""s12-attachment feature 모듈.

첨부·이미지 저장과 파일 생명주기(보관 이동·참조 소멸 아카이브)를 소유한다. s01 공용
계약(`attachment` 모델·Base Schemas·Settings)·s05 resolver·s07 문서→WS 어댑터를 소비하며
`s09`/`s10`/`s14` 를 import 하지 않고 하위 계층의 관측 가능한 결과(문서 status·현재 버전
참조)에만 의존한다(design.md §Dependency Direction).
"""
