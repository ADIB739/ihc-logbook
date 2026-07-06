"""
One-off cleanup: remove the demo artifacts that seed.py added, so the live
database matches the real IHC setup produced by setup_real_data.py.

REMOVES:
  - ALL log entries (and their readings + supervisor remarks) — these are dummy
  - Demo-only equipment: Cooling Tower-1, AHU-1, DG Set-1, Fire Pump-1,
    Jockey Pump-1 (and their parameters)
  - Any now-empty demo department (e.g. 'Fire Systems')

KEEPS:
  - Real equipment: Chiller-1..6, VFD & Pumps, Transformer-1, HT Panel Board, Genset
  - Departments HVAC and Electrical
  - All user accounts (manage those from the Manage Users page in the app)

HOW TO RUN (against the LIVE database, from your project folder):
    $env:DATABASE_URL = "<your Render EXTERNAL database url>"
    venv\Scripts\python cleanup_demo_data.py

Safe by design: it refuses to run unless DATABASE_URL points at PostgreSQL,
so it can never wipe your local SQLite dev database by accident.
"""
from app import create_app
from app.extensions import db
from app.models import (
    Department, Equipment, EquipmentParam, LogEntry, User,
)

# Exact names of the REAL equipment created by setup_real_data.py
REAL_EQUIPMENT = {
    "Chiller-1", "Chiller-2", "Chiller-3", "Chiller-4", "Chiller-5", "Chiller-6",
    "VFD & Pumps",
    "Transformer-1", "HT Panel Board", "Genset",
}
REAL_DEPARTMENTS = {"HVAC", "Electrical"}

app = create_app()
with app.app_context():
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    target = uri.split("@")[-1] if "@" in uri else uri
    print("Target database:", target)
    if not uri.startswith("postgresql"):
        print("\nREFUSING TO RUN: DATABASE_URL is not a PostgreSQL (Render) database.")
        print("Set DATABASE_URL to your Render EXTERNAL url first, then re-run.")
        raise SystemExit(1)

    # 1. Delete ALL log entries — cascade removes readings + supervisor remarks.
    logs = LogEntry.query.all()
    for log in logs:
        db.session.delete(log)
    db.session.flush()
    print(f"Deleted {len(logs)} log entries (plus their readings and remarks).")

    # 2. Delete demo-only equipment (params first — no cascade on that relationship).
    demo_equip = Equipment.query.filter(~Equipment.name.in_(REAL_EQUIPMENT)).all()
    for e in demo_equip:
        n = EquipmentParam.query.filter_by(equipment_id=e.id).delete(synchronize_session=False)
        print(f"Removing demo equipment: [{e.department.name}] {e.name} ({n} params)")
        db.session.delete(e)
    db.session.flush()

    # 3. Delete demo departments that are not real AND now have no equipment or users.
    for d in Department.query.all():
        if d.name in REAL_DEPARTMENTS:
            continue
        equip_left = Equipment.query.filter_by(dept_id=d.id).count()
        users_left = User.query.filter_by(dept_id=d.id).count()
        if equip_left == 0 and users_left == 0:
            print(f"Removing demo department: {d.name}")
            db.session.delete(d)

    db.session.commit()

    # 4. Report the final, cleaned state.
    print("\n=== Final equipment (should be the real IHC set only) ===")
    for e in Equipment.query.order_by(Equipment.dept_id, Equipment.name).all():
        pc = EquipmentParam.query.filter_by(equipment_id=e.id).count()
        print(f"  [{e.department.name}] {e.name} — {pc} params")
    print("\nDepartments:", [d.name for d in Department.query.order_by(Department.name)])
    print("Log entries remaining:", LogEntry.query.count())
    print("\nCleanup complete.")
