"""워크스페이스 라우터용 의존성 (design.md §Feature/Dependency #WsIdAdapter).

경로 `{id}` 를 workspace_id 로 추출해 s01 `require_ws_role` 에 주입하는 얇은 어댑터를
소유한다. admin 게이트(`require_admin`)는 s01 공통을 소비하며 여기서 소유하지 않는다.
구현은 후속 task 에서 채운다.
"""
