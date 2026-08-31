"""Sharing service — privacy toggle, share URL, public image access, create-similar."""

import secrets
from typing import Optional

from app.extensions import db
from app.models.image import Image
from app.models.generation import Generation
from app.models.user import User
from app.utils import now_utc


# ============================================================
# PRIVACY TOGGLE
# ============================================================


def toggle_privacy(user_id: int, image_id: int) -> dict:
    """Toggle image between public and private.

    Returns dict with new is_public state and share_url if made public.
    Raises ValueError on ownership or existence issues.
    """
    image = Image.query.filter_by(
        id=image_id, user_id=user_id, is_deleted=False
    ).first()
    if not image:
        raise ValueError("Image not found")

    if image.is_public:
        # Make private
        image.make_private()
        db.session.commit()
        return {
            "is_public": False,
            "share_url": None,
            "message": "Image is now private",
        }
    else:
        # Make public
        image.make_public()
        db.session.commit()
        return {
            "is_public": True,
            "share_url": f"/share/{image.share_token}",
            "share_token": image.share_token,
            "message": "Image is now public",
        }


def set_privacy(user_id: int, image_id: int, make_public: bool) -> dict:
    """Explicitly set image to public or private.

    Returns dict with the new state and share_url if public.
    Raises ValueError on ownership or existence issues.
    """
    image = Image.query.filter_by(
        id=image_id, user_id=user_id, is_deleted=False
    ).first()
    if not image:
        raise ValueError("Image not found")

    if make_public and not image.is_public:
        image.make_public()
        db.session.commit()
        return {
            "is_public": True,
            "share_url": f"/share/{image.share_token}",
            "share_token": image.share_token,
            "message": "Image is now public",
        }
    elif not make_public and image.is_public:
        image.make_private()
        db.session.commit()
        return {
            "is_public": False,
            "share_url": None,
            "message": "Image is now private",
        }
    else:
        return {
            "is_public": image.is_public,
            "share_url": f"/share/{image.share_token}" if image.is_public and image.share_token else None,
            "message": "No change needed",
        }


def regenerate_share_token(user_id: int, image_id: int) -> dict:
    """Generate a new share token for an image (invalidates old one).

    Raises ValueError on ownership or existence issues.
    """
    image = Image.query.filter_by(
        id=image_id, user_id=user_id, is_deleted=False
    ).first()
    if not image:
        raise ValueError("Image not found")

    image.generate_share_token()
    if not image.is_public:
        image.is_public = True
    if not image.published_at:
        image.published_at = now_utc()
    db.session.commit()

    return {
        "share_token": image.share_token,
        "share_url": f"/share/{image.share_token}",
        "is_public": image.is_public,
    }


# ============================================================
# PUBLIC ACCESS — secure, no private data leaks
# ============================================================


def get_public_image_by_token(share_token: str) -> Optional[dict]:
    """Retrieve a public image by its share token.

    Returns a sanitized public-safe dict or None.
    Enforces: is_public=True AND moderation_state='active' AND not deleted.
    NEVER returns private images, internal IDs, emails, filesystem paths.
    """
    image = Image.query.filter_by(
        share_token=share_token,
        is_deleted=False,
    ).first()

    if not image:
        return None

    # SECURITY: Must be public AND in active moderation state
    if not image.is_public or image.moderation_state != "active":
        return None

    # Increment view count (non-blocking, in-place)
    image.view_count = (image.view_count or 0) + 1
    db.session.commit()

    return image.to_public_dict()


def get_image_for_owner(user_id: int, image_id: int) -> Optional[Image]:
    """Get image detail for the owner (includes private data)."""
    return Image.query.filter_by(
        id=image_id, user_id=user_id, is_deleted=False
    ).first()


# ============================================================
# CREATE SIMILAR — starts new generation workflow, never modifies original
# ============================================================


def get_create_similar_params(user_id: int, image_id: int) -> dict:
    """Extract generation parameters from an image for 'Create Similar'.

    Returns a dict to prefill the generator with the original's settings.
    The original image is NEVER modified — this is read-only.
    """
    image = Image.query.filter_by(
        id=image_id, is_deleted=False
    ).first()
    if not image:
        raise ValueError("Image not found")

    # SECURITY: Owner can always access their own image's params
    # For public images, non-owners can also use create-similar (it only returns generation params)
    is_owner = (image.user_id == user_id)

    if not is_owner and (not image.is_public or image.moderation_state != "active"):
        raise ValueError("Image not found")

    gen = image.generation
    if not gen:
        raise ValueError("No generation data available")

    params = gen.parameters or {}

    return {
        "prompt": gen.prompt,
        "negative_prompt": gen.negative_prompt,
        "style": params.get("style", "auto"),
        "aspect_ratio": params.get("aspect_ratio", "1:1"),
        "quality": params.get("quality", "standard"),
        "seed": None,  # Intentionally not copying seed for variety
        "provider": gen.provider,
        "model": gen.model,
        "reference_image_id": image.id if is_owner else None,
        "reference_url": f"/api/v1/images/{image.id}/file" if is_owner else None,
        "source_image_token": image.share_token if image.is_public else None,
    }


# ============================================================
# BULK PRIVACY OPERATIONS
# ============================================================


def bulk_set_privacy(user_id: int, image_ids: list, make_public: bool) -> int:
    """Set privacy state for multiple images. Returns count affected."""
    images = Image.query.filter(
        Image.id.in_(image_ids),
        Image.user_id == user_id,
        Image.is_deleted == False,
    ).all()

    count = 0
    for img in images:
        if make_public and not img.is_public:
            img.make_public()
            count += 1
        elif not make_public and img.is_public:
            img.make_private()
            count += 1

    db.session.commit()
    return count


# ============================================================
# QR CODE
# ============================================================


def generate_share_qrcode_png(share_token: str, base_url: str) -> bytes:
    """Generate a scannable QR code (PNG bytes) pointing to a public share
    page — lets someone viewing a share link on desktop hand it off to a
    phone instantly instead of typing/copying the URL.

    Raises ValueError if the token doesn't correspond to a public image
    (mirrors the same lookup the share page itself uses, so a QR code is
    never generated for something that isn't actually publicly viewable).
    """
    image_data = get_public_image_by_token(share_token)
    if not image_data:
        raise ValueError("Image not found or not public")

    import io
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    url = f"{base_url.rstrip('/')}/share/{share_token}"
    qr = qrcode.QRCode(border=2, box_size=8, error_correction=ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#292a2e", back_color="#ffffff").convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
