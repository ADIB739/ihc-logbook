from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import bcrypt, db
from app.models import User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.must_change_password:
            return redirect(url_for("auth.change_password"))
        return redirect(
            url_for("worker.dashboard") if current_user.role == "worker"
            else url_for("supervisor.dashboard")
        )
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email, is_active=True).first()

        if user and bcrypt.check_password_hash(user.password, password):
            session.permanent = True   # apply PERMANENT_SESSION_LIFETIME timeout
            login_user(user)
            if user.must_change_password:
                flash("Please set a new password before continuing.", "warning")
                return redirect(url_for("auth.change_password"))
            next_page = request.args.get("next")
            if user.role == "supervisor":
                return redirect(next_page or url_for("supervisor.dashboard"))
            return redirect(next_page or url_for("worker.dashboard"))

        flash("Invalid email or password. Please try again.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "").strip()
        confirm_pw = request.form.get("confirm_password", "").strip()

        if not bcrypt.check_password_hash(current_user.password, current_pw):
            flash("Current password is incorrect.", "danger")
            return render_template("auth/change_password.html")

        if len(new_pw) < 6:
            flash("New password must be at least 6 characters.", "danger")
            return render_template("auth/change_password.html")

        if new_pw != confirm_pw:
            flash("New passwords do not match.", "danger")
            return render_template("auth/change_password.html")

        current_user.password = bcrypt.generate_password_hash(new_pw).decode("utf-8")
        current_user.must_change_password = False
        db.session.commit()
        flash("Password changed successfully.", "success")
        return redirect(url_for("auth.index"))

    return render_template("auth/change_password.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
