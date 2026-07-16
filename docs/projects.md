# Notion-lite: 최종 명세서

> 소규모 폐쇄형(closed) 협업 문서 서비스. Notion과 유사하나 필수 기능만 포함한다.
>
> **기술 스택**
> - DB: MySQL 8
> - Backend: FastAPI (Python)
> - Frontend: React + Vite + Tailwind CSS 4
> - 구현 방식: Claude Code + cc-sdd (Spec-Driven Development)
>
> 본 문서는 cc-sdd의 `spec-requirements` / `spec-design` 단계 입력으로 사용하는 것을 전제로,
> 수용 기준(EARS 스타일) · 데이터 모델 · 상태 전이 · 도메인 불변식을 명시한다.

---

## 1. 서비스 개요

폐쇄형 서비스로, 회원 가입 흐름은 존재하지 않는다. 모든 사용자 계정은 **단일 admin**이 수동 등록한다.
사용자는 하나 이상의 워크스페이스에 소속되어, 계층적 markdown 문서를 편집·열람하고,
읽기 전용 링크로 외부에 공유할 수 있다.

### 1.1 핵심 개념

| 개념 | 설명 |
|------|------|
| **User** | id/password로 로그인하는 일반 사용자. admin이 생성. |
| **Admin** | 단일 관리자. DB에 수동(manual) 설정. 사용자 CRUD·비활동 처리·소유권 변경 권한. |
| **Workspace** | 문서의 최상위 컨테이너. 사용자별 권한(owner/editor/viewer)이 부여되는 단위. |
| **Document** | 워크스페이스에 속하는 계층적 markdown 문서. |
| **Version** | 문서 저장 시마다 생성되는 스냅샷(무한 보관, rollback 없음). |
| **Attachment** | 문서에 붙는 이미지·첨부 파일. 파일로 저장, 워크스페이스별 격리. |
| **Share Link** | 문서 단위 읽기 전용 공개 링크. |

### 1.2 권한 3종 (워크스페이스 레벨 한정)

권한은 **워크스페이스 단위로만** 부여된다. 문서별 개별 권한은 없다.

| 권한 | 문서 읽기 | 문서 CRUD | 하위 문서 생성 | 휴지통 접근 | 멤버/권한 관리 | 워크스페이스 생성·삭제 | 공유 플래그 설정 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **viewer** | O | X | X | X | X | X | X |
| **editor** | O | O | O | O | X | X | X |
| **owner**  | O | O | O | O | O | O | O |

- owner는 복수일 수 있다.
- owner는 editor의 모든 권한을 포함한다("editor 이상이 CRUD").
- admin은 위 표와 무관하게 **모든 워크스페이스·문서·데이터에 제약 없이 접근**한다(멤버가 아니어도 접근 가능).

---

## 2. 데이터 모델 (MySQL 8)

논리 모델이다. 실제 DDL·인덱스·제약은 design 단계에서 확정한다.

### 2.1 user

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGINT PK | 내부 식별자 |
| login_id | VARCHAR, UNIQUE | 로그인 id |
| password_hash | VARCHAR | 해시된 비밀번호 |
| name | VARCHAR | 이름 |
| email | VARCHAR | 이메일 |
| is_active | BOOLEAN | 비활동 여부(로그인 금지 시 false) |
| is_deleted | BOOLEAN | soft-delete flag. true여도 레코드는 보존 |
| created_at / updated_at | DATETIME | |

- 삭제·비활동은 flag 변경만 수행한다(물리 삭제 없음).
- `is_deleted = true` 사용자도 문서 작성자·버전 히스토리에 **이름이 그대로 표시**된다.
- `is_active = false`(비활동)와 `is_deleted = true`(삭제)는 별개 상태다.
- 삭제된 사용자는 flag만 되돌리면 **재활성화**된다.

