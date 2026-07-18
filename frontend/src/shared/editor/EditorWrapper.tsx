/**
 * Toast UI Editor 단일 래퍼 (s16 단일 소유, Requirements 8.1~8.5).
 *
 * 편집(`mode:"edit"`)·읽기(`mode:"read"`) 렌더 경로를 **단일 컴포넌트**로 통일한다.
 * 하위 feature 는 Editor/Viewer 를 직접 고르지 않는다(렌더 경로 이원화 금지 — 8.1, 8.3):
 *   - edit → Toast `Editor`(WYSIWYG 기본 + toolbar markdown 토글)(8.2)
 *   - read → Toast Viewer(`Editor.factory({ viewer:true })`), `ReadOnlyProse` 컨테이너로
 *            감싸 s22 게스트 뷰와 동일한 공용 prose 시각 언어를 공유(8.3)
 * `onReady(handle)` 로 초기 콘텐츠 주입·현재 콘텐츠 조회 인터페이스(`EditorHandle`)를
 * 노출하여 s20(편집 생명주기)·s19/s22(읽기 뷰)가 저장·표시 로직을 결선한다(8.4).
 *
 * React 19 호환: `@toast-ui/react-editor`(React 16~18 peer)를 쓰지 않고 vanilla
 * `@toast-ui/editor` 클래스를 `ref` 컨테이너에 인스턴스화하고 cleanup 에서 destroy 한다.
 *
 * Toast UI CSS import 는 **이 래퍼가 단일 소유**한다(design). 하위 feature 는 별도로
 * Toast CSS 를 import 하지 않는다.
 *
 * POLICY NOT IMPLEMENTED (계약만 노출, 동작은 후속 spec 소유):
 *   - 자동저장(문서 이탈 시 1회)·lock 생명주기 등 편집 정책 **동작** → s20(8.5).
 *   - 붙여넣기/드롭 훅·삽입/치환 콜백·커스텀 렌더러 오버라이드(capability 슬롯) → task 6.2
 *     (s21 소비). 본 파일은 6.2 가 props/handle 을 깔끔히 확장하도록 인터페이스를 열어둔다.
 */

import { useEffect, useRef, type ReactElement } from "react";

// `@toast-ui/editor`(v3.2.2)의 package.json `exports` 는 `types` 컨디션을 선언하지
// 않아 `moduleResolution: "bundler"` 에서 tsc 가 동봉 타입을 찾지 못한다(TS7016).
// 값 import 는 런타임 클래스만 받고, 실제 타입은 패키지가 제공하는 선언 파일
// (`types/index.d.ts`, default = Editor 클래스)에서 직접 가져와 `any` 없이 재부여한다.
import type EditorClass from "../../../node_modules/@toast-ui/editor/types/index";
// @ts-expect-error — exports 맵의 types 컨디션 부재로 값 import 는 타입지정 불가(TS7016). 위 EditorClass 로 정식 타입 확보.
import EditorRuntime from "@toast-ui/editor";

const Editor: typeof EditorClass = EditorRuntime;

import "@toast-ui/editor/dist/toastui-editor.css";
import "@toast-ui/editor/dist/toastui-editor-viewer.css";

import { ReadOnlyProse } from "./ReadOnlyProse";

/**
 * 콘텐츠 in/out 을 위한 안정적 명령형 핸들(8.4).
 *
 * 현재는 `getMarkdown()` 만 노출한다. 콘텐츠 삽입/치환 콜백(`insert`·`replaceRange`)은
 * capability 슬롯(task 6.2)에서 이 인터페이스를 확장하여 추가한다.
 */
export interface EditorHandle {
  /** 현재 콘텐츠를 markdown 으로 조회한다(s20 저장 결선용). */
  getMarkdown(): string;
}

export interface EditorWrapperProps {
  /** 렌더 모드 — 단일 진입점이 내부적으로 Editor/Viewer 를 선택(8.1). */
  mode: "edit" | "read";
  /** 초기 콘텐츠(markdown). */
  initialContent?: string;
  /** 인스턴스 준비 시 콘텐츠 핸들을 제공한다(8.4). */
  onReady?: (handle: EditorHandle) => void;
}

/**
 * Toast UI Editor 단일 래퍼. `mode` 에 따라 Editor(편집) 또는 Viewer(읽기)를
 * 내부 선택하여 렌더한다 — 호출자는 단일 컴포넌트만 소비한다.
 */
export function EditorWrapper({
  mode,
  initialContent,
  onReady,
}: EditorWrapperProps): ReactElement {
  const elRef = useRef<HTMLDivElement | null>(null);

  // onReady 를 ref 로 캡처하여 inline 콜백 재생성이 effect 재실행을 유발하지 않게 한다.
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    const el = elRef.current;
    if (el === null) {
      return;
    }

    const content = initialContent ?? "";

    if (mode === "read") {
      // 읽기 전용 — Viewer 로 렌더(편집 인스턴스 없음). Viewer 는 getMarkdown 이 없어
      // 핸들의 getMarkdown 은 주입된 콘텐츠를 반영한다.
      const viewer = Editor.factory({ el, viewer: true, initialValue: content });
      const handle: EditorHandle = {
        getMarkdown: () => content,
      };
      onReadyRef.current?.(handle);

      return () => {
        viewer.destroy();
      };
    }

    // 편집 — WYSIWYG 기본 + toolbar markdown 토글(mode switch) 유지(8.2).
    const editor = new Editor({
      el,
      initialEditType: "wysiwyg",
      initialValue: content,
      previewStyle: "vertical",
      hideModeSwitch: false, // markdown 토글을 강제로 숨기지 않는다(8.2).
    });
    const handle: EditorHandle = {
      getMarkdown: () => editor.getMarkdown(),
    };
    onReadyRef.current?.(handle);

    return () => {
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

  return <div ref={elRef} />;
}
