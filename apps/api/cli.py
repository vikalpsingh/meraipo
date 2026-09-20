import argparse
import asyncio
from getpass import getpass

from sqlalchemy import delete, select

from apps.api.security import hasher
from packages.database.models import AdminSession, AdminUser, Audit
from packages.database.session import Session


async def change(command, email, password):
    if len(password) < 14:
        raise ValueError("Use at least 14 characters")
    async with Session() as db:
        user = await db.scalar(select(AdminUser).where(AdminUser.email == email.lower()))
        if command == "create_admin":
            if user:
                raise ValueError("Admin already exists")
            user = AdminUser(email=email.lower(), password_hash=hasher.hash(password))
            db.add(user)
        elif user:
            user.password_hash = hasher.hash(password)
            await db.execute(delete(AdminSession).where(AdminSession.admin_id == user.id))
        else:
            raise ValueError("Admin not found")
        await db.flush()
        db.add(Audit(admin_id=user.id, action=command, changes={"email": user.email}))
        await db.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["create_admin", "reset_admin_password"])
    parser.add_argument("email")
    args = parser.parse_args()
    password = getpass("Password (14+ characters): ")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords differ")
    asyncio.run(change(args.command, args.email, password))
    print("Administrator updated; existing sessions revoked for password resets.")
