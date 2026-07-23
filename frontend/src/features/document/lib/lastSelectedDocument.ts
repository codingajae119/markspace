/**
 * 워크스페이스별 "마지막 선택/편집 문서" 영속 (localStorage).
 *
 * 문서 트리의 선택(`selectedId`)은 `DocumentWorkspacePage` 의 컴포넌트-로컬 상태라, 편집 화면
 * (`/documents/:id/edit`)으로 이동하면 페이지가 언마운트되며 선택이 사라진다. "읽기로 돌아가기"
 * 버튼이든 헤더의 "문서" NavLink 든, 돌아오면 페이지는 새로 마운트되어 선택이 초기화된다. 두 진입
 * 경로 모두를 가로지르며 살아남는 seam 은 라우터 state 가 아니라 이 중립 영속 계층뿐이다(두
 * feature 는 서로 import 하지 않는다, s19/s20 Req 7.5).
 *
 * 스코프: 키를 **워크스페이스별**로 분리해 다른 WS 의 문서 id 가 교차 복원되지 않게 한다.
 * s16 `CURRENT_WORKSPACE_STORAGE_KEY` 와 동일한 `markspace.*` 접두 규약을 따른다.
 *
 * 견고성: localStorage 접근이 실패(사파리 프라이빗 모드 등)해도 선택 복원은 best-effort 이므로
 * 조용히 무시한다. 저장 값이 손상(비정수·음수)됐거나 현재 트리에 없는 id 는 소비 측(복원 시점)이
 * 트리 존재 검사로 걸러낸다.
 */

/** 마지막 문서 id 영속 키 접두. WS id 를 접미해 워크스페이스별로 분리한다. */
const STORAGE_PREFIX = "markspace.lastDocumentId.";

function keyFor(workspaceId: string): string {
  return `${STORAGE_PREFIX}${workspaceId}`;
}

/** 저장된 마지막 문서 id 를 읽는다. 없음·손상·접근불가 시 null. */
export function readLastDocumentId(workspaceId: string): number | null {
  try {
    const raw = localStorage.getItem(keyFor(workspaceId));
    if (raw === null || raw === "") {
      return null;
    }
    const id = Number(raw);
    return Number.isInteger(id) && id > 0 ? id : null;
  } catch {
    return null;
  }
}

/** 마지막 문서 id 를 저장한다. 접근불가 시 조용히 무시(best-effort). */
export function writeLastDocumentId(workspaceId: string, documentId: number): void {
  try {
    localStorage.setItem(keyFor(workspaceId), String(documentId));
  } catch {
    // storage 불가: 복원은 선택 편의일 뿐이므로 무시한다.
  }
}
