"""
Admin seed script for SmartLedger.

Usage:
    python scripts/create_admin.py \
        --username admin \
        --email admin@example.com \
        --password "SecurePass1" \
        --full-name "System Admin"

Or via environment variables (useful in Docker / CI):
    ADMIN_USERNAME=admin
    ADMIN_EMAIL=admin@example.com
    ADMIN_PASSWORD=SecurePass1
    ADMIN_FULL_NAME="System Admin"

    python scripts/create_admin.py

What it does:
  1. Deletes ALL existing admin users from the database.
  2. Creates one new admin user with the supplied credentials.
  3. The database partial unique index (uq_one_admin) then permanently
     prevents a second admin row from being inserted.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Ensure the project root is on sys.path when running as a script.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password, validate_password_policy
from app.models.auth import User
from app.models.enums import UserRole


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the single admin user.")
    parser.add_argument("--username",  default=os.getenv("ADMIN_USERNAME"))
    parser.add_argument("--email",     default=os.getenv("ADMIN_EMAIL"))
    parser.add_argument("--password",  default=os.getenv("ADMIN_PASSWORD"))
    parser.add_argument("--full-name", default=os.getenv("ADMIN_FULL_NAME", "System Admin"))
    return parser.parse_args()


async def run(username: str, email: str, password: str, full_name: str) -> None:
    # Validate password before touching the DB
    try:
        validate_password_policy(password, username=username.lower())
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        async with db.begin():
            # Step 1 — delete all existing admin users
            result = await db.execute(
                select(User.id, User.username).where(User.role == UserRole.admin)
            )
            existing_admins = result.all()
            if existing_admins:
                names = ", ".join(f"'{r.username}' (id={r.id})" for r in existing_admins)
                print(f"Deleting {len(existing_admins)} existing admin(s): {names}")
                await db.execute(
                    delete(User).where(User.role == UserRole.admin)
                )
            else:
                print("No existing admin users found.")

            # Remove any non-admin user occupying the target username (e.g. demoted by migration)
            conflict = await db.execute(
                select(User.id).where(User.username == username.lower(), User.role != UserRole.admin)
            )
            if conflict.scalar_one_or_none() is not None:
                print(f"Removing existing non-admin user with username '{username.lower()}'.")
                await db.execute(
                    delete(User).where(User.username == username.lower(), User.role != UserRole.admin)
                )

            # Step 2 — create the single new admin
            admin = User(
                username=username.lower(),
                email=email.lower(),
                hashed_password=hash_password(password),
                full_name=full_name,
                role=UserRole.admin,
                is_active=True,
            )
            db.add(admin)

    # Reload to get DB-assigned id
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.username == username.lower())
        )
        created = result.scalar_one()
        print(
            f"\nAdmin created successfully:\n"
            f"  id       : {created.id}\n"
            f"  username : {created.username}\n"
            f"  email    : {created.email}\n"
            f"  role     : {created.role.value}\n"
        )


def main() -> None:
    args = _parse_args()

    missing = [
        name for name, val in [
            ("--username / ADMIN_USERNAME", args.username),
            ("--email / ADMIN_EMAIL",       args.email),
            ("--password / ADMIN_PASSWORD", args.password),
        ]
        if not val
    ]
    if missing:
        print("ERROR: Missing required arguments:")
        for m in missing:
            print(f"  {m}")
        sys.exit(1)

    asyncio.run(run(
        username=args.username,
        email=args.email,
        password=args.password,
        full_name=args.full_name,
    ))


if __name__ == "__main__":
    main()
