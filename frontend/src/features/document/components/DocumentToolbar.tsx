/**
 * DocumentToolbar — 문서 조작 단일 컨트롤 행 (design.md §화면 컴포넌트 DocumentToolbar).
 *
 * 트리 표시 토글 · 생성/이름변경 · 편집/삭제 진입 seam 을 **한 행**으로 합쳐 소유한다.
 * 행 전체를 하나의 `flex` 컨테이너로 두어 좌측(토글·입력·생성/이름변경)과 우측(편집·삭제,
 * `ml-auto` 로 오른쪽 정렬)을 한 줄에 배치한다.
 *
 * **휴지통 모드(`trashMode`)**: 패널이 휴지통을 표시 중이면 생성 클러스터(입력·이름 바꾸기·
 * 새문서·하위문서 추가)와 편집·삭제를 **통째로** 내리고 복구·완전삭제만 노출한다. 절반만 교체하면
 * "일부는 살아있고 일부는 죽은 툴바"가 되어 어떤 컨트롤이 무엇에 작용하는지 모호해지기 때문이다.
 * 대상은 항상 **묶음**이므로 버튼 옆에 `"{루트 제목}" 묶음 n개` 를 함께 적어 복구 단위를 명시한다.
 *
 * 게이팅은 두 축으로 분리된다:
 * - 트리 토글: 권한과 무관하게 모든 사용자에게 노출(읽기 전용 뷰어 포함). `onToggleTree` 가
 *   주입되지 않으면 렌더하지 않는다(단독 사용 시 토글 생략). 패널이 접혀 있을 때의 라벨은
 *   `canUseTrash`(member+) 에 따라 "문서 목록/휴지통 보기" 또는 "문서 목록 보기"로 통합한다 —
 *   패널을 접으면 패널 상단의 모드 탭도 함께 사라지므로, 다시 여는 단일 진입점이 두 대상 모두를
 *   가리켜야 휴지통이 도달 불가능해지지 않는다.
 * - 생성·이름변경: `<RequireRole minimum={MEMBER} currentRole=...>` 단일 게이트로 감싼다
 *   (Req 3.6·4.5·9.2). admin override(세션 is_admin)는 RequireRole 내부가 소유하므로 여기서
 *   별도 role 비교를 하지 않는다. `RequireRole` 은 래퍼 DOM 을 만들지 않아, fragment 로 감싼
 *   입력·버튼들이 행 flex 의 직접 자식이 되어 나란히 배치된다.
 * - 편집·삭제: `canEdit`(admin override 포함, 상위 페이지가 판정) + 선택 문서 존재 시에만 노출한다.
 * - 공유(우측 클러스터, Req 3.1~3.4): 편집·삭제 옆에서 `!trashMode && canShare && shareable &&
 *   hasSelection` 일 때만 sharing 배럴의 `<DocumentShareControl>` 을 마운트한다. `canShare` 는
 *   owner+/admin(상위 페이지가 `hasWorkspaceRole({minimum:OWNER})` 로 산정, canEdit 의 MEMBER 최소보다
 *   좁은 축), `shareable` 은 WS 공유 가능 여부다. owner⊇member 이므로 canShare 이면 편집·삭제 클러스터도
 *   함께 존재해 하나의 우측 클러스터로 묶인다. 프론트 노출 게이팅은 UX 편의일 뿐 서버 강제를 대체하지
 *   않는다(Req 3.5).
 *
 * 단일 입력(하나의 텍스트 필드)이 세 조작에 공유된다:
 * - 프리필: 선택 문서의 현재 제목(`selectedTitle`). 선택이 바뀌면 새 제목으로 재프리필한다.
 * - 이름 바꾸기(Req 4.1): 입력값으로 선택 문서를 rename(selectedId, title). 선택 필요.
 * - 새문서(Req 3.1): 입력값을 제목으로 루트 문서 create({ title, parentId: null }).
 * - 하위문서 추가(Req 3.1): 입력값을 제목으로 선택 문서의 자식 create({ title, parentId: selectedId }).
 * 제목은 trim 후 공백이면 버튼을 비활성화(서버도 422 로 방어).
 *
 * 삭제(Req 5.1): 삭제 버튼 클릭 시 로컬 `ConfirmDialog`(irreversible=false, 휴지통행이라 복구 가능)로
 * 확인받고, 확인 시 `onDelete?.(selectedId)` seam 을 호출한다. 확인 문구는 `selectedTitle` 로 구성한다.
 * 실제 삭제 변이(휴지통 이동·트리 반영·오류 표면화)는 상위 페이지의 `useDocumentMutations` 가 소유한다.
 *
 * 편집(Req 7.4·7.5): 편집 버튼 클릭 시 `onEnterEdit?.(selectedId)` seam 을 호출한다. 실제 편집
 * 모드 동작(lock/자동저장/버전)은 s20 이 소유하며 여기서는 진입점만 노출한다.
 *
 * 오류(Req 9.4 소비): create/rename/삭제가 공유하는 `mutations.state.error` 는 상위 페이지가 단일
 * sink 로 표면화한다(여기서 표시하지 않는다).
 *
 * Requirements: 3.1(생성), 3.6·4.5·9.2(RequireRole 단일 게이트), 4.1(이름변경), 5.1(삭제),
 *   7.4·7.5(편집 진입 seam), s28 3.1~3.5(공유 클러스터 노출 게이트).
 */