### 2.2 workspace

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGINT PK | |
| name | VARCHAR | 워크스페이스 이름 |
| is_shareable | BOOLEAN | 공유 가능 플래그(게이트). owner/admin이 설정 |
| trash_retention_days | INT | 휴지통 보관일. 기본 30, 설정 가능 |
| created_at / updated_at | DATETIME | |

### 2.3 workspace_member (사용자 ↔ 워크스페이스, N:M + 권한)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGINT PK | |
| workspace_id | BIGINT FK | |
| user_id | BIGINT FK | |
| role | ENUM('owner','editor','viewer') | |

- 한 사용자는 여러 워크스페이스에 소속될 수 있다.
- (workspace_id, user_id) 조합은 유일하다.

### 2.4 document

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGINT PK | |
| workspace_id | BIGINT FK | 소속 워크스페이스 |
| parent_id | BIGINT FK NULL | 상위 문서(루트면 NULL). 계층 구조 |
| title | VARCHAR | 문서 제목 |
| status | ENUM('active','trashed','deleted') | 문서 상태 3단계 (§4) |
| sort_order | INT/DECIMAL | 같은 부모 내 재정렬용 순서 |
| current_version_id | BIGINT FK NULL | 현재 표시 버전 |
| lock_user_id | BIGINT FK NULL | 편집 잠금 보유자(NULL이면 미잠금) |
| lock_acquired_at | DATETIME NULL | 잠금 시각 |
| trashed_at | DATETIME NULL | 휴지통 진입 시각(보관일 기산점). **삭제 항목별로 독립 보유** |
| created_by | BIGINT FK | 최초 작성자 |
| created_at / updated_at | DATETIME | |

- `sort_order`는 삭제 후에도 컬럼에 **보존**되어 복구 시 원위치 복원에 사용된다(§4.2). DECIMAL 권장(형제 사이 중간 삽입 지원).
- `parent_id`는 삭제 시에도 유지되며, 복구 시 부모 상태에 따라 재해석된다(§4.2).

### 2.5 document_version

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGINT PK | |
| document_id | BIGINT FK | |
| content | MEDIUMTEXT/LONGTEXT | markdown 본문 스냅샷 |
| created_by | BIGINT FK | 저장한 사용자 |
| created_at | DATETIME | |

- 저장(save) 시마다 새 버전 레코드 생성. **무한 보관**.
- rollback(과거 버전 복원) 기능은 제공하지 않는다. 열람 UI 제공 여부는 design 단계 판단.

### 2.6 attachment

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGINT PK | |
| workspace_id | BIGINT FK | 워크스페이스별 격리 |
| document_id | BIGINT FK | 참조 문서 |
| file_path | VARCHAR | 파일 저장 경로(WS별 격리 디렉터리) |
| original_name | VARCHAR | 원본 파일명 |
| kind | ENUM('image','file') | 붙여넣기 이미지 / 일반 첨부 |
| is_archived | BOOLEAN | "삭제된 파일 보관 폴더"로 이동 여부 |
| created_at | DATETIME | |

- 붙여넣기 이미지도 **파일로 저장**한다(base64 인라인 아님).
- 파일 물리 저장·보관 폴더 모두 **워크스페이스별로 격리**한다.

### 2.7 share_link

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGINT PK | |
| document_id | BIGINT FK | 공유 대상 문서(문서 단위 공유) |
| token | VARCHAR UNIQUE | 공개 URL 토큰 |
| is_enabled | BOOLEAN | 토글 on/off |
| created_at | DATETIME | |

- 공유는 **문서 단위**다. 워크스페이스 `is_shareable`는 공유 허용 여부의 **게이트**일 뿐이다.

---

## 3. 기능 요구사항 (수용 기준 · EARS 스타일)

각 요구사항은 cc-sdd requirements 단계의 Acceptance Criteria로 전개 가능하도록
`WHEN / IF ... THEN the system shall ...` 형태로 기술한다.

