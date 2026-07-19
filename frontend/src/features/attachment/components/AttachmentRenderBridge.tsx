/**
 * 첨부 콘텐츠 참조 → 인증 렌더 컴포넌트 결선 브리지
 * (design.md "features/attachment — AttachmentRenderBridge" ~507-524, Requirements 3.5, 5.3, 7.2, 7.5).
 *
 * s16 `EditorWrapper` 의 `renderers` 슬롯에 넘길 `CustomRenderers`
 * (`customImageRenderer`·`customHTMLRenderer`, **edit·read 양 모드 공통**)를 구성한다.
 * 래퍼가 두 모드에서 동일 렌더러를 소비하므로 렌더 경로를 이원화하지 않는다(Req 3.5·7.5).
 *
 *   - `customImageRenderer(ref)`: `resolveAttachmentReference` 로 `/attachments/{id}` 참조를
 *     파싱해 `attachmentId` 를 얻고, 인증 blob 기반 `AttachmentImage` 를 마운트한 `HTMLElement`
 *     를 반환한다(원시 `<img src="/attachments/{id}">` 금지, Req 3.2). 비첨부 참조는 무해한 빈
 *     `<span>` 으로 폴백한다(throw·원시 src 없음).
 *   - `customHTMLRenderer.link`: 파일 링크(`[name](/attachments/{id})`)를 `AttachmentFileLink`
 *     로 라우팅한다. 비첨부 링크는 Toast 기본 렌더(`context.origin`)로 위임한다.
 *
 * 첨부 상태(보관·소멸)는 이 브리지가 판정하지 않는다 — `AttachmentImage`·`AttachmentFileLink`
 * 가 서빙 결과(404/403)만 관측해 placeholder 로 폴백한다(Req 5.3). 브리지는 라우팅만 한다.
 *
 * ┌─ REVALIDATION TRIGGER (s16 소유 seam, design.md Revalidation Triggers) ──────────────┐
 * │ s16 `EditorWrapper.toToastHTMLRenderer` 의 image 컨버터는                             │
 * │   `{ type:"html", content: imageRenderer(ref).outerHTML }`                            │
 * │ 로 **반환 HTMLElement 를 동기 `.outerHTML` 로 직렬화**한다. React 19 `createRoot`     │
 * │ 는 비동기 커밋이라, 마운트한 라이브 컴포넌트는 그 동기 read 시점에 아직 DOM 에 없어    │
 * │ 직렬화 문자열에 포착되지 않는다. 즉 이 브리지가 반환하는 라이브 React 루트를 통한       │
 * │ 진정한 end-to-end 인증 렌더는 **s16 이 소유한 `.outerHTML` 직렬화 단계에 의해 제한**   │
 * │ 된다. 파일 링크 경로도 동일하게 `container.outerHTML` 직렬화(아래)에 종속된다.        │
 * │ 근본 해결(반환 HTMLElement 를 직렬화하지 않고 라이브 마운트로 삽입)은 s16 소유이며,    │
 * │ 이 브리지는 계약대로 마운트 가능한 렌더러를 반환하고 seam 은 상위(s16)로 보고한다.     │
 * │ 이 파일은 s16 을 수정하지 않는다.                                                     │
 * └───────────────────────────────────────────────────────────────────────────────────────┘
 */

import type { ReactElement } from "react";
import { createRoot } from "react-dom/client";

// `CustomRenderers`·`CustomImageRenderer` 계약 소유자는 s16 — 소비만 한다.
import type {
  CustomRenderers,
  CustomImageRenderer,
} from "@/shared/editor/EditorWrapper";

// 이미 존재하는 순수 파서(task 2.1)를 재사용한다(재정의 금지, Req 7.2).
import { resolveAttachmentReference } from "../lib/attachmentReference";
import { AttachmentImage } from "./AttachmentImage";
import { AttachmentFileLink } from "./AttachmentFileLink";

/**
 * Toast `link` 컨버터가 받는 노드/컨텍스트의 **구조적 최소 형태**(s21 측 정밀 타입).
 *
 * s16 `CustomRenderers.customHTMLRenderer` 가 `unknown` 이라 latitude 가 있으며, `@toast-ui/editor`
 * 내부 타입(`Context` 미export)에 결합하지 않고 실제 호출 계약과 구조적으로 호환되는 최소 타입만
 * 선언해 `any` 없이 정밀하게 유지한다.
 */
interface ToastLinkNode {
  /** 링크/이미지 목적지(첨부 참조 판정 대상). null 가능. */
  destination: string | null;
}

