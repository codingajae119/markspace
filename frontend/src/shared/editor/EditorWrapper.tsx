/**
 * Toast UI Editor 단일 래퍼 (s16 단일 소유, Requirements 8.1~8.8).
 *
 * 편집(`mode:"edit"`)·읽기(`mode:"read"`) 렌더 경로를 **단일 컴포넌트**로 통일한다.
 * 하위 feature 는 Editor/Viewer 를 직접 고르지 않는다(렌더 경로 이원화 금지 — 8.1, 8.3):
 *   - edit → Toast `Editor`(markdown(Write) 기본 + toolbar WYSIWYG 토글)(8.2)
 *   - read → Toast Viewer(`Editor.factory({ viewer:true })`), `ReadOnlyProse` 컨테이너로
 *            감싸 s22 게스트 뷰와 동일한 공용 prose 시각 언어를 공유(8.3)
 * `onReady(handle)` 로 초기 콘텐츠 주입·현재 콘텐츠 조회 인터페이스(`EditorHandle`)를
 * 노출하여 s20(편집 생명주기)·s19/s22(읽기 뷰)가 저장·표시 로직을 결선한다(8.4).
 *
 * capability 슬롯(8.6~8.8) — s20(편집)·s21(첨부)이 **Toast 인스턴스를 포크하지 않고**
 * 단일 래퍼를 소비하도록 다음을 노출한다:
 *   - 붙여넣기/드롭 구독 훅 `onImagePaste`·`onFileDrop`(8.6): Toast `addImageBlobHook`
 *     (붙여넣기/드롭 이미지)·에디터 루트 DOM `drop`(일반 파일)에서 `File` 을 그대로 전달.
 *   - `EditorHandle.insert`/`replaceRange`(8.7): 커서 삽입·범위 치환(s21 업로드 placeholder
 *     → 최종 `/attachments/{id}` 참조 치환). 읽기 모드는 편집 인스턴스가 없어 no-op.
 *   - `renderers.customImageRenderer`/`customHTMLRenderer`(8.8): edit·read **양 모드에서
 *     동일 override** 를 Toast `customHTMLRenderer` 로 위임(렌더 경로 이원화 없음).
 *
 * React 19 호환: `@toast-ui/react-editor`(React 16~18 peer)를 쓰지 않고 vanilla
 * `@toast-ui/editor` 클래스를 `ref` 컨테이너에 인스턴스화하고 cleanup 에서 destroy 한다.
 *
 * Toast UI CSS import 는 **이 래퍼가 단일 소유**한다(design). 하위 feature 는 별도로
 * Toast CSS 를 import 하지 않는다.
 *
 * POLICY NOT IMPLEMENTED (계약만 노출, 동작은 후속 spec 소유):
 *   - 자동저장(문서 이탈 시 1회)·lock 생명주기 등 편집 정책 **동작** → s20(8.5).
 *   - 실제 업로드·blob 인증 로딩 **동작** → s21. 본 래퍼는 파일 전달 슬롯·콜백·렌더러
 *     override 결선만 제공하며, 업로드/placeholder 치환/blob 로딩 정책은 구현하지 않는다.
 */

import { useEffect, useRef, type ReactElement } from "react";

// `@toast-ui/editor`(v3.2.2)의 package.json `exports` 는 `types` 컨디션을 선언하지
// 않아 `moduleResolution: "bundler"` 에서 tsc 가 동봉 타입을 찾지 못한다(TS7016).
// 값 import 는 런타임 클래스만 받고, 실제 타입은 패키지가 제공하는 선언 파일
// (`types/index.d.ts`, default = Editor 클래스)에서 직접 가져와 `any` 없이 재부여한다.
import type EditorClass from "../../../node_modules/@toast-ui/editor/types/index";
import type {
  CustomHTMLRenderer,
  LinkMdNode,
} from "../../../node_modules/@toast-ui/editor/types/index";
// @ts-expect-error — exports 맵의 types 컨디션 부재로 값 import 는 타입지정 불가(TS7016). 위 EditorClass 로 정식 타입 확보.
import EditorRuntime from "@toast-ui/editor";

