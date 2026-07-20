"""admin 계정 관리 CLI (운영용 out-of-band 도구).

애플리케이션 HTTP 경로는 설계상(D3, 승격 차단) `is_admin` 을 절대 변경하지
않는다: `UserRepository.create` 는 `is_admin=False` 로 고정하고, 갱신 화이트리스트
에서도 `is_admin` 을 제외한다. admin 플래그는 `User` 모델 주석대로 "수동 설정"
이며, 이 CLI 가 바로 그 정당한 out-of-band 경로다.

그래서 이 도구는 `AdminAccountService`(항상 비관리자 생성) 대신 s01 `User` ORM 을
직접 기록하되, 해싱(`app.common.security.hash_password`, Argon2id)과 세션 팩토리
(`app.common.db.SessionLocal`)는 앱과 동일하게 재사용해 정합을 유지한다.

실행(설정 파일 해석을 위해 반드시 backend/ 에서)::

    uv run admin_cli.py create --login-id admin --name "관리자"
    uv run admin_cli.py set-password --login-id admin
    uv run admin_cli.py list

비밀번호는 인자로 주지 않으면 대화형(getpass)으로 입력받아 셸 히스토리 노출을
피한다. 정책 최소 길이는 s02 auth 스키마(8자)와 맞춘다.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.common.db import SessionLocal
from app.common.security import hash_password
from app.models import User

# s02 auth `PasswordChangeRequest.new_password = Field(min_length=8)` 와 동일 정책.
MIN_PASSWORD_LENGTH = 8


def _fail(message: str) -> None:
    """오류 메시지를 stderr 로 출력하고 비정상 종료한다."""
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def _read_password(provided: str | None) -> str:
    """비밀번호를 확보한다.

    `--password` 로 주어졌으면 그 값을, 아니면 대화형으로 두 번 입력받아 확인한다
    (셸 히스토리 노출 방지). 어느 경로든 최소 길이 정책을 강제한다.
    """
    if provided is not None:
        password = provided
    else:
        password = getpass.getpass("새 비밀번호: ")
        confirm = getpass.getpass("비밀번호 확인: ")
        if password != confirm:
            _fail("두 비밀번호가 일치하지 않습니다.")

    if len(password) < MIN_PASSWORD_LENGTH:
        _fail(f"비밀번호는 최소 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.")
    return password


def _get_by_login_id(db: Session, login_id: str) -> User | None:
    from sqlalchemy import select

    return db.scalar(select(User).where(User.login_id == login_id))


def cmd_create(args: argparse.Namespace) -> None:
    """신규 admin 계정을 생성한다.

    login_id 중복이면 거부한다. 이미 활성 admin 이 존재하면 단일 admin 원칙에 따라
    `--force` 없이는 거부한다(모델 §단일 admin).
    """
    password = _read_password(args.password)

    with SessionLocal() as db:
        if _get_by_login_id(db, args.login_id) is not None:
            _fail(f"login_id '{args.login_id}' 는 이미 존재합니다.")

        if not args.force:
            from sqlalchemy import select

            existing_admin = db.scalar(
                select(User).where(User.is_admin.is_(True), User.is_deleted.is_(False))
            )
            if existing_admin is not None:
                _fail(
                    f"이미 admin 계정이 존재합니다 (login_id='{existing_admin.login_id}'). "
                    "추가 admin 생성을 강제하려면 --force 를 사용하세요."
                )

        user = User(
            login_id=args.login_id,
            password_hash=hash_password(password),
            name=args.name,
            email=args.email,
            is_admin=True,
            is_active=True,
            is_deleted=False,
            created_at=datetime.utcnow(),
        )
        db.add(user)
        try:
            db.commit()
        except SQLAlchemyError as exc:  # unique 제약 등 경합/무결성 위반
            db.rollback()
            _fail(f"계정 생성 실패: {exc}")
        db.refresh(user)

    print(
        f"admin 계정 생성 완료: id={user.id} login_id='{user.login_id}' "
        f"name='{user.name}' is_admin={user.is_admin}"
    )


def cmd_set_password(args: argparse.Namespace) -> None:
    """login_id 로 대상을 찾아 비밀번호를 재설정한다."""
    password = _read_password(args.password)

    with SessionLocal() as db:
        user = _get_by_login_id(db, args.login_id)
        if user is None:
            _fail(f"login_id '{args.login_id}' 사용자를 찾을 수 없습니다.")

        user.password_hash = hash_password(password)
        user.updated_at = datetime.utcnow()
        try:
            db.commit()
        except SQLAlchemyError as exc:
            db.rollback()
            _fail(f"비밀번호 변경 실패: {exc}")

    print(f"비밀번호 변경 완료: login_id='{args.login_id}'")


def cmd_list(args: argparse.Namespace) -> None:
    """계정 목록을 출력한다(기본 admin 만; --all 로 전체)."""
    from sqlalchemy import select

    with SessionLocal() as db:
        stmt = select(User).order_by(User.id)
        if not args.all:
            stmt = stmt.where(User.is_admin.is_(True))
        users = list(db.scalars(stmt))

    if not users:
        print("(계정 없음)")
        return

    header = f"{'id':>4}  {'login_id':<20} {'admin':<5} {'active':<6} {'deleted':<7} name"
    print(header)
    print("-" * len(header))
    for u in users:
        print(
            f"{u.id:>4}  {u.login_id:<20} "
            f"{str(u.is_admin):<5} {str(u.is_active):<6} {str(u.is_deleted):<7} {u.name}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="admin_cli",
        description="notion-lite admin 계정 관리 CLI (backend/ 에서 실행).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="admin 계정 생성")
    p_create.add_argument("--login-id", required=True, help="로그인 ID (고유)")
    p_create.add_argument("--name", required=True, help="표시 이름")
    p_create.add_argument("--email", default=None, help="이메일 (선택)")
    p_create.add_argument(
        "--password",
        default=None,
        help="비밀번호(비권장: 셸 히스토리 노출). 생략 시 대화형 입력.",
    )
    p_create.add_argument(
        "--force",
        action="store_true",
        help="이미 admin 이 존재해도 추가 admin 생성 강제.",
    )
    p_create.set_defaults(func=cmd_create)

    p_pw = sub.add_parser("set-password", help="비밀번호 변경")
    p_pw.add_argument("--login-id", required=True, help="대상 로그인 ID")
    p_pw.add_argument(
        "--password",
        default=None,
        help="새 비밀번호(비권장: 셸 히스토리 노출). 생략 시 대화형 입력.",
    )
    p_pw.set_defaults(func=cmd_set_password)

    p_list = sub.add_parser("list", help="계정 목록 출력")
    p_list.add_argument(
        "--all", action="store_true", help="admin 뿐 아니라 전체 계정 출력."
    )
    p_list.set_defaults(func=cmd_list)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
