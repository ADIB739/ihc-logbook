"""
Run once to populate sample departments, equipment, parameters, and two test users.
    python seed.py
"""
from datetime import date, time, timedelta
import os
import random
from app import create_app
from app.extensions import db, bcrypt
from app.models import Department, Equipment, EquipmentParam, User, LogEntry, LogReading

app = create_app()


DEPARTMENTS = [
    {"name": "HVAC",         "description": "Heating, Ventilation & Air Conditioning"},
    {"name": "Electrical",   "description": "Power supply, DG sets, transformers"},
    {"name": "Fire Systems", "description": "Fire pumps, suppression, detection"},
]

EQUIPMENT = {
    "HVAC": [
        {"name": "Chiller-1",        "params": [
            ("Suction Temperature",    "°C"),
            ("Discharge Temperature",  "°C"),
            ("Suction Pressure",       "Bar"),
            ("Discharge Pressure",     "Bar"),
            ("Chilled Water Inlet",    "°C"),
            ("Chilled Water Outlet",   "°C"),
        ]},
        {"name": "Cooling Tower-1",   "params": [
            ("Inlet Water Temp",       "°C"),
            ("Outlet Water Temp",      "°C"),
            ("Fan Current",            "A"),
        ]},
        {"name": "AHU-1",             "params": [
            ("Supply Air Temp",        "°C"),
            ("Return Air Temp",        "°C"),
            ("Filter Pressure Drop",   "Pa"),
        ]},
    ],
    "Electrical": [
        {"name": "DG Set-1",          "params": [
            ("Voltage R-Y",            "V"),
            ("Voltage Y-B",            "V"),
            ("Voltage B-R",            "V"),
            ("Frequency",              "Hz"),
            ("Fuel Level",             "%"),
            ("Oil Pressure",           "Bar"),
            ("Coolant Temperature",    "°C"),
        ]},
        {"name": "Transformer-1",     "params": [
            ("Primary Voltage",        "V"),
            ("Secondary Voltage",      "V"),
            ("Oil Temperature",        "°C"),
            ("Load Current",           "A"),
        ]},
    ],
    "Fire Systems": [
        {"name": "Fire Pump-1",       "params": [
            ("Suction Pressure",       "Bar"),
            ("Discharge Pressure",     "Bar"),
            ("Motor Current",          "A"),
        ]},
        {"name": "Jockey Pump-1",     "params": [
            ("Suction Pressure",       "Bar"),
            ("Discharge Pressure",     "Bar"),
            ("Motor Current",          "A"),
        ]},
    ],
}

# Local demo accounts only. Passwords come from env vars so no real credential
# ever lives in the repo; set them before running, or accept the throwaway default.
_DEMO_PW = os.environ.get("DEMO_PASSWORD", "changeme123")
USERS = [
    {"name": "Demo Worker 1",  "email": "worker1@example.com",    "password": _DEMO_PW, "role": "worker",     "dept": "HVAC"},
    {"name": "Demo Worker 2",  "email": "worker2@example.com",    "password": _DEMO_PW, "role": "worker",     "dept": "Electrical"},
    {"name": "Demo Supervisor","email": "supervisor@example.com", "password": _DEMO_PW, "role": "supervisor", "dept": None},
]


