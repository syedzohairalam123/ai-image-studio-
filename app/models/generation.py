from app.extensions import db
from app.utils import now_utc


class Generation(db.Model):
    __tablename__ = "generations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    prompt = db.Column(db.Text, nullable=False)
    negative_prompt = db.Column(db.Text, nullable=True)
    provider = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(100), nullable=True)
    parameters = db.Column(db.JSON, nullable=True, default=dict)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    # Relationships
    images = db.relationship("Image", backref="generation", lazy="dynamic")

    STATUSES = ("pending", "processing", "completed", "failed", "cancelled")

    def to_dict(self):
        params = self.parameters or {}
        return {
            "id": self.id,
            "user_id": self.user_id,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "provider": self.provider,
            "model": self.model,
            "style": params.get("style"),
            "aspect_ratio": params.get("aspect_ratio"),
            "quality": params.get("quality"),
            "width": params.get("width"),
            "height": params.get("height"),
            "seed": params.get("seed"),
            "parameters": params,
            "status": self.status,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def __repr__(self):
        return f"<Generation {self.id} [{self.status}]>"
