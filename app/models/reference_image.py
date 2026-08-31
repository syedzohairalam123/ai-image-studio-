from app.extensions import db
from app.utils import now_utc


class ReferenceImage(db.Model):
    __tablename__ = "reference_images"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(255), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    mime_type = db.Column(db.String(100), nullable=True)
    is_permanent = db.Column(db.Boolean, default=False, nullable=False)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "filename": self.filename,
            "file_path": self.file_path,
            "original_filename": self.original_filename,
            "file_size": self.file_size,
            "width": self.width,
            "height": self.height,
            "mime_type": self.mime_type,
            "is_permanent": self.is_permanent,
            "is_deleted": self.is_deleted,
            "url": f"/api/v1/references/{self.id}/file",
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def soft_delete(self):
        self.is_deleted = True

    def __repr__(self):
        return f"<ReferenceImage {self.id} '{self.filename}'>"
