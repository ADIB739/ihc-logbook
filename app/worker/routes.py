from datetime import date, time as dtime, datetime
from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Department, Equipment, EquipmentParam, LogEntry, LogReading
from app.utils import group_readings, ist_now, ist_today

worker_bp = Blueprint("worker", __name__)

# Checklist (Fire dept) logs are filled once per shift, not per hour. Each shift
# maps to a fixed representative time so the existing one-per-hour uniqueness
# naturally enforces one entry per shift without a schema change.
SHIFT_TIMES = {"A": dtime(6, 0), "B": dtime(14, 0), "C": dtime(22, 0)}
SHIFT_OPTIONS = ["A", "B", "C"]


def current_shift(now):
    h = now.hour
    if 6 <= h < 14:
        return "A"
    if 14 <= h < 22:
        return "B"
    return "C"


def is_checklist_equipment(params):
    return any((p.input_type == "check") for p in params)


def worker_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.role not in ("worker", "supervisor"):
            abort(403)
        return f(*args, **kwargs)
    return decorated


@worker_bp.route("/dashboard")
@login_required
@worker_required
def dashboard():
    if current_user.role == "supervisor":
        return redirect(url_for("supervisor.dashboard"))

    today = ist_today()
    today_logs = (
        LogEntry.query
        .filter_by(worker_id=current_user.id)
        .filter(LogEntry.log_date == today)
        .order_by(LogEntry.log_time)
        .all()
    )
    today_count = len(today_logs)

    # Per-equipment hourly coverage for today
    coverage = {}
    for log in today_logs:
        eid = log.equipment_id
        if eid not in coverage:
            coverage[eid] = {"name": log.equipment.name, "hours": set()}
        coverage[eid]["hours"].add(log.log_time.hour)
    coverage = [
        {"name": v["name"], "hours": sorted(v["hours"])}
        for v in coverage.values()
    ]

    recent_logs = (
        LogEntry.query
        .filter_by(worker_id=current_user.id)
        .order_by(LogEntry.submitted_at.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "worker/dashboard.html",
        recent_logs=recent_logs,
        today_count=today_count,
        coverage=coverage,
        today=today,
    )


@worker_bp.route("/history")
@login_required
@worker_required
def history():
    """Browse this worker's own submitted logs for any past date."""
    if current_user.role == "supervisor":
        return redirect(url_for("supervisor.dashboard"))

    from datetime import timedelta
    today = ist_today()

    history_date_str = request.args.get("history_date")
    try:
        history_date = date.fromisoformat(history_date_str) if history_date_str else today
    except ValueError:
        history_date = today
    # Never allow a future date
    if history_date > today:
        history_date = today

    history_logs = (
        LogEntry.query
        .filter_by(worker_id=current_user.id)
        .filter(LogEntry.log_date == history_date)
        .order_by(LogEntry.log_time)
        .all()
    )

    return render_template(
        "worker/history.html",
        history_logs=history_logs,
        history_date=history_date,
        history_prev=history_date - timedelta(days=1),
        history_next=history_date + timedelta(days=1),
        today=today,
    )


@worker_bp.route("/log/new", methods=["GET"])
@login_required
@worker_required
def log_new():
    import json
    now = ist_now()
    today = now.date().isoformat()
    now_time = f"{now.hour:02d}:00"

    worker_dept = current_user.department

    # Build department → equipment hierarchy for the 3-level dropdown
    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    departments_json = json.dumps([
        {
            "id": dept.id,
            "name": dept.name,
            "equipment": [
                {"id": e.id, "name": e.name}
                for e in Equipment.query
                    .filter_by(dept_id=dept.id, is_active=True)
                    .order_by(Equipment.name).all()
            ]
        }
        for dept in departments
    ])

    # Only load equipment when user explicitly selects it via dropdown
    selected_equip = request.args.get("equipment_id", type=int)

    params = []
    if selected_equip:
        params = (
            EquipmentParam.query
            .filter_by(equipment_id=selected_equip)
            .order_by(EquipmentParam.display_order)
            .all()
        )

    checklist = is_checklist_equipment(params)

    return render_template(
        "worker/log_form.html",
        worker_dept=worker_dept,
        departments_json=departments_json,
        params=params,
        today=today,
        now_time=now_time,
        selected_equip=selected_equip,
        is_checklist=checklist,
        shift_options=SHIFT_OPTIONS,
        current_shift=current_shift(now),
    )


@worker_bp.route("/log/submit", methods=["POST"])
@login_required
@worker_required
def log_submit():
    f = request.form

    # Validate date
    try:
        log_date = date.fromisoformat(f.get("log_date"))
    except (ValueError, TypeError):
        flash("Invalid date.", "danger")
        return redirect(url_for("worker.log_new"))

    equipment_id = f.get("equipment_id", type=int)
    worker_remark = f.get("worker_remark", "").strip()

    if not equipment_id:
        flash("Please select an equipment.", "danger")
        return redirect(url_for("worker.log_new"))

    equipment = Equipment.query.get_or_404(equipment_id)

    # Ensure the equipment belongs to the worker's department
    if current_user.dept_id and equipment.dept_id != current_user.dept_id:
        abort(403)

    checklist = is_checklist_equipment(equipment.params)

    if checklist:
        # Fire-style checklist: one entry per shift; time derived from shift.
        shift = f.get("shift", "")
        if shift not in SHIFT_TIMES:
            flash("Please select a shift (A, B or C).", "danger")
            return redirect(url_for("worker.log_new", equipment_id=equipment_id))
        log_time = SHIFT_TIMES[shift]
        status = "Completed"
        dup_label = f"Shift {shift}"
    else:
        try:
            log_time = dtime.fromisoformat(f.get("log_time"))
        except (ValueError, TypeError):
            flash("Invalid time.", "danger")
            return redirect(url_for("worker.log_new"))
        shift = ""
        status = f.get("status")
        if not status:
            flash("Please fill in all required fields.", "danger")
            return redirect(url_for("worker.log_new"))
        dup_label = f"{log_time.hour:02d}:00"

    # Prevent duplicate within the same slot (per hour, or per shift for checklists)
    same_day_logs = LogEntry.query.filter_by(
        worker_id=current_user.id,
        equipment_id=equipment_id,
        log_date=log_date,
    ).all()
    submitted_hour = log_time.hour
    for existing in same_day_logs:
        if existing.log_time.hour == submitted_hour:
            flash(
                f"A log for {equipment.name} ({dup_label}) on {log_date} "
                "was already submitted.",
                "warning",
            )
            return redirect(url_for("worker.dashboard"))

    # Collect parameter readings (with optional per-parameter remark)
    readings = []
    for param in equipment.params:
        raw_val = f.get(f"param_{param.param_name}", "").strip()
        raw_rem = f.get(f"remark_{param.param_name}", "").strip()
        readings.append(
            LogReading(
                param_name=param.param_name,
                param_value=raw_val if raw_val else None,
                unit=param.unit,
                remark=raw_rem if raw_rem else None,
            )
        )

    log = LogEntry(
        equipment_id=equipment_id,
        worker_id=current_user.id,
        log_date=log_date,
        log_time=log_time,
        shift=shift,
        status=status,
        worker_remark=worker_remark or None,
    )
    log.readings = readings

    db.session.add(log)
    try:
        db.session.commit()
    except Exception:
        # FIX 2: DB unique constraint catches race-condition double submissions
        db.session.rollback()
        flash(
            f"A log for {equipment.name} ({dup_label}) on {log_date} "
            "was already submitted (duplicate blocked).",
            "warning",
        )
        return redirect(url_for("worker.dashboard"))

    flash(f"Log submitted successfully for {equipment.name}.", "success")
    return redirect(url_for("worker.dashboard"))


@worker_bp.route("/log/<int:log_id>")
@login_required
@worker_required
def log_view(log_id):
    log = LogEntry.query.get_or_404(log_id)
    if current_user.role == "worker" and log.worker_id != current_user.id:
        abort(403)
    return render_template("worker/log_view.html", log=log,
                           grouped_readings=group_readings(log))


@worker_bp.route("/log/<int:log_id>/edit", methods=["GET", "POST"])
@login_required
@worker_required
def log_edit(log_id):
    from datetime import timedelta
    log = LogEntry.query.get_or_404(log_id)

    if log.worker_id != current_user.id:
        abort(403)

    if not log.is_editable:
        flash("The 5-minute edit window has passed. Ask your supervisor for a correction.", "warning")
        return redirect(url_for("worker.log_view", log_id=log_id))

    equipment = log.equipment
    params = (
        EquipmentParam.query
        .filter_by(equipment_id=equipment.id)
        .order_by(EquipmentParam.display_order)
        .all()
    )

    if request.method == "POST":
        if not log.is_editable:
            flash("The 5-minute window expired while you were editing.", "warning")
            return redirect(url_for("worker.log_view", log_id=log_id))

        log.status = request.form.get("status", log.status)
        log.worker_remark = request.form.get("worker_remark", "").strip() or None

        # Replace all readings
        for r in list(log.readings):
            db.session.delete(r)
        db.session.flush()

        for param in params:
            raw_val = request.form.get(f"param_{param.param_name}", "").strip()
            raw_rem = request.form.get(f"remark_{param.param_name}", "").strip()
            db.session.add(LogReading(
                log_id=log.id,
                param_name=param.param_name,
                param_value=raw_val if raw_val else None,
                unit=param.unit,
                remark=raw_rem if raw_rem else None,
            ))

        log.is_edited = True
        log.edited_at = datetime.utcnow()
        db.session.commit()

        flash("Log updated successfully.", "success")
        return redirect(url_for("worker.log_view", log_id=log_id))

    readings_map = {r.param_name: r.param_value for r in log.readings}
    readings_remarks = {r.param_name: r.remark for r in log.readings}
    ref = log.edited_at or log.submitted_at
    edit_deadline_utc = ref + timedelta(minutes=5)

    # Seconds remaining — computed in UTC so timezone doesn't matter
    seconds_remaining = max(0, int((edit_deadline_utc - datetime.utcnow()).total_seconds()))

    # Display time in IST (UTC+5:30) so the worker sees the correct local time
    from datetime import timezone
    IST = timezone(timedelta(hours=5, minutes=30))
    edit_deadline_display = edit_deadline_utc.replace(tzinfo=timezone.utc).astimezone(IST)

    return render_template(
        "worker/log_form.html",
        edit_mode=True,
        log=log,
        worker_dept=equipment.department,
        equipment_list=[equipment],
        params=params,
        readings_map=readings_map,
        readings_remarks=readings_remarks,
        today=log.log_date.isoformat(),
        now_time=log.log_time.strftime("%H:%M"),
        selected_equip=equipment.id,
        edit_deadline_display=edit_deadline_display,
        seconds_remaining=seconds_remaining,
        is_checklist=is_checklist_equipment(params),
        shift_options=SHIFT_OPTIONS,
    )
