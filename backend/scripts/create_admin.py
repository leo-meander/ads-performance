"""Create initial admin user. Run after migration.

Usage:
  python -m scripts.create_admin --email admin@meander.com --name "Admin" --password "your-password"
"""
import argparse
import sys
from pathlib import Path

# Add backend dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.database import SessionLocal
from app.models.user import User
from app.services.auth_service import hash_password


def main():
    parser = argparse.ArgumentParser(description="Create admin user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == args.email).first()
        if existing:
            print(f"User {args.email} already exists (id={existing.id})")
            return

        user = User(
            email=args.email,
            full_name=args.name,
            password_hash=hash_password(args.password),
            roles=["admin", "creator", "reviewer"],
            is_active=True,
            notification_email=True,
        )
        db.add(user)
        db.commit()
        print(f"Admin user created: {args.email} (id={user.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
