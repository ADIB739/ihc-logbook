"""
Sets up real IHC equipment data.
Safe to run on a live database — does NOT delete any logs or users.

What this does:
  - Adds the `section` column to equipment_params if missing
  - Replaces Chiller-1 to Chiller-6 parameters with the actual IHC Water Cooled
    Chiller Plant logbook readings (creates Chiller-2 to 6 if they don't exist)
  - Creates "VFD & Pumps" equipment with 68 parameters (Voltage, VFD Freq,
    Secondary Pump, Primary Pump, Condenser Pump, C.T Fan)
  - Creates Transformer-1 to Transformer-5 (18 params each) under Electrical
  - Creates Genset-1 to Genset-4 (18 params each) under Electrical, migrating
    the legacy single "Genset" to "Genset-1" so its logs are preserved

Run: python setup_real_data.py
"""
from app.extensions import db, bcrypt
from app.models import Department, Equipment, EquipmentParam, User
from sqlalchemy import text

# ── Real Chiller-1 parameters from IHC Water Cooled Chiller Plant Log ─────────
# Format: (section, param_name, unit, display_order)

CHILLER_PARAMS = [
    # GENERAL
    ("General",     "Ambient Temp",                 "°C",        1),
    ("General",     "RH",                           "%",         2),
    ("General",     "Voltage",                      "VOLT",      3),
    ("General",     "Current",                      "AMP",       4),
    ("General",     "Starter Power Demand",         "KW",        5),

    # EVAPORATOR
    ("Evaporator",  "Set Point",                    "°C",        6),
    ("Evaporator",  "CHW Leaving Temp",             "°C",        7),
    ("Evaporator",  "CHW Entering Temp",            "°C",        8),
    ("Evaporator",  "ΔT",                           "°C",        9),
    ("Evaporator",  "Evap. Ref. Pressure",          "Psig/Kpag", 10),
    ("Evaporator",  "Evap. Set Ref Temp",           "°C",        11),
    ("Evaporator",  "Evap. Approach Temp",          "°C",        12),
    ("Evaporator",  "Expansion Valve Position",     "%",         13),
    ("Evaporator",  "Evap. Ref Liquid Level",       "MM",        14),
    ("Evaporator",  "Evap. LWP",                    "Kg/cm²",    15),
    ("Evaporator",  "Evap. EWP",                    "Kg/cm²",    16),

    # CONDENSER
    ("Condenser",   "Cond Leaving Temp",            "°C",        17),
    ("Condenser",   "Cond Entering Temp",           "°C",        18),
    ("Condenser",   "ΔT (Condenser)",               "°C",        19),
    ("Condenser",   "Cond. Approach Temp",          "°C",        20),
    ("Condenser",   "Cond Sat Ref Temp",            "°C",        21),
    ("Condenser",   "Cond. Ref Pressure",           "Psig/Kpag", 22),
    ("Condenser",   "Diff Ref Pressure",            "Psig/Kpag", 23),
    ("Condenser",   "Cond. LWP",                    "Kg/cm²",    24),
    ("Condenser",   "Cond EWP",                     "Kg/cm²",    25),

    # COMPRESSOR
    ("Compressor",  "Comp of Starts",               "Nos",       26),
    ("Compressor",  "Comp Running Time",            "Hrs.",      27),
    ("Compressor",  "Oil Tank Temp",                "°C",        28),
    ("Compressor",  "IGV-1 Position",               "%",         29),
    ("Compressor",  "Starter Meter Current (RLA)",  "%",         30),
    ("Compressor",  "Motor Winding Temp",           "°C",        31),
    ("Compressor",  "Off Pressure",                 "Psig/Kpag", 32),
    ("Compressor",  "Comp Ref Discharge Temp",      "°C",        33),
    ("Compressor",  "Discharge Superheat",          "°C",        34),
]


# ── VFD & Pumps parameters from IHC VFD & Pumps Log Book ─────────────────────
# Format: (section, param_name, unit, display_order)

