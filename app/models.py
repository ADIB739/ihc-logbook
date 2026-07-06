from datetime import datetime
from flask_login import UserMixin
from app.extensions import db, login_manager


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class Department(db.Model):
    __tablename__ = "departments"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    equipment = db.relationship("Equipment", backref="department", lazy=True)
    users = db.relationship("User", backref="department", lazy=True)

    def __repr__(self):
        return f"<Department {self.name}>"


class Equipment(db.Model):
    __tablename__ = "equipment"

    id = db.Column(db.Integer, primary_key=True)
    dept_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    params = db.relationship(
        "EquipmentParam", backref="equipment", lazy=True,
        order_by="EquipmentParam.display_order"
    )
    log_entries = db.relationship("LogEntry", backref="equipment", lazy=True)

    def __repr__(self):
        return f"<Equipment {self.name}>"


class EquipmentParam(db.Model):
    __tablename__ = "equipment_params"

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False)
    param_name = db.Column(db.String(100), nullable=False)
    unit = db.Column(db.String(20))
    section = db.Column(db.String(50))
    subsection = db.Column(db.String(100))
    display_order = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):
        return f"<Param {self.param_name} ({self.unit})>"


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    dept_id = db.Column(db.Integer, db.ForeignKey("departments.id"), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    log_entries = db.relationship("LogEntry", backref="worker", lazy=True)
    remarks = db.relationship("SupervisorRemark", backref="supervisor", lazy=True)

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


class LogEntry(db.Model):
    __tablename__ = "log_entries"

    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False)
    worker_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    log_date = db.Column(db.Date, nullable=False)
    log_time = db.Column(db.Time, nullable=False)
    shift = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    worker_remark = db.Column(db.Text)
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_edited = db.Column(db.Boolean, nullable=False, default=False)
    edited_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        # FIX 2: DB-level unique constraint prevents race-condition duplicate submissions
        db.UniqueConstraint(
            "worker_id", "equipment_id", "log_date", "log_time",
            name="uq_worker_equip_datetime"
        ),
        db.Index("ix_log_date_equip",   "log_date", "equipment_id"),
        db.Index("ix_log_worker_date",  "worker_id", "log_date"),
        db.Index("ix_log_submitted_at", "submitted_at"),
    )

    readings = db.relationship(
        "LogReading", backref="log_entry", lazy=True, cascade="all, delete-orphan"
    )
    supervisor_remarks = db.relationship(
        "SupervisorRemark", backref="log_entry", lazy="select",
        cascade="all, delete-orphan",
        order_by="SupervisorRemark.created_at.desc()"
    )

    @property
    def is_editable(self):
        from datetime import timedelta
        ref = self.edited_at or self.submitted_at
        return (datetime.utcnow() - ref) < timedelta(minutes=5)

    @property
    def needs_re_review(self):
        if not self.is_edited or not self.edited_at:
            return False
        latest = self.latest_remark
        if not latest:
            return False
        return self.edited_at > latest.created_at

    # FIX 3: Use already-loaded supervisor_remarks — zero extra queries when
    # selectinload(LogEntry.supervisor_remarks) is used on the parent query.
    @property
    def review_status(self):
        remarks = self.supervisor_remarks
        return remarks[0].review_status if remarks else "Pending"

    @property
    def latest_remark(self):
        return self.supervisor_remarks[0] if self.supervisor_remarks else None

    def __repr__(self):
        return f"<LogEntry {self.id} {self.log_date}>"


class LogReading(db.Model):
    __tablename__ = "log_readings"

    id = db.Column(db.Integer, primary_key=True)
    log_id = db.Column(db.Integer, db.ForeignKey("log_entries.id"), nullable=False)
    param_name = db.Column(db.String(100), nullable=False)
    param_value = db.Column(db.String(50))
    unit = db.Column(db.String(20))

    def __repr__(self):
        return f"<Reading {self.param_name}={self.param_value}>"


class SupervisorRemark(db.Model):
    __tablename__ = "supervisor_remarks"

    id = db.Column(db.Integer, primary_key=True)
    log_id = db.Column(db.Integer, db.ForeignKey("log_entries.id"), nullable=False)
    supervisor_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    remark = db.Column(db.Text, nullable=False)
    review_status = db.Column(db.String(20), nullable=False, default="Pending")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Remark log={self.log_id} status={self.review_status}>"
