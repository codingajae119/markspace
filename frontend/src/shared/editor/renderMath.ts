/**
 * 공용 수식(LaTeX) 렌더 패스 — KaTeX 단일 소유 (읽기 렌더 경로 공통).
 *
 * 이 프로젝트의 읽기 렌더는 **두 경로**로 갈리지만 시각 언어는 하나다(`.readonly-prose`):
 *   1. 인증 읽기 뷰  — `EditorWrapper(mode:"read")` 의 Toast Viewer 가 markdown → HTML 렌더.
 *   2. 게스트 공개 뷰 — 백엔드(markdown-it-py + nh3)가 만든 `content_html` 을 그대로 표시.
 * 두 경로 모두 최종 산출물은 **DOM 에 박힌 HTML** 이고, Toast/markdown-it/nh3 어느 쪽도
 * 수식을 모르므로 `$$…$$`·`$…$` 구분자는 **텍스트 그대로** DOM 에 남는다. 그래서 렌더 직후
 * 그 컨테이너에 KaTeX 패스를 한 번 태우면 백엔드·nh3 allowlist·SSR 을 전혀 건드리지 않고
 * 양쪽 경로를 동시에 커버한다(단일 소유·단일 시각 언어).
 *
 * ── 왜 "블록 요소 textContent" 스캔인가 (중요) ──
 * 두 마크다운 엔진은 **여러 줄 블록 `$$…$$` 를 서로 다르게 DOM 청킹**한다:
 *   - Toast(ToastMark): `<p>$$<br>E = mc^2<br>$$</p>` — 여는/닫는 `$$` 가 `<br>` 로 분리된
 *     **별개 텍스트 노드**.
 *   - 백엔드(markdown-it-py): `<p>$$\nE = mc^2\n$$</p>` — 한 텍스트 노드(개행 포함).
 * KaTeX 의 `renderMathInElement`(auto-render)는 텍스트 노드를 **개별로** 훑어 구분자가
 * 노드 경계를 넘으면 매칭하지 못한다 → Toast 의 `<br>` 분리 블록이 렌더되지 않는다(관측).
 * 반면 **블록 요소의 `textContent` 는 자식 노드를 이어 붙인 문자열**이라 `<br>` 이 사라지고
 * `$$E = mc^2$$` 로 복원된다. 그래서 "블록 전체가 곧 하나의 display 수식"인 경우
 * 요소 자체에 `katex.render(displayMode)` 로 통째 렌더하여 노드 분리에 면역이 되게 한다.
 * 남은 인라인 `$…$`·단일 노드 수식은 auto-render 로 보조 처리한다.
 *
 * 편집(WYSIWYG) 표면에는 **적용하지 않는다** — ProseMirror 가 소유한 편집 DOM 의 텍스트
 * 노드를 KaTeX 가 교체하면 에디터 상태가 깨진다. 수식은 읽기 경로에서만 렌더한다
 * (호출부: EditorWrapper read 분기 · ReadOnlyProse html 경로).
 *
 * KaTeX CSS(폰트 포함)는 **이 모듈이 단일 소유**로 import 한다. 다른 곳에서 별도 import 금지.
 */

import katex from "katex";
import type { KatexOptions } from "katex";
// katex `./contrib/auto-render` 서브패스 export 는 types 컨디션이 없어
// moduleResolution:"bundler" 에서 tsc 가 동봉 타입을 찾지 못한다(TS7016). 값 import 는
// 런타임 함수만 받고, 실제 함수 타입은 아래에서 정식으로 재부여한다(EditorWrapper 의 Toast
// 값 import 와 동일한 idiom).
// @ts-expect-error — contrib/auto-render 는 types 컨디션 부재로 값 import 가 타입지정 불가(TS7016).
import renderMathInElementRuntime from "katex/contrib/auto-render";

import "katex/dist/katex.min.css";

/** auto-render 구분자 스펙(좌/우 델리미터 + display 여부). */
interface AutoRenderDelimiter {
  left: string;
  right: string;
  display: boolean;
}