VFD_PUMP_PARAMS = [
    # VOLTAGE
    ("Voltage",          "R Phase",                  "V",    1),
    ("Voltage",          "Y Phase",                  "V",    2),
    ("Voltage",          "B Phase",                  "V",    3),

    # VFD FREQUENCY — North pumps 1-3, South pumps 4-5
    ("VFD Frequency",    "Pump-1 Frequency (North)", "Hz",   4),
    ("VFD Frequency",    "Pump-2 Frequency (North)", "Hz",   5),
    ("VFD Frequency",    "Pump-3 Frequency (North)", "Hz",   6),
    ("VFD Frequency",    "Pump-4 Frequency (South)", "Hz",   7),
    ("VFD Frequency",    "Pump-5 Frequency (South)", "Hz",   8),

    # SECONDARY PUMP — 5 pumps × 3 phases
    ("Secondary Pump",   "Pump-1 R Phase",           "A",    9),
    ("Secondary Pump",   "Pump-1 Y Phase",           "A",    10),
    ("Secondary Pump",   "Pump-1 B Phase",           "A",    11),
    ("Secondary Pump",   "Pump-2 R Phase",           "A",    12),
    ("Secondary Pump",   "Pump-2 Y Phase",           "A",    13),
    ("Secondary Pump",   "Pump-2 B Phase",           "A",    14),
    ("Secondary Pump",   "Pump-3 R Phase",           "A",    15),
    ("Secondary Pump",   "Pump-3 Y Phase",           "A",    16),
    ("Secondary Pump",   "Pump-3 B Phase",           "A",    17),
    ("Secondary Pump",   "Pump-4 R Phase",           "A",    18),
    ("Secondary Pump",   "Pump-4 Y Phase",           "A",    19),
    ("Secondary Pump",   "Pump-4 B Phase",           "A",    20),
    ("Secondary Pump",   "Pump-5 R Phase",           "A",    21),
    ("Secondary Pump",   "Pump-5 Y Phase",           "A",    22),
    ("Secondary Pump",   "Pump-5 B Phase",           "A",    23),

    # PRIMARY PUMP — 5 pumps × 3 phases
    ("Primary Pump",     "Pump-1 R Phase",           "A",    24),
    ("Primary Pump",     "Pump-1 Y Phase",           "A",    25),
    ("Primary Pump",     "Pump-1 B Phase",           "A",    26),
    ("Primary Pump",     "Pump-2 R Phase",           "A",    27),
    ("Primary Pump",     "Pump-2 Y Phase",           "A",    28),
    ("Primary Pump",     "Pump-2 B Phase",           "A",    29),
    ("Primary Pump",     "Pump-3 R Phase",           "A",    30),
    ("Primary Pump",     "Pump-3 Y Phase",           "A",    31),
    ("Primary Pump",     "Pump-3 B Phase",           "A",    32),
    ("Primary Pump",     "Pump-4 R Phase",           "A",    33),
    ("Primary Pump",     "Pump-4 Y Phase",           "A",    34),
    ("Primary Pump",     "Pump-4 B Phase",           "A",    35),
    ("Primary Pump",     "Pump-5 R Phase",           "A",    36),
    ("Primary Pump",     "Pump-5 Y Phase",           "A",    37),
    ("Primary Pump",     "Pump-5 B Phase",           "A",    38),

    # CONDENSER PUMP — 5 pumps × 3 phases
    ("Condenser Pump",   "Pump-1 R Phase",           "A",    39),
    ("Condenser Pump",   "Pump-1 Y Phase",           "A",    40),
    ("Condenser Pump",   "Pump-1 B Phase",           "A",    41),
    ("Condenser Pump",   "Pump-2 R Phase",           "A",    42),
    ("Condenser Pump",   "Pump-2 Y Phase",           "A",    43),
    ("Condenser Pump",   "Pump-2 B Phase",           "A",    44),
    ("Condenser Pump",   "Pump-3 R Phase",           "A",    45),
    ("Condenser Pump",   "Pump-3 Y Phase",           "A",    46),
    ("Condenser Pump",   "Pump-3 B Phase",           "A",    47),
    ("Condenser Pump",   "Pump-4 R Phase",           "A",    48),
    ("Condenser Pump",   "Pump-4 Y Phase",           "A",    49),
    ("Condenser Pump",   "Pump-4 B Phase",           "A",    50),
    ("Condenser Pump",   "Pump-5 R Phase",           "A",    51),
    ("Condenser Pump",   "Pump-5 Y Phase",           "A",    52),
    ("Condenser Pump",   "Pump-5 B Phase",           "A",    53),

    # C.T FAN — 5 fans × 3 phases
    ("C.T Fan",          "Fan-1 R Phase",            "A",    54),
    ("C.T Fan",          "Fan-1 Y Phase",            "A",    55),
    ("C.T Fan",          "Fan-1 B Phase",            "A",    56),
    ("C.T Fan",          "Fan-2 R Phase",            "A",    57),
    ("C.T Fan",          "Fan-2 Y Phase",            "A",    58),
    ("C.T Fan",          "Fan-2 B Phase",            "A",    59),
    ("C.T Fan",          "Fan-3 R Phase",            "A",    60),
    ("C.T Fan",          "Fan-3 Y Phase",            "A",    61),
    ("C.T Fan",          "Fan-3 B Phase",            "A",    62),
    ("C.T Fan",          "Fan-4 R Phase",            "A",    63),
    ("C.T Fan",          "Fan-4 Y Phase",            "A",    64),
    ("C.T Fan",          "Fan-4 B Phase",            "A",    65),
    ("C.T Fan",          "Fan-5 R Phase",            "A",    66),
    ("C.T Fan",          "Fan-5 Y Phase",            "A",    67),
    ("C.T Fan",          "Fan-5 B Phase",            "A",    68),
]


