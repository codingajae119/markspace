"""문서 상태 전이 엔진 — `DocumentStateEngine`·`Bundle`
(design.md §Components and Interfaces #DocumentStateEngine).

삭제·복구·완전삭제·묶음 식별을 담는 **상태 전이 단일 구현**이다. active → trashed 삭제
캐스케이드(그 시점 active 하위만 포착·공통 trashed_at·이미 trashed 하위 제외, 비흡수),
trashed → active 복구 primitive(부모 상태 기준 복귀 위치·sort_order 원위치 복원·자동 재중첩
없음), trashed → deleted 완전삭제 primitive(묶음 단위 원자적 전이), 묶음 식별·열거(묶음 =
루트 문서 id), active 하위 집합 질의를 소유한다. 잠금과 무관하게 전이하며 lock 값은 설정하지
않는다(상태·잠금 독립).

`Bundle` DTO 와 `DocumentStateEngine` primitive 의 실제 구현은 후속 task 3.1~3.4 의 소유다.
이 모듈은 현재 import 가능한 골격이며, 상태 전이·묶음 규칙의 유일 소유자로서 s10/s14 가 이
primitive 를 호출만 하고 규칙을 재구현하지 않는다.
"""