const Editor: typeof EditorClass = EditorRuntime;

import "@toast-ui/editor/dist/toastui-editor.css";
import "@toast-ui/editor/dist/toastui-editor-viewer.css";

import { ReadOnlyProse } from "./ReadOnlyProse";
import { renderMathIn } from "./renderMath";

/**
 * 위치 좌표 `[line, ch]` — **1-based line, 0-based ch**(에디터 비종속 규약).
 *
 * 소비자(s21 `locateToken`)는 자연스러운 JS 문자열 규약(0-based ch)으로 좌표를 만든다.
 * Toast markdown 은 line·ch **모두 1-based**(ch=1 이 첫 글자)이므로, 이 래퍼가
 * `replaceRange` 위임 시 ch 를 1-based 로 보정한다(아래 `toToastPos`). 이 Toast 좌표계
 * 흡수가 래퍼 단일 소유이며, 소비자는 Toast 의 base 를 알 필요가 없다.
 */
export type EditorPos = [line: number, ch: number];

/**
 * 콘텐츠 in/out·삽입/치환을 위한 안정적 명령형 핸들(8.4, 8.7).
 *
 * `insert`/`replaceRange` 는 편집(`mode:"edit"`) 인스턴스의 mutation 이다. 읽기
 * (`mode:"read"`) 모드에는 편집 인스턴스가 없어 무해한 no-op 으로 노출한다.
 */
export interface EditorHandle {
  /** 현재 콘텐츠를 markdown 으로 조회한다(s20 저장 결선용). */
  getMarkdown(): string;
  /** 커서 위치에 텍스트 삽입(s21 업로드 placeholder 삽입). 읽기 모드 no-op. */
  insert(text: string): void;
  /** `from`~`to` 범위를 치환(s21 placeholder→최종 참조 치환). 읽기 모드 no-op. */
  replaceRange(from: EditorPos, to: EditorPos, text: string): void;
}

/** `(ref) => HTMLElement` 이미지 렌더 override(s21 이 인증 blob 로딩으로 구현). */
export type CustomImageRenderer = (ref: string) => HTMLElement;

/**
 * Toast image 노드 컨버터가 받는 컨텍스트의 **구조적 최소 형태**(사용하는 멤버만).
 * `entering`(진입/이탈 구분)·`skipChildren`(자식·이탈 방문 스킵)만 소비한다.
 */
interface ToastImageContext {
  entering: boolean;
  skipChildren: () => void;
}

/**
 * 첨부/이미지 커스텀 렌더러 오버라이드(edit·read 양 모드 공통).
 * `/attachments/{id}` 참조 → 인증 blob 로딩 렌더는 s21 이 소비 계약으로 구현한다.
 */
export interface CustomRenderers {
  /** 상위 이미지 override — 래퍼가 Toast image 노드 컨버터로 결선한다. */
  customImageRenderer?: CustomImageRenderer;
  /** Toast `customHTMLRenderer` 형태 — 래퍼가 그대로 위임한다. */
  customHTMLRenderer?: unknown;
  /**
   * Toast 가 읽기/미리보기 DOM 을 채운 **직후** 호출되는 후처리 훅(edit preview·read 공통).
   *
   * Toast `customHTMLRenderer` 는 컨버터 반환을 **문자열**로만 받으므로, 인증 blob 이미지처럼
   * 비동기 커밋이 필요한 컴포넌트는 컨버터가 빈 placeholder(`data-*` 마커)만 내보내고 이 훅이
   * 렌더 후 실 DOM 마커에 라이브 마운트한다(s21 `hydrateAttachmentsInDom`). 반환한 disposer 는
   * 다음 hydrate 직전·언마운트 시 호출되어 마운트한 자원을 해제한다(오브젝트 URL 누수 방지).
   * 편집(WYSIWYG) 표면에는 적용하지 않는다 — 읽기 경로(read Viewer·edit preview)만 대상.
   */
  hydrateDom?: (root: HTMLElement) => (() => void) | void;
}