# ── Transformer parameters (33 kV/433 V Basement Substation) ──────────────────
# Format: (section, param_name, unit, display_order)

TRANSFORMER_PARAMS = [
    # HV VOLTAGES
    ("HV Voltages",      "HV RY",                   "kV",   1),
    ("HV Voltages",      "HV YB",                   "kV",   2),
    ("HV Voltages",      "HV BR",                   "kV",   3),
    # LV VOLTAGES
    ("LV Voltages",      "LV RY",                   "V",    4),
    ("LV Voltages",      "LV YB",                   "V",    5),
    ("LV Voltages",      "LV BR",                   "V",    6),
    # HV CURRENT
    ("HV Current",       "HV Current R",            "A",    7),
    ("HV Current",       "HV Current Y",            "A",    8),
    ("HV Current",       "HV Current B",            "A",    9),
    # LV CURRENT
    ("LV Current",       "LV Current R",            "A",    10),
    ("LV Current",       "LV Current Y",            "A",    11),
    ("LV Current",       "LV Current B",            "A",    12),
    # OPERATING CHECKS
    ("Operating Checks", "Power Factor",            "",     13),
    ("Operating Checks", "Frequency",               "Hz",   14),
    ("Operating Checks", "Room Temp",               "°C",   15),
    ("Operating Checks", "Winding Temp",            "°C",   16),
    ("Operating Checks", "Trip CKT",                "",     17),
    ("Operating Checks", "DC Voltage",              "V",    18),
]


# ── Genset parameters (Alternator & Control Panel) ────────────────────────────
# Format: (section, subsection, param_name, unit, display_order)

GENSET_PARAMS = [
    # ENGINE — direct readings
    ("Engine",                     None,                   "Hour Meter",    "Hrs",    1),
    ("Engine",                     None,                   "LO Pressure",   "Kg/cm²", 2),
    ("Engine",                     None,                   "LO Temperature","°C",     3),
    ("Engine",                     None,                   "Water Temp",    "°C",     4),
    ("Engine",                     None,                   "Room Temp",     "°C",     5),
    # ENGINE — Heat Ex. Raw Water subsection
    ("Engine",                     "Heat Ex. Raw Water",   "Temp In",       "°C",     6),
    ("Engine",                     "Heat Ex. Raw Water",   "Temp Out",      "°C",     7),
    ("Engine",                     "Heat Ex. Raw Water",   "PR",            "Psi",    8),
    # ALTERNATOR & CONTROL PANEL — Voltage subsection
    ("Alternator & Control Panel", "Voltage",              "Voltage RY",    "V",      9),
    ("Alternator & Control Panel", "Voltage",              "Voltage YB",    "V",      10),
    ("Alternator & Control Panel", "Voltage",              "Voltage BR",    "V",      11),
    # ALTERNATOR & CONTROL PANEL — Current subsection
    ("Alternator & Control Panel", "Current",              "Current R",     "A",      12),
    ("Alternator & Control Panel", "Current",              "Current Y",     "A",      13),
    ("Alternator & Control Panel", "Current",              "Current B",     "A",      14),
    # ALTERNATOR & CONTROL PANEL — direct readings
    ("Alternator & Control Panel", None,                   "Frequency",     "Hz",     15),
    ("Alternator & Control Panel", None,                   "Power Factor",  "",       16),
    ("Alternator & Control Panel", None,                   "KW",            "kW",     17),
    ("Alternator & Control Panel", None,                   "KW Hours",      "kWh",    18),
]


