import csv
import io
from datetime import date, timedelta
from functools import wraps
from urllib.parse import urlencode, parse_qs
from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    request, abort, Response,
)
from flask_login import login_required, current_user
from sqlalchemy import func
from app.extensions import db, bcrypt
from app.utils import group_readings, ist_now, ist_today
from app.models import (
    Department, Equipment, EquipmentParam, LogEntry, LogReading,
    SupervisorRemark, User,
)

supervisor_bp = Blueprint("supervisor", __name__)


def supervisor_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.role != "supervisor":
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ─── Dashboard ────────────────────────────────────────────────────────────────

@supervisor_bp.route("/dashboard")
@login_required
@supervisor_required
def dashboard():
    today = ist_today()

    total_today = LogEntry.query.filter(LogEntry.log_date == today).count()

    # Approved / NeedsAttention counts via latest remark per log
    approved = (
        db.session.query(LogEntry)
        .join(SupervisorRemark, SupervisorRemark.log_id == LogEntry.id)
        .filter(SupervisorRemark.review_status == "Approved")
        .filter(LogEntry.log_date == today)
        .distinct(LogEntry.id)
        .count()
    )
    needs_attention = (
        db.session.query(LogEntry)
        .join(SupervisorRemark, SupervisorRemark.log_id == LogEntry.id)
        .filter(SupervisorRemark.review_status == "NeedsAttention")
        .filter(LogEntry.log_date == today)
        .distinct(LogEntry.id)
        .count()
    )
    # Pending = submitted today but no remark yet
    reviewed_ids_subq = (
        db.session.query(SupervisorRemark.log_id)
        .join(LogEntry, LogEntry.id == SupervisorRemark.log_id)
        .filter(LogEntry.log_date == today)
        .distinct()
        .scalar_subquery()
    )
    pending = (
        LogEntry.query
        .filter(LogEntry.log_date == today)
        .filter(~LogEntry.id.in_(reviewed_ids_subq))
        .count()
    )

    # All-time pending: every log (any date) that has not yet been actioned
    # (no remark, or its remark is still "Pending"). Powers the pending queue.
    handled_ids_subq = (
        db.session.query(SupervisorRemark.log_id)
        .filter(SupervisorRemark.review_status != "Pending")
        .distinct()
        .scalar_subquery()
    )
    pending_all = (
        LogEntry.query
        .filter(~LogEntry.id.in_(handled_ids_subq))
        .count()
    )

    # FIX 3: one query for all today's logs instead of 1-per-equipment loop
    from sqlalchemy.orm import joinedload, selectinload
    from collections import defaultdict

    today_logs_all = (
        LogEntry.query
        .options(
            joinedload(LogEntry.equipment),
            selectinload(LogEntry.supervisor_remarks),
        )
        .filter(LogEntry.log_date == today)
        .all()
    )

    # Build dept_summary entirely in Python from the single query above
    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    all_equip = (
        Equipment.query
        .filter_by(is_active=True)
        .order_by(Equipment.name)
        .all()
    )
    # For each equipment, map every submitted hour -> that hour's log id, so the
    # green coverage boxes can link straight to the log entry (keep the latest
    # one if an hour happens to have more than one submission).
    hour_logs_by_equip = defaultdict(dict)   # {equip_id: {hour: (log_id, submitted_at)}}
    for log in today_logs_all:
        h = log.log_time.hour
        slot = hour_logs_by_equip[log.equipment_id]
        if h not in slot or log.submitted_at > slot[h][1]:
            slot[h] = (log.id, log.submitted_at)

    dept_summary = []
    for dept in departments:
        equip_coverage = []
        for e in all_equip:
            if e.dept_id != dept.id:
                continue
            hour_logs = {h: v[0] for h, v in hour_logs_by_equip.get(e.id, {}).items()}
            equip_coverage.append({"name": e.name, "id": e.id, "hour_logs": hour_logs})
        dept_summary.append({
            "id": dept.id,
            "name": dept.name,
            "count": sum(len(ec["hour_logs"]) for ec in equip_coverage),
            "equipment": equip_coverage,
        })

    re_review_count = sum(1 for l in today_logs_all if l.needs_re_review)

    # Recent logs — eager load everything needed to render the table
    recent_logs = (
        LogEntry.query
        .options(
            joinedload(LogEntry.equipment).joinedload(Equipment.department),
            joinedload(LogEntry.worker),
            selectinload(LogEntry.supervisor_remarks),
        )
        .order_by(LogEntry.submitted_at.desc())
        .limit(8)
        .all()
    )

    # Recent supervisor remarks
    recent_remarks = (
        SupervisorRemark.query
        .order_by(SupervisorRemark.created_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "supervisor/dashboard.html",
        total_today=total_today,
        pending=pending,
        pending_all=pending_all,
        approved=approved,
        needs_attention=needs_attention,
        re_review_count=re_review_count,
        dept_summary=dept_summary,
        recent_logs=recent_logs,
        recent_remarks=recent_remarks,
        today=today,
        now_hour=ist_now().hour,
    )


# ─── Pending Reviews Queue ────────────────────────────────────────────────────

@supervisor_bp.route("/pending")
@login_required
@supervisor_required
def pending_reviews():
    """All logs (any date) still awaiting review, oldest first — a work queue."""
    from datetime import datetime
    from sqlalchemy.orm import joinedload, selectinload

    handled_ids_subq = (
        db.session.query(SupervisorRemark.log_id)
        .filter(SupervisorRemark.review_status != "Pending")
        .distinct()
        .scalar_subquery()
    )
    base_q = (
        LogEntry.query
        .options(
            joinedload(LogEntry.equipment).joinedload(Equipment.department),
            joinedload(LogEntry.worker),
            selectinload(LogEntry.supervisor_remarks),
        )
        .filter(~LogEntry.id.in_(handled_ids_subq))
    )
    total = base_q.count()

    PER_PAGE = 25
    page = request.args.get("page", 1, type=int)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))

    logs = (
        base_q
        .order_by(LogEntry.log_date.asc(), LogEntry.log_time.asc())
        .offset((page - 1) * PER_PAGE)
        .limit(PER_PAGE)
        .all()
    )

    # Attach a human-readable "waiting" age (submitted_at is naive UTC)
    now_utc = datetime.utcnow()
    for log in logs:
        delta = now_utc - log.submitted_at
        secs = max(0, delta.total_seconds())
        days = int(secs // 86400)
        hours = int((secs % 86400) // 3600)
        mins = int((secs % 3600) // 60)
        if days > 0:
            log.waiting_str = f"{days}d {hours}h"
        elif hours > 0:
            log.waiting_str = f"{hours}h {mins}m"
        else:
            log.waiting_str = f"{mins}m"
        log.waiting_days = days

    return render_template(
        "supervisor/pending_reviews.html",
        logs=logs,
        total=total,
        page=page,
        total_pages=total_pages,
        today=ist_today(),
    )


# ─── Log List ─────────────────────────────────────────────────────────────────

@supervisor_bp.route("/logs")
@login_required
@supervisor_required
def log_list():
    from sqlalchemy.orm import joinedload, selectinload
    query = (
        LogEntry.query
        .join(Equipment).join(Department)
        .options(
            joinedload(LogEntry.equipment).joinedload(Equipment.department),
            joinedload(LogEntry.worker),
            selectinload(LogEntry.supervisor_remarks),
        )
    )

    # Filters
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    dept_id = request.args.get("dept_id", type=int)
    equipment_id = request.args.get("equipment_id", type=int)
    worker_id = request.args.get("worker_id", type=int)
    status_filter = request.args.get("status")
    review_filter = request.args.get("review_status")

    if date_from:
        try:
            query = query.filter(LogEntry.log_date >= date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(LogEntry.log_date <= date.fromisoformat(date_to))
        except ValueError:
            pass
    if dept_id:
        query = query.filter(Equipment.dept_id == dept_id)
    if equipment_id:
        query = query.filter(LogEntry.equipment_id == equipment_id)
    if worker_id:
        query = query.filter(LogEntry.worker_id == worker_id)
    if status_filter:
        query = query.filter(LogEntry.status == status_filter)

    ordered = query.order_by(LogEntry.log_date.desc(), LogEntry.submitted_at.desc()).all()

    # Filter by review status in Python (computed property, not a DB column)
    if review_filter:
        ordered = [l for l in ordered if l.review_status == review_filter]

    # Export CSV — do before pagination so all matching rows are exported
    if request.args.get("export") == "csv":
        return _export_csv(ordered)

    # Paginate manually (paginate() doesn't work after Python-side filtering)
    PER_PAGE = 25
    page = request.args.get("page", 1, type=int)
    total = len(ordered)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    logs = ordered[(page - 1) * PER_PAGE : page * PER_PAGE]

    departments = Department.query.filter_by(is_active=True).all()
    equipment_all = Equipment.query.filter_by(is_active=True).order_by(Equipment.name).all()
    workers = User.query.filter_by(role="worker", is_active=True).all()

    # Build CSV export URL preserving current filters (without page)
    csv_args = {k: v for k, v in request.args.items() if k != "page"}
    csv_args["export"] = "csv"
    export_url = url_for("supervisor.log_list") + "?" + urlencode(csv_args)

    return render_template(
        "supervisor/log_list.html",
        logs=logs,
        total=total,
        page=page,
        total_pages=total_pages,
        departments=departments,
        equipment_all=equipment_all,
        workers=workers,
        export_url=export_url,
        filters={
            "date_from": date_from or "",
            "date_to": date_to or "",
            "dept_id": dept_id or "",
            "equipment_id": equipment_id or "",
            "worker_id": worker_id or "",
            "status": status_filter or "",
            "review_status": review_filter or "",
        },
    )


def _export_csv(logs):
    # Collect all unique parameter names across the result set (preserving order)
    param_names = []
    seen = set()
    for log in logs:
        for r in log.readings:
            if r.param_name not in seen:
                param_names.append(r.param_name)
                seen.add(r.param_name)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row: fixed columns + one column per parameter
    writer.writerow([
        "Log ID", "Date", "Time", "Department", "Equipment",
        "Worker", "Equip. Status", "Review Status", "Worker Remark",
        "Supervisor Remark",
    ] + param_names)

    for log in logs:
        readings_map = {r.param_name: r.param_value for r in log.readings}
        sup_remark = log.latest_remark.remark if log.latest_remark else ""
        writer.writerow([
            log.id,
            log.log_date.isoformat(),
            log.log_time.strftime("%H:%M"),
            log.equipment.department.name,
            log.equipment.name,
            log.worker.name,
            log.status,
            log.review_status,
            log.worker_remark or "",
            sup_remark,
        ] + [readings_map.get(p, "") for p in param_names])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ihc_logs.csv"},
    )


# ─── Log Detail ───────────────────────────────────────────────────────────────


@supervisor_bp.route("/log/<int:log_id>", methods=["GET", "POST"])
@login_required
@supervisor_required
def log_detail(log_id):
    log = LogEntry.query.get_or_404(log_id)

    if request.method == "POST":
        remark_text = request.form.get("remark", "").strip()
        review_status = request.form.get("review_status", "Pending")

        if not remark_text:
            flash("Remark cannot be empty.", "danger")
            return redirect(url_for("supervisor.log_detail", log_id=log_id))

        existing = (
            SupervisorRemark.query
            .filter_by(log_id=log_id, supervisor_id=current_user.id)
            .order_by(SupervisorRemark.created_at.desc())
            .first()
        )
        if existing:
            existing.remark = remark_text
            existing.review_status = review_status
            from datetime import datetime
            existing.updated_at = datetime.utcnow()
        else:
            remark = SupervisorRemark(
                log_id=log_id,
                supervisor_id=current_user.id,
                remark=remark_text,
                review_status=review_status,
            )
            db.session.add(remark)

        db.session.commit()
        flash("Remark saved.", "success")
        return redirect(url_for("supervisor.log_detail", log_id=log_id))

    existing_remark = (
        SupervisorRemark.query
        .filter_by(log_id=log_id, supervisor_id=current_user.id)
        .order_by(SupervisorRemark.created_at.desc())
        .first()
    )

    return render_template(
        "supervisor/log_detail.html",
        log=log,
        grouped_readings=group_readings(log),
        existing_remark=existing_remark,
    )


# ─── Historical Comparison ────────────────────────────────────────────────────

@supervisor_bp.route("/log/<int:log_id>/compare")
@login_required
@supervisor_required
def log_compare(log_id):
    log = LogEntry.query.get_or_404(log_id)
    equipment = log.equipment

    ref_date = log.log_date
    comparison = {
        "today": _get_log_for_date(equipment.id, ref_date),
        "yesterday": _get_log_for_date(equipment.id, ref_date - timedelta(days=1)),
        "last_week": _get_log_for_date(equipment.id, ref_date - timedelta(days=7)),
        "last_month": _get_log_for_date(equipment.id, ref_date - timedelta(days=30)),
    }

    # All param names from today's log
    param_names = [r.param_name for r in log.readings]

    # 30-day trend data for Chart.js
    trend_data = _get_trend_data(equipment.id, ref_date, param_names)

    return render_template(
        "supervisor/log_compare.html",
        log=log,
        equipment=equipment,
        comparison=comparison,
        param_names=param_names,
        trend_data=trend_data,
        ref_date=ref_date,
        timedelta=timedelta,
    )


def _get_log_for_date(equipment_id, target_date):
    log = (
        LogEntry.query
        .filter_by(equipment_id=equipment_id, log_date=target_date)
        .order_by(LogEntry.submitted_at.desc())
        .first()
    )
    if not log:
        return None
    return {
        "log": log,
        "readings": {r.param_name: r.param_value for r in log.readings},
        "status": log.status,
    }


def _get_trend_data(equipment_id, ref_date, param_names):
    """Returns {param_name: [(date_str, value), ...]} for last 30 days."""
    start = ref_date - timedelta(days=29)
    logs = (
        LogEntry.query
        .filter(
            LogEntry.equipment_id == equipment_id,
            LogEntry.log_date >= start,
            LogEntry.log_date <= ref_date,
        )
        .order_by(LogEntry.log_date)
        .all()
    )

    trend = {p: [] for p in param_names}
    for log in logs:
        readings_map = {r.param_name: r.param_value for r in log.readings}
        for p in param_names:
            val = readings_map.get(p)
            try:
                trend[p].append({"x": log.log_date.isoformat(), "y": float(val)})
            except (TypeError, ValueError):
                pass

    return trend


# ─── User Management ──────────────────────────────────────────────────────────

@supervisor_bp.route("/users")
@login_required
@supervisor_required
def user_list():
    users = User.query.order_by(User.role, User.name).all()
    departments = Department.query.filter_by(is_active=True).order_by(Department.name).all()
    return render_template("supervisor/users.html", users=users, departments=departments)


@supervisor_bp.route("/users/add", methods=["POST"])
@login_required
@supervisor_required
def user_add():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    role = request.form.get("role", "worker")
    dept_id = request.form.get("dept_id", type=int) or None

    if not all([name, email, password]):
        flash("Name, email and password are all required.", "danger")
        return redirect(url_for("supervisor.user_list"))

    if role not in ("worker", "supervisor"):
        flash("Invalid role.", "danger")
        return redirect(url_for("supervisor.user_list"))

    if User.query.filter_by(email=email).first():
        flash(f"A user with email {email} already exists.", "danger")
        return redirect(url_for("supervisor.user_list"))

    user = User(
        name=name,
        email=email,
        password=bcrypt.generate_password_hash(password).decode("utf-8"),
        role=role,
        dept_id=dept_id,
        must_change_password=True,
    )
    db.session.add(user)
    db.session.commit()
    flash(f"User '{name}' created. They must change their password on first login.", "success")
    return redirect(url_for("supervisor.user_list"))


@supervisor_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@supervisor_required
def user_toggle(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "warning")
        return redirect(url_for("supervisor.user_list"))
    user.is_active = not user.is_active
    db.session.commit()
    state = "activated" if user.is_active else "deactivated"
    flash(f"User '{user.name}' {state}.", "success")
    return redirect(url_for("supervisor.user_list"))


@supervisor_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@supervisor_required
def user_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get("new_password", "").strip()
    if len(new_password) < 6:
        flash("Password must be at least 6 characters.", "danger")
        return redirect(url_for("supervisor.user_list"))
    user.password = bcrypt.generate_password_hash(new_password).decode("utf-8")
    user.must_change_password = True
    db.session.commit()
    flash(f"Password reset for '{user.name}'. They must change it on next login.", "success")
    return redirect(url_for("supervisor.user_list"))
