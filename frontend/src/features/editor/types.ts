/**
 * s20 편집(editor) feature 도메인 계약 미러 + 프론트 파생 타입.
 *
 * 백엔드 `app/lock_version/schemas.py`(잠금/저장/버전)와 편집에 필요한
 * `app/document/schemas.py::DocumentRead` 부분집합을 정확히 미러링한다(s01 계약 소비).
 * 새 필드를 발명하지 않으며 필드 이름·형태는 실제 라우터/스키마와 1:1 로 대응한다. 공통
 * 엔벨로프 `Page<T>` 는 s16 소유이므로 여기서 재정의하지 않고 import 만 하며, 다운스트림
 * 소비 편의를 위해 재-export 한다.
 * (Req 1.1·1.2·2.1·3.1·6.1)
 *
 * `LockState`·`EditSessionStatus` 는 백엔드 응답이 아니라 편집 세션을 구동하기 위한 프론트
 * 파생 타입이다.
 */
import type { Page } from "@/shared/types/page";
import type { ApiError } from "@/shared/api/errors";

// s16 소유 타입 재-export (형태 재정의 없음, import 만) — 다운스트림 소비 편의용.
export type { Page };

/**
 * 편집 잠금 획득/보유 정보 응답 — 백엔드 `DocumentLockRead`(ORMReadModel 상속) 미러 (Req 1.1).
 *
 * `lock_acquired_at` 은 백엔드 `datetime` 의 ISO 문자열 직렬화 형태다. 잠금 판정 근거는
 * `document.lock_user_id` 단일 컬럼(INV-9)이며, 이 응답은 잠금이 설정된 상태를 표현한다.
 */
export interface DocumentLockRead {
  document_id: number;
  lock_user_id: number;
  lock_acquired_at: string; // ISO datetime
}

/**
 * 저장 버전 메타데이터 응답 — 백엔드 `DocumentVersionRead`(ORMReadModel 상속) 미러 (Req 5.1).
 *
 * 과거 본문 조회·rollback 미제공이므로 계약 그대로 **본문(content) 필드를 포함하지 않는다**.
 * 식별자·저장자·저장 시각 메타데이터만 노출한다. `created_at` 은 ISO 문자열이다. 목록은
 * `Page<DocumentVersionRead>` 로 반환된다.
 */
export interface DocumentVersionRead {
  id: number;
  document_id: number;
  created_by: number;
  created_at: string; // ISO datetime — 본문(content) 필드 없음(rollback 미제공)
}

/**
 * 저장 요청 본문 — 백엔드 `DocumentSaveRequest` 미러 (Req 2.1).
 *
 * 잠금 보유자가 저장할 markdown 본문 스냅샷을 담는다. `content` 는 필수이며 **빈 문자열을
 * 허용**한다(빈 문서 저장).
 */
export interface DocumentSaveRequest {
  content: string; // 빈 문자열 허용
}

/**
 * 편집에 필요한 문서 상세 부분집합 — 백엔드 `DocumentRead` 미러 (Req 1.3·3.1).
 *
 * 편집 진입 시 초기 콘텐츠(EditorWrapper edit 주입)·저장 낙관 갱신 판단에 필요한 필드만
 * 취한다. `content` 는 현재 버전 markdown 본문, `current_version_id` 는 현재 버전 식별자
 * (버전 없으면 null)다. 백엔드 `DocumentRead` 의 그 외 필드는 편집 경계에서 사용하지 않는다.
 */
export interface EditableDocument {
  id: number;
  workspace_id: number;
  title: string;
  content: string; // markdown 초기 콘텐츠(EditorWrapper edit 주입)
  current_version_id: number | null;
}

/**
 * 편집 진입 시 잠금 획득 결과의 프론트 파생 상태(응답 아님) (Req 1.1·1.5·6.1).
 *
 * - `acquiring`: 잠금 획득 요청 진행 중.
 * - `self`: 200 — 현재 사용자가 잠금을 보유(획득/멱등 재획득). `lock` 에 응답을 보존.
 * - `other`: 409 — 타인이 잠금을 보유. 게이팅·안내에 `error` 사용.
 * - `error`: 403/404 등 그 외 실패. `error` 에 정규화된 {@link ApiError} 보존.
 */
export type LockState =
  | { kind: "acquiring" }
  | { kind: "self"; lock: DocumentLockRead } // 200: 현재 사용자 보유
  | { kind: "other"; error: ApiError } // 409: 타인 보유
  | { kind: "error"; error: ApiError }; // 403/404 등

/**
 * 편집 세션 라이프사이클 상태(응답 아님) (Req 1.1·2.1·6.1).
 *
 * idle→acquiring→editing 진입, blocked(타인 잠금), saving(저장 중), released(이탈·해제),
 * error(획득/저장 실패) 로 전이한다.
 */
export type EditSessionStatus =
  | "idle"
  | "acquiring"
  | "editing"
  | "blocked"
  | "saving"
  | "released"
  | "error";
