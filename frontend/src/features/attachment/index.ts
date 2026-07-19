/**
 * s21 첨부(attachment) feature 소비 진입점 — 순수 re-export 배럴(비행동적).
 *
 * 이 feature 가 소유하는 첨부 UX **소비 표면**을 단일 진입점으로 노출한다:
 *  - 업로드 브리지(`useEditorUploadBridge`)와 렌더 브리지(`buildAttachmentRenderers`)를
 *    s20 편집 표면이 s16 `EditorWrapper` props(`onImagePaste`/`onFileDrop`/`onReady`·
 *    `renderers`)에 바인딩해 소비한다.
 *  - 렌더 컴포넌트(`AttachmentImage`/`AttachmentFileLink`/`AttachmentPlaceholder`)와
 *    resolver 를 s19 문서 읽기 뷰·s22 공유 뷰가 소비한다.
 *  - 공개 타입(`AttachmentRead`·`AttachmentKind`·업로드/리소스 파생 타입)을 소비자가 계약으로
 *    참조한다(백엔드 s12 스키마 미러, 재정의 금지).
 * (Req 6.6·7.3·7.4·7.5, design.md "File Structure Plan → index.ts"·"Boundary Commitments")
 *
 * ── 경계(비소유 명시) ─────────────────────────────────────────────────────────
 *  - 첨부 **저장·격리·아카이브 판정**은 백엔드 s12 소유다. 이 feature 는 서빙 결과(200/404/403)만
 *    관측하며 첨부 상태를 재판정하지 않는다.
 *  - **편집 생명주기**(편집 진입/이탈·lock·이탈 시 1회 자동저장·버전 스냅샷)와 에디터 표면·라우트는
 *    s20 소유다. 이 feature 는 콘텐츠에 참조를 삽입·렌더링하는 브리지 계약만 제공한다.
 *  - **공유 링크 경유 첨부 서빙**(`GET /public/{token}/attachments/{aid}`)은 s22 소유다.
 *  - 전역 401 은 s16 `apiClient` 인터셉터에 위임하며 이 feature 는 특수 처리하지 않는다(Req 6.3).
 *  - 이 배럴은 **다른 feature 폴더**(`../auth`·`../document`·`../editor`·`../workspace`)를 직접
 *    import 하지 않는다. 자체 모듈만 re-export 하고 공통 레이어(s16)는 전이적으로만 소비한다(Req 6.6).
 *
 * `verbatimModuleSyntax` 하에서 타입 전용 재-export 는 `export type` 로 분리한다.
 */

// 타입: 계약 미러 + 업로드/리소스 파생 + 컴포넌트 props (Req 7.1·7.3·7.4).
export type {
  AttachmentKind,
  AttachmentRead,
  AttachmentResourceState,
  UploadItem,
  UploadStatus,
} from "./types";

// api: s16 apiClient 위 첨부 업로드/서빙 얇은 래퍼.
export { attachmentApi } from "./api/attachmentApi";

// lib: 순수 참조/자리표시자 유틸(부수효과 없음).
export {
  buildErrorMarker,
  buildPlaceholderToken,
  buildReferenceMarkdown,
  replacePlaceholder,
  resolveAttachmentReference,
} from "./lib/attachmentReference";

// hooks: 서빙 리소스·낙관 업로드·에디터 업로드 브리지.
export { useAttachmentResource } from "./hooks/useAttachmentResource";
export { useAttachmentUpload } from "./hooks/useAttachmentUpload";
export type { InsertContext } from "./hooks/useAttachmentUpload";
export { locateToken, useEditorUploadBridge } from "./hooks/useEditorUploadBridge";

// components: 렌더/다운로드/placeholder + s16 renderers 결선 브리지.
export { AttachmentImage } from "./components/AttachmentImage";
export type { AttachmentImageProps } from "./components/AttachmentImage";
export { AttachmentFileLink } from "./components/AttachmentFileLink";
export type { AttachmentFileLinkProps } from "./components/AttachmentFileLink";
export { AttachmentPlaceholder } from "./components/AttachmentPlaceholder";
export type { AttachmentPlaceholderProps } from "./components/AttachmentPlaceholder";
export { buildAttachmentRenderers } from "./components/AttachmentRenderBridge";