/** `renderMathInElement` 옵션 — KaTeX 렌더 옵션 + auto-render 전용 확장. */
interface AutoRenderOptions extends KatexOptions {
  delimiters?: AutoRenderDelimiter[];
  ignoredTags?: string[];
  ignoredClasses?: string[];
  errorCallback?: (message: string, error: unknown) => void;
}

type RenderMathInElement = (
  elem: HTMLElement,
  options?: AutoRenderOptions,
) => void;

const renderMathInElement = renderMathInElementRuntime as RenderMathInElement;

/** 잘못된 수식이 있어도 렌더 전체를 중단하지 않는다(원문을 오류색으로 남김). */
const KATEX_OPTIONS: KatexOptions = { throwOnError: false };

/**
 * 인라인 구분자. 순서가 중요하다 — 더 긴 구분자(`$$`·`\[`)를 인라인(`$`·`\(`)보다 먼저
 * 매칭해야 인접 인라인이 블록으로 오인되지 않는다. 블록 display 는 아래 스캐너가 선처리하고,
 * 여기서는 한 텍스트 노드 안에 남은 인라인/단일 노드 수식만 보조 처리한다.
 */
const INLINE_DELIMITERS: AutoRenderDelimiter[] = [
  { left: "$$", right: "$$", display: true },
  { left: "\\[", right: "\\]", display: true },
  { left: "$", right: "$", display: false },
  { left: "\\(", right: "\\)", display: false },
];

/** 코드펜스 언어 마커가 math/latex/katex 인지 판정(Toast: data-language·lang-* 클래스). */
const MATH_LANG_RE = /(?:^|[\s-])(?:math|latex|katex)(?:$|[\s-])/i;

/** display 수식을 요소 자체에 통째로 렌더(요소 자식을 KaTeX 출력으로 교체). */
function renderDisplayInto(element: Element, tex: string): void {
  try {
    katex.render(tex.trim(), element as HTMLElement, {
      ...KATEX_OPTIONS,
      displayMode: true,
    });
  } catch {
    // throwOnError:false 로 통상 예외는 없으나, 방어적으로 원문을 보존한다.
  }
}

/**
 * 1) 코드펜스 math 블록(` ```math ` → `<pre><code>`)을 display 로 렌더한다.
 *    Toast 인증 경로는 `data-language="math"`·`lang-math` 마커를 보존하므로 식별 가능하다.
 *    (게스트 백엔드 경로는 nh3 가 언어 클래스를 제거하므로 일반 코드블록으로 남는다 — 수용.)
 */
function renderFencedMath(root: HTMLElement): void {
  root.querySelectorAll("pre > code").forEach((code) => {
    const marker = `${code.getAttribute("data-language") ?? ""} ${
      code.className
    } ${code.parentElement?.className ?? ""}`;
    if (!MATH_LANG_RE.test(marker)) {
      return;
    }
    const pre = code.parentElement;
    if (pre === null) {
      return;
    }
    const wrap = document.createElement("div");
    renderDisplayInto(wrap, code.textContent ?? "");
    pre.replaceWith(wrap);
  });
}

/**
 * 2) 블록 display `$$…$$` 를 렌더한다. **여러 형제 블록에 걸친 경우까지** 처리한다.
 *
 * 마크다운은 `$$` 와 내용 사이에 빈 줄이 있으면 문단을 나눈다. 그래서 사용자가 흔히 쓰는
 *   $$
 *
 *   x+y=1
 *
 *   $$
 * 형태는 Toast/백엔드 모두 `<p>$$</p><p>x+y=1</p><p>$$</p>` 처럼 **여는/닫는 `$$` 가 서로
 * 다른 블록**으로 쪼개진다. 단일 블록 textContent 검사로는 못 잡으므로, 콘텐츠 루트의
 * **형제 블록을 순회하며 여는 `$$` 부터 닫는 `$$` 까지 누적**하여 하나의 display 로 렌더하고
 * 사이 블록들을 제거한다. 한 블록 안에 여닫이가 모두 있는 형태(단일 라인·`<br>` 분리·개행
 * 블록)도 같은 경로로 흡수한다.
 */