### REQ-1. 인증·계정

1.1 WHEN 사용자가 올바른 login_id와 password를 제출하면 THEN 시스템은 세션을 생성하고 로그인시킨다.
1.2 IF 사용자의 `is_active`가 false이면 THEN 시스템은 자격 증명이 맞아도 로그인을 거부한다.
1.3 IF 사용자의 `is_deleted`가 true이면 THEN 시스템은 로그인을 거부한다.
1.4 WHEN 로그인한 사용자가 로그아웃하면 THEN 시스템은 세션을 종료한다.
1.5 WHEN 로그인한 사용자가 현재 비밀번호와 새 비밀번호를 제출하면 THEN 시스템은 본인 비밀번호를 변경한다.
1.6 IF 사용자가 비밀번호를 분실하면 THEN 재설정은 **admin만** 수행할 수 있다(사용자 self-reset 없음).
1.7 회원 가입(self sign-up) 기능은 제공하지 않는다.

### REQ-2. Admin

2.1 admin은 단일 계정이며 DB에 수동 설정된다(애플리케이션 상 admin 생성 기능 없음).
2.2 WHEN admin이 사용자 등록을 요청하면 THEN 시스템은 신규 user 계정을 생성한다.
2.3 WHEN admin이 사용자 삭제를 요청하면 THEN 시스템은 해당 user의 `is_deleted`를 true로 설정한다(물리 삭제 없음).
2.4 WHEN admin이 사용자 비활동 처리를 하면 THEN 시스템은 `is_active`를 false로 설정하여 로그인을 금지한다.
2.5 WHEN admin이 삭제된 사용자의 flag를 되돌리면 THEN 해당 사용자는 재활성화된다.
2.6 admin은 모든 워크스페이스·문서·데이터에 멤버 여부와 무관하게 접근할 수 있다.
2.7 WHEN admin이 특정 워크스페이스의 owner를 변경하면 THEN 시스템은 워크스페이스 소유권을 갱신한다.

### REQ-3. 워크스페이스

3.1 WHEN owner 또는 admin이 워크스페이스 생성을 요청하면 THEN 시스템은 워크스페이스를 생성한다.
3.2 WHEN owner 또는 admin이 워크스페이스 삭제를 요청하면 THEN 시스템은 워크스페이스를 삭제한다.
3.3 WHEN owner가 전체 사용자 목록에서 사용자를 선택해 워크스페이스에 추가하면 THEN 시스템은 지정한 role로 멤버를 등록한다.
3.4 WHEN owner가 멤버를 제거하면 THEN 시스템은 해당 멤버십을 삭제한다.
3.5 WHEN owner가 멤버의 role을 변경하면 THEN 시스템은 권한을 갱신한다.
3.6 한 워크스페이스에는 복수의 owner가 존재할 수 있다.
3.7 IF 워크스페이스의 유일한 owner가 비활동/삭제되어도 THEN editor·viewer의 활동에는 영향이 없으며, owner 변경이 필요하면 admin이 수행한다.

### REQ-4. 문서 — 기본 CRUD·계층

4.1 WHEN editor 이상이 문서 생성을 요청하면 THEN 시스템은 active 상태의 문서를 생성한다.
4.2 WHEN editor 이상이 특정 문서의 하위 문서 생성을 요청하면 THEN 시스템은 해당 문서를 parent로 하는 문서를 생성한다.
4.3 viewer는 문서를 읽을 수만 있고 생성·수정·삭제할 수 없다.
4.4 WHEN 사용자가 문서를 열면 THEN 시스템은 현재 버전의 markdown을 렌더링해 보여준다.
4.5 시스템은 편집 화면에서 markdown preview 창을 제공한다.
4.6 WHEN editor 이상이 문서를 같은 워크스페이스 내 다른 위치로 이동/재정렬하면 THEN 시스템은 parent_id/sort_order를 갱신한다.
4.7 문서 이동은 **같은 워크스페이스 내**로 한정된다(타 워크스페이스 이동 불가).
4.8 IF 이동 대상이 자기 자신 또는 자신의 하위 문서이면 THEN 시스템은 이동을 거부한다(순환 방지).

