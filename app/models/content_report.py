"""Content report model for moderation of public content."""

from app.extensions import db
from app.utils import now_utc


class ContentReport(db.Model):
    """A user-submitted report against a public image."""

    __tablename__ = "content_reports"

    id = db.Column(db.Integer, primary_key=True)
    image_id = db.Column(db.Integer, db.ForeignKey("images.id"), nullable=False, index=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    reason = db.Column(db.String(50), nullable=False)  # spam, inappropriate, copyright, other
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)  # pending, reviewed, dismissed, actioned
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)

    # Relationships
    image = db.relationship("Image", backref="reports", lazy="joined")
    reporter = db.relationship("User", foreign_keys=[reporter_id], lazy="joined")
    reviewer = db.relationship("User", foreign_keys=[reviewed_by], lazy="joined")

    VALID_REASONS = ("spam", "inappropriate", "copyright", "other")
    VALID_STATUSES = ("pending", "reviewed", "dismissed", "actioned")

    __table_args__ = (
        db.UniqueConstraint("image_id", "reporter_id", name="uq_report_per_user"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "image_id": self.image_id,
            "reporter_id": self.reporter_id,
            "reporter_name": self.reporter.display_name if self.reporter else None,
            "reason": self.reason,
            "description": self.description,
            "status": self.status,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<ContentReport {self.id} image={self.image_id} status={self.status}>"
