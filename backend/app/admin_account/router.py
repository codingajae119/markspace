"""AdminUserRouter: 계정관리 4개 엔드포인트 (design.md §AdminUserRouter).

POST/GET /admin/users, PATCH/POST /admin/users/{id}[/password] 를 노출하며 전 라우트에
s01 common `require_admin` 게이트를 부착한다(재정의 없음). 구현은 task 3.1 에서 채운다.
"""
