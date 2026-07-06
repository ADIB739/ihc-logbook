"""
IHC Logbook — Automated Test Suite
Run: python tests.py
"""
import os
import sys
import unittest
from datetime import date, time, datetime, timedelta

# Use an in-memory SQLite DB and disable CSRF for tests
os.environ["FLASK_DEBUG"] = "1"

from app import create_app
from app.extensions import db, bcrypt
from app.models import (
    Department, Equipment, EquipmentParam,
    User, LogEntry, LogReading, SupervisorRemark,
)


# ── Test config: in-memory DB, no CSRF ───────────────────────────────────────
class TestConfig:
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    TESTING = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)


# ── Base: build a fresh app + seed minimal data for every test ────────────────
class BaseTestCase(unittest.TestCase):

    def setUp(self):
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        self.app_ctx = self.app.app_context()
        self.app_ctx.push()
        db.create_all()
        self._seed()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_ctx.pop()

    # ── Seed: 2 depts, 2 equipment, 3 users ──────────────────────────────────
    def _seed(self):
        hvac = Department(name="HVAC", is_active=True)
        elec = Department(name="Electrical", is_active=True)
        db.session.add_all([hvac, elec])
        db.session.flush()

        chiller = Equipment(dept_id=hvac.id, name="Chiller-1", is_active=True)
        transformer = Equipment(dept_id=elec.id, name="Transformer-1", is_active=True)
        db.session.add_all([chiller, transformer])
        db.session.flush()

        # 2 params for Chiller-1
        db.session.add_all([
            EquipmentParam(equipment_id=chiller.id, param_name="Ambient Temp",
                           unit="°C", section="General", display_order=1),
            EquipmentParam(equipment_id=chiller.id, param_name="Voltage",
                           unit="V", section="General", display_order=2),
        ])
        # 2 params for Transformer-1
        db.session.add_all([
            EquipmentParam(equipment_id=transformer.id, param_name="HV RY",
                           unit="kV", section="HV Voltages", display_order=1),
            EquipmentParam(equipment_id=transformer.id, param_name="LV RY",
                           unit="V", section="LV Voltages", display_order=2),
        ])

        pw_hash = bcrypt.generate_password_hash("password123").decode("utf-8")
        supervisor = User(name="Supervisor", email="supervisor@example.com",
                          password=pw_hash, role="supervisor", is_active=True)
        hvac_worker = User(name="HVAC Worker", email="hvac@example.com",
                           password=pw_hash, role="worker",
                           dept_id=hvac.id, is_active=True)
        elec_worker = User(name="Elec Worker", email="elec@example.com",
                           password=pw_hash, role="worker",
                           dept_id=elec.id, is_active=True)
        db.session.add_all([supervisor, hvac_worker, elec_worker])
        db.session.commit()

        # Store IDs for use in tests
        self.hvac_id = hvac.id
        self.elec_id = elec.id
        self.chiller_id = chiller.id
        self.transformer_id = transformer.id

    # ── Helpers ───────────────────────────────────────────────────────────────
    def login(self, email, password="password123"):
        return self.client.post("/login", data={"email": email, "password": password},
                                follow_redirects=True)

    def logout(self):
        return self.client.get("/logout", follow_redirects=True)

    def submit_log(self, equipment_id, hour=9, status="Running", params=None):
        data = {
            "equipment_id": equipment_id,
            "log_date": date.today().isoformat(),
            "log_time": f"{hour:02d}:00",
            "status": status,
            "worker_remark": "",
        }
        if params:
            for k, v in params.items():
                data[f"param_{k}"] = v
        return self.client.post("/worker/log/submit", data=data,
                                follow_redirects=True)


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE A — Authentication
# ═══════════════════════════════════════════════════════════════════════════════
class TestAuthentication(BaseTestCase):

    def test_A1_supervisor_login_redirects_to_supervisor_dashboard(self):
        r = self.login("supervisor@example.com")
        self.assertIn(b"Supervisor", r.data)
        self.assertEqual(r.status_code, 200)

    def test_A2_worker_login_redirects_to_worker_dashboard(self):
        r = self.login("hvac@example.com")
        self.assertIn(b"Dashboard", r.data)
        self.assertEqual(r.status_code, 200)

    def test_A3_wrong_password_shows_error(self):
        r = self.login("hvac@example.com", "wrongpassword")
        self.assertIn(b"Invalid email or password", r.data)

    def test_A4_wrong_email_shows_error(self):
        r = self.login("nobody@example.com")
        self.assertIn(b"Invalid email or password", r.data)

    def test_A5_unauthenticated_dashboard_redirects_to_login(self):
        r = self.client.get("/worker/dashboard", follow_redirects=True)
        self.assertIn(b"Sign In", r.data)

    def test_A6_logout_clears_session(self):
        self.login("hvac@example.com")
        self.logout()
        r = self.client.get("/worker/dashboard", follow_redirects=True)
        self.assertIn(b"Sign In", r.data)

    def test_A7_worker_cannot_access_supervisor_dashboard(self):
        self.login("hvac@example.com")
        r = self.client.get("/supervisor/dashboard")
        self.assertEqual(r.status_code, 403)


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE C — Worker Log Submission (HVAC)
# ═══════════════════════════════════════════════════════════════════════════════
class TestWorkerSubmissionHVAC(BaseTestCase):

    def test_C1_submit_chiller_log_success(self):
        self.login("hvac@example.com")
        r = self.submit_log(self.chiller_id, hour=9,
                            params={"Ambient Temp": "25.5", "Voltage": "415"})
        self.assertIn(b"submitted successfully", r.data)
        entry = LogEntry.query.first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.status, "Running")

    def test_C2_submit_with_blank_params_still_succeeds(self):
        self.login("hvac@example.com")
        r = self.submit_log(self.chiller_id, hour=10)
        self.assertIn(b"submitted successfully", r.data)
        readings = LogReading.query.all()
        # Both readings saved but with null value
        self.assertEqual(len(readings), 2)
        self.assertIsNone(readings[0].param_value)

    def test_C3_readings_saved_correctly(self):
        self.login("hvac@example.com")
        self.submit_log(self.chiller_id, hour=11,
                        params={"Ambient Temp": "28.0", "Voltage": "410"})
        readings = {r.param_name: r.param_value for r in LogReading.query.all()}
        self.assertEqual(readings["Ambient Temp"], "28.0")
        self.assertEqual(readings["Voltage"], "410")

    def test_C4_duplicate_same_hour_blocked(self):
        self.login("hvac@example.com")
        self.submit_log(self.chiller_id, hour=9)
        r = self.submit_log(self.chiller_id, hour=9)
        self.assertIn(b"already submitted", r.data)
        self.assertEqual(LogEntry.query.count(), 1)

    def test_C5_different_hours_both_accepted(self):
        self.login("hvac@example.com")
        self.submit_log(self.chiller_id, hour=9)
        r = self.submit_log(self.chiller_id, hour=10)
        self.assertIn(b"submitted successfully", r.data)
        self.assertEqual(LogEntry.query.count(), 2)

    def test_C6_missing_status_rejected(self):
        self.login("hvac@example.com")
        r = self.client.post("/worker/log/submit", data={
            "equipment_id": self.chiller_id,
            "log_date": date.today().isoformat(),
            "log_time": "09:00",
            "status": "",           # blank status
            "worker_remark": "",
        }, follow_redirects=True)
        self.assertNotIn(b"submitted successfully", r.data)
        self.assertEqual(LogEntry.query.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE D — Worker Log Submission (Electrical)
# ═══════════════════════════════════════════════════════════════════════════════
class TestWorkerSubmissionElectrical(BaseTestCase):

    def test_D1_electrical_worker_submits_transformer_log(self):
        self.login("elec@example.com")
        r = self.submit_log(self.transformer_id, hour=9,
                            params={"HV RY": "33.1", "LV RY": "433"})
        self.assertIn(b"submitted successfully", r.data)
        self.assertEqual(LogEntry.query.first().equipment_id, self.transformer_id)

    def test_D4_electrical_worker_blocked_from_hvac_equipment(self):
        self.login("elec@example.com")
        r = self.submit_log(self.chiller_id, hour=9)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(LogEntry.query.count(), 0)

    def test_D4b_hvac_worker_blocked_from_electrical_equipment(self):
        self.login("hvac@example.com")
        r = self.submit_log(self.transformer_id, hour=9)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(LogEntry.query.count(), 0)


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE E — Edit Window
# ═══════════════════════════════════════════════════════════════════════════════
class TestEditWindow(BaseTestCase):

    def _make_log(self, minutes_ago=0):
        """Insert a log entry directly into DB, submitted N minutes ago."""
        self.login("hvac@example.com")
        worker = User.query.filter_by(email="hvac@example.com").first()
        log = LogEntry(
            equipment_id=self.chiller_id,
            worker_id=worker.id,
            log_date=date.today(),
            log_time=time(9, 0),
            shift="",
            status="Running",
            submitted_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
        )
        db.session.add(log)
        db.session.commit()
        return log

    def test_E1_edit_within_5_minutes_opens_form(self):
        log = self._make_log(minutes_ago=1)
        r = self.client.get(f"/worker/log/{log.id}/edit")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Edit Log", r.data)

    def test_E4_edit_after_5_minutes_blocked(self):
        log = self._make_log(minutes_ago=6)
        r = self.client.get(f"/worker/log/{log.id}/edit", follow_redirects=True)
        self.assertIn(b"edit window has passed", r.data)

    def test_E5_edit_saves_changes(self):
        log = self._make_log(minutes_ago=1)
        # Add a reading so it can be updated
        db.session.add(LogReading(log_id=log.id, param_name="Ambient Temp",
                                  param_value="25.0", unit="°C"))
        db.session.commit()

        r = self.client.post(f"/worker/log/{log.id}/edit", data={
            "status": "Standby",
            "worker_remark": "Updated remark",
            "param_Ambient Temp": "30.5",
        }, follow_redirects=True)
        self.assertIn(b"updated successfully", r.data)
        updated = LogEntry.query.get(log.id)
        self.assertEqual(updated.status, "Standby")

    def test_E_other_worker_cannot_edit(self):
        log = self._make_log(minutes_ago=1)
        self.logout()
        self.login("elec@example.com")
        r = self.client.get(f"/worker/log/{log.id}/edit")
        self.assertEqual(r.status_code, 403)


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE F — Supervisor Review
# ═══════════════════════════════════════════════════════════════════════════════
class TestSupervisorReview(BaseTestCase):

    def _make_log(self):
        hvac_worker = User.query.filter_by(email="hvac@example.com").first()
        log = LogEntry(
            equipment_id=self.chiller_id,
            worker_id=hvac_worker.id,
            log_date=date.today(),
            log_time=time(9, 0),
            shift="", status="Running",
        )
        db.session.add(log)
        db.session.commit()
        return log

    def test_F1_supervisor_dashboard_loads(self):
        self.login("supervisor@example.com")
        r = self.client.get("/supervisor/dashboard")
        self.assertEqual(r.status_code, 200)

    def test_F5_supervisor_can_approve_log(self):
        log = self._make_log()
        self.login("supervisor@example.com")
        r = self.client.post(f"/supervisor/log/{log.id}", data={
            "review_status": "Approved",
            "remark": "All values nominal.",
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        remark = SupervisorRemark.query.filter_by(log_id=log.id).first()
        self.assertIsNotNone(remark)
        self.assertEqual(remark.review_status, "Approved")

    def test_F6_supervisor_can_flag_needs_attention(self):
        log = self._make_log()
        self.login("supervisor@example.com")
        self.client.post(f"/supervisor/log/{log.id}", data={
            "review_status": "NeedsAttention",
            "remark": "Voltage reading too low.",
        }, follow_redirects=True)
        remark = SupervisorRemark.query.filter_by(log_id=log.id).first()
        self.assertIsNotNone(remark)
        self.assertEqual(remark.review_status, "NeedsAttention")

    def test_F_worker_cannot_review_logs(self):
        log = self._make_log()
        self.login("hvac@example.com")
        r = self.client.post(f"/supervisor/log/{log.id}", data={
            "review_status": "Approved", "remark": "test",
        })
        self.assertIn(r.status_code, [403, 302])


# ═══════════════════════════════════════════════════════════════════════════════
# MODULE H — Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════
class TestEdgeCases(BaseTestCase):

    def test_H1_decimal_values_saved_correctly(self):
        self.login("hvac@example.com")
        self.submit_log(self.chiller_id, hour=9,
                        params={"Ambient Temp": "23.45"})
        r = LogReading.query.filter_by(param_name="Ambient Temp").first()
        self.assertEqual(r.param_value, "23.45")

    def test_H2_negative_values_accepted(self):
        self.login("hvac@example.com")
        self.submit_log(self.chiller_id, hour=9,
                        params={"Ambient Temp": "-5.0"})
        r = LogReading.query.filter_by(param_name="Ambient Temp").first()
        self.assertEqual(r.param_value, "-5.0")

    def test_H5_supervisor_redirected_away_from_worker_routes(self):
        self.login("supervisor@example.com")
        r = self.client.get("/worker/dashboard", follow_redirects=True)
        # Supervisor should land on supervisor dashboard, not worker
        self.assertNotIn(b"Submit Hourly Log", r.data)

    def test_H_log_form_loads_with_equipment_id(self):
        self.login("hvac@example.com")
        r = self.client.get(f"/worker/log/new?equipment_id={self.chiller_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Ambient Temp", r.data)

    def test_H_log_form_empty_without_equipment_id(self):
        self.login("hvac@example.com")
        r = self.client.get("/worker/log/new")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Select an equipment", r.data)

    def test_H_inactive_user_cannot_login(self):
        worker = User.query.filter_by(email="hvac@example.com").first()
        worker.is_active = False
        db.session.commit()
        r = self.login("hvac@example.com")
        self.assertIn(b"Invalid email or password", r.data)


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    loader = unittest.TestLoader()
    loader.sortTestMethodsUsing = None  # keep declaration order

    suite = unittest.TestSuite()
    for cls in [
        TestAuthentication,
        TestWorkerSubmissionHVAC,
        TestWorkerSubmissionElectrical,
        TestEditWindow,
        TestSupervisorReview,
        TestEdgeCases,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
