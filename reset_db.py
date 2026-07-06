"""
Clears ALL dummy data and creates a clean starting point.

What this does:
  - Deletes every log entry, reading, and supervisor remark
  - Removes all test/sample user accounts
  - Keeps all departments, equipment, and parameter definitions intact
  - Creates ONE supervisor account that you control

Run:  python reset_db.py
"""
import os
import sys
from app import create_app
from app.extensions import db, bcrypt
from app.models import (
    User, LogEntry, LogReading, SupervisorRemark,
    Department, Equipment, EquipmentParam,
)

app = create_app()

# ── Supervisor account to create ──────────────────────────────────────────────
# Change these before running!
# Supplied via environment variables so no real credential lives in the repo.
# Set these before running:  $env:SUPERVISOR_EMAIL / $env:SUPERVISOR_PASSWORD
SUPERVISOR_NAME  = os.environ.get("SUPERVISOR_NAME", "Site Supervisor")
SUPERVISOR_EMAIL = os.environ.get("SUPERVISOR_EMAIL", "supervisor@example.com")
SUPERVISOR_PASSWORD = os.environ.get("SUPERVISOR_PASSWORD", "changeme123")  # MUST be changed on first login
# ─────────────────────────────────────────────────────────────────────────────


def confirm():
    print("=" * 55)
    print("  IHC Logbook — Reset to clean state")
    print("=" * 55)
    print()
    print("This will PERMANENTLY DELETE:")
    print("  - All log entries and readings")
    print("  - All supervisor remarks")
    print("  - All existing user accounts")
    print()
    print("This will KEEP:")
    print("  - All departments")
    print("  - All equipment and parameter definitions")
    print()
    print(f"A new supervisor account will be created:")
    print(f"  Email   : {SUPERVISOR_EMAIL}")
    print(f"  Password: {SUPERVISOR_PASSWORD}")
    print()
    answer = input("Type YES to continue: ").strip()
    if answer != "YES":
        print("Cancelled.")
        sys.exit(0)


def reset():
    confirm()

    with app.app_context():
        print()

        # 1. Delete all log data (order matters for foreign keys)
        deleted_readings  = db.session.query(LogReading).delete()
        deleted_remarks   = db.session.query(SupervisorRemark).delete()
        deleted_logs      = db.session.query(LogEntry).delete()
        db.session.commit()
        print(f"  Deleted {deleted_logs} log entries")
        print(f"  Deleted {deleted_readings} readings")
        print(f"  Deleted {deleted_remarks} supervisor remarks")

        # 2. Delete all users
        deleted_users = db.session.query(User).delete()
        db.session.commit()
        print(f"  Deleted {deleted_users} user accounts")

        # 3. Create the real supervisor account
        supervisor = User(
            name=SUPERVISOR_NAME,
            email=SUPERVISOR_EMAIL.lower(),
            password=bcrypt.generate_password_hash(SUPERVISOR_PASSWORD).decode("utf-8"),
            role="supervisor",
            dept_id=None,
            is_active=True,
            must_change_password=True,   # forces password change on first login
        )
        db.session.add(supervisor)
        db.session.commit()
        print(f"  Created supervisor: {SUPERVISOR_EMAIL}")

        # 4. Verify structure is intact
        depts  = Department.query.count()
        equips = Equipment.query.count()
        params = EquipmentParam.query.count()
        print()
        print(f"  Departments kept : {depts}")
        print(f"  Equipment kept   : {equips}")
        print(f"  Parameters kept  : {params}")

        print()
        print("=" * 55)
        print("  Reset complete. Ready for real use.")
        print("=" * 55)
        print()
        print("Next steps:")
        print(f"  1. Run: python run.py")
        print(f"  2. Login with: {SUPERVISOR_EMAIL} / {SUPERVISOR_PASSWORD}")
        print(f"  3. You will be asked to set a new password immediately.")
        print(f"  4. Go to Manage Users to add real worker accounts.")
        print()


if __name__ == "__main__":
    reset()
