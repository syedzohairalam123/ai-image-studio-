"""Gallery service — search, filter, sort, multi-select, and bulk operations."""

from datetime import datetime, timezone
from typing import List, Optional

from app.extensions import db
from app.models.image import Image
from app.models.generation import Generation
from app.models.tag import Tag, image_tags
from app.models.collection import Collection, collection_images
from app.utils import now_utc


# ============================================================
# GALLERY QUERY
# ============================================================


def query_gallery(
    user_id: int,
    search: str = "",
    style: str = "",
    model: str = "",
    favorite: str = "",
    collection_id: int = None,
    tag_id: int = None,
    date_from: str = "",
    date_to: str = "",
    sort: str = "newest",
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Query images with comprehensive filtering, searching, and sorting.

    Returns a dict with items, total, page, pages, has_next, has_prev.
    """
    from app.utils import paginate_query

    query = Image.query.filter_by(user_id=user_id, is_deleted=False)

    # ---- Search ----
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            db.or_(
                Image.title.ilike(search_term),
                Image.prompt.ilike(search_term),
                Image.filename.ilike(search_term),
                Image.tags.any(Tag.name.ilike(search_term)),
            )
        )

    # ---- Filter: style ----
    if style:
        query = query.join(Generation, Image.generation_id == Generation.id)
        query = query.filter(Generation.parameters["style"].as_string() == style)

    # ---- Filter: model ----
    if model:
        query = query.join(Generation, Image.generation_id == Generation.id)
        query = query.filter(Generation.model.ilike(f"%{model}%"))

    # ---- Filter: favorite ----
    if favorite == "true":
        query = query.filter(Image.is_favorite == True)

    # ---- Filter: collection ----
    if collection_id:
        query = query.filter(
            Image.collections.any(Collection.id == collection_id)
        )

    # ---- Filter: tag ----
    if tag_id:
        query = query.filter(
            Image.tags.any(Tag.id == tag_id)
        )

    # ---- Filter: date range ----
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            query = query.filter(Image.created_at >= dt_from)
        except (ValueError, TypeError):
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            query = query.filter(Image.created_at <= dt_to)
        except (ValueError, TypeError):
            pass

    # ---- Sort ----
    if sort == "oldest":
        query = query.order_by(Image.created_at.asc())
    elif sort == "az":
        query = query.order_by(Image.title.asc().nullslast(), Image.filename.asc())
    elif sort == "favorite":
        query = query.order_by(
            Image.is_favorite.desc(),
            Image.created_at.desc(),
        )
    else:  # newest (default)
        query = query.order_by(Image.created_at.desc())

    result = paginate_query(query, page=page, per_page=per_page)

    # Enrich images with extra data
    images = []
    for img in result["items"]:
        img_dict = img.to_dict()
        img_dict["aspect_ratio"] = img.aspect_ratio
        img_dict["url"] = f"/api/v1/images/{img.id}/file"
        img_dict["thumb_url"] = f"/api/v1/images/{img.id}/thumbnail"
        img_dict["style"] = img.style
        img_dict["model"] = img.model_name
        img_dict["prompt"] = img.prompt or (img.generation.prompt if img.generation else None)
        img_dict["collection_ids"] = [c.id for c in img.collections]
        images.append(img_dict)

    return {
        "items": images,
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "per_page": result["per_page"],
        "has_next": result["has_next"],
        "has_prev": result["has_prev"],
    }


# ============================================================
# BULK OPERATIONS
# ============================================================


def bulk_favorite(user_id: int, image_ids: List[int], favorite: bool = True) -> int:
    """Set favorite status for multiple images. Returns count affected."""
    images = Image.query.filter(
        Image.id.in_(image_ids),
        Image.user_id == user_id,
        Image.is_deleted == False,
    ).all()

    count = 0
    for img in images:
        img.is_favorite = favorite
        count += 1

    db.session.commit()
    return count


def bulk_delete(user_id: int, image_ids: List[int]) -> int:
    """Soft-delete multiple images. Returns count affected."""
    images = Image.query.filter(
        Image.id.in_(image_ids),
        Image.user_id == user_id,
        Image.is_deleted == False,
    ).all()

    count = 0
    for img in images:
        img.soft_delete()
        count += 1

    db.session.commit()
    return count


def bulk_add_to_collection(user_id: int, image_ids: List[int], collection_id: int) -> int:
    """Add multiple images to a collection. Returns count added."""
    collection = Collection.query.filter_by(
        id=collection_id, user_id=user_id, is_deleted=False
    ).first()
    if not collection:
        raise ValueError("Collection not found")

    images = Image.query.filter(
        Image.id.in_(image_ids),
        Image.user_id == user_id,
        Image.is_deleted == False,
    ).all()

    # Get current max position
    existing = db.session.query(
        db.func.max(collection_images.c.position)
    ).filter(collection_images.c.collection_id == collection_id).scalar() or 0

    count = 0
    for i, img in enumerate(images):
        # Check if already in collection
        already = db.session.query(collection_images).filter_by(
            collection_id=collection_id, image_id=img.id
        ).first()
        if not already:
            db.session.execute(
                collection_images.insert().values(
                    collection_id=collection_id,
                    image_id=img.id,
                    position=existing + i + 1,
                )
            )
            count += 1

    db.session.commit()
    return count


def bulk_add_tags(user_id: int, image_ids: List[int], tag_names: List[str]) -> int:
    """Add tags to multiple images. Returns count of tag-image associations created."""
    images = Image.query.filter(
        Image.id.in_(image_ids),
        Image.user_id == user_id,
        Image.is_deleted == False,
    ).all()

    count = 0
    for tag_name in tag_names:
        tag_name = tag_name.strip().lower()
        if not tag_name:
            continue

        # Get or create tag
        tag = Tag.query.filter_by(user_id=user_id, name=tag_name).first()
        if not tag:
            tag = Tag(user_id=user_id, name=tag_name)
            db.session.add(tag)
            db.session.flush()

        for img in images:
            # Reload tags relationship to check membership
            current_tags = [t.id for t in img.tags]
            if tag.id not in current_tags:
                img.tags.append(tag)
                count += 1

    db.session.commit()
    return count


# ============================================================
# FILTER OPTIONS
# ============================================================


def get_filter_options(user_id: int) -> dict:
    """Get available filter options for the gallery."""
    # Get all non-deleted images for this user
    images = Image.query.filter_by(user_id=user_id, is_deleted=False).all()

    styles = set()
    models = set()
    for img in images:
        if img.style:
            styles.add(img.style)
        if img.model_name:
            models.add(img.model_name)

    # Get user's tags
    tags = Tag.query.filter_by(user_id=user_id).all()

    # Get user's collections
    collections = Collection.query.filter_by(user_id=user_id, is_deleted=False).all()

    return {
        "styles": sorted(styles),
        "models": sorted(models),
        "tags": [t.to_dict() for t in tags],
        "collections": [c.to_dict() for c in collections],
    }


# ============================================================
# IMAGE UPDATE
# ============================================================


def update_image(user_id: int, image_id: int, data: dict) -> Image:
    """Update image metadata (title, tags)."""
    image = Image.query.filter_by(
        id=image_id, user_id=user_id, is_deleted=False
    ).first()
    if not image:
        raise ValueError("Image not found")

    if "title" in data:
        image.title = data["title"]

    if "tags" in data:
        # Replace tags
        tag_names = data["tags"]
        new_tags = []
        for tag_name in tag_names:
            tag_name = tag_name.strip().lower()
            if not tag_name:
                continue
            tag = Tag.query.filter_by(user_id=user_id, name=tag_name).first()
            if not tag:
                tag = Tag(user_id=user_id, name=tag_name)
                db.session.add(tag)
                db.session.flush()
            new_tags.append(tag)
        image.tags = new_tags

    db.session.commit()
    return image