### REQ-5. 편집 잠금(lock)·버전

5.1 WHEN editor 이상이 "편집 시작"을 하면 THEN 시스템은 해당 문서에 편집 잠금을 설정한다.
5.2 IF 문서가 다른 사용자에 의해 잠겨 있으면 THEN 시스템은 편집 시작을 막고 UI에 "다른 사용자가 편집 중"임을 표시한다.
5.3 WHEN 편집자가 "저장"하면 THEN 시스템은 새 document_version을 생성하고 current_version을 갱신하며 잠금을 해제한다.
5.4 WHEN 편집자가 저장하지 않고 편집을 취소/이탈하면 THEN 시스템은 잠금을 해제하고 변경분을 폐기한다.
5.5 lock 자동 타임아웃은 두지 않는다.
5.6 WHEN owner 또는 admin이 강제 해제를 하면 THEN 시스템은 잠금을 해제한다(편집 중이던 변경분은 폐기).
5.7 각 저장은 새 버전을 만들며 버전은 무한 보관된다. rollback 기능은 없다.

### REQ-6. 문서 상태 3단계·휴지통 (핵심 §4 참조)

**모델 요지:** 삭제는 그 시점의 서브트리를 **묶음(bundle)** 으로 포착한다. 서로 다른 시점의 삭제는 **별개 묶음**이며, 이후에도 서로 흡수·병합되지 않는다. 먼저 삭제된 자식은 부모가 나중에 삭제되어도 **독립 항목**으로 유지되고, 각자 자신의 보관 타이머를 갖는다.

6.1 문서 status는 active → trashed → deleted 세 단계를 가진다.

6.2 WHEN editor 이상이 active 문서를 삭제하면 THEN 시스템은 해당 문서와 **그 시점의 active 하위 문서만** 하나의 묶음으로 trashed 전환하고 묶음 공통 trashed_at을 기록한다.
- 6.2.1 이미 trashed 상태인 하위(먼저 삭제된 자식)는 이 캐스케이드에서 **제외**한다. 흡수·재편입하지 않으며, 그 자식은 자신의 기존 묶음·기존 trashed_at을 그대로 유지한다.

6.3 editor 이상은 active 상태에서 **하위 문서만 개별 삭제**(trashed 전환)할 수 있다. 이 경우 그 자식(및 자식의 active 하위)은 휴지통에서 **독립 묶음**이 된다.

6.4 IF 자식이 부모보다 먼저 trashed되어 독립 묶음으로 존재하는 상태에서 부모가 trashed되면 THEN 시스템은 그 자식을 **흡수하지 않고 독립 묶음으로 유지**한다.
- 6.4.1 자식과 부모는 서로 다른 trashed_at을 가지므로 **보관 타이머가 분리**된다. 동일 `trash_retention_days`라면 통상 **자식이 부모보다 먼저 만료(deleted)** 된다. 이 동작은 의도된 것으로 수용한다.
- 6.4.2 (불변) 별개 묶음인 자식은 항상 부모보다 먼저 trash에 진입했으므로 `child.trashed_at ≤ parent.trashed_at`이 성립한다. "부모가 자식보다 먼저 독립 trash 항목이 되는" 상황은 캐스케이드(6.2)로 인해 발생하지 않는다.

