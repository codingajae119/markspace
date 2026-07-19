/**
 * 에디터 업로드 브리지 — s16 `EditorWrapper` 이벤트/`EditorHandle` 계약을 소비해 업로드 훅에
 * 결선하는 **소비 어댑터**(계약 미소유).
 *
 * s16 `EditorWrapper` 가 소유·노출하는 슬롯(`onImagePaste`·`onFileDrop`·`onReady`·
 * `EditorHandle.insert`/`replaceRange`)을 **소비만** 하며 Toast 인스턴스나 래퍼 내부를
 * 소유하지 않는다(Req 7.5). s20 편집 표면이 `<EditorWrapper .../>` 를 마운트하고 이 훅이
 * 반환하는 핸들러를 그 props 에 바인딩한다.
 *
 * 결선 규약:
 *  - `onImagePaste(file)` → `startUpload({ file, fileName: file.name, kind:"image" })`
 *    (붙여넣기는 이미지로 확정, Req 1.1·1.4).
 *  - `onFileDrop(file)` → `startUpload({ file, fileName: file.name })` (종류 없음 → 백엔드
 *    추론에 위임, Req 1.1·1.4·1.5).
 *  - `onReady(handle)` → `EditorHandle` 저장 후 그 위에 `InsertContext` 를 구현하여
 *    자리표시자 삽입(→`handle.insert(token)`)·성공/실패 치환(→`handle.replaceRange(range,…)`)을
 *    결선한다(Req 7.5, design "useEditorUploadBridge").
 *
 * `documentId` 는 s19 문서 컨텍스트·s20 편집 표면 seam 에서 주입(Req 1.2). viewer 권한이면
 * `canUpload:false` 로 주입되어 진입점을 비활성화한다(Req 1.6). 두 조건 중 하나라도 미충족이면
 * 붙여넣기/드롭 진입점을 방어적으로 no-op 처리한다. 단, 이 클라이언트 게이팅은 UI 노출 편의일
 * 뿐이며 서버측 권한 강제(백엔드 403)를 대체하지 않는다(Req 6.5). 이 훅은 스스로 역할을
 * 판정하지 않고 주입된 `canUpload` 를 그대로 존중한다(역할 판정은 s16 `hasWorkspaceRole`/
 * `RequireRole` 경유로 s20 소비자가 수행).
 * (design.md "useEditorUploadBridge"; Requirements 1.1·1.2·1.4·1.6·6.5·7.5)
 */
import { useCallback, useMemo, useRef } from "react";

import { buildPlaceholderToken } from "../lib/attachmentReference";
import { useAttachmentUpload } from "./useAttachmentUpload";
import type { InsertContext } from "./useAttachmentUpload";
import type { EditorHandle, EditorPos } from "@/shared/editor/EditorWrapper";

/**
 * `EditorPos` 좌표 규약: **1-based line, 0-based ch**.
 *
 * Toast markdown 의 라인 번호는 1 부터 시작하고 ch(열)는 0 부터 시작한다. 이 훅의 책임은
 * 콘텐츠 문자열 안에서 토큰 위치를 정확히 찾아 `EditorPos` 로 환산하는 것까지이며,
 * `EditorPos`→Toast API 매핑 정확성은 s16 `EditorWrapper.replaceRange`(Toast
 * `replaceSelection` 위임) 가 소유한다(CONCERNS 참고).
 */
const LINE_BASE = 1;

/**
 * `useAttachmentUpload` 는 hook 규칙상 무조건 호출해야 하나 `documentId: number` 를 요구한다.
 * `documentId` 미확보(null) 시 이 센티넬로 호출하되, 진입점 핸들러가 `startUpload` 도달을
 * 방어적으로 차단하므로(gating guard) 실제 요청은 발생하지 않는다.
 */
const DISABLED_DOCUMENT_ID = -1;

/**
 * markdown 문자열에서 `token` 의 첫 등장 위치를 `{ from, to }`(`EditorPos`)로 환산한다.
 *
 * "\n" 로 라인을 분할해 라인 인덱스와 열 인덱스를 찾고, 1-based line·0-based ch 규약으로
 * 반환한다(위 `LINE_BASE`). 토큰이 없으면 `null` 을 반환한다(치환 no-op 유도). 순수 함수로
 * 부수효과가 없어 단위 테스트로 계약을 고정한다.
 */
