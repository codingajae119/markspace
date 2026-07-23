/**
 * 첨부 콘텐츠 참조 → 인증 렌더 컴포넌트 결선 브리지
 * (design.md "features/attachment — AttachmentRenderBridge" ~507-524, Requirements 3.5, 5.3, 7.2, 7.5).
 *
 * s16 `EditorWrapper` 의 `renderers` 슬롯에 넘길 `CustomRenderers`
 * (`customImageRenderer`·`customHTMLRenderer`·`hydrateDom`, **edit·read 양 모드 공통**)를 구성한다.
 * 래퍼가 두 모드에서 동일 렌더러를 소비하므로 렌더 경로를 이원화하지 않는다(Req 3.5·7.5).
 *
 * ── 2단계 렌더(placeholder → hydrate): 왜 필요한가 ──
 * s16 `EditorWrapper` 의 Toast `customHTMLRenderer` 는 컨버터가 반환한 HTML 을 **문자열**로만
 * 받는다(`{ type:"html", content: string }`). 라이브 React 루트를 그 자리에서 `.outerHTML` 로
 * 직렬화하면 React 19 `createRoot` 의 **비동기 커밋** 전이라 빈 컨테이너가 잡혀 인증 blob 이미지가
 * 끝내 뜨지 않는다(과거 관측: preview 에서 alt 텍스트만 표시). 그래서 컨버터는 **직렬화 가능한
 * 빈 placeholder(`data-*` 마커)** 만 내보내고, Toast 가 DOM 을 채운 **뒤** `hydrateDom` 이 그
 * 마커에 `AttachmentImage`·`AttachmentFileLink` 를 **라이브 마운트**한다. 이는 이미 공용 읽기
 * 경로가 쓰는 후처리 패스(`renderMathIn`)와 동일한 idiom 이며, blob 로딩·placeholder 폴백·오브젝트
 * URL 생명주기는 기존 컴포넌트(훅)가 그대로 소유한다(재구현 없음).
 *
 *   - `customImageRenderer(ref)`: `resolveAttachmentReference` 로 `/attachments/{id}` 참조를
 *     파싱해 `<span data-attachment-image-id="{id}">` 마커를 반환한다(원시 `<img src>` 금지, Req 3.2).
 *     비첨부 참조는 무해한 빈 `<span>` 으로 폴백한다(throw·원시 src 없음).
 *   - `customHTMLRenderer.link`: 파일 링크(`[name](/attachments/{id})`)를
 *     `<span data-attachment-file-id="{id}" data-attachment-file-name="{name}">` 마커로 치환한다.
 *     비첨부 링크는 Toast 기본 렌더(`context.origin`)로 위임한다.
 *   - `hydrateDom(root)`: 렌더된 DOM 의 위 마커를 찾아 인증 컴포넌트를 라이브 마운트하고,
 *     마운트한 React 루트를 해제하는 disposer 를 반환한다(재렌더/언마운트 시 누수·중복 방지).
 *
 * 첨부 상태(보관·소멸)는 이 브리지가 판정하지 않는다 — `AttachmentImage`·`AttachmentFileLink`
 * 가 서빙 결과(404/403)만 관측해 placeholder 로 폴백한다(Req 5.3). 브리지는 라우팅만 한다.
 */

import type { ReactElement } from "react";
import { createRoot, type Root } from "react-dom/client";

// `CustomRenderers`·`CustomImageRenderer` 계약 소유자는 s16 — 소비만 한다.
import type {
  CustomRenderers,
  CustomImageRenderer,
} from "@/shared/editor/EditorWrapper";

// 이미 존재하는 순수 파서(task 2.1)를 재사용한다(재정의 금지, Req 7.2).
import { resolveAttachmentReference } from "../lib/attachmentReference";
import { AttachmentImage } from "./AttachmentImage";
import { AttachmentFileLink } from "./AttachmentFileLink";

/** placeholder 마커 속성 이름(브리지가 내보내고 `hydrateDom` 이 소비하는 단일 규약). */
const IMAGE_ID_ATTR = "data-attachment-image-id";
const FILE_ID_ATTR = "data-attachment-file-id";
const FILE_NAME_ATTR = "data-attachment-file-name";
/** 중복 마운트 방지 마커(같은 DOM 에 hydrate 가 두 번 걸려도 1회만 마운트). */
const HYDRATED_ATTR = "data-attachment-hydrated";

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
 * 상위 이미지 override(edit·read 공통) — `/attachments/{id}` 이미지 참조를 hydrate 대상 마커로.
 *
 * 첨부 참조면 `data-attachment-image-id` 마커 `<span>` 을 반환하고(라이브 마운트는 `hydrateDom`
 * 이 수행), 비첨부 href 는 무해한 빈 `<span>` 을 반환한다(throw 없음·원시 `src` 없음, Req 3.2).
 * 반환 요소는 s16 래퍼가 `.outerHTML` 로 직렬화하므로 **동기 직렬화 가능한 빈 마커**여야 한다.
 */
