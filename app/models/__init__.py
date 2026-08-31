"""Models package — import all models here so SQLAlchemy knows about them."""

from app.models.user import User
from app.models.generation import Generation
from app.models.image import Image
from app.models.saved_prompt import SavedPrompt
from app.models.style_preset import StylePreset
from app.models.reference_image import ReferenceImage
from app.models.image_version import ImageVersion
from app.models.tag import Tag, image_tags
from app.models.collection import Collection, collection_images
from app.models.utility_operation import UtilityOperation
from app.models.content_report import ContentReport
from app.models.user_settings import UserSettings
from app.models.audit_log import AuditLog

__all__ = [
    "User",
    "Generation",
    "Image",
    "SavedPrompt",
    "StylePreset",
    "ReferenceImage",
    "ImageVersion",
    "Tag",
    "image_tags",
    "Collection",
    "collection_images",
    "UtilityOperation",
    "ContentReport",
    "UserSettings",
    "AuditLog",
]