def _apply_params(chiller):
    """Delete existing params for this equipment and insert the 34 IHC params."""
    old = EquipmentParam.query.filter_by(equipment_id=chiller.id).delete()
    db.session.flush()
    for section, param_name, unit, order in CHILLER_PARAMS:
        db.session.add(EquipmentParam(
            equipment_id=chiller.id,
            param_name=param_name,
            unit=unit,
            section=section,
            display_order=order,
        ))
    return old


def _apply_flat_params(equip, param_rows):
    """Replace params for equipment defined as (section, name, unit, order)."""
    EquipmentParam.query.filter_by(equipment_id=equip.id).delete()
    db.session.flush()
    for section, param_name, unit, order in param_rows:
        db.session.add(EquipmentParam(
            equipment_id=equip.id,
            param_name=param_name,
            unit=unit,
            section=section,
            display_order=order,
        ))


def _apply_subsection_params(equip, param_rows):
    """Replace params for equipment defined as (section, subsection, name, unit, order)."""
    EquipmentParam.query.filter_by(equipment_id=equip.id).delete()
    db.session.flush()
    for section, subsection, param_name, unit, order in param_rows:
        db.session.add(EquipmentParam(
            equipment_id=equip.id,
            param_name=param_name,
            unit=unit,
            section=section,
            subsection=subsection,
            display_order=order,
        ))


# ── Fire Dept — "Fighting" daily fire pumps inspection checklist ──────────────
# Each item is answered OK / Not OK / N/A per shift. Format: (param_name, order)

FIGHTING_CHECKLIST = [
    "Fire water tank level (terrace & underground) is > 90%",
    "All pumps selector switches are kept in AUTO mode",
    "All valves are secured in open/close position (as required)",
    "No leakage from pump gland, pipes etc.",
    "All pressure gauges in pump room are within the displayed range",
    "Fuel level in fire diesel engine pump tank is > 90%",
    "Engine oil level of fire diesel engine is adequate",
    "Coolant level is adequate in heat exchanger of DG fire pump",
    "Battery charging condition is healthy",
]


# ── Fire Dept — "Shift Round" checklist (2nd logbook) ─────────────────────────
# A grid: each SYSTEM (section) is checked across every ZONE (item), OK per cell,
# once per shift. Param names are "System - Zone" so they stay unique; the form
# shows just the zone under each system heading.

SHIFT_ROUND_SYSTEMS = [
    "Staircase", "FHC", "Extinguisher", "Detectors/MCP", "Signage", "Fire Alarm Panel",
]
SHIFT_ROUND_ZONES = [
    "Room Block", "Lite Zone", "C.C.", "Audi.", "6C", "5A", "5B", "7A", "6A", "4B", "4A",
]


def _apply_checklist_params(equip, section, items):
    """Replace params for a checklist unit. `items` is a list of param names."""
    EquipmentParam.query.filter_by(equipment_id=equip.id).delete()
    db.session.flush()
    for order, param_name in enumerate(items, start=1):
        db.session.add(EquipmentParam(
            equipment_id=equip.id,
            param_name=param_name,
            unit="",
            section=section,
            input_type="check",
            display_order=order,
        ))


def _apply_grid_checklist(equip, systems, zones):
    """Replace params for a System x Zone checklist grid. Returns the item count."""
    EquipmentParam.query.filter_by(equipment_id=equip.id).delete()
    db.session.flush()
    order = 0
    for system in systems:
        for zone in zones:
            order += 1
            db.session.add(EquipmentParam(
                equipment_id=equip.id,
                param_name=f"{system} - {zone}",
                unit="",
                section=system,
                input_type="check",
                display_order=order,
            ))
    return order


