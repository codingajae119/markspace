/**
 * s21 첨부(attachment) feature 도메인 계약 미러 타입.
 *
 * 백엔드 `app/attachment/schemas.py` 의 응답 스키마(`AttachmentRead`·`AttachmentKind`)를
 * 정확히 미러링한다(s01 계약 소비). 새 필드를 발명하지 않으며 필드 이름·형태는 실제
 * 스키마와 1:1 로 대응한다. 공통 에러 계약 `ApiError` 는 s16 소유이므로 여기서 재정의하지
 * 않고 import 만 한다.
 * (Req 1.1·2.1·3.1·5.1·7.1)
 *
 * `url` 규약: `AttachmentRead.url`(`/attachments/{id}`)은 ORM 컬럼이 아니라 서버가 응답 시
 * 산정하는 **파생 참조값**(문서 본문에서의 안정 참조)이다. 프론트에서 재구성·재계산하지 않고
 * 서버가 준 문자열을 그대로 취급한다(Req 1.1).
 */
import type { ApiError } from "@/shared/api/errors";

/**
 * 첨부 종류 문자열 유니온 — 백엔드 `AttachmentKind`(str Enum) 미러.
 *
 * 값은 백엔드 s01 `attachment.kind` ENUM(image/file)과 동일하다.
 */
export type AttachmentKind = "image" | "file";

/**
 * 첨부 메타데이터 응답 — 백엔드 `AttachmentRead`(ORMReadModel 상속) 미러 (Req 1.1·7.1).
 *
 * 바이너리가 아닌 메타데이터 응답이다. `created_at` 은 백엔드 `datetime` 의 ISO 8601 문자열
 * 직렬화 형태이므로 string 으로 취급한다. `url` 은 서버 산정 파생값(`/attachments/{id}`)이며
 * 프론트에서 재구성하지 않는다.
 */
export interface AttachmentRead {
  id: number;
  workspace_id: number;
  document_id: number;
  kind: AttachmentKind;
  original_name: string;
  is_archived: boolean;
  created_at: string; // 백엔드 datetime → ISO 8601 문자열
  url: string; // = "/attachments/{id}" (문서 본문 참조 규약, 서버 산정 파생값·재구성 금지)
}

/**
 * 업로드 자리표시자 진행 상태 — 프론트 파생 타입(응답 아님).
 *
 * 낙관적 업로드 자리표시자가 거치는 단계(진행/성공/실패)를 표현한다.
 */
export type UploadStatus = "uploading" | "done" | "error";

/**
 * 업로드 자리표시자 추적 항목 — 프론트 파생 타입(응답 아님) (Req 2.1).
 *
 * 동시 업로드를 독립 추적하기 위한 낙관 상태 단위다. `attachment` 는 성공 시 서버 응답으로
 * 채워지고(그 전엔 null), `error` 는 실패 시 정규화된 `ApiError` 로 채워진다(그 외 null).
 */
export interface UploadItem {
  uploadId: string; // 낙관 자리표시자 토큰 키(동시 업로드 독립 추적)
  status: UploadStatus;
  fileName: string;
  attachment: AttachmentRead | null; // 성공 시 채워짐
  error: ApiError | null; // 실패 시 채워짐
}

/**
 * 첨부 리소스(서빙) 로딩 상태 — 프론트 파생 판별 유니온(응답 아님) (Req 3.1·5.1).
 *
 * 인증 서빙 요청의 로딩 결과를 판별 태그(`status`)로 표현한다.
 * - `loading`: 요청 진행 중.
 * - `ready`: 서빙 성공(blob object URL·종류·표시 이름 확보).
 * - `unavailable`: 404/403 → 안전 placeholder 로 폴백(참조 소멸·권한 없음).
 * - `error`: 일시 오류(재시도 여지) — 정규화된 `ApiError` 보존.
 */
export type AttachmentResourceState =
  | { status: "loading" }
  | { status: "ready"; objectUrl: string; kind: AttachmentKind; fileName: string }
  | { status: "unavailable"; reason: "not_found" | "forbidden" }
  | { status: "error"; error: ApiError };
