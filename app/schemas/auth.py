import re

from marshmallow import fields, validate, validates, ValidationError


EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


class SignupSchema:
    """Validates signup form data."""

    def __init__(self, data):
        self.data = data
        self.errors = {}

    def validate(self):
        self._validate_email()
        self._validate_username()
        self._validate_password()
        return len(self.errors) == 0

    def _validate_email(self):
        email = (self.data.get("email") or "").strip().lower()
        if not email:
            self.errors["email"] = "Email is required."
        elif not EMAIL_REGEX.match(email):
            self.errors["email"] = "Please enter a valid email address."
        else:
            self.data["email"] = email

    def _validate_username(self):
        username = (self.data.get("username") or "").strip()
        if not username:
            self.errors["username"] = "Username is required."
        elif len(username) < 3:
            self.errors["username"] = "Username must be at least 3 characters."
        elif len(username) > 100:
            self.errors["username"] = "Username must be at most 100 characters."
        elif not re.match(r"^[a-zA-Z0-9_-]+$", username):
            self.errors["username"] = "Username can only contain letters, numbers, underscores, and hyphens."
        else:
            self.data["username"] = username

    def _validate_password(self):
        password = self.data.get("password") or ""
        if not password:
            self.errors["password"] = "Password is required."
        elif len(password) < 8:
            self.errors["password"] = "Password must be at least 8 characters."
        elif len(password) > 128:
            self.errors["password"] = "Password must be at most 128 characters."

    def validate_unique(self, User):
        """Check email and username uniqueness. Call after basic validation."""
        if "email" not in self.errors:
            email = self.data["email"]
            if User.query.filter_by(email=email).first():
                self.errors["email"] = "An account with this email already exists."
        if "username" not in self.errors:
            username = self.data["username"]
            if User.query.filter_by(username=username).first():
                self.errors["username"] = "This username is already taken."


class LoginSchema:
    """Validates login form data."""

    def __init__(self, data):
        self.data = data
        self.errors = {}

    def validate(self):
        email = (self.data.get("email") or "").strip().lower()
        password = self.data.get("password") or ""

        if not email:
            self.errors["email"] = "Email is required."
        elif not EMAIL_REGEX.match(email):
            self.errors["email"] = "Please enter a valid email address."
        else:
            self.data["email"] = email

        if not password:
            self.errors["password"] = "Password is required."

        return len(self.errors) == 0


class ProfileUpdateSchema:
    """Validates profile update form data."""

    def __init__(self, data):
        self.data = data
        self.errors = {}

    def validate(self):
        username = (self.data.get("username") or "").strip()
        if not username:
            self.errors["username"] = "Username is required."
        elif len(username) < 3:
            self.errors["username"] = "Username must be at least 3 characters."
        elif len(username) > 100:
            self.errors["username"] = "Username must be at most 100 characters."
        elif not re.match(r"^[a-zA-Z0-9_-]+$", username):
            self.errors["username"] = "Username can only contain letters, numbers, underscores, and hyphens."
        else:
            self.data["username"] = username
        return len(self.errors) == 0

    def validate_unique(self, User, current_user_id):
        """Check username uniqueness, excluding current user."""
        if "username" not in self.errors:
            username = self.data["username"]
            existing = User.query.filter(User.username == username, User.id != current_user_id).first()
            if existing:
                self.errors["username"] = "This username is already taken."


class ForgotPasswordSchema:
    """Validates forgot password form data."""

    def __init__(self, data):
        self.data = data
        self.errors = {}

    def validate(self):
        email = (self.data.get("email") or "").strip().lower()
        if not email:
            self.errors["email"] = "Email is required."
        elif not EMAIL_REGEX.match(email):
            self.errors["email"] = "Please enter a valid email address."
        else:
            self.data["email"] = email
        return len(self.errors) == 0


class ChangePasswordSchema:
    """Validates change password form data."""

    def __init__(self, data):
        self.data = data
        self.errors = {}

    def validate(self):
        current = self.data.get("current_password") or ""
        new = self.data.get("new_password") or ""
        confirm = self.data.get("confirm_password") or ""

        if not current:
            self.errors["current_password"] = "Current password is required."
        if not new:
            self.errors["new_password"] = "New password is required."
        elif len(new) < 8:
            self.errors["new_password"] = "New password must be at least 8 characters."
        elif len(new) > 128:
            self.errors["new_password"] = "New password must be at most 128 characters."
        if new and confirm != new:
            self.errors["confirm_password"] = "Passwords do not match."
        return len(self.errors) == 0
