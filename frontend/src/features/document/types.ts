/**
 * s19 문서(document) feature 도메인 계약 미러 타입.
 *
 * 백엔드 `app/document/schemas.py`·`app/trash/schemas.py` 의 요청/응답 스키마를 정확히
 * 미러링한다(s01 계약 소비). 새 필드를 발명하지 않으며 필드 이름·형태는 실제 라우터/스키마와
 * 1:1 로 대응한다. 공통 엔벨로프 `Page<T>` 는 s16 소유이므로 여기서 재정의하지 않고 import 만
 * 하며, 다운스트림 소비 편의를 위해 재-export 한다.
 * (Req 1.1·2.1·3.1·4.1·5.1·6.1·7.1·8.1)
 *
 * `sort_order` 규약: 백엔드에서 `Decimal` 이며 JSON 직렬화 형태가 문자열일 수 있으므로
 * **불투명 정렬 키**(string)로 취급한다. 프론트에서 값 재계산·산술은 금지한다(Req 1.7·6.6).
 */
import type { Page } from "@/shared/types/page";

// s16 소유 타입 재-export (형태 재정의 없음, import 만) — 다운스트림 소비 편의용.
export type { Page };

/**
 * 문서 상태 문자열 유니온 — 백엔드 `document.status` ENUM 미러.
 *
 * 값은 백엔드 `DocumentRead.status`(active/trashed/deleted)와 동일하다.
 */
export type DocumentStatus = "active" | "trashed" | "deleted";

/**
 * 문서 응답용 정보 — 백엔드 `DocumentRead`(TimestampedRead 상속) 미러 (Req 1.1).
 *
 * id·created_at·updated_at 은 s01 `TimestampedRead` 공통 필드다. `sort_order` 는 백엔드
 * `Decimal` 의 불투명 정렬 키(string, 산술 금지). `content` 는 현재 버전 markdown 본문,
 * `content_html` 은 안전 렌더 HTML 이다 — 뷰어는 이원화를 피하고자 `content` 를 사용하지만
 * 응답에는 두 필드가 모두 존재하므로 타입에서도 둘 다 유지한다.
 */
export interface DocumentRead {
  id: number;
  created_at: string;
  updated_at: string | null;
  workspace_id: number;
  parent_id: number | null;
  title: string;
  status: DocumentStatus;
  sort_order: string; // 백엔드 Decimal → 불투명 정렬 키(산술 금지)
  current_version_id: number | null;
  created_by: number;
  content: string; // markdown 본문(현재 버전)
  content_html: string; // 안전 렌더 HTML(뷰어는 이원화 금지 위해 content 사용)
}

/**
 * 문서/하위 문서 생성 요청 본문 — 백엔드 `DocumentCreate` 미러 (Req 1.1).
 *
 * `title` 필수(공백 전용 금지는 서버 검증). `parent_id` 가 없거나 null 이면 루트 문서,
 * 지정 시 해당 문서를 부모로 하는 하위 문서. status·sort_order·created_by 는 서버가 채운다.
 */
export interface DocumentCreate {
  title: string;
  parent_id?: number | null;
}

/**
 * 문서 부분 갱신 요청 본문 — 백엔드 `DocumentUpdate` 미러 (Req 3.1).
 *
 * `title` 만 선택적으로 갱신한다. 본문 내용·버전 저장은 s09 소유이므로 필드를 두지 않는다.
 */
export interface DocumentUpdate {
  title?: string;
}

/**
 * 문서 이동/재정렬 요청 본문 — 백엔드 `DocumentMoveRequest` 미러 (Req 4.1).
 *
 * `new_parent_id` 가 없거나 null 이면 루트로 이동, 지정 시 그 문서를 새 부모로 삼는다.
 * 두 형제 사이 삽입 기준은 `before_sibling_id`·`after_sibling_id` 로 지정한다.
 */
export interface DocumentMoveRequest {
  new_parent_id?: number | null;
  before_sibling_id?: number | null;
  after_sibling_id?: number | null;
}

/**
 * 휴지통 묶음 구성원 요약 — 백엔드 `TrashMemberRead`(ORMReadModel) 미러 (Req 6.1).
 *
 * 계층 파악에 필요한 최소 필드(id·parent_id·title)만 노출한다.
 */
export interface TrashMemberRead {
  id: number;
  parent_id: number | null;
  title: string;
}

/**
 * 휴지통 묶음 표시 스키마 — 백엔드 `TrashBundleRead`(ORMReadModel) 미러 (Req 6.1).
 *
 * `bundle_id` 는 s07 묶음 식별자(= root_document_id, 카탈로그 `{bundleId}`)와 동일하다.
 * `expires_at` 은 서버 산정 파생값(= trashed_at + 워크스페이스 trash_retention_days)이며
 * 문자열(ISO 8601)로 직렬화된다.
 */
export interface TrashBundleRead {
  bundle_id: number; // = root_document_id (카탈로그 {bundleId})
  root_document_id: number;
  root_title: string;
  workspace_id: number;
  trashed_at: string;
  expires_at: string; // 서버 산정 파생값(trashed_at + retention)
  member_count: number;
  members: TrashMemberRead[];
}

/**
 * 문서 트리 노드 — 프론트 파생 타입(응답 아님).
 *
 * 평면 `DocumentRead[]` 를 `parent_id` 로 부모-자식 연결한 트리 조립 결과다.
 */
export interface DocumentNode {
  doc: DocumentRead;
  children: DocumentNode[];
}

/**
 * 드래그&드롭 드롭 위치 — 프론트 파생 타입(응답 아님).
 *
 * 대상 노드 기준 안쪽(inside)·앞(before)·뒤(after) 삽입, 또는 루트(root)로의 이동을
 * 표현한다. `computeMoveTarget` 이 이를 `DocumentMoveRequest` 로 변환한다.
 */
export type DropPosition =
  | { kind: "inside"; targetId: number }
  | { kind: "before"; targetId: number }
  | { kind: "after"; targetId: number }
  | { kind: "root" };