6.5 **복구 위치는 복구 실행 시점의 부모 상태로 결정한다.**
- 6.5.1 IF 복구 대상의 부모가 **active**이면 THEN 자식(묶음)을 **부모 밑으로** 복귀시킨다(parent_id 유지).
- 6.5.2 IF 부모가 **non-active**(trashed 또는 deleted, 혹은 부재)이면 THEN 자식(묶음)을 **root로** 복귀시킨다(parent_id = NULL).
- 6.5.3 자식을 root로 복구한 뒤 부모를 복구하더라도 시스템은 자식을 부모 밑으로 **자동 재중첩하지 않는다**. 재중첩이 필요하면 사용자가 수동 이동(REQ-4.6)한다.
- 6.5.4 (대칭) 부모를 먼저 복구해 active로 만든 뒤 자식을 복구하면 6.5.1에 의해 부모 밑으로 복귀한다.
- 6.5.5 복구는 부모 status 1회 검사만으로 결정된다. 물리 삭제가 없으므로(INV-4) dangling FK는 발생하지 않으며, 부모가 deleted status면 6.5.2의 non-active로 처리된다.

6.6 하위 묶음은 **독립 복구가 가능**하다(먼저 삭제되어 독립 항목이 된 자식은 부모와 무관하게 단독 복구 가능). 단, 복구 위치는 6.5를 따른다.

6.7 **복구 시 sort_order는 가능한 한 원위치로 복원한다.**
- 6.7.1 (부모 밑 복귀, 6.5.1·6.5.4) 보존된 원래 sort_order로 재삽입한다. 해당 위치가 비어 있으면 그대로 복원하고, 충돌하면 원래 직전·직후 형제 사이 중간값으로 삽입한다. 원래 이웃 형제가 모두 사라졌으면 가장 가까운 잔존 형제 기준 근사 위치, 그마저 불가하면 **맨 뒤 append**로 폴백한다.
- 6.7.2 (root 복귀, 6.5.2) 원위치가 "부모 밑"이라 재현 불가하므로 원위치 복원을 적용하지 않고 **root 맨 뒤 append**한다.

6.8 WHEN 문서 묶음이 trashed된 지 워크스페이스의 `trash_retention_days`(기본 30일)를 경과하면 THEN 시스템은 **그 묶음을** deleted(영구삭제)로 전환한다. 타이머는 묶음별 trashed_at을 기준으로 독립 산정한다.

6.9 WHEN editor 이상이 휴지통에서 "완전 삭제"를 하면 THEN 시스템은 해당 **묶음 전체**를 즉시 deleted로 전환한다(다른 독립 묶음에는 영향 없음).

6.10 완전 삭제는 되돌릴 수 없으므로 UI는 확인 절차를 제공한다.

6.11 editor 이상은 **워크스페이스 휴지통 전체**(본인 삭제분 외 포함)를 열람·복구·완전삭제할 수 있다. viewer는 휴지통에 접근할 수 없다.

### REQ-7. 공유

7.1 IF 문서가 속한 워크스페이스의 `is_shareable`가 false이면 THEN 공유 링크를 생성/활성화할 수 없다.
7.2 WHEN owner 또는 admin이 워크스페이스의 `is_shareable`를 설정하면 THEN 시스템은 공유 가능 여부(게이트)를 갱신한다.
7.3 WHEN editor 이상이 공유 가능한 워크스페이스의 문서에 대해 공유를 켜면 THEN 시스템은 읽기 전용 공개 링크(token)를 발급/활성화한다.
7.4 공유 링크는 **문서 단위**이며 읽기 전용이다.
7.5 WHEN 외부 사용자가 활성 공유 링크에 접근하면 THEN 시스템은 해당 문서와 **그 하위 문서(active 한정)**를 읽기 전용으로 보여준다.
7.6 WHEN 공유된 문서에 새 하위 문서가 추가되면 THEN 링크에 자동으로 포함된다(동적 반영).
7.7 WHEN 공유 링크를 토글 off하면 THEN 시스템은 링크 접근을 차단한다(재토글 on 시 다시 활성).
7.8 WHEN 공유 중인 문서가 trashed되면 THEN 공개 링크는 즉시 무효화된다.
7.9 WHEN trashed 문서가 복구되면 THEN 링크는 되살아나지 않고 **재발급**해야 한다.
7.10 WHEN 워크스페이스 `is_shareable`가 off로 바뀌면 THEN 기존 발급 링크는 즉시 무효화되고, 다시 on 시 **재발급**해야 한다.