def sync_fire_department():
    """Create the Fire department and its 'Fighting' checklist unit."""
    print()
    print("-- Fire Department -----------------------------------------")
    fire = Department.query.filter_by(name="Fire").first()
    if not fire:
        fire = Department(name="Fire", is_active=True,
                          description="Fire Safety — Fighting, Detection & Electrical")
        db.session.add(fire)
        db.session.commit()
        print("  Created Fire department.")
    else:
        print(f"  Fire department already exists (id={fire.id}).")

    # Fighting-1 — Daily Fire Pumps Inspection Checklist
    fighting = Equipment.query.filter_by(name="Fighting-1").first()
    if not fighting:
        fighting = Equipment(dept_id=fire.id, name="Fighting-1", is_active=True,
                             description="Daily Fire Pumps Inspection Checklist (Pacific Fire Controls)")
        db.session.add(fighting)
        db.session.flush()
        print("  Created Fighting-1 equipment.")
    else:
        fighting.dept_id = fire.id
        fighting.is_active = True
        db.session.flush()
        print(f"  Found existing Fighting-1 (id={fighting.id}).")

    _apply_checklist_params(fighting, "Daily Fire Pumps Inspection", FIGHTING_CHECKLIST)
    db.session.commit()
    print(f"  [Fighting-1]  {len(FIGHTING_CHECKLIST)} checklist items (OK / Not OK / N/A per shift).")

    # Shift Round-1 — Shift Round Checklist (System x Zone grid), 2nd logbook
    shift_round = Equipment.query.filter_by(name="Shift Round-1").first()
    if not shift_round:
        shift_round = Equipment(dept_id=fire.id, name="Shift Round-1", is_active=True,
                                description="Shift Round Checklist — IHC (Pacific Fire Controls)")
        db.session.add(shift_round)
        db.session.flush()
        print("  Created Shift Round-1 equipment.")
    else:
        shift_round.dept_id = fire.id
        shift_round.is_active = True
        db.session.flush()
        print(f"  Found existing Shift Round-1 (id={shift_round.id}).")

    n = _apply_grid_checklist(shift_round, SHIFT_ROUND_SYSTEMS, SHIFT_ROUND_ZONES)
    db.session.commit()
    print(f"  [Shift Round-1]  {n} checklist items "
          f"({len(SHIFT_ROUND_SYSTEMS)} systems x {len(SHIFT_ROUND_ZONES)} zones).")


def fix_user_directory():
    """One-time (idempotent) staff name corrections + add supervisor Amar Nath.

    Renaming a User updates every historical log display automatically, because
    log entries reference the worker by id (worker_id) — the name is not copied
    into each log. Every step is guarded so re-running is a no-op once applied,
    and so a later name change made through the UI is not reverted.
    """
    print()
    print("-- Staff directory corrections -----------------------------")
    changed = []

    # 1. Rename workers by their current name (matches nothing once applied)
    for old, new in (("Ramesh Kumar", "Rohit Kumar"),
                     ("Suresh Singh", "Nanak Chand")):
        for u in User.query.filter_by(name=old).all():
            u.name = new
            changed.append(f"{old} -> {new}")

    # 2. Name the existing (sole) supervisor "Brij Mohan Chaubey" — only if that
    #    name isn't already present, so it acts exactly once.
    if not User.query.filter_by(name="Brij Mohan Chaubey").first():
        sup = (
            User.query.filter_by(role="supervisor")
            .filter(User.name != "Amar Nath")
            .order_by(User.id)
            .first()
        )
        if sup:
            changed.append(f"{sup.name} -> Brij Mohan Chaubey (supervisor)")
            sup.name = "Brij Mohan Chaubey"

    # 3. Add supervisor Amar Nath — only if missing.
    if not (User.query.filter_by(email="amarnath@ihc.in").first()
            or User.query.filter_by(name="Amar Nath").first()):
        db.session.add(User(
            name="Amar Nath",
            email="amarnath@ihc.in",
            password=bcrypt.generate_password_hash("supervisor@123").decode("utf-8"),
            role="supervisor",
            dept_id=None,
            must_change_password=True,
            is_active=True,
        ))
        changed.append("created supervisor Amar Nath (amarnath@ihc.in)")

    if changed:
        db.session.commit()
        for c in changed:
            print(f"  {c}")
    else:
        print("  No changes needed — directory already up to date.")