def seed():
    with app.app_context():
        db.drop_all()
        db.create_all()
        print("Tables created.")

        # Departments
        dept_map = {}
        for d in DEPARTMENTS:
            dept = Department(name=d["name"], description=d["description"])
            db.session.add(dept)
            db.session.flush()
            dept_map[d["name"]] = dept
        print(f"  {len(DEPARTMENTS)} departments seeded.")

        # Equipment + params
        equip_map = {}
        for dept_name, equip_list in EQUIPMENT.items():
            dept = dept_map[dept_name]
            for e in equip_list:
                equip = Equipment(dept_id=dept.id, name=e["name"])
                db.session.add(equip)
                db.session.flush()
                equip_map[e["name"]] = equip
                for order, (pname, unit) in enumerate(e["params"], 1):
                    db.session.add(EquipmentParam(
                        equipment_id=equip.id,
                        param_name=pname,
                        unit=unit,
                        display_order=order,
                    ))
        print(f"  Equipment + params seeded.")

        # Users
        user_map = {}
        for u in USERS:
            dept = dept_map.get(u["dept"]) if u["dept"] else None
            user = User(
                name=u["name"],
                email=u["email"],
                password=bcrypt.generate_password_hash(u["password"]).decode("utf-8"),
                role=u["role"],
                dept_id=dept.id if dept else None,
            )
            db.session.add(user)
            db.session.flush()
            user_map[u["email"]] = user
        print(f"  {len(USERS)} users seeded.")

        # Sample logs — last 10 days for Chiller-1 and DG Set-1
        worker = user_map["worker1@example.com"]
        worker2 = user_map["worker2@example.com"]
        chiller = equip_map["Chiller-1"]
        dg = equip_map["DG Set-1"]

        today = date.today()
        for i in range(10):
            log_date = today - timedelta(days=i)

            # Chiller log
            c_log = LogEntry(
                equipment_id=chiller.id,
                worker_id=worker.id,
                log_date=log_date,
                log_time=time(8, 0),
                shift="Morning",
                status=random.choice(["Running", "Running", "Running", "Standby"]),
                worker_remark="Equipment running normally." if i % 3 != 0 else "Minor vibration noted.",
            )
            db.session.add(c_log)
            db.session.flush()
            base_suction = 6.5 + round(random.uniform(-0.5, 1.0), 1)
            readings_c = [
                ("Suction Temperature",   str(base_suction),          "°C"),
                ("Discharge Temperature", str(round(base_suction + 34 + random.uniform(-1,1), 1)), "°C"),
                ("Suction Pressure",      str(round(3.1 + random.uniform(-0.2,0.3), 1)), "Bar"),
                ("Discharge Pressure",    str(round(12.3 + random.uniform(-0.5,0.5), 1)), "Bar"),
                ("Chilled Water Inlet",   str(round(11.5 + random.uniform(-0.5,0.5), 1)), "°C"),
                ("Chilled Water Outlet",  str(base_suction), "°C"),
            ]
            for pname, val, unit in readings_c:
                db.session.add(LogReading(log_id=c_log.id, param_name=pname, param_value=val, unit=unit))

            # DG log
            d_log = LogEntry(
                equipment_id=dg.id,
                worker_id=worker2.id,
                log_date=log_date,
                log_time=time(9, 0),
                shift="Morning",
                status="Running" if i < 8 else "Standby",
                worker_remark="DG running on load." if i < 8 else "DG on standby.",
            )
            db.session.add(d_log)
            db.session.flush()
            fuel = max(20, 85 - i * 5)
            readings_d = [
                ("Voltage R-Y",         str(random.randint(413, 417)), "V"),
                ("Voltage Y-B",         str(random.randint(413, 417)), "V"),
                ("Voltage B-R",         str(random.randint(413, 417)), "V"),
                ("Frequency",           "50.0",  "Hz"),
                ("Fuel Level",          str(fuel), "%"),
                ("Oil Pressure",        str(round(3.5 + random.uniform(-0.2,0.2), 1)), "Bar"),
                ("Coolant Temperature", str(random.randint(78, 85)), "°C"),
            ]
            for pname, val, unit in readings_d:
                db.session.add(LogReading(log_id=d_log.id, param_name=pname, param_value=val, unit=unit))

        db.session.commit()
        print(f"  Sample logs seeded (last 10 days).")

        print("\nSeed complete!")
        print("-" * 40)
        print("Login credentials (local demo — set DEMO_PASSWORD to override):")
        print(f"  Worker     : worker1@example.com    / {_DEMO_PW}")
        print(f"  Worker 2   : worker2@example.com    / {_DEMO_PW}")
        print(f"  Supervisor : supervisor@example.com / {_DEMO_PW}")
        print("-" * 40)
        print("Run: python run.py")
        print("Open: http://127.0.0.1:5000")


if __name__ == "__main__":
    seed()
