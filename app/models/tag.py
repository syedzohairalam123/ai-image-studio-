"""Tag model for organizing images with labels."""

from app.extensions import db
from app.utils import now_utc


# Association table for many-to-many relationship between images and tags
image_tags = db.Table(
    "image_tags",
    db.Column("image_id", db.Integer, db.ForeignKey("images.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id"), primary_key=True),
)


class Tag(db.Model):
    """A tag that can be applied to multiple images."""

    __tablename__ = "tags"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), nullable=True)  # Hex color like #FF5733
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)

    # Relationships
    images = db.relationship("Image", secondary=image_tags, backref="tags", lazy="dynamic")

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_tag_user_name"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "color": self.color,
            "image_count": self.images.count(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Tag {self.name}>"