def run():
    from app import create_app
    app = create_app()
    with app.app_context():
        # 1. Add `section` and `subsection` columns if they don't exist yet
        for col_def in [
            "ALTER TABLE equipment_params ADD COLUMN section VARCHAR(50)",
            "ALTER TABLE equipment_params ADD COLUMN subsection VARCHAR(100)",
            "ALTER TABLE equipment_params ADD COLUMN input_type VARCHAR(20)",
            "ALTER TABLE log_readings ADD COLUMN remark VARCHAR(255)",
        ]:
            tbl = col_def.split("ALTER TABLE ")[1].split()[0]
            col = col_def.split("ADD COLUMN ")[1].split()[0]
            try:
                db.session.execute(text(col_def))
                db.session.commit()
                print(f"  Added `{col}` column to {tbl}.")
            except Exception:
                db.session.rollback()
                print(f"  `{col}` column already exists on {tbl} — skipping.")

        # 2. Find HVAC department
        hvac = Department.query.filter_by(name="HVAC").first()
        if not hvac:
            print("ERROR: HVAC department not found. Run python seed.py first.")
            return

        # 3. Process Chiller-1 through Chiller-6
        for n in range(1, 7):
            name = f"Chiller-{n}"
            chiller = Equipment.query.filter_by(name=name).first()

            if not chiller:
                chiller = Equipment(dept_id=hvac.id, name=name, is_active=True)
                db.session.add(chiller)
                db.session.flush()
                print(f"  Created {name}.")
            else:
                print(f"  Found existing {name} (id={chiller.id}).")

            old = _apply_params(chiller)
            db.session.commit()
            print(f"    -> Removed {old} old params, added {len(CHILLER_PARAMS)} IHC params.")

        print()
        # Print chiller section summary once
        sections = {}
        for s, p, u, o in CHILLER_PARAMS:
            sections.setdefault(s, []).append(p)
        for sec, params in sections.items():
            print(f"  [{sec}]  {len(params)} params")
        print()
        print("Done. Chiller-1 to Chiller-6 all have 34 real IHC parameters.")

        # 4. Create / update VFD & Pumps
        print()
        print("-- VFD & Pumps ------------------------------------------")
        vfd = Equipment.query.filter_by(name="VFD & Pumps").first()
        if not vfd:
            vfd = Equipment(dept_id=hvac.id, name="VFD & Pumps", is_active=True,
                            description="VFD & Pumps — Voltage, VFD Frequency, Secondary/Primary/Condenser Pump, C.T Fan")
            db.session.add(vfd)
            db.session.flush()
            print("  Created VFD & Pumps equipment.")
        else:
            print(f"  Found existing VFD & Pumps (id={vfd.id}).")

        EquipmentParam.query.filter_by(equipment_id=vfd.id).delete()
        db.session.flush()
        for section, param_name, unit, order in VFD_PUMP_PARAMS:
            db.session.add(EquipmentParam(
                equipment_id=vfd.id,
                param_name=param_name,
                unit=unit,
                section=section,
                display_order=order,
            ))
        db.session.commit()

        vfd_sections = {}
        for s, p, u, o in VFD_PUMP_PARAMS:
            vfd_sections.setdefault(s, []).append(p)
        for sec, params in vfd_sections.items():
            print(f"  [{sec}]  {len(params)} params")
        print(f"  Total: {len(VFD_PUMP_PARAMS)} parameters")
        print()
        print("Done. Restart the server to see the updated forms.")

        # 5. Ensure Electrical department exists
        print()
        print("-- Electrical Department -----------------------------------")
        electrical = Department.query.filter_by(name="Electrical").first()
        if not electrical:
            electrical = Department(name="Electrical", is_active=True,
                                    description="Electrical Engineering Department")
            db.session.add(electrical)
            db.session.commit()
            print("  Created Electrical department.")
        else:
            print(f"  Electrical department already exists (id={electrical.id}).")

        # 6. Create / update Transformer-1 through Transformer-5 under Electrical
        print()
        print("-- Transformers (33kV/433V Basement Substation) ------------")
        for n in range(1, 6):
            name = f"Transformer-{n}"
            tr = Equipment.query.filter_by(name=name).first()
            if not tr:
                tr = Equipment(dept_id=electrical.id, name=name, is_active=True,
                               description="33 kV/433 V Transformer at Basement Substation")
                db.session.add(tr)
                db.session.flush()
                print(f"  Created {name} equipment.")
            else:
                tr.dept_id = electrical.id
                tr.is_active = True
                db.session.flush()
                print(f"  Found existing {name} (id={tr.id}).")

            _apply_flat_params(tr, TRANSFORMER_PARAMS)
            db.session.commit()

        tr_sections = {}
        for s, p, u, o in TRANSFORMER_PARAMS:
            tr_sections.setdefault(s, []).append(p)
        for sec, params in tr_sections.items():
            print(f"  [{sec}]  {len(params)} params")
        print(f"  Total: {len(TRANSFORMER_PARAMS)} parameters each")
        print()
        print("Done. Transformer-1 to Transformer-5 ready (18 parameters each).")

        # 7. Create / update HT Panel Board under Electrical
        print()
        print("-- HT Panel Board (33 kV Incoming Supply) ------------------")
        ht = Equipment.query.filter_by(name="HT Panel Board").first()
        if not ht:
            ht = Equipment(dept_id=electrical.id, name="HT Panel Board", is_active=True,
                           description="33 kV Incoming Supply at Basement Substation")
            db.session.add(ht)
            db.session.flush()
            print("  Created HT Panel Board equipment.")
        else:
            ht.dept_id = electrical.id
            ht.is_active = True
            db.session.flush()
            print(f"  Found existing HT Panel Board (id={ht.id}).")

        HT_PANEL_PARAMS = [
            # VOLTAGES
            ("Voltages",       "Voltage RY",           "kV",   1),
            ("Voltages",       "Voltage YB",           "kV",   2),
            ("Voltages",       "Voltage BR",           "kV",   3),
            # CURRENT
            ("Current",        "Current R",            "A",    4),
            ("Current",        "Current Y",            "A",    5),
            ("Current",        "Current B",            "A",    6),
            # POWER & ENERGY
            ("Power & Energy", "Frequency",            "Hz",   7),
            ("Power & Energy", "Power Factor",         "",     8),
            ("Power & Energy", "KW",                   "kW",   9),
            ("Power & Energy", "KWH",                  "kWh",  10),
            ("Power & Energy", "KVA",                  "kVA",  11),
            ("Power & Energy", "KVAh",                 "kVAh", 12),
            ("Power & Energy", "KVAr",                 "kVAr", 13),
            ("Power & Energy", "KVArh",                "kVArh",14),
            # OPERATING CHECKS
            ("Operating Checks", "Trip CKT Condition", "",     15),
        ]

        EquipmentParam.query.filter_by(equipment_id=ht.id).delete()
        db.session.flush()
        for section, param_name, unit, order in HT_PANEL_PARAMS:
            db.session.add(EquipmentParam(
                equipment_id=ht.id,
                param_name=param_name,
                unit=unit,
                section=section,
                display_order=order,
            ))
        db.session.commit()

        ht_sections = {}
        for s, p, u, o in HT_PANEL_PARAMS:
            ht_sections.setdefault(s, []).append(p)
        for sec, params in ht_sections.items():
            print(f"  [{sec}]  {len(params)} params")
        print(f"  Total: {len(HT_PANEL_PARAMS)} parameters")
        print()
        print("Done. HT Panel Board ready under Electrical department.")

        # 8. Create / update Genset-1 through Genset-4 under Electrical
        print()
        print("-- Gensets (Alternator & Control Panel) ---------------------")
        # Migrate the legacy single "Genset" to "Genset-1" so its logs are preserved
        # and it joins the numbered unit series (like the Chillers).
        legacy = Equipment.query.filter_by(name="Genset").first()
        if legacy and not Equipment.query.filter_by(name="Genset-1").first():
            legacy.name = "Genset-1"
            db.session.flush()
            print(f"  Renamed legacy 'Genset' -> 'Genset-1' (id={legacy.id}).")

        for n in range(1, 5):
            name = f"Genset-{n}"
            genset = Equipment.query.filter_by(name=name).first()
            if not genset:
                genset = Equipment(dept_id=electrical.id, name=name, is_active=True,
                                   description="Genset — Alternator & Control Panel Log")
                db.session.add(genset)
                db.session.flush()
                print(f"  Created {name} equipment.")
            else:
                genset.dept_id = electrical.id
                genset.is_active = True
                db.session.flush()
                print(f"  Found existing {name} (id={genset.id}).")

            _apply_subsection_params(genset, GENSET_PARAMS)
            db.session.commit()

        gs_sections = {}
        for s, ss, p, u, o in GENSET_PARAMS:
            gs_sections.setdefault(s, []).append(p)
        for sec, params in gs_sections.items():
            print(f"  [{sec}]  {len(params)} params")
        print(f"  Total: {len(GENSET_PARAMS)} parameters each")
        print()
        print("Done. Genset-1 to Genset-4 ready under Electrical department.")

        # 9. Fire department — Fighting checklist unit
        sync_fire_department()

        # 10. Staff directory corrections (names + new supervisor)
        fix_user_directory()


if __name__ == "__main__":
    run()
