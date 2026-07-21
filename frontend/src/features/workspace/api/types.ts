/**
 * s18 워크스페이스 feature 도메인 계약 미러 타입.
 *
 * 백엔드 `app/workspace/schemas.py`·`app/admin_account/schemas.py` 의 요청/응답 스키마를
 * 정확히 미러링한다. 공통 엔벨로프 `Page<T>` 와 응답 타입 `WorkspaceRead` 는 s16 소유이므로
 * 여기서 재정의하지 않고 import 만 하며, 다운스트림 편의를 위해 재-export 한다.
 * (Req 2.1·3.1·4.1·5.1·6.1·8.1)
 */
import type { Page } from "@/shared/types/page";
import type { WorkspaceRead } from "@/shared/types/workspace";

// s16 소유 타입 재-export (형태 재정의 없음, import 만) — 다운스트림 소비 편의용.
export type { Page, WorkspaceRead };

/**
 * 멤버 role 의 API 직렬화용 문자열 유니온 — 백엔드 `MemberRole`(str Enum) 미러.
 *
 * 값은 백엔드 `workspace_member.role` ENUM(owner/member)과 동일하다.
 * 위계 비교용 s16 `Role`(enum, MEMBER<OWNER)과는 별개다: 권한 게이팅에는
 * `Role` 을, 요청/응답 직렬화에는 이 `MemberRole` 을 사용한다.
 */
export type MemberRole = "owner" | "member";

/**
 * 워크스페이스 생성 요청 본문 — 백엔드 `WorkspaceCreate` 미러 (Req 2.1).
 *
 * `name` 만 받는다. `is_shareable`·`trash_retention_days` 는 서버가 기본값으로 채운다.
 */
export interface WorkspaceCreate {
  name: string;
}

/**
 * 워크스페이스 부분 갱신 요청 본문 — 백엔드 `WorkspaceUpdate` 미러 (Req 2.1).
 *
 * name·is_shareable·trash_retention_days 를 선택적으로 갱신한다.
 */
export interface WorkspaceUpdate {
  name?: string;
  is_shareable?: boolean;
  trash_retention_days?: number;
}

/**
 * 멤버십 응답용 정보 — 백엔드 `MemberRead`(ORMReadModel) 미러 (Req 3.1).
 *
 * 백엔드 스키마는 타임스탬프를 노출하지 않는다(TimestampedRead 미상속).
 */
export interface MemberRead {
  id: number;
  workspace_id: number;
  user_id: number;
  role: MemberRole;
}

/**
 * 멤버 추가 요청 본문 — 백엔드 `MemberCreate` 미러 (Req 3.1).
 */
export interface MemberCreate {
  user_id: number;
  role: MemberRole;
}

/**
 * 멤버 role 변경 요청 본문 — 백엔드 `MemberUpdate` 미러 (Req 3.1).
 */
export interface MemberUpdate {
  role: MemberRole;
}

/**
 * 계정 응답용 사용자 정보 — 백엔드 `UserRead`(TimestampedRead) 미러 (Req 8.1).
 *
 * created_at·updated_at 은 ISO 8601 문자열로 직렬화되며 updated_at 은 null 가능하다.
 * `password_hash` 등 민감 필드는 백엔드에서 노출되지 않는다.
 */
export interface UserRead {
  id: number;
  created_at: string;
  updated_at: string | null;
  login_id: string;
  name: string;
  email: string | null;
  is_admin: boolean;
  is_active: boolean;
  is_deleted: boolean;
}

/**
 * 신규 사용자 생성 요청 본문 — 백엔드 `UserCreate` 미러 (Req 8.1).
 *
 * login_id·password·name 필수, email 선택. 상태 flag·is_admin 은 입력받지 않는다.
 */
export interface UserCreate {
  login_id: string;
  password: string;
  name: string;
  email?: string | null;
}

/**
 * 계정 부분 갱신 요청 본문 — 백엔드 `UserUpdate` 미러 (Req 8.1).
 *
 * name·email·is_active·is_deleted 를 선택적으로 갱신한다. is_admin 은 포함하지 않는다.
 */
export interface UserUpdate {
  name?: string;
  email?: string | null;
  is_active?: boolean;
  is_deleted?: boolean;
}

/**
 * 워크스페이스 멤버 로스터 행 — 백엔드 `MemberRosterRead`(BaseModel) 미러 (s25 Req 1.2).
 *
 * `GET /workspaces/{id}/members` 응답 항목으로, 멤버 사용자 식별자·이름·이메일·role 을 노출한다
 * (`MemberRead` 와 달리 user 표시 정보 name·email 을 결합해 로스터 표시에 사용). email 은 null 가능.
 */
export interface MemberRosterRow {
  user_id: number;
  name: string;
  email: string | null;
  role: MemberRole;
}

/**
 * 배정 가능 사용자 응답용 narrow 정보 — 백엔드 `AssignableUserRead`(ORMReadModel) 미러 (s23 Req 3.1).
 *
 * `GET /workspaces/{id}/assignable-users` 응답 항목으로, 식별자·이름·이메일만 노출한다
 * (`login_id`·상태 플래그·타임스탬프 등은 백엔드 스키마에서 직렬화 대상이 아님). email 은 null 가능.
 */
export interface AssignableUser {
  id: number;
  name: string;
  email: string | null;
}

/**
 * admin 비밀번호 재설정 요청 본문 — 백엔드 `AdminPasswordResetRequest` 미러 (Req 8.1).
 */
export interface AdminPasswordResetRequest {
  new_password: string;
}

/**
 * admin 소유권 변경 요청 본문 — 백엔드 `OwnerChangeRequest` 미러 (Req 5.1).
 */
export interface OwnerChangeRequest {
  new_owner_user_id: number;
}