### REQ-8. 첨부·이미지 파일

8.1 WHEN 사용자가 편집 중 이미지를 붙여넣으면 THEN 시스템은 이미지를 파일로 저장하고 문서에서 참조한다(base64 인라인 아님).
8.2 WHEN editor 이상이 파일을 첨부하면 THEN 시스템은 파일을 저장하고 문서에 연결한다.
8.3 파일은 워크스페이스별로 격리 저장된다.
8.4 WHEN 활성 공유 링크로 문서를 열면 THEN 시스템은 첨부 파일 다운로드·이미지 로딩을 허용한다.
8.5 IF 워크스페이스 `is_shareable`가 off이거나 문서가 trashed이면 THEN 공유 링크를 통한 파일 접근도 함께 차단된다.
8.6 WHEN 문서가 deleted(영구삭제)되면 THEN 시스템은 연결된 첨부 파일을 삭제하지 않고 "삭제된 파일 보관 폴더"로 이동(`is_archived = true`)한다.
8.7 WHEN 저장으로 인해 과거 버전이 참조하던 이미지가 현재 버전에서 더 이상 참조되지 않으면 THEN 해당 파일을 "삭제된 파일 보관 폴더"로 이동한다.
8.8 "삭제된 파일 보관 폴더"에도 워크스페이스별 격리가 적용된다.
8.9 보관 폴더로 이동한 파일은 영구삭제된 것으로 간주되며 애플리케이션 상 복원 대상이 아니다.
8.10 보관 폴더는 admin을 포함해 어떤 애플리케이션 사용자도 조회할 수 없으며, 시스템 관리(수동)를 통해서만 다룬다.
8.11 보관 폴더의 스토리지 단조 증가는 수용한다(자동 정리 없음).

---

## 4. 문서 상태 전이 (상세)

문서·파일·공유 링크의 생명주기를 한 곳에 모은다. 구현 시 이 전이표가 단일 기준(source of truth)이다.

### 4.1 문서 상태 머신

```
          삭제(editor+)              보관일 경과(자동)
  ┌────────┐ ─────────────► ┌─────────┐ ──────────────► ┌─────────┐
  │ active │                │ trashed │  완전삭제(editor+)  │ deleted │
  └────────┘ ◄───────────── └─────────┘ ──────────────► └─────────┘
              복구(editor+)
```

| 전이 | 트리거 | 주체 | 동작 |
|------|--------|------|------|
| active → trashed | 삭제 | editor 이상 | 문서 + **그 시점 active 하위**를 하나의 묶음으로 trashed, 묶음 trashed_at 기록. 이미 trashed된 하위는 제외 |
| trashed → active | 복구 | editor 이상 | 묶음 단위 active 복귀. 복귀 위치는 §4.2(부모 상태 기준) |
| trashed → deleted | 보관일(기본 30d) 경과 | 시스템(자동) | **묶음별 독립 타이머**로 영구삭제 |
| trashed → deleted | 완전 삭제 | editor 이상 | 해당 묶음만 즉시 영구삭제 |

- deleted는 종착 상태다. 되돌릴 수 없다.
- 전이는 **묶음 단위**로 원자적이다. 단, active 상태에서는 하위만 개별 삭제할 수 있고, 그 결과 생긴 독립 묶음은 이후 부모 삭제 시에도 병합되지 않는다.

### 4.2 묶음(bundle) 규칙 — 비흡수(no-absorption) 모델

