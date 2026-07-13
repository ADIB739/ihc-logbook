from datetime import datetime, timezone, timedelta

from app.models import EquipmentParam

# The server runs in UTC (e.g. on Render). IHC operates in India Standard Time,
# so all "current date/time" values shown or defaulted in the app must use IST,
# not the server clock — otherwise logs default to the wrong hour/day.
IST = timezone(timedelta(hours=5, minutes=30))


def ist_now():
    """Current time in IST (timezone-aware)."""
    return datetime.now(IST)


def ist_today():
    """Current calendar date in IST."""
    return ist_now().date()


def group_readings(log):
    """Return readings grouped by section: [(section_name, [dict, ...]), ...]"""
    params = (
        EquipmentParam.query
        .filter_by(equipment_id=log.equipment_id)
        .order_by(EquipmentParam.display_order)
        .all()
    )

    section_order = []
    section_map = {}
    for p in params:
        sec = p.section or "General"
        if sec not in section_map:
            section_map[sec] = []
            section_order.append(sec)
        section_map[sec].append(p.param_name)

    reading_map = {r.param_name: r for r in log.readings}

    grouped = []
    for sec in section_order:
        rows = []
        for pname in section_map[sec]:
            r = reading_map.get(pname)
            rows.append({
                "param_name": pname,
                "param_value": r.param_value if r else None,
                "unit": r.unit if r else "",
                "remark": r.remark if r else "",
            })
        grouped.append((sec, rows))

    # Catch any readings not in the param definitions
    known = {pname for names in section_map.values() for pname in names}
    extras = [r for r in log.readings if r.param_name not in known]
    if extras:
        grouped.append(("Other", [
            {"param_name": r.param_name, "param_value": r.param_value,
             "unit": r.unit or "", "remark": r.remark or ""}
            for r in extras
        ]))

    return grouped
