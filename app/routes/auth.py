from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user, login_required

from app.extensions import db
from app.models.user import User
from app.routes import main_bp
from app.schemas.auth import (
    ChangePasswordSchema,
    ForgotPasswordSchema,
    LoginSchema,
    ProfileUpdateSchema,
    SignupSchema,
)


# ---- Signup ----

@main_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "GET":
        return render_template("auth/signup.html")

    data = request.form.to_dict()
    schema = SignupSchema(data)

    if not schema.validate():
        flash("Please fix the errors below.", "error")
        return render_template("auth/signup.html", errors=schema.errors, data=data), 422

    schema.validate_unique(User)
    if schema.errors:
        flash("Please fix the errors below.", "error")
        return render_template("auth/signup.html", errors=schema.errors, data=data), 422

    user = User(
        email=data["email"],
        username=data["username"],
    )
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()

    login_user(user)
    flash("Account created successfully! Welcome to AI Studio.", "success")
    return redirect(url_for("main.index"))


# ---- Login ----

@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "GET":
        return render_template("auth/login.html")

    data = request.form.to_dict()
    schema = LoginSchema(data)

    if not schema.validate():
        flash("Please fix the errors below.", "error")
        return render_template("auth/login.html", errors=schema.errors, data=data), 422

    user = User.query.filter_by(email=data["email"]).first()

    if user is None or not user.check_password(data["password"]):
        flash("Invalid email or password.", "error")
        return render_template("auth/login.html", errors={"email": "Invalid email or password."}, data=data), 401

    if not user.is_active:
        flash("Your account has been deactivated. Please contact support.", "error")
        return render_template("auth/login.html", errors={"email": "Account is deactivated."}, data=data), 403

    login_user(user, remember=request.form.get("remember") == "on")
    flash(f"Welcome back, {user.username}!", "success")

    next_page = request.args.get("next")
    # SECURITY: Only allow relative paths (start with / but NOT // or http:)
    # This prevents open redirects to external sites
    if next_page and next_page.startswith("/") and not next_page.startswith("//"):
        return redirect(next_page)
    return redirect(url_for("main.index"))


# ---- Logout ----

@main_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))


# ---- Profile ----

@main_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "GET":
        return render_template("auth/profile.html")

    data = request.form.to_dict()
    schema = ProfileUpdateSchema(data)

    if not schema.validate():
        flash("Please fix the errors below.", "error")
        return render_template("auth/profile.html", errors=schema.errors, data=data), 422

    schema.validate_unique(User, current_user.id)
    if schema.errors:
        flash("Please fix the errors below.", "error")
        return render_template("auth/profile.html", errors=schema.errors, data=data), 422

    current_user.username = data["username"]
    db.session.commit()
    flash("Profile updated successfully.", "success")
    return redirect(url_for("main.profile"))


# ---- Change Password ----

@main_bp.route("/profile/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "GET":
        return render_template("auth/change_password.html")

    data = request.form.to_dict()
    schema = ChangePasswordSchema(data)

    if not schema.validate():
        flash("Please fix the errors below.", "error")
        return render_template("auth/change_password.html", errors=schema.errors), 422

    if not current_user.check_password(data["current_password"]):
        flash("Current password is incorrect.", "error")
        return render_template("auth/change_password.html", errors={"current_password": "Incorrect password."}), 401

    current_user.set_password(data["new_password"])
    db.session.commit()
    flash("Password changed successfully.", "success")
    return redirect(url_for("main.profile"))


# ---- Forgot Password (placeholder) ----

@main_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))

    if request.method == "GET":
        return render_template("auth/forgot_password.html")

    data = request.form.to_dict()
    schema = ForgotPasswordSchema(data)

    if not schema.validate():
        flash("Please fix the errors below.", "error")
        return render_template("auth/forgot_password.html", errors=schema.errors, data=data), 422

    user = User.query.filter_by(email=data["email"]).first()
    # Always show success to prevent email enumeration
    flash("If an account exists with that email, a password reset link has been sent.", "info")
    return render_template("auth/forgot_password.html", success=True)


# ---- API: Auth status (for frontend) ----

@main_bp.route("/api/auth/status")
def auth_status():
    if current_user.is_authenticated:
        return jsonify({
            "authenticated": True,
            "user": current_user.to_dict(),
        })
    return jsonify({"authenticated": False, "user": None})
