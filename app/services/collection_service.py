"""Collection service — full CRUD and image management for collections."""

from typing import List

from app.extensions import db
from app.models.collection import Collection, collection_images
from app.models.image import Image
from app.utils import now_utc


# ============================================================
# COLLECTION CRUD
# ============================================================


def list_collections(user_id: int) -> list:
    """List all non-deleted collections for a user, ordered by position."""
    collections = (
        Collection.query
        .filter_by(user_id=user_id, is_deleted=False)
        .order_by(Collection.position.asc(), Collection.created_at.desc())
        .all()
    )
    return [c.to_dict() for c in collections]


def get_collection(user_id: int, collection_id: int) -> Collection:
    """Get a single collection by ID."""
    collection = Collection.query.filter_by(
        id=collection_id, user_id=user_id, is_deleted=False
    ).first()
    if not collection:
        raise ValueError("Collection not found")
    return collection


def create_collection(user_id: int, name: str, description: str = "", cover_image_id: int = None) -> Collection:
    """Create a new collection."""
    name = name.strip()
    if not name:
        raise ValueError("Collection name is required")
    if len(name) > 200:
        raise ValueError("Collection name must be 200 characters or fewer")

    # Validate cover image if provided
    if cover_image_id:
        cover = Image.query.filter_by(
            id=cover_image_id, user_id=user_id, is_deleted=False
        ).first()
        if not cover:
            raise ValueError("Cover image not found")

    # Get max position
    max_pos = db.session.query(
        db.func.max(Collection.position)
    ).filter_by(user_id=user_id, is_deleted=False).scalar() or 0

    collection = Collection(
        user_id=user_id,
        name=name,
        description=description.strip() if description else "",
        cover_image_id=cover_image_id,
        position=max_pos + 1,
    )
    db.session.add(collection)
    db.session.commit()

    return collection


def update_collection(user_id: int, collection_id: int, data: dict) -> Collection:
    """Update collection name, description, or cover image."""
    collection = Collection.query.filter_by(
        id=collection_id, user_id=user_id, is_deleted=False
    ).first()
    if not collection:
        raise ValueError("Collection not found")

    if "name" in data:
        name = data["name"].strip()
        if not name:
            raise ValueError("Collection name cannot be empty")
        if len(name) > 200:
            raise ValueError("Collection name must be 200 characters or fewer")
        collection.name = name

    if "description" in data:
        collection.description = (data["description"] or "").strip()

    if "cover_image_id" in data:
        cover_id = data["cover_image_id"]
        if cover_id:
            cover = Image.query.filter_by(
                id=cover_id, user_id=user_id, is_deleted=False
            ).first()
            if not cover:
                raise ValueError("Cover image not found")
        collection.cover_image_id = cover_id

    collection.updated_at = now_utc()
    db.session.commit()
    return collection


def delete_collection(user_id: int, collection_id: int) -> bool:
    """Soft-delete a collection. Does NOT delete the images inside."""
    collection = Collection.query.filter_by(
        id=collection_id, user_id=user_id, is_deleted=False
    ).first()
    if not collection:
        raise ValueError("Collection not found")

    collection.soft_delete()
    db.session.commit()
    return True


# ============================================================
# IMAGE MANAGEMENT
# ============================================================


def add_image_to_collection(user_id: int, collection_id: int, image_id: int) -> bool:
    """Add a single image to a collection."""
    collection = Collection.query.filter_by(
        id=collection_id, user_id=user_id, is_deleted=False
    ).first()
    if not collection:
        raise ValueError("Collection not found")

    image = Image.query.filter_by(
        id=image_id, user_id=user_id, is_deleted=False
    ).first()
    if not image:
        raise ValueError("Image not found")

    # Check if already in collection
    existing = db.session.query(collection_images).filter_by(
        collection_id=collection_id, image_id=image_id
    ).first()
    if existing:
        return True  # Already added

    # Get current max position
    max_pos = db.session.query(
        db.func.max(collection_images.c.position)
    ).filter_by(collection_id=collection_id).scalar() or 0

    db.session.execute(
        collection_images.insert().values(
            collection_id=collection_id,
            image_id=image_id,
            position=max_pos + 1,
        )
    )
    db.session.commit()
    return True


def remove_image_from_collection(user_id: int, collection_id: int, image_id: int) -> bool:
    """Remove an image from a collection."""
    collection = Collection.query.filter_by(
        id=collection_id, user_id=user_id, is_deleted=False
    ).first()
    if not collection:
        raise ValueError("Collection not found")

    result = db.session.execute(
        collection_images.delete().where(
            collection_images.c.collection_id == collection_id,
            collection_images.c.image_id == image_id,
        )
    )
    db.session.commit()
    return result.rowcount > 0


def get_collection_images(user_id: int, collection_id: int) -> list:
    """Get all images in a collection, ordered by position."""
    collection = Collection.query.filter_by(
        id=collection_id, user_id=user_id, is_deleted=False
    ).first()
    if not collection:
        raise ValueError("Collection not found")

    # Query images through the association table to get ordering
    images = (
        db.session.query(Image)
        .join(collection_images, Image.id == collection_images.c.image_id)
        .filter(
            collection_images.c.collection_id == collection_id,
            Image.is_deleted == False,
        )
        .order_by(collection_images.c.position.asc())
        .all()
    )

    result = []
    for img in images:
        img_dict = img.to_dict()
        img_dict["aspect_ratio"] = img.aspect_ratio
        img_dict["url"] = f"/api/v1/images/{img.id}/file"
        img_dict["thumb_url"] = f"/api/v1/images/{img.id}/thumbnail"
        img_dict["prompt"] = img.prompt or (img.generation.prompt if img.generation else None)
        result.append(img_dict)

    return result


def reorder_collection(user_id: int, collection_id: int, image_ids: List[int]) -> bool:
    """Reorder images within a collection.

    image_ids should be the desired order from first to last.
    Images not in the list keep their relative order at the end.
    """
    collection = Collection.query.filter_by(
        id=collection_id, user_id=user_id, is_deleted=False
    ).first()
    if not collection:
        raise ValueError("Collection not found")

    for position, image_id in enumerate(image_ids):
        db.session.execute(
            collection_images.update()
            .where(
                collection_images.c.collection_id == collection_id,
                collection_images.c.image_id == image_id,
            )
            .values(position=position)
        )

    db.session.commit()
    return True