export interface EditorWrapperProps {
  /** 렌더 모드 — 단일 진입점이 내부적으로 Editor/Viewer 를 선택(8.1). */
  mode: "edit" | "read";
  /** 초기 콘텐츠(markdown). */
  initialContent?: string;
  /** 인스턴스 준비 시 콘텐츠 핸들을 제공한다(8.4). */
  onReady?: (handle: EditorHandle) => void;
  /** 붙여넣기/드롭 이미지 구독(s21 업로드 브리지) — File 을 그대로 전달(8.6). */
  onImagePaste?: (file: File) => void;
  /** 드롭 파일 구독(s21 업로드 브리지) — File 을 그대로 전달(8.6). */
  onFileDrop?: (file: File) => void;
  /** 커스텀 렌더러 override — edit·read 양 모드에서 동일 소비(8.8). */
  renderers?: CustomRenderers;
}

/**
 * Toast `addImageBlobHook` 은 `Blob | File` 을 전달한다. 붙여넣기는 통상 File 이지만
 * Blob 인 경우 File 로 승격하여 `onImagePaste(file: File)` 계약을 만족시킨다.
 */
function asFile(blob: Blob | File): File {
  return blob instanceof File
    ? blob
    : new File([blob], "pasted-image", { type: blob.type });
}

/**
 * caller 의 `renderers` 를 Toast `customHTMLRenderer` 옵션으로 변환한다(edit·read 공통).
 *   - `customHTMLRenderer` 만 있으면 **참조 그대로 위임**(렌더 경로 이원화 없음).
 *   - `customImageRenderer` 가 있으면 Toast image 노드 컨버터로 결선하여 병합한다.
 * 실제 blob 로딩은 s21 이 `customImageRenderer` 구현으로 소유한다.
 */
function toToastHTMLRenderer(
  renderers: CustomRenderers | undefined,
): CustomHTMLRenderer | undefined {
  if (renderers === undefined) {
    return undefined;
  }
  const passthrough = renderers.customHTMLRenderer as
    | CustomHTMLRenderer
    | undefined;
  const imageRenderer = renderers.customImageRenderer;
  if (imageRenderer === undefined) {
    return passthrough;
  }
  const merged: CustomHTMLRenderer = {
    ...(passthrough ?? {}),
    // Toast image 노드는 컨테이너다 — walker 가 진입(entering)·이탈(leaving) 두 번 방문하고 그
    // 사이에 alt 텍스트 자식을 방문한다. Toast 기본 image 컨버터처럼 **진입 시 `skipChildren()`
    // 을 호출**해야 walker 가 자식(alt)과 이탈 이벤트를 함께 건너뛴다. 이를 빠뜨리면 진입에서 1회,
    // 이탈에서 또 1회 렌더되고 사이에 alt 텍스트까지 나와 "이미지·alt·이미지" 3중 출력이 된다.
    image: (node, context) => {
      const ctx = context as ToastImageContext;
      if (ctx.entering === false) {
        return null; // 이탈 이벤트(방어적) — 진입에서 skipChildren 하면 통상 도달하지 않는다.
      }
      ctx.skipChildren();
      const ref = (node as LinkMdNode).destination ?? "";
      return { type: "html", content: imageRenderer(ref).outerHTML };
    },
  };
  return merged;
}

/**
 * Toast UI Editor 단일 래퍼. `mode` 에 따라 Editor(편집) 또는 Viewer(읽기)를
 * 내부 선택하여 렌더한다 — 호출자는 단일 컴포넌트만 소비한다.
 */