import { useEffect, useState } from "react";
import type { ReactElement } from "react";

import { Role } from "@/shared/auth/roles";
import { RequireRole } from "@/shared/auth/RequireRole";
import { Button } from "@/shared/ui";
// 공유 컨트롤은 sharing feature 배럴에서 교차-feature import 로 결선한다(DocumentViewer →
// @/features/attachment 와 동일 선례, 비순환). sharing 내부 조각(useShareManager 등)이 아니라
// 배럴이 공개한 자기완결 컨트롤만 소비한다.
import { DocumentShareControl } from "@/features/sharing";
import type { useDocumentMutations } from "../hooks/useDocumentMutations";
import { ConfirmDialog } from "./ConfirmDialog";

export interface DocumentToolbarProps {
  /** 변이 오케스트레이션(생성·이름변경·삭제 + 상태). 주입된 의존을 그대로 소비한다. */
  mutations: ReturnType<typeof useDocumentMutations>;
  /** RequireRole 게이팅용 현재 WS role(useDocumentScope().role 주입). 비멤버·미확정이면 null. */
  currentRole: Role | null;
  /** 현재 선택 문서 id(이름변경·삭제·편집 대상, 하위 생성 부모). 없으면 null. */
  selectedId: number | null;
  /** 선택 문서 현재 제목(이름변경 프리필·삭제 확인 문구). 없으면 null. */
  selectedTitle: string | null;
  /** 트리 패널 표시 여부(토글 라벨·aria-expanded). `onToggleTree` 와 함께 제공해야 토글이 렌더된다. */
  treeVisible?: boolean;
  /** 트리 패널 표시 토글 seam. 미제공 시 토글 버튼을 렌더하지 않는다. */
  onToggleTree?: () => void;
  /** editor+ 여부(편집·삭제 seam 노출, admin override 포함). 상위 페이지가 판정. 기본 false. */
  canEdit?: boolean;
  /**
   * owner+ 여부(공유 컨트롤 노출 축, admin override 포함). 상위 페이지가 `hasWorkspaceRole({minimum:OWNER})`
   * 로 판정해 주입한다. canEdit(minimum MEMBER)보다 좁은 별도 축이다(owner⊇member 라 canShare 이면
   * canEdit 도 참). 기본 false. 프론트 게이팅은 UX 편의일 뿐 서버 강제를 대체하지 않는다(Req 3.5).
   */
  canShare?: boolean;
  /** 현재 워크스페이스 공유 가능 여부(useDocumentScope().isShareable 주입). false 면 공유 컨트롤 미노출. 기본 false. */
  shareable?: boolean;
  /** 편집 진입 seam — 편집 버튼 클릭 시 호출(동작은 s20 소유). */
  onEnterEdit?: (documentId: number) => void;
  /** 삭제 seam — 삭제 확인 후 호출(실제 휴지통 이동 변이는 상위 페이지 소유, Req 5.1). */
  onDelete?: (documentId: number) => void;
  /** 패널이 휴지통을 표시 중인지. 참이면 생성/편집/삭제 대신 복구·완전삭제를 노출한다. */
  trashMode?: boolean;
  /** 휴지통 사용 가능(member+) 여부. 접힘 상태 토글 라벨에만 쓴다(뷰어는 "문서 목록 보기"). */
  canUseTrash?: boolean;
  /** 현재 선택된 휴지통 묶음 요약. null 이면 복구·완전삭제를 노출하지 않는다. */
  trashSelection?: { rootTitle: string; memberCount: number } | null;
  /** 복구 seam — 묶음 전체 복구(되돌릴 수 있으므로 확인 없이 즉시 발화). */
  onRestore?: () => void;
  /** 완전삭제 seam — 비가역 ConfirmDialog 확인 이후에만 발화. */
  onPurge?: () => void;
}