export function locateToken(
  markdown: string,
  token: string,
): { from: EditorPos; to: EditorPos } | null {
  const lines = markdown.split("\n");
  for (let i = 0; i < lines.length; i += 1) {
    const ch = lines[i].indexOf(token);
    if (ch !== -1) {
      const line = i + LINE_BASE;
      return { from: [line, ch], to: [line, ch + token.length] };
    }
  }
  return null;
}

/** `useEditorUploadBridge` 반환 계약(s16 이벤트 슬롯 핸들러). */
interface UseEditorUploadBridgeResult {
  /** s16 `onReady` — `EditorHandle` 저장 후 `InsertContext` 결선. */
  onReady: (handle: EditorHandle) => void;
  /** s16 `onImagePaste` — 붙여넣기 → 이미지 업로드. */
  onImagePaste: (file: File) => void;
  /** s16 `onFileDrop` — 드롭 → 종류 미지정 업로드(백엔드 추론). */
  onFileDrop: (file: File) => void;
}

/**
 * 에디터 업로드 브리지 훅.
 *
 * @param input.documentId 업로드 대상 문서 식별자(s19/s20 seam 주입). null 이면 방어적 비활성.
 * @param input.canUpload  업로드 허용 여부(viewer 면 false, s16 게이팅 결과 주입).
 */
export function useEditorUploadBridge(input: {
  documentId: number | null;
  canUpload: boolean;
}): UseEditorUploadBridgeResult {
  const { documentId, canUpload } = input;

  // 수신한 EditorHandle 을 ref 로 보관(onReady 저장 → InsertContext 결선). 계약 소유는 s16.
  const handleRef = useRef<EditorHandle | null>(null);

  const onReady = useCallback((handle: EditorHandle): void => {
    handleRef.current = handle;
  }, []);

  // EditorHandle.insert/replaceRange 위에 InsertContext 를 구현한다. handle 이 없거나 토큰을
  // 찾지 못하면 안전하게 no-op 한다. insert 는 삽입 위치를 반환하지 않으므로 치환 시 현재
  // 콘텐츠에서 uploadId 토큰 위치를 재계산한다(Req 2.1·2.2 via 7.5).
  const insert = useMemo<InsertContext>(
    () => ({
      insertPlaceholder: (_uploadId: string, token: string): void => {
        handleRef.current?.insert(token);
      },
      replaceToken: (uploadId: string, replacement: string): void => {
        const handle = handleRef.current;
        if (handle === null) {
          return;
        }
        const token = buildPlaceholderToken(uploadId);
        const range = locateToken(handle.getMarkdown(), token);
        if (range === null) {
          return;
        }
        handle.replaceRange(range.from, range.to, replacement);
      },
    }),
    [],
  );

  // hook 규칙상 무조건 호출한다. documentId 미확보 시 센티넬로 호출하되 실제 요청은 핸들러
  // 게이팅으로 차단된다(아래 guard).
  const { startUpload } = useAttachmentUpload(
    documentId ?? DISABLED_DOCUMENT_ID,
    insert,
  );

  // 최신 게이팅/식별자/startUpload 를 ref 로 잡아 핸들러 참조 안정성을 유지한다.
  const canUploadRef = useRef(canUpload);
  canUploadRef.current = canUpload;
  const documentIdRef = useRef(documentId);
  documentIdRef.current = documentId;
  const startUploadRef = useRef(startUpload);
  startUploadRef.current = startUpload;

  // 진입점 방어적 비활성: viewer(!canUpload) 또는 documentId 미확보 시 no-op. 클라이언트
  // 게이팅은 UI 편의일 뿐 서버 403 을 대체하지 않는다(Req 1.6·6.5).
  const isEnabled = (): boolean =>
    canUploadRef.current && documentIdRef.current !== null;

  const onImagePaste = useCallback((file: File): void => {
    if (!isEnabled()) {
      return;
    }
    // 붙여넣기는 이미지로 확정(Req 1.4). fileName 은 File.name 그대로 사용.
    void startUploadRef.current({ file, fileName: file.name, kind: "image" });
  }, []);

  const onFileDrop = useCallback((file: File): void => {
    if (!isEnabled()) {
      return;
    }
    // 드롭은 종류를 지정하지 않아 백엔드 추론에 위임(Req 1.4·1.5).
    void startUploadRef.current({ file, fileName: file.name });
  }, []);

  return { onReady, onImagePaste, onFileDrop };
}
