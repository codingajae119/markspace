# Research & Design Decisions — s05-workspace

## Summary
- **Feature**: `s05-workspace`
- **Discovery Scope**: Extension (기존 `s01-contract-foundation` 계약·인프라 위에 워크스페이스 도메인 동작을 채움)
- **Key Findings**:
  - `s01` 권한 resolver는 `workspace_member` 데이터가 없으면 admin만 통과한다. 이 spec이 그 데이터를
    소유·채워 resolver를 실동작시키는 것이 핵심 가치다(INV-1·2·3 실동작).
  - `workspace`·`workspace_member`에는 `s01` 스키마상 soft-delete 컬럼이 없다(INV-4는 user/document/
    attachment만 대상). 따라서 워크스페이스·멤버십 삭제는 물리 삭제로 설계한다(계약 변경 없이 수용 가능).
  - admin 소유권 변경 엔드포인트(카탈로그 행 9)는 s03가 명시적으로 이양했다. 이 spec이 소유를 확정한다.

## Research Log

### 권한 resolver 실동작 경계 (s01 ↔ s05)
- **Context**: 브리프가 "s01 권한 resolver를 실제 role 조회로 채우고"를 요구한다. resolver 로직 재정의는
  계약 위반이므로 경계를 명확히 해야 한다.
- **Sources Consulted**: `s01/design.md` Common/Permissions(`WorkspaceRoleResolver`, `require_ws_role`,
  "실제 멤버십 데이터는 s05가 채운다"), `docs/projects.md` §1.2 권한표·§5 INV-1·2·3, steering `structure.md`
  (권한 검사 공통 레이어 단일 구현 원칙).
- **Findings**:
  - `s01`이 owner ≥ editor ≥ viewer 위계 비교와 admin bypass(`has_at_least`)를 소유한다. 이 로직은 재정의하지 않는다.
  - resolver가 판정 근거로 삼는 `workspace_member` 행은 s05가 생성·갱신·삭제한다. s05는 멤버십 role
    조회를 리포지토리로 제공하고, resolver는 그 데이터(= `workspace_member` 테이블)를 읽는다.
- **Implications**: s05는 resolver의 **데이터 소스**와 자기 라우터용 `workspace_id` 추출 어댑터만 소유한다.
  resolver 비교·bypass 코드는 s01 소유로 남긴다. 통합 검증에서 "멤버십 생성 후 `require_ws_role`이 실제
  role로 게이팅됨"을 확인한다.

### 워크스페이스·멤버십 삭제 방식 (물리 삭제 채택)
- **Context**: `DELETE /workspaces/{id}`(행 14)·`DELETE .../members/{uid}`(행 17)의 삭제 의미 확정 필요.
- **Sources Consulted**: `s01/design.md` Physical Data Model(workspace·workspace_member에 soft-delete
  컬럼 없음), `docs/projects.md` §5 INV-4(user/document/attachment 한정), steering `tech.md`(물리 삭제 없음은
  세 엔티티만).
- **Findings**: INV-4는 workspace·workspace_member를 포함하지 않는다. `s01` 스키마에도 두 테이블에
  `is_deleted`/status가 없다. soft-delete 컬럼을 추가하면 `s01` 스키마 계약 변경(전 체크포인트 재검증 유발)이 된다.
- **Selected Approach**: 워크스페이스·멤버십은 **물리 삭제**한다. 워크스페이스 삭제 시 그 워크스페이스의
  `workspace_member` 행을 먼저 제거한 뒤 워크스페이스 행을 제거(단일 트랜잭션)한다.
- **Trade-offs**: 계약 무변경·단순함을 얻는다. 단, s07+ 도입 후 문서를 가진 워크스페이스 삭제는 FK
  RESTRICT로 제약되므로, 문서가 있는 워크스페이스 삭제 정책은 s07 이후 재검토 대상(revalidation note).
  L2 시점에는 문서가 없어 이 경계는 트리비얼하게 성립한다.

