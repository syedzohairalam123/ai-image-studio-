"""Explore service — public gallery discovery with categories, search, styles, and featured content."""

from typing import Optional

from app.extensions import db
from app.models.image import Image
from app.models.generation import Generation
from app.models.user import User
from app.utils import paginate_query


# ============================================================
# EXPLORE CATEGORIES (built-in)
# ============================================================

EXPLORE_CATEGORIES = [
    {
        "id": "all",
        "name": "All",
        "icon": "🌐",
        "description": "Browse all public creations",
    },
    {
        "id": "photography",
        "name": "Photography",
        "icon": "📷",
        "description": "Realistic and stylized photography",
        "styles": ["photo", "portrait", "landscape", "macro", "street", "aerial"],
    },
    {
        "id": "digital_art",
        "name": "Digital Art",
        "icon": "🖌️",
        "description": "Concept art, illustrations, and digital paintings",
        "styles": ["art", "concept", "illustration", "painting"],
    },
    {
        "id": "traditional_art",
        "name": "Traditional Art",
        "icon": "🎨",
        "description": "Watercolor, oil painting, charcoal, and sketch styles",
        "styles": ["paint", "watercolor", "oil", "sketch", "charcoal"],
    },
    {
        "id": "illustration",
        "name": "Illustration",
        "icon": "✏️",
        "description": "Anime, manga, comic, and storybook illustrations",
        "styles": ["anime", "manga", "comic", "storybook"],
    },
    {
        "id": "cinematic",
        "name": "Cinematic",
        "icon": "🎬",
        "description": "Film noir, retro, and sci-fi cinematic looks",
        "styles": ["film", "noir", "retro", "sci-fi-cinema"],
    },
    {
        "id": "fantasy",
        "name": "Fantasy",
        "icon": "🧙",
        "description": "Medieval, magical, ethereal, and dark fantasy worlds",
        "styles": ["medieval", "magical", "ethereal", "dark-fantasy"],
    },
    {
        "id": "sci_fi",
        "name": "Science Fiction",
        "icon": "🚀",
        "description": "Cyberpunk, space, mecha, and alien landscapes",
        "styles": ["cyberpunk", "space", "mech", "alien"],
    },
    {
        "id": "architecture",
        "name": "Architecture",
        "icon": "🏛️",
        "description": "Modern, classical, brutalist, and futuristic buildings",
        "styles": ["modern", "classical", "brutalist", "futuristic"],
    },
    {
        "id": "minimal",
        "name": "Minimal",
        "icon": "📐",
        "description": "Clean, geometric, and flat design aesthetics",
        "styles": ["clean", "geometric", "flat"],
    },
]


# ============================================================
# BASE QUERY — only active, public, non-deleted images
# ============================================================


def _public_query():
    """Base query for public images — enforces security constraints."""
    return (
        Image.query
        .filter_by(is_deleted=False, is_public=True, moderation_state="active")
    )


# ============================================================
# EXPLORE LISTING
# ============================================================


def explore_images(
    search: str = "",
    style: str = "",
    category: str = "",
    sort: str = "recent",
    page: int = 1,
    per_page: int = 24,
) -> dict:
    """List public images with search, style/category filter, and sorting.

    Returns paginated results with sanitized public data.
    """
    query = _public_query()

    # ---- Search ----
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            db.or_(
                Image.title.ilike(search_term),
                Image.public_prompt.ilike(search_term),
                Image.prompt.ilike(search_term),
            )
        )

    # ---- Filter: style (via generation parameters) ----
    if style:
        query = query.join(Generation, Image.generation_id == Generation.id)
        query = query.filter(Generation.parameters["style"].as_string() == style)

    # ---- Filter: category (maps to multiple styles) ----
    if category and category != "all":
        cat = next((c for c in EXPLORE_CATEGORIES if c["id"] == category), None)
        if cat and "styles" in cat:
            query = query.join(Generation, Image.generation_id == Generation.id)
            style_conditions = [
                Generation.parameters["style"].as_string() == s
                for s in cat["styles"]
            ]
            query = query.filter(db.or_(*style_conditions))

    # ---- Sort ----
    if sort == "popular":
        query = query.order_by(Image.view_count.desc(), Image.like_count.desc())
    elif sort == "liked":
        query = query.order_by(Image.like_count.desc())
    else:  # recent (default)
        query = query.order_by(Image.published_at.desc().nullslast(), Image.created_at.desc())

    result = paginate_query(query, page=page, per_page=per_page)

    # Serialize with public-safe data only
    images = [img.to_public_dict() for img in result["items"]]

    return {
        "images": images,
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "has_next": result["has_next"],
        "has_prev": result["has_prev"],
    }