function renderBlockMath(container: HTMLElement): void {
  // Toast 는 `.toastui-editor-contents` 하위에 블록을 둔다. 게스트(content_html)는 컨테이너
  // 자신이 블록의 부모다. 어느 쪽이든 "블록의 부모"를 콘텐츠 루트로 삼는다.
  const root =
    container.querySelector(".toastui-editor-contents") ?? container;
  const children = Array.from(root.children);

  let i = 0;
  while (i < children.length) {
    const el = children[i];
    // 이미 렌더된 수식·코드펜스는 건너뛴다.
    if (el.tagName === "PRE" || el.querySelector(".katex") !== null) {
      i += 1;
      continue;
    }
    const text = (el.textContent ?? "").trim();
    if (!text.startsWith("$$")) {
      i += 1;
      continue;
    }

    const afterOpen = text.slice(2);
    // (a) 한 블록에 여닫이가 모두 있는 경우: `$$ … $$`.
    if (afterOpen.endsWith("$$") && afterOpen.length > 2) {
      const inner = afterOpen.slice(0, -2).trim();
      if (inner.length > 0) {
        renderDisplayInto(el, inner);
      }
      i += 1;
      continue;
    }

    // (b) 여는 `$$` 만 있는 경우: 닫는 `$$` 를 만날 때까지 형제 블록을 누적한다.
    const parts: string[] = [];
    if (afterOpen.length > 0) {
      parts.push(afterOpen);
    }
    let j = i + 1;
    let closed = false;
    while (j < children.length) {
      const t = (children[j].textContent ?? "").trim();
      if (t.endsWith("$$")) {
        const beforeClose = t.slice(0, -2);
        if (beforeClose.length > 0) {
          parts.push(beforeClose);
        }
        closed = true;
        break;
      }
      parts.push(t);
      j += 1;
    }
    if (!closed) {
      // 닫는 `$$` 가 없다(오작성) — 원문을 그대로 두고 다음으로 넘어간다.
      i += 1;
      continue;
    }
    const inner = parts.join("\n").trim();
    if (inner.length > 0) {
      renderDisplayInto(el, inner);
      // 여는 블록(el)에 렌더했으므로 사이~닫는 블록(i+1 … j)을 제거한다.
      for (let k = i + 1; k <= j; k += 1) {
        children[k].remove();
      }
    }
    i = j + 1;
  }
}

/**
 * 렌더된 컨테이너의 텍스트에서 LaTeX 수식을 찾아 KaTeX 로 치환한다(제자리 변형).
 * `element` 가 없으면(null/undefined) 무해하게 무시한다. 렌더 실패는 본문 표시를 막지
 * 않는다 — 잘못된 수식은 원문이 그대로 남는다(`throwOnError:false`).
 *
 * 순서: 펜스 → 블록 display → 인라인. 앞 단계가 처리한 요소에는 `$` 가 남지 않으므로
 * 뒤 단계가 이중 처리하지 않는다.
 */
export function renderMathIn(element: HTMLElement | null | undefined): void {
  if (!element) {
    return;
  }
  try {
    renderFencedMath(element);
    renderBlockMath(element);
    renderMathInElement(element, {
      delimiters: INLINE_DELIMITERS,
      throwOnError: false,
      // 코드/스크립트/편집영역 텍스트의 `$` 는 수식이 아니다 — 오탐 방지로 건너뛴다.
      ignoredTags: [
        "script",
        "noscript",
        "style",
        "textarea",
        "pre",
        "code",
        "option",
      ],
      // 이미 렌더된 KaTeX 내부는 다시 훑지 않는다.
      ignoredClasses: ["katex"],
    });
  } catch {
    // auto-render 자체가 던지는 예외도 본문 표시를 막지 않는다 — 원문 텍스트가 남는다.
  }
}