### admin 소유권 변경 의미 (upsert-to-owner)
- **Context**: REQ-2.7 "admin이 owner를 변경" + 복수 owner 허용(3.6) + 유일 owner 소실(3.7)에서 의미 확정.
- **Alternatives Considered**:
  1. 기존 owner 전원 강등 후 지정 사용자만 owner — 복수 owner 허용 원칙(3.6)과 충돌.
  2. 지정 사용자를 owner로 보장(멤버면 role=owner 갱신, 아니면 owner 멤버 신규 등록), 기존 owner는 유지.
- **Selected Approach**: (2) upsert-to-owner. 3.7의 목적(소유자 없는 워크스페이스에 새 owner 지정)을
  충족하면서 복수 owner 허용과 정합한다. 기존 owner 강등은 일반 멤버십 role 변경(owner 자신 또는 다른 owner가 수행)으로 처리.
- **Rationale**: docs 문언("소유권을 갱신")을 만족하며 최소 놀람 원칙. 강등까지 강제하면 다중 owner 협업이 깨진다.
- **Follow-up**: `OwnerChangeRequest`는 `new_owner_user_id` 단일 필드. 대상 사용자·워크스페이스 부재는 404.

### admin 전용 게이트 (feature-local, s01 단일 출처 소비)
- **Context**: 행 9는 요구 role이 admin(owner 아님)이다. `require_ws_role(OWNER)`는 워크스페이스 owner도
  통과시키므로 부적합하다. admin-only 게이트가 필요하다.
- **Findings**: `s01`은 admin bypass가 포함된 `require_ws_role`만 제공하고 순수 admin-only 게이트는 두지 않았다.
  s03가 이미 `require_admin`(feature-local, `AuthContext.is_admin` 3줄 가드)을 구현했다.
- **Selected Approach**: s05도 `app/workspace/dependencies.py`에 `s01` `AuthContext.is_admin`만 소비하는
  얇은 `require_admin` 가드를 둔다. 이는 워크스페이스 단위 권한 로직(resolver, structure.md의 단일 구현
  대상)이 아니라 3줄짜리 admin 플래그 검사이므로, 다른 feature 모듈을 import하는 결합보다 국소 재구현이 낫다.
- **Trade-offs**: s03·s05에 동일한 3줄 가드가 존재한다. 장래 계약 개정 시 `s01`으로 승격하면 통일 가능하나,
  지금 승격은 `s01` 계약 변경(전 체크포인트 재검증)을 유발하므로 보류한다.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Feature 모듈 + 레이어드 | `app/workspace/`에 schemas→repository→service→router 캡슐화 | s01·s03 패턴과 정합, 단일 책임, 병렬 구현 용이 | 없음(스택 재사용) | **채택** — structure.md 정렬 |
| resolver 로직 s05로 이전 | 위계·bypass 판정을 s05가 재구현 | 없음 | s01 계약 위반·중복·드리프트 | 기각 |
| workspace soft-delete 컬럼 추가 | is_deleted 추가로 삭제 표현 | INV-4 스타일 일관 | s01 스키마 계약 변경(전 체크포인트 재검증) | 기각 |

## Risks & Mitigations
- **Risk**: resolver 데이터 소스 경계가 모호하면 s01/s05 이중 소유가 생긴다 — **Mitigation**: s05는 데이터·
  멤버십 조회만, s01은 비교·bypass만. 통합 테스트로 실동작 확인.
- **Risk**: 워크스페이스 물리 삭제가 s07+ 문서와 충돌 — **Mitigation**: FK RESTRICT로 문서 보유 시 삭제 차단.
  s07 도입 시 삭제 정책 재검토(revalidation trigger에 기록).
- **Risk**: 유일 owner 제거로 소유자 없는 워크스페이스 발생 — **Mitigation**: 의도된 동작(docs 3.7),
  admin 소유권 변경으로 복구. 마지막 owner 제거를 막지 않는다.

## References
- 계약 단일 소스(스키마·에러·인증·resolver·카탈로그·불변식): `.kiro/specs/s01-contract-foundation/design.md`.
- 소유권 이양(행 9) 근거: `.kiro/specs/s03-admin-account/design.md` §Out of Boundary.
- 상위 근거: `docs/projects.md` §1.2, §2.2~2.3, §3 REQ-2.7·REQ-3·REQ-7.2, §5 INV-1·2·3·4·6.