# ============================================================
# EXPLORE CATEGORIES LIST
# ============================================================


def get_categories_with_counts() -> list:
    """Return explore categories with image counts."""
    base = _public_query()
    total_public = base.count()

    categories = []
    for cat in EXPLORE_CATEGORIES:
        if cat["id"] == "all":
            count = total_public
        elif "styles" in cat:
            style_conditions = []
            # We need to join generation for style filtering
            styled_query = (
                _public_query()
                .join(Generation, Image.generation_id == Generation.id)
            )
            for s in cat["styles"]:
                style_conditions.append(Generation.parameters["style"].as_string() == s)
            if style_conditions:
                count = styled_query.filter(db.or_(*style_conditions)).count()
            else:
                count = 0
        else:
            count = 0

        categories.append({
            "id": cat["id"],
            "name": cat["name"],
            "icon": cat["icon"],
            "description": cat.get("description", ""),
            "count": count,
        })

    return categories


# ============================================================
# EXPLORE STYLES — unique styles from public images
# ============================================================


def get_public_styles() -> list:
    """Get all unique styles from public images with counts."""
    query = (
        db.session.query(
            Generation.parameters["style"].as_string().label("style"),
            db.func.count(Image.id).label("count"),
        )
        .join(Image, Image.generation_id == Generation.id)
        .filter(
            Image.is_deleted == False,
            Image.is_public == True,
            Image.moderation_state == "active",
            Generation.parameters["style"].isnot(None),
        )
        .group_by(Generation.parameters["style"].as_string())
        .order_by(db.func.count(Image.id).desc())
    )

    return [
        {"style": row.style, "count": row.count}
        for row in query.all()
        if row.style
    ]


# ============================================================
# FEATURED / CURATED CONTENT
# ============================================================


def get_featured_images(limit: int = 8) -> list:
    """Get top featured images — highest liked + viewed public images."""
    images = (
        _public_query()
        .order_by(
            Image.like_count.desc(),
            Image.view_count.desc(),
            Image.published_at.desc().nullslast(),
        )
        .limit(limit)
        .all()
    )
    return [img.to_public_dict() for img in images]


def get_recent_public(limit: int = 12) -> list:
    """Get most recently published public images."""
    images = (
        _public_query()
        .order_by(Image.published_at.desc().nullslast(), Image.created_at.desc())
        .limit(limit)
        .all()
    )
    return [img.to_public_dict() for img in images]


# ============================================================
# EXPLORE IMAGE DETAIL (public, by share token)
# ============================================================


def get_explore_image_detail(share_token: str) -> Optional[dict]:
    """Get full public detail for an explore image."""
    image = Image.query.filter_by(
        share_token=share_token,
        is_deleted=False,
    ).first()

    if not image or not image.is_public or image.moderation_state != "active":
        return None

    # Increment view count
    image.view_count = (image.view_count or 0) + 1
    db.session.commit()

    # Build public-safe detail
    creator = db.session.get(User, image.user_id) if image.user_id else None
    gen = image.generation
    params = gen.parameters if gen else {}

    return {
        "title": image.title,
        "public_prompt": image.public_prompt or image.prompt,
        "style": params.get("style"),
        "model": gen.model if gen else None,
        "width": image.width,
        "height": image.height,
        "aspect_ratio": image.aspect_ratio,
        "seed": image.seed,
        "view_count": image.view_count,
        "like_count": image.like_count,
        "creator": creator.to_public_dict() if creator else None,
        "created_at": image.created_at.isoformat() if image.created_at else None,
        "published_at": image.published_at.isoformat() if image.published_at else None,
        "image_url": f"/api/v1/images/{image.id}/file",
        "thumb_url": f"/api/v1/images/{image.id}/thumbnail",
        "share_url": f"/share/{image.share_token}",
    }


# ============================================================
# LIKE A PUBLIC IMAGE
# ============================================================


def like_public_image(share_token: str) -> dict:
    """Increment like count on a public image. Returns new count."""
    image = Image.query.filter_by(
        share_token=share_token,
        is_deleted=False,
    ).first()

    if not image or not image.is_public or image.moderation_state != "active":
        raise ValueError("Image not found")

    image.like_count = (image.like_count or 0) + 1
    db.session.commit()

    return {"like_count": image.like_count}