- **묶음의 정의:** 한 번의 삭제 조작이 그 시점에 포착한 서브트리. 서로 다른 시점의 삭제는 서로 다른 묶음이며, 이후 병합·흡수되지 않는다.
- 활성 상태에서 하위 문서를 부모와 독립적으로 삭제할 수 있다 → 그 자식은 휴지통에서 **독립 묶음**이 된다.
- 이후 부모가 삭제되어도 먼저 삭제된 자식은 **흡수하지 않는다**(자식은 자기 묶음·자기 trashed_at 유지). 부모 삭제 캐스케이드는 **그 시점 active 하위**만 포착한다.
- **보관 타이머:** 묶음마다 자신의 trashed_at 기준으로 독립 산정한다. 동일 보관일이면 통상 자식이 부모보다 먼저 만료된다(수용).
- **복구 위치 규칙(단일 기준):** 먼저 삭제된 자식의 복구 목적지는 *복구 시점의 부모 상태* 로 결정한다.
  - 부모 **active** → 부모 밑으로 복귀(parent_id 유지, sort_order 원위치 복원).
  - 부모 **non-active**(trashed/deleted/부재) → **root**로 복귀(parent_id = NULL, root 맨 뒤 append).
- **자동 재중첩 없음:** 자식을 root로 복구한 뒤 부모를 복구해도 자동으로 부모 밑에 다시 넣지 않는다. 필요 시 수동 이동한다.
- **불변:** `child.trashed_at ≤ parent.trashed_at`. 따라서 "부모가 자식보다 먼저 독립 trash 항목이 되는" 케이스는 없다.
- 복구·완전삭제는 각 묶음에 독립 적용된다. 부모 묶음 복구가 다른 독립 자식 묶음을 함께 되살리지 않는다.

> **참고(현행 대비 변경):** 이전 명세의 "먼저 삭제된 자식을 부모 묶음으로 흡수 + 보관 기산점 재설정" 규칙은 폐지되었다. 자식은 항상 독립 항목으로 남고, 보관 타이머 재설정도 하지 않는다.

### 4.3 편집 잠금 상태

| 조건 | 상태 |
|------|------|
| lock_user_id = NULL | 미잠금(누구나 편집 시작 가능, editor 이상) |
| lock_user_id = 특정 사용자 | 해당 사용자만 편집·저장 가능, 타인은 편집 불가(UI 표시) |
| 강제 해제 | owner/admin이 잠금 해제, 편집 중 변경분 폐기 |

- 타임아웃 없음. 방치된 잠금은 owner/admin의 강제 해제로만 풀린다.
- 삭제 상태와 잠금 상태는 서로 독립이며 충돌하지 않는다(잠긴 문서도 trashed/deleted 가능).

### 4.4 파일(첨부) 생명주기

```
  참조됨(active) ──────────────────────────► 보관 폴더(= 영구삭제, 앱 불가시·복원불가)
       │  트리거:
       │   - 소속 문서 deleted(영구삭제)
       │   - 저장으로 현재 버전에서 참조 소멸(과거 버전만 참조)
```

- 파일은 2단계다: 참조됨 → 보관 폴더 이동.
- 보관 폴더 이동 = 영구삭제로 간주. 앱에서 조회·복원 불가(시스템 수동 관리 전용).
- 참조 상태·보관 폴더 모두 워크스페이스별 격리.

### 4.5 공유 링크 — "재발급 통일" 원칙

무효화 이후에는 절대 자동 복원되지 않고 **항상 재발급**한다. 관련 전이를 하나의 원칙으로 통일.

| 사건 | 링크 결과 |
|------|-----------|
| 토글 off | 접근 차단(재토글 on 시 동일 링크 재활성 — 토글은 예외적으로 상태 기반) |
| 문서 trashed | 즉시 무효화 |
| trashed 문서 복구 | 재발급 필요(되살아나지 않음) |
| WS is_shareable off | 즉시 무효화 |
| WS is_shareable 재 on | 재발급 필요 |

