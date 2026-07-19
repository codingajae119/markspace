/**
 * 워크스페이스 생성 폼 (design.md "WorkspaceSwitcher / CreateWorkspaceDialog", Req 2.1·2.2·2.4).
 *
 * 이름 입력과 제출 컨트롤(`<form>` + submit 버튼)을 렌더하고, 제출 시 `useWorkspaceActions().create`
 * 를 호출한다. 생성 성공/실패 후처리(owner 기록·s16 refresh·현재 WS 선택·오류 상태)는 훅 소관이며
 * 이 폼은 트림된 이름 전달·성공 시 입력 초기화만 담당한다.
 *
 * - **클라이언트 가드**: 빈/공백-only 이름은 요청 전에 막는다(Req 2.2). 제출 버튼을 비활성화하고,
 *   폼 제출 핸들러에서도 재확인해 방어한다(버튼 우회 제출 방지).
 * - **성공 신호**: `create` 가 생성물을 반환하면(성공) 입력을 초기화한다. `null`(실패) 이면 유지.
 * - **오류 표시**: 서버 422 등은 `useWorkspaceActions().error` 를 s16 `ErrorMessage` 로 인라인 표시(Req 2.4).
 * - **진행 중**: `creating` 동안 입력·제출을 비활성화하고 `Spinner` 로 로딩을 표시(중복 제출 방지).
 *
 * 계약 경계(모두 s16 소비): `Button`·`Spinner`·`ErrorMessage` 는 `@/shared/ui` 배럴에서만, 생성
 * useCase 는 같은 feature 의 `useWorkspaceActions` 에서만 소비한다(다른 feature import 금지).
 *
 * Requirements: 2.1(이름 입력·생성), 2.2(빈/공백 이름 방지 또는 422 표시), 2.4(실패 오류 인라인 표시).
 */

import { useState, type FormEvent, type ReactElement } from "react";

import { Button, Spinner, ErrorMessage } from "@/shared/ui";
import { useWorkspaceActions } from "../hooks/useWorkspaceActions";

/** 워크스페이스 이름 입력·생성 폼. useWorkspaceActions 로 생성 뮤테이션에 결선한다. */
export function CreateWorkspaceDialog(): ReactElement {
  const { create, creating, error } = useWorkspaceActions();
  const [name, setName] = useState("");

  const trimmed = name.trim();
  const canSubmit = trimmed.length > 0 && !creating;

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    // 기본 폼 제출(페이지 리로드)을 막고 훅 플로우로만 진행한다.
    event.preventDefault();
    // 클라이언트 가드: 빈/공백-only 이름은 요청 전에 차단(Req 2.2).
    if (trimmed.length === 0) {
      return;
    }
    // 성공(생성물 반환) 시 입력 초기화, 실패(null) 시 유지.
    void create({ name: trimmed }).then((workspace) => {
      if (workspace) {
        setName("");
      }
    });
  };

  return (
    <form onSubmit={handleSubmit} noValidate>
      <div>
        <label htmlFor="workspace_name">워크스페이스 이름</label>
        <input
          id="workspace_name"
          name="workspace_name"
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          disabled={creating}
        />
      </div>

      {/* 단일 에러 표시 유틸(s16). error 가 null 이면 아무것도 렌더하지 않는다. */}
      <ErrorMessage error={error} />

      <Button type="submit" disabled={!canSubmit}>
        {creating ? <Spinner /> : "워크스페이스 생성"}
      </Button>
    </form>
  );
}