/** Toast 컨버터가 반환하는 html 토큰(전체 치환용). */
interface ToastHtmlToken {
  type: "html";
  content: string;
}

/** Toast 컨버터 호출 컨텍스트의 구조적 최소 형태(사용하는 멤버만). */
interface ToastConvertorContext {
  /** 여는 토큰이면 true, 닫는 토큰이면 false. */
  entering: boolean;
  /** 노드의 자식 텍스트(링크 표시 텍스트=파일명)를 조회한다. */
  getChildrenText: (node: ToastLinkNode) => string;
  /** 자식 기본 렌더를 건너뛴다(전체 치환 시). */
  skipChildren: () => void;
  /** 기본(원래) 컨버터 결과 — 비첨부 링크는 이 기본 렌더로 위임한다. */
  origin?: () => unknown;
}

/** s21 측 `link` 컨버터 시그니처(구조적으로 Toast `HTMLConvertor` 와 호환). */
type LinkConvertor = (
  node: ToastLinkNode,
  context: ToastConvertorContext,
) => ToastHtmlToken | unknown;

/** 브리지가 노출하는 `customHTMLRenderer` 형태(정밀 타입, `any` 없음). */
interface AttachmentHTMLRenderer {
  link: LinkConvertor;
}

/**
 * React element 를 새 `<span>` 컨테이너에 `createRoot` 로 마운트하고 컨테이너를 반환한다.
 *
 * 반환 컨테이너의 lifecycle 은 Toast 렌더가 소유한다. 인증 blob 로딩·placeholder 폴백은
 * 마운트된 컴포넌트(`AttachmentImage`·`AttachmentFileLink`)가 관측 상태로 수행한다.
 */
function mountElement(element: ReactElement): HTMLElement {
  const container = document.createElement("span");
  createRoot(container).render(element);
  return container;
}

/**
 * 상위 이미지 override(edit·read 공통) — `/attachments/{id}` 이미지 참조를 인증 렌더에 연결.
 *
 * 첨부 참조면 `AttachmentImage` 를 마운트한 컨테이너를 반환하고, 비첨부 href 는 무해한 빈
 * `<span>` 을 반환한다(throw 없음·원시 `src` 없음, Req 3.2).
 */
const customImageRenderer: CustomImageRenderer = (ref) => {
  const parsed = resolveAttachmentReference(ref);
  if (parsed === null) {
    // 비첨부 참조 → 원시 /attachments src 를 만들지 않고 무해 요소로 폴백.
    return document.createElement("span");
  }
  return mountElement(<AttachmentImage attachmentId={parsed.attachmentId} />);
};

/**
 * 파일 링크 override — `[name](/attachments/{id})` 를 `AttachmentFileLink` 로 라우팅한다.
 *
 * 첨부 링크(여는 토큰)면 링크 텍스트(=파일명)로 `AttachmentFileLink` 를 마운트해 html 토큰으로
 * 전체 치환하고 자식 기본 렌더를 건너뛴다. 닫는 토큰(entering=false)은 중복 마운트를 피하려
 * null 을 반환한다. 비첨부/목적지 부재 링크는 Toast 기본 렌더(`origin`)로 위임한다(일반 링크 무영향).
 */
const linkRenderer: LinkConvertor = (node, context) => {
  const destination = node.destination ?? "";
  const parsed = resolveAttachmentReference(destination);
  if (parsed === null) {
    // 일반 링크 → 기본 렌더 위임(라우팅하지 않음).
    return context.origin?.() ?? null;
  }
  if (!context.entering) {
    // 여는 토큰에서 전체 치환했으므로 닫는 토큰은 생략(중복 마운트 방지).
    return null;
  }
  const fileName = context.getChildrenText(node);
  context.skipChildren();
  const container = mountElement(
    <AttachmentFileLink attachmentId={parsed.attachmentId} fileName={fileName} />,
  );
  return { type: "html", content: container.outerHTML };
};

/**
 * s16 `EditorWrapper.renderers` 슬롯에 주입할 첨부 렌더러 묶음을 구성한다(Req 3.5·5.3·7.2·7.5).
 *
 * edit·read 양 모드에서 **동일 객체**를 소비한다(모드 분기 없음 — 단일 렌더 경로, Req 7.5).
 */
export function buildAttachmentRenderers(): CustomRenderers {
  const customHTMLRenderer: AttachmentHTMLRenderer = { link: linkRenderer };
  return { customImageRenderer, customHTMLRenderer };
}
