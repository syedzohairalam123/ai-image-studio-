"""Utility operation model — tracks every utility action for history display."""

from app.extensions import db
from app.utils import now_utc


class UtilityOperation(db.Model):
    """Tracks utility operations: upscale, background removal, image-to-prompt.

    Each operation is logged with its status, parameters, and result.
    The UI shows this as a scrollable history panel.
    """

    __tablename__ = "utility_operations"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    image_id = db.Column(db.Integer, db.ForeignKey("images.id"), nullable=True, index=True)

    # Operation details
    operation = db.Column(db.String(50), nullable=False, index=True)  # upscale, bg_remove, describe, batch
    provider = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)  # pending, processing, completed, failed

    # Parameters & result
    params = db.Column(db.JSON, nullable=True, default=dict)
    result = db.Column(db.JSON, nullable=True, default=dict)
    error_message = db.Column(db.Text, nullable=True)

    # Batch tracking
    batch_id = db.Column(db.String(36), nullable=True, index=True)  # UUID for batch operations
    batch_total = db.Column(db.Integer, nullable=True)
    batch_completed = db.Column(db.Integer, nullable=True, default=0)
    batch_failed = db.Column(db.Integer, nullable=True, default=0)

    # Timing
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)

    # Relationships
    image = db.relationship("Image", backref="utility_operations")
    user = db.relationship("User", backref="utility_operations")

    STATUSES = ("pending", "processing", "completed", "failed")
    OPERATIONS = ("upscale", "bg_remove", "describe", "batch_upscale", "batch_describe")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "image_id": self.image_id,
            "operation": self.operation,
            "provider": self.provider,
            "status": self.status,
            "params": self.params or {},
            "result": self.result or {},
            "error_message": self.error_message,
            "batch_id": self.batch_id,
            "batch_total": self.batch_total,
            "batch_completed": self.batch_completed,
            "batch_failed": self.batch_failed,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "duration_ms": self._duration_ms,
        }

    @property
    def _duration_ms(self):
        """Calculate duration in milliseconds."""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return int(delta.total_seconds() * 1000)
        return None

    @property
    def operation_label(self):
        """Human-readable operation name."""
        labels = {
            "upscale": "Upscale",
            "bg_remove": "Background Removal",
            "describe": "Image to Prompt",
            "batch_upscale": "Batch Upscale",
            "batch_describe": "Batch Image to Prompt",
        }
        return labels.get(self.operation, self.operation)

    @property
    def status_icon(self):
        """Status icon for display."""
        icons = {
            "pending": "⏳",
            "processing": "⚙️",
            "completed": "✓",
            "failed": "✕",
        }
        return icons.get(self.status, "—")

    def __repr__(self):
        return f"<UtilityOperation {self.id} [{self.operation}] {self.status}>"
