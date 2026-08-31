"""Collection model for organizing images into groups."""

from app.extensions import db
from app.utils import now_utc


# Association table for many-to-many relationship between collections and images
collection_images = db.Table(
    "collection_images",
    db.Column("collection_id", db.Integer, db.ForeignKey("collections.id"), primary_key=True),
    db.Column("image_id", db.Integer, db.ForeignKey("images.id"), primary_key=True),
    db.Column("position", db.Integer, default=0, nullable=False),
    db.Column("added_at", db.DateTime(timezone=True), default=now_utc, nullable=False),
)


class Collection(db.Model):
    """A user-created collection to organize images."""

    __tablename__ = "collections"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    cover_image_id = db.Column(db.Integer, db.ForeignKey("images.id"), nullable=True)
    is_deleted = db.Column(db.Boolean, default=False, nullable=False, index=True)
    position = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    # Relationships
    cover_image = db.relationship("Image", foreign_keys=[cover_image_id], post_update=True)
    images = db.relationship(
        "Image",
        secondary=collection_images,
        backref="collections",
        lazy="dynamic",
        order_by="collection_images.c.position",
    )

    def to_dict(self):
        cover_url = None
        if self.cover_image_id:
            cover_url = f"/api/v1/images/{self.cover_image_id}/thumbnail"

        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "description": self.description,
            "cover_image_id": self.cover_image_id,
            "cover_url": cover_url,
            "image_count": self.images.count(),
            "position": self.position,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def soft_delete(self):
        self.is_deleted = True
        self.updated_at = now_utc()

    def __repr__(self):
        return f"<Collection {self.name}>"
