"""Image model with support for tags, collections, and search."""

import secrets

from app.extensions import db
from app.utils import now_utc


class Image(db.Model):
    """A generated or uploaded image."""

    __tablename__ = "images"

    id = db.Column(db.Integer, primary_key=True)
    generation_id = db.Column(db.Integer, db.ForeignKey("generations.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=True)
    file_path = db.Column(db.String(500), nullable=False)
    thumb_path = db.Column(db.String(500), nullable=True)
    format = db.Column(db.String(10), nullable=True, default="png")
    title = db.Column(db.String(200), nullable=True)
    prompt = db.Column(db.Text, nullable=True)  # Denormalized from generation for search
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    seed = db.Column(db.Integer, nullable=True)
    is_favorite = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    meta = db.Column("metadata", db.JSON, nullable=True, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)

    # --- Privacy & Public Sharing ---
    is_public = db.Column(db.Boolean, default=False, nullable=False, index=True)
    share_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    public_prompt = db.Column(db.Text, nullable=True)  # Optional prompt shown publicly (sanitized)
    moderation_state = db.Column(
        db.String(20), default="active", nullable=False, index=True
    )  # active, reported, hidden
    view_count = db.Column(db.Integer, default=0, nullable=False)
    like_count = db.Column(db.Integer, default=0, nullable=False)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)

    MODERATION_STATES = ("active", "reported", "hidden")

    def generate_share_token(self):
        """Generate a cryptographically secure share token."""
        self.share_token = secrets.token_urlsafe(48)
        return self.share_token

    def make_public(self):
        """Make this image public. Generates share token if needed."""
        self.is_public = True
        if not self.share_token:
            self.generate_share_token()
        if not self.published_at:
            self.published_at = now_utc()

    def make_private(self):
        """Remove public visibility."""
        self.is_public = False
        self.moderation_state = "active"

    def to_dict(self, include_metadata=True):
        data = {
            "id": self.id,
            "generation_id": self.generation_id,
            "user_id": self.user_id,
            "filename": self.filename,
            "file_path": self.file_path,
            "thumb_path": self.thumb_path,
            "format": self.format,
            "title": self.title,
            "prompt": self.prompt,
            "width": self.width,
            "height": self.height,
            "file_size": self.file_size,
            "seed": self.seed,
            "is_favorite": self.is_favorite,
            "is_deleted": self.is_deleted,
            "is_public": self.is_public,
            "share_token": self.share_token,
            "moderation_state": self.moderation_state,
            "view_count": self.view_count,
            "like_count": self.like_count,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "tags": [t.to_dict() for t in self.tags] if hasattr(self, "tags") else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_metadata:
            data["metadata"] = self.meta
        return data

    def to_public_dict(self):
        """Serialize for public consumption — NO private data exposed."""
        from app.models.user import User
        creator = db.session.get(User, self.user_id) if self.user_id else None
        return {
            "id": self.share_token or str(self.id),
            "title": self.title,
            "public_prompt": self.public_prompt,
            "style": self.style,
            "width": self.width,
            "height": self.height,
            "aspect_ratio": self.aspect_ratio,
            "view_count": self.view_count,
            "like_count": self.like_count,
            "creator_display_name": creator.display_name if creator else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "url": f"/share/{self.share_token}" if self.share_token else None,
            "image_url": f"/api/v1/images/{self.id}/file",
            "thumb_url": f"/api/v1/images/{self.id}/thumbnail",
        }

    @property
    def aspect_ratio(self):
        if self.width and self.height:
            from math import gcd
            d = gcd(self.width, self.height)
            return f"{self.width // d}:{self.height // d}"
        return None

    @property
    def style(self):
        """Get style from generation parameters."""
        if self.generation and self.generation.parameters:
            return self.generation.parameters.get("style")
        return None

    @property
    def model_name(self):
        """Get model name from generation."""
        if self.generation:
            return self.generation.model
        return None

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = now_utc()

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None

    def __repr__(self):
        return f"<Image {self.id} {self.filename}>"
