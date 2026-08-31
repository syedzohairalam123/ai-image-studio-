"""AuditLog model — records important administrative actions for accountability.

Every admin action that modifies system state (moderating content, managing
users, changing provider config) should create an audit entry.  The log is
append-only and never modified after creation.

Fields:
  - action: short verb-noun key (e.g. "hide_image", "deactivate_user")
  - entity_type: what kind of object was acted on (user, image, generation, provider, settings)
  - entity_id: ID of the target object
  - details: freeform JSON for extra context (before/after values, reason, etc.)
  - admin_id: who performed the action
  - ip_address: request IP (when available)
"""

from app.extensions import db
from app.utils import now_utc


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    action = db.Column(db.String(80), nullable=False, index=True)
    entity_type = db.Column(db.String(50), nullable=True, index=True)
    entity_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4/IPv6
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False, index=True)

    # Relationships
    admin = db.relationship("User", backref=db.backref("audit_entries", lazy="dynamic"))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "admin_id": self.admin_id,
            "admin_name": self.admin.username if self.admin else None,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<AuditLog {self.id} {self.action} by={self.admin_id}>"
