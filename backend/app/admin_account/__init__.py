"""admin_account feature 모듈 (s03-admin-account).

단일 admin 이 사용자 계정 생명주기(생성·목록·삭제/비활동 flag·재활성화·비밀번호
재설정)를 수동 관리하는 동작을 캡슐화한다. s01 계약(user 모델·스키마 베이스·에러
모델·세션 인증·해싱 헬퍼·권한 게이트)을 재사용하며 어떤 계약 엔티티도 재정의하지 않는다
(design.md §Boundary Commitments).
"""