const customImageRenderer: CustomImageRenderer = (ref) => {
  const parsed = resolveAttachmentReference(ref);
  const span = document.createElement("span");
  if (parsed !== null) {
    // 비첨부 참조 → 마커 없이 무해한 빈 span(원시 /attachments src 미생성).
    span.setAttribute(IMAGE_ID_ATTR, String(parsed.attachmentId));
  }
  return span;
};

/**
 * 파일 링크 override — `[name](/attachments/{id})` 를 hydrate 대상 마커로 치환한다.
 *
 * 첨부 링크(여는 토큰)면 `data-attachment-file-id`·`data-attachment-file-name` 마커로 전체
 * 치환하고 자식 기본 렌더를 건너뛴다(라이브 마운트는 `hydrateDom`). 파일명은 DOM 속성으로
 * `setAttribute` 후 `outerHTML` 직렬화하여 브라우저가 안전하게 이스케이프한다(주입 방지). 닫는
 * 토큰(entering=false)은 중복 마운트를 피하려 null 을 반환한다. 비첨부/목적지 부재 링크는 Toast
 * 기본 렌더(`origin`)로 위임한다(일반 링크 무영향).
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
  const span = document.createElement("span");
  span.setAttribute(FILE_ID_ATTR, String(parsed.attachmentId));
  // setAttribute + outerHTML 로 직렬화 → 파일명의 따옴표·`<` 등이 안전하게 이스케이프된다.
  span.setAttribute(FILE_NAME_ATTR, fileName);
  return { type: "html", content: span.outerHTML };
};

/** 정규 `/attachments/{id}` 마커의 id 를 양의 정수로 파싱한다(비정상 마커는 null). */
function parsePositiveId(raw: string | null): number | null {
  if (raw === null) {
    return null;
  }
  const id = Number(raw);
  if (!Number.isInteger(id) || id <= 0 || String(id) !== raw) {
    return null;
  }
  return id;
}

/**
 * 렌더된 DOM 의 첨부 placeholder 마커에 인증 컴포넌트를 라이브 마운트한다(Req 3.1·3.5·4.3·5.3).
 *
 * s16 래퍼가 Toast 렌더 **직후** 호출한다(read Viewer 생성 후·edit preview `afterPreviewRender`).
 * 이 시점 마커는 이미 실 DOM 에 붙어 있어 `createRoot(...).render(...)` 가 정상 커밋되고 blob
 * 로딩이 진행된다(과거 `.outerHTML` 직렬화 seam 을 우회). 마운트한 루트들을 해제하는 disposer 를
 * 반환하여, 재렌더(다음 hydrate 전)·언마운트 시 래퍼가 루트를 해제하도록 한다 — 이로써
 * `useAttachmentResource` 의 cleanup 이 실행돼 오브젝트 URL 이 revoke 되고 누수가 없다.
 */
export function hydrateAttachmentsInDom(root: HTMLElement): () => void {
  const roots: Root[] = [];

  const mount = (el: Element, node: ReactElement): void => {
    if (el.getAttribute(HYDRATED_ATTR) === "true") {
      return; // 같은 실 DOM 에 재호출돼도 1회만 마운트(멱등).
    }
    el.setAttribute(HYDRATED_ATTR, "true");
    const reactRoot = createRoot(el);
    reactRoot.render(node);
    roots.push(reactRoot);
  };

  root.querySelectorAll(`span[${IMAGE_ID_ATTR}]`).forEach((el) => {
    const id = parsePositiveId(el.getAttribute(IMAGE_ID_ATTR));
    if (id === null) {
      return;
    }
    mount(el, <AttachmentImage attachmentId={id} />);
  });

  root.querySelectorAll(`span[${FILE_ID_ATTR}]`).forEach((el) => {
    const id = parsePositiveId(el.getAttribute(FILE_ID_ATTR));
    if (id === null) {
      return;
    }
    const fileName = el.getAttribute(FILE_NAME_ATTR) ?? "";
    mount(el, <AttachmentFileLink attachmentId={id} fileName={fileName} />);
  });

  return () => {
    // 라이브 루트 해제 → 컴포넌트 언마운트 → 훅 cleanup(오브젝트 URL revoke)로 누수 방지.
    roots.forEach((reactRoot) => reactRoot.unmount());
  };
}

/**
 * s16 `EditorWrapper.renderers` 슬롯에 주입할 첨부 렌더러 묶음을 구성한다(Req 3.5·5.3·7.2·7.5).
 *
 * edit·read 양 모드에서 **동일 객체**를 소비한다(모드 분기 없음 — 단일 렌더 경로, Req 7.5).
 * placeholder 컨버터(`customImageRenderer`·`customHTMLRenderer`)와 후처리 라이브 마운트
 * (`hydrateDom`)를 함께 제공하여 인증 blob 이미지/다운로드 링크가 실제로 렌더되게 한다.
 */
export function buildAttachmentRenderers(): CustomRenderers {
  const customHTMLRenderer: AttachmentHTMLRenderer = { link: linkRenderer };
  return {
    customImageRenderer,
    customHTMLRenderer,
    hydrateDom: hydrateAttachmentsInDom,
  };
}