> 참고: **토글 on/off**만 동일 링크의 상태 변경이고, **trash·WS 플래그로 인한 무효화**는 재발급 대상이다.

---

## 5. 도메인 불변식 (Invariants)

구현·테스트에서 항상 성립해야 하는 규칙. cc-sdd의 boundary/검증에 활용.

- INV-1. 권한은 워크스페이스 단위로만 존재한다. 문서별 개별 권한은 없다.
- INV-2. viewer는 어떤 경우에도 문서·휴지통을 변경할 수 없다(읽기 전용).
- INV-3. admin의 접근은 어떤 권한 검사로도 차단되지 않는다.
- INV-4. 사용자·문서·첨부는 물리 삭제되지 않는다(모두 flag/상태 전환 또는 보관 폴더 이동). → dangling FK는 발생하지 않는다.
- INV-5. 문서 이동 결과 그래프에 사이클이 생기지 않는다(자기/후손 하위로 이동 금지).
- INV-6. 문서·이동·공유는 워크스페이스 경계를 넘지 않는다.
- INV-7. deleted 문서·보관 폴더 파일은 애플리케이션에서 복원 경로가 없다.
- INV-8. 무효화된 공유 링크(trash/WS 플래그 기인)는 재발급 없이는 접근 불가.
- INV-9. 한 문서에 대한 편집 잠금은 최대 1인이 보유한다.
- INV-10. 삭제/복구/완전삭제는 **묶음 단위로 원자적**으로 적용된다. 여기서 묶음은 "한 번의 삭제가 포착한 서브트리"이며, 서로 다른 시점의 삭제로 생긴 별개 묶음은 병합되지 않고 각각 독립적으로 전이된다.
- INV-11. 독립 묶음으로 존재하는 자식은 항상 부모보다 먼저 trash에 진입했다(`child.trashed_at ≤ parent.trashed_at`).
- INV-12. 묶음의 보관 만료(자동 deleted)는 각 묶음의 trashed_at 기준으로 독립 산정된다(다른 묶음 삭제·복구가 타이머에 영향을 주지 않는다).

---

## 6. 범위 밖(Out of Scope) · 추후 결정

| 항목 | 상태 |
|------|------|
| 문서 **검색**(제목/본문) | **추후 결정** — 이번 범위에서 제외 |
| 과거 버전 rollback(복원) | 미도입 확정 |
| lock 자동 타임아웃 | 미도입 확정 |
| 첨부 파일 **용량 제한** | 미정(design 단계 판단) |
| 실시간 동시 편집(CRDT 등) | 미도입 — lock 방식으로 대체 |
| self sign-up / SSO / OAuth | 미도입(폐쇄형) |
| 보관 폴더 자동 정리 | 미도입(단조 증가 수용) |
| 다중 admin | 미도입(단일 admin, 수동 설정) |
| 자식→부모 자동 재중첩(root 복구 후) | 미도입(수동 이동으로 대체, §4.2·6.5.3) |

---

## 7. cc-sdd 진행 가이드 (참고)

권장 순서:

1. `/kiro:steering` — 스택(MySQL8 / FastAPI / React+Vite+Tailwind4)과 본 명세의 불변식(§5)을 프로젝트 메모리로 등록.
2. `/kiro:spec-init` — 스펙을 기능 단위로 분해(예: auth / workspace / document-core / trash / lock-version / sharing / attachment).
3. `/kiro:spec-requirements` — §3의 EARS 기준을 각 스펙의 Acceptance Criteria로 전개.
4. `/kiro:spec-design` — §2 데이터 모델을 DDL·API 스키마·레이어 구조로 구체화.
5. `/kiro:spec-tasks` → `/kiro:spec-impl` — TDD로 구현.

분해 시 경계 주의: **trash·version·sharing·attachment는 document-core의 상태(status/lock)에 의존**하므로,
document-core를 먼저 안정화한 뒤 나머지를 얹는 것이 의존성상 안전하다.