/**
 * 문서 조작 단일 컨트롤 행. 트리 토글 + (RequireRole 게이트) 입력·생성·이름변경 + (canEdit 게이트)
 * 편집·삭제(오른쪽 정렬)를 한 줄로 배치한다.
 */
export function DocumentToolbar({
  mutations,
  currentRole,
  selectedId,
  selectedTitle,
  treeVisible,
  onToggleTree,
  canEdit = false,
  canShare = false,
  shareable = false,
  onEnterEdit,
  onDelete,
  trashMode = false,
  canUseTrash = false,
  trashSelection = null,
  onRestore,
  onPurge,
}: DocumentToolbarProps): ReactElement {
  // 세 조작(이름변경·새문서·하위문서 추가)이 공유하는 단일 입력. 선택 문서 제목으로 프리필한다.
  const [title, setTitle] = useState(selectedTitle ?? "");
  // 삭제 확인 모달 개폐(로컬 UI 상태).
  const [confirmOpen, setConfirmOpen] = useState(false);
  // 완전삭제(비가역) 확인 모달 개폐(로컬 UI 상태).
  const [purgeOpen, setPurgeOpen] = useState(false);

  // 선택 문서가 바뀌면 입력을 새 제목으로 재프리필한다(서버 제목 기준).
  useEffect(() => {
    setTitle(selectedTitle ?? "");
  }, [selectedId, selectedTitle]);

  const pending = mutations.state.pending;
  const hasSelection = selectedId !== null;
  const trimmed = title.trim();
  const emptyTitle = trimmed.length === 0;

  const submitCreate = (parentId: number | null): void => {
    if (emptyTitle) {
      // 클라이언트 가드: 빈 제목 미제출(서버도 422로 방어).
      return;
    }
    void mutations.create({ title: trimmed, parentId });
  };

  const submitRename = (): void => {
    if (selectedId === null || emptyTitle) {
      return;
    }
    void mutations.rename(selectedId, trimmed);
  };

  // 접힘 상태에서는 두 대상(문서 목록·휴지통)을 함께 가리키는 통합 라벨을 쓴다 — 패널을 접으면
  // 모드 탭도 사라지므로 이 버튼이 휴지통의 유일한 재진입점이 된다. 뷰어(휴지통 불가)는 기존 라벨.
  const toggleLabel = treeVisible
    ? trashMode
      ? "휴지통 숨기기"
      : "문서 목록 숨기기"
    : canUseTrash
      ? "문서 목록/휴지통 보기"
      : "문서 목록 보기";

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* 트리 토글 — 권한과 무관하게 모든 사용자에게 노출. onToggleTree 주입 시에만 렌더. */}
      {onToggleTree ? (
        <Button
          variant="secondary"
          onClick={onToggleTree}
          aria-expanded={treeVisible ?? false}
          aria-controls="document-tree-panel"
        >
          {toggleLabel}
        </Button>
      ) : null}

      {trashMode ? (
        /* 휴지통 모드 — 생성·편집·삭제를 전부 내리고 묶음 복구·완전삭제만 노출한다.
           대상이 묶음임을 버튼 옆 텍스트로 명시해 "이 문서만 돌아온다"는 오해를 막는다. */
        trashSelection !== null ? (
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <span className="max-w-64 truncate text-sm text-slate-600">
              {`"${trashSelection.rootTitle}" 묶음 ${trashSelection.memberCount}개`}
            </span>
            <Button variant="primary" onClick={() => onRestore?.()}>
              복구
            </Button>
            <Button
              variant="secondary"
              onClick={() => setPurgeOpen(true)}
              className="border-red-300 text-red-700 hover:bg-red-50 focus-visible:ring-red-400"
            >
              완전삭제
            </Button>
          </div>
        ) : null
      ) : (
        <>
      {/* 생성·이름변경 — RequireRole(MEMBER) 단일 게이트. RequireRole 은 래퍼 DOM 을 만들지 않아
          입력·버튼들이 행 flex 의 직접 자식으로 나란히 배치된다. */}
      <RequireRole minimum={Role.MEMBER} currentRole={currentRole}>
        <input
          type="text"
          aria-label="문서 이름"
          placeholder="문서 이름"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          className="w-48 min-w-0 rounded-md border border-slate-300 px-3 py-2 text-sm sm:w-56 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400"
        />
        <Button
          variant="secondary"
          disabled={pending || !hasSelection || emptyTitle}
          onClick={submitRename}
        >
          이름 바꾸기
        </Button>
        <Button
          variant="primary"
          disabled={pending || emptyTitle}
          onClick={() => submitCreate(null)}
        >
          새문서
        </Button>
        <Button
          variant="secondary"
          disabled={pending || !hasSelection || emptyTitle}
          onClick={() => submitCreate(selectedId)}
        >
          하위문서 추가
        </Button>
      </RequireRole>

      {/* 우측 클러스터(편집·삭제 + 공유) — ml-auto 로 오른쪽 정렬. 편집·삭제와 공유는 서로 독립
          축이지만 owner⊇member 이므로 canShare 이면 canEdit 도 참이라 항상 한 덩어리 우측 클러스터로
          묶인다. 클러스터 자체는 선택이 있고(편집·삭제 또는 공유) 중 하나라도 노출될 때 렌더한다. */}
      {hasSelection && (canEdit || (canShare && shareable)) ? (
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {canEdit ? (
            <>
              <Button variant="primary" onClick={() => onEnterEdit?.(selectedId)}>
                편집
              </Button>
              <Button
                variant="secondary"
                onClick={() => setConfirmOpen(true)}
                className="border-red-300 text-red-700 hover:bg-red-50 focus-visible:ring-red-400"
              >
                삭제
              </Button>
            </>
          ) : null}
          {/* 공유 컨트롤 — canShare(owner+/admin) && shareable(WS 공유 가능) 일 때만 노출한다.
              trashMode 는 이 분기(else) 밖이라 자동으로 배제되고(휴지통=비active, Req 3.4),
              active 문맥에서만 마운트되므로 documentStatus 는 상수 "active" 로 안전하다. 노출 게이트
              자체(owner/admin·공유가능·active·선택)는 여기(툴바)가 소유하고, 컨트롤은 마운트되면
              공유 상태 조회·토글·복사를 자기완결로 수행한다. */}
          {canShare && shareable ? (
            <DocumentShareControl documentId={selectedId} documentStatus="active" />
          ) : null}
        </div>
      ) : null}
        </>
      )}

      {/* 삭제 확인 모달(휴지통행이라 복구 가능 → irreversible=false). 확인 시 삭제 seam 호출. */}
      <ConfirmDialog
        open={confirmOpen}
        irreversible={false}
        title="문서 삭제"
        message={`"${selectedTitle ?? ""}" 문서와 하위 문서 묶음이 함께 휴지통으로 이동합니다. 휴지통에서 복구할 수 있습니다.`}
        confirmLabel="휴지통으로 이동"
        cancelLabel="취소"
        onConfirm={() => {
          if (selectedId !== null) {
            onDelete?.(selectedId);
          }
          setConfirmOpen(false);
        }}
        onCancel={() => setConfirmOpen(false)}
      />

      {/* 완전삭제 확인 모달(비가역). 백엔드 purge 계약(복구 불가)과 정합을 이룬다. */}
      <ConfirmDialog
        open={purgeOpen}
        irreversible
        title="완전삭제"
        message={`"${trashSelection?.rootTitle ?? ""}" 묶음 ${trashSelection?.memberCount ?? 0}개 문서를 완전히 삭제합니다.`}
        confirmLabel="완전삭제"
        cancelLabel="취소"
        onConfirm={() => {
          onPurge?.();
          setPurgeOpen(false);
        }}
        onCancel={() => setPurgeOpen(false)}
      />
    </div>
  );
}
