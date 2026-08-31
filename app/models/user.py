from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager
from app.utils import now_utc


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100), nullable=True)  # Shown publicly on shared images
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    # Relationships
    generations = db.relationship("Generation", backref="user", lazy="dynamic")
    images = db.relationship("Image", backref="owner", lazy="dynamic")
    saved_prompts = db.relationship("SavedPrompt", backref="user", lazy="dynamic")
    style_presets = db.relationship("StylePreset", backref="user", lazy="dynamic")
    reference_images = db.relationship("ReferenceImage", backref="user", lazy="dynamic")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def effective_display_name(self):
        """Return display_name if set, otherwise username."""
        return self.display_name or self.username

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "display_name": self.effective_display_name,
            "is_admin": self.is_admin,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def to_public_dict(self):
        """Public-safe serialization — NO email, NO internal IDs, NO secrets."""
        return {
            "display_name": self.effective_display_name,
            "member_since": self.created_at.strftime("%B %Y") if self.created_at else None,
        }

    def __repr__(self):
        return f"<User {self.username}>"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))