export function EditorWrapper({
  mode,
  initialContent,
  onReady,
  onImagePaste,
  onFileDrop,
  renderers,
}: EditorWrapperProps): ReactElement {
  const elRef = useRef<HTMLDivElement | null>(null);

  // 콜백/옵션을 ref 로 캡처하여 inline 값 재생성이 effect 재실행(=인스턴스 재생성)을
  // 유발하지 않게 한다. 슬롯 결선 여부는 effect(=mount) 시점의 ref 값으로 판정한다.
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;
  const onImagePasteRef = useRef(onImagePaste);
  onImagePasteRef.current = onImagePaste;
  const onFileDropRef = useRef(onFileDrop);
  onFileDropRef.current = onFileDrop;
  const renderersRef = useRef(renderers);
  renderersRef.current = renderers;

  useEffect(() => {
    const el = elRef.current;
    if (el === null) {
      return;
    }

    const content = initialContent ?? "";
    // edit·read 양 모드가 동일 override 를 소비한다(렌더 경로 단일화 — 8.8).
    const customHTMLRenderer = toToastHTMLRenderer(renderersRef.current);

    if (mode === "read") {
      // 읽기 전용 — Viewer 로 렌더(편집 인스턴스 없음). Viewer 는 getMarkdown 이 없어
      // 핸들의 getMarkdown 은 주입된 콘텐츠를 반영하고, mutation 은 no-op 이다(8.7).
      const viewer = Editor.factory({
        el,
        viewer: true,
        initialValue: content,
        ...(customHTMLRenderer !== undefined ? { customHTMLRenderer } : {}),
      });
      const handle: EditorHandle = {
        getMarkdown: () => content,
        insert: () => {
          // 읽기 모드는 편집 인스턴스가 없다 — mutation 은 무해한 no-op(8.7).
        },
        replaceRange: () => {
          // 읽기 모드는 편집 인스턴스가 없다 — mutation 은 무해한 no-op(8.7).
        },
      };
      onReadyRef.current?.(handle);

      // 읽기 전용 — Toast 가 채운 뷰어 DOM 에 남은 LaTeX 구분자를 KaTeX 로 렌더한다(8.3
      // 게스트 뷰와 동일 수식 렌더). 편집 표면(WYSIWYG)에는 적용하지 않는다(ProseMirror
      // 텍스트 노드 교체 시 에디터 상태 손상). Viewer 는 생성 시 initialValue 를 동기 렌더한다.
      renderMathIn(el);
      // 렌더된 DOM 의 첨부 placeholder 마커에 인증 컴포넌트를 라이브 마운트한다(s21). Viewer 는
      // 1회 렌더이므로 disposer 를 cleanup 에서 호출해 마운트 자원을 해제한다.
      const disposeHydrate = renderersRef.current?.hydrateDom?.(el);

      return () => {
        disposeHydrate?.();
        viewer.destroy();
      };
    }

    // 편집 — markdown(Write) 기본 + toolbar WYSIWYG 토글(mode switch) 유지(8.2).
    // 붙여넣기/드롭 이미지 훅은 콜백이 있을 때만 결선한다(8.6). 실제 업로드는 s21 소유:
    // 훅은 File 만 전달하고 Toast 삽입 callback(정책)은 호출하지 않는다.
    const wireImagePaste = onImagePasteRef.current !== undefined;
    const editor = new Editor({
      el,
      initialEditType: "markdown",
      initialValue: content,
      // 편집 표면이 mount 컨테이너(전폭·전고 flex 셀)를 가득 채우도록 100% 로 둔다. Toast 기본
      // 값은 300px 이라 지정하지 않으면 뷰포트가 큰 브라우저에서 화면 절반만 차지한다. 조상 flex
      // 높이 체인(AppLayout main → section → EditorPane → 이 el)이 확정 높이를 전달한다.
      height: "100%",
      // 마크다운 모드는 preview 를 상시 표시하지 않고 탭(Write/Preview) 방식으로 둔다.
      // 기본 Write 탭에서 편집 영역이 전폭이 되며, 렌더 결과는 WYSIWYG 전환으로 확인한다.
      previewStyle: "tab",
      hideModeSwitch: false, // markdown 토글을 강제로 숨기지 않는다(8.2).
      ...(customHTMLRenderer !== undefined ? { customHTMLRenderer } : {}),
      ...(wireImagePaste
        ? {
            hooks: {
              addImageBlobHook: (blob: Blob | File) => {
                onImagePasteRef.current?.(asFile(blob));
              },
            },
          }
        : {}),
    });

    // 마크다운 모드 Preview 탭 수식 렌더(읽기 뷰와 동일 KaTeX 패스). Preview 는 편집 표면이
    // 아니라 markdown → HTML 로 그린 **읽기 전용 출력 DOM** 이므로 KaTeX 패스가 안전하다.
    // (WYSIWYG 편집 표면은 ProseMirror 소유라 수식을 렌더하지 않고 원문을 유지한다.)
    // Preview 는 탭 전환·타이핑마다 markdown 에서 재렌더되어 KaTeX 가 지워지므로, 매 렌더
    // 완료(`afterPreviewRender`)마다 다시 태운다. 이 mutation 은 재렌더를 유발하지 않아 루프가
    // 없다.
    // preview 재렌더마다 이전 hydrate 루트를 해제한 뒤 재마운트한다. Toast 가 preview DOM 을
    // 통째로 재생성하므로 이전 루트를 방치하면 언마운트 없이 detach 되어 오브젝트 URL 이 누수된다.
    let disposePreviewHydrate: (() => void) | void;
    const renderPreviewMath = (): void => {
      const mdPreview = editor.getEditorElements().mdPreview;
      renderMathIn(mdPreview);
      disposePreviewHydrate?.();
      disposePreviewHydrate = renderersRef.current?.hydrateDom?.(mdPreview);
    };
    editor.on("afterPreviewRender", renderPreviewMath);

    // 일반 파일 드롭 — 콜백이 있을 때만 에디터 루트에 DOM drop 리스너 결선(8.6).
    // 브라우저 기본 파일 열기/네비게이션만 최소 차단하고, 업로드 정책은 s21 소유.
    const wireFileDrop = onFileDropRef.current !== undefined;
    const handleDrop = (event: Event): void => {
      const dataTransfer = (event as DragEvent).dataTransfer;
      if (dataTransfer === null) {
        return;
      }
      const files = Array.from(dataTransfer.files);
      if (files.length === 0) {
        return;
      }
      event.preventDefault();
      for (const file of files) {
        onFileDropRef.current?.(file);
      }
    };
    if (wireFileDrop) {
      el.addEventListener("drop", handleDrop);
    }

    // EditorPos(1-based line, 0-based ch) → Toast markdown 좌표(1-based line, 1-based ch).
    // Toast `getMdToEditorPos` 는 line-1 로 인덱싱하고 ch 를 그대로 문자 오프셋에 더하며
    // ch=1 이 첫 글자를 가리킨다(ProseMirror pos). 따라서 line 은 그대로, ch 만 +1 보정한다.
    // 이 +1 이 빠지면 range 가 좌로 한 칸 밀려 토큰 마지막 글자(예: 센티넬 `⟧`)가 남는다.
    const toToastPos = (pos: EditorPos): [number, number] => [pos[0], pos[1] + 1];
    const handle: EditorHandle = {
      getMarkdown: () => editor.getMarkdown(),
      insert: (text) => {
        editor.insertText(text);
      },
      replaceRange: (from, to, text) => {
        editor.replaceSelection(text, toToastPos(from), toToastPos(to));
      },
    };
    onReadyRef.current?.(handle);

    return () => {
      if (wireFileDrop) {
        el.removeEventListener("drop", handleDrop);
      }
      disposePreviewHydrate?.();
      editor.off("afterPreviewRender");
      editor.destroy();
    };
  }, [mode, initialContent]);

  if (mode === "read") {
    // 읽기 컨테이너는 ReadOnlyProse 를 소비 → s22 게스트 뷰와 동일 시각 언어(8.3).
    return (
      <ReadOnlyProse>
        <div ref={elRef} />
      </ReadOnlyProse>
    );
  }

  // 편집 mount 컨테이너 — Toast height:"100%" 가 채울 확정 높이를 확보하도록 flex 셀로 채운다
  // (부모 flex 컬럼에서 남은 세로 공간 전부 차지, min-h-0 로 내부 스크롤 허용).
  return <div ref={elRef} className="min-h-0 flex-1" />;
}
