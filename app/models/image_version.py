"""Image version model — tracks every edit version of an image."""

from app.extensions import db
from app.utils import now_utc


class ImageVersion(db.Model):
    """Tracks every version of an image through the editing workflow.

    Each edit creates a new version while preserving the original.
    Version chain: original → v2 → v3 → ...
    """

    __tablename__ = "image_versions"

    id = db.Column(db.Integer, primary_key=True)
    image_id = db.Column(db.Integer, db.ForeignKey("images.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    version_number = db.Column(db.Integer, nullable=False, default=1)
    parent_version_id = db.Column(db.Integer, db.ForeignKey("image_versions.id"), nullable=True)

    # File info
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    thumb_path = db.Column(db.String(500), nullable=True)
    width = db.Column(db.Integer, nullable=True)
    height = db.Column(db.Integer, nullable=True)
    file_size = db.Column(db.Integer, nullable=True)

    # Edit metadata
    edit_type = db.Column(db.String(50), nullable=False)  # local, ai_inpaint, ai_outpaint, etc.
    edit_params = db.Column(db.JSON, nullable=True, default=dict)
    edit_description = db.Column(db.Text, nullable=True)

    # Status
    status = db.Column(db.String(20), nullable=False, default="completed")

    # Timestamps
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)

    # Relationships
    image = db.relationship("Image", backref="versions")
    parent_version = db.relationship("ImageVersion", remote_side=[id], backref="child_versions")

    def to_dict(self):
        return {
            "id": self.id,
            "image_id": self.image_id,
            "version_number": self.version_number,
            "parent_version_id": self.parent_version_id,
            "filename": self.filename,
            "file_path": self.file_path,
            "thumb_path": self.thumb_path,
            "width": self.width,
            "height": self.height,
            "file_size": self.file_size,
            "edit_type": self.edit_type,
            "edit_params": self.edit_params,
            "edit_description": self.edit_description,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "url": f"/api/v1/editor/versions/{self.id}/file",
        }

    def __repr__(self):
        return f"<ImageVersion {self.id} v{self.version_number} [{self.edit_type}]>"
