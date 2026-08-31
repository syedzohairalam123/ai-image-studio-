"""Moderation service — content reports, moderation state management, admin actions."""

from typing import Optional

from app.extensions import db
from app.models.image import Image
from app.models.content_report import ContentReport
from app.utils import now_utc


# ============================================================
# REPORT CONTENT
# ============================================================


def report_image(
    reporter_id: int,
    image_id: int,
    reason: str,
    description: str = None,
) -> ContentReport:
    """Submit a report against a public image.

    Validates: image exists, is public, reporter is not the owner,
    reason is valid, and reporter hasn't already reported this image.
    """
    if reason not in ContentReport.VALID_REASONS:
        raise ValueError(f"Invalid reason. Must be one of: {', '.join(ContentReport.VALID_REASONS)}")

    image = Image.query.filter_by(
        id=image_id, is_deleted=False
    ).first()
    if not image:
        raise ValueError("Image not found")

    if not image.is_public:
        raise ValueError("Cannot report a private image")

    if image.user_id == reporter_id:
        raise ValueError("Cannot report your own image")

    # Check for duplicate report
    existing = ContentReport.query.filter_by(
        image_id=image_id, reporter_id=reporter_id
    ).first()
    if existing:
        raise ValueError("You have already reported this image")

    report = ContentReport(
        image_id=image_id,
        reporter_id=reporter_id,
        reason=reason,
        description=description,
    )
    db.session.add(report)

    # Update image moderation state
    image.moderation_state = "reported"

    db.session.commit()
    return report


# ============================================================
# ADMIN MODERATION ACTIONS
# ============================================================


def get_pending_reports(page: int = 1, per_page: int = 20) -> dict:
    """Get paginated list of pending content reports (admin only)."""
    from app.utils import paginate_query

    query = (
        ContentReport.query
        .filter_by(status="pending")
        .order_by(ContentReport.created_at.asc())
    )

    result = paginate_query(query, page=page, per_page=per_page)
    reports = [r.to_dict() for r in result["items"]]

    return {
        "reports": reports,
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "has_next": result["has_next"],
        "has_prev": result["has_prev"],
    }


def get_all_reports(
    status: str = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Get all reports with optional status filter (admin only)."""
    from app.utils import paginate_query

    query = ContentReport.query

    if status and status in ContentReport.VALID_STATUSES:
        query = query.filter_by(status=status)

    query = query.order_by(ContentReport.created_at.desc())

    result = paginate_query(query, page=page, per_page=per_page)
    reports = [r.to_dict() for r in result["items"]]

    return {
        "reports": reports,
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "has_next": result["has_next"],
        "has_prev": result["has_prev"],
    }


def moderate_report(
    admin_id: int,
    report_id: int,
    action: str,
    note: str = None,
) -> ContentReport:
    """Admin action on a report.

    Actions:
    - 'dismiss': Report is invalid, restore image to active
    - 'actioned': Report is valid, hide the image
    - 'reviewed': Mark as reviewed without hiding
    """
    VALID_ACTIONS = ("dismiss", "actioned", "reviewed")

    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action. Must be one of: {', '.join(VALID_ACTIONS)}")

    report = db.session.get(ContentReport, report_id)
    if not report:
        raise ValueError("Report not found")

    if report.status != "pending":
        raise ValueError("This report has already been processed")

    report.status = action
    report.reviewed_by = admin_id
    report.reviewed_at = now_utc()

    # Update image moderation state
    image = db.session.get(Image, report.image_id)
    if image:
        if action == "actioned":
            image.moderation_state = "hidden"
        elif action == "dismiss":
            image.moderation_state = "active"
        elif action == "reviewed":
            # Keep as-is (reported state) — admin acknowledged but didn't hide
            pass

    db.session.commit()
    return report


# ============================================================
# MODERATION STATE MANAGEMENT
# ============================================================


def set_moderation_state(image_id: int, state: str) -> Image:
    """Directly set moderation state of an image (admin only)."""
    if state not in Image.MODERATION_STATES:
        raise ValueError(f"Invalid state. Must be one of: {', '.join(Image.MODERATION_STATES)}")

    image = db.session.get(Image, image_id)
    if not image:
        raise ValueError("Image not found")

    image.moderation_state = state
    db.session.commit()
    return image


def get_moderation_stats() -> dict:
    """Get moderation statistics (admin dashboard)."""
    total_reports = ContentReport.query.count()
    pending_reports = ContentReport.query.filter_by(status="pending").count()
    actioned_reports = ContentReport.query.filter_by(status="actioned").count()
    dismissed_reports = ContentReport.query.filter_by(status="dismissed").count()

    hidden_images = Image.query.filter_by(
        is_deleted=False, moderation_state="hidden"
    ).count()
    reported_images = Image.query.filter_by(
        is_deleted=False, moderation_state="reported"
    ).count()
    public_images = Image.query.filter_by(
        is_deleted=False, is_public=True, moderation_state="active"
    ).count()

    return {
        "reports": {
            "total": total_reports,
            "pending": pending_reports,
            "actioned": actioned_reports,
            "dismissed": dismissed_reports,
        },
        "images": {
            "public": public_images,
            "reported": reported_images,
            "hidden": hidden_images,
        },
    }
