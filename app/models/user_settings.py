"""UserSettings model — stores all user preferences and personalization data.

Sections:
  - appearance: theme preference (light/dark/system)
  - generation_defaults: default model, style, ratio, output count, quality
  - privacy: default image visibility, sharing preferences
  - notifications: in-app notification preferences
  - account: profile metadata (display_name, etc.)

All settings are stored as a single JSON column for flexibility, with
typed accessors and strict validation at the service layer.
"""

from app.extensions import db
from app.utils import now_utc


# ── Valid values per setting ──────────────────────────────────────

VALID_THEMES = ("light", "dark", "system")
VALID_STYLES = ("auto", "photo", "art", "paint", "anime", "3d", "pixel", "minimal")
VALID_RATIOS = ("1:1", "16:9", "9:16", "4:3", "3:4")
VALID_QUALITIES = ("draft", "standard", "hd", "ultra")
VALID_OUTPUT_COUNTS = (1, 2, 3, 4)
VALID_PRIVACY_LEVELS = ("private", "unlisted", "public")


# ── Default settings factory ──────────────────────────────────────

def _default_settings() -> dict:
    """Return the factory default settings dict."""
    return {
        # ── Appearance ──
        "theme": "system",
        "compact_mode": False,
        "animations_enabled": True,
        "reduce_motion": False,

        # ── Generation Defaults ──
        "default_model": "stub",
        "default_style": "auto",
        "default_ratio": "1:1",
        "default_output_count": 1,
        "default_quality": "standard",
        "auto_enhance": False,
        "show_negative_prompt": False,
        "show_seed": False,
        "show_advanced": False,

        # ── Privacy ──
        "default_image_visibility": "private",
        "allow_sharing": True,
        "show_profile_publicly": True,
        "show_activity_publicly": False,
        "watermark_enabled": False,

        # ── Notifications ──
        "notify_generation_complete": True,
        "notify_generation_failed": True,
        "notify_system_updates": True,
        "notify_tips_tricks": False,
        "email_notifications": False,
        "toast_duration": 4000,

        # ── Account ──
        "display_name": "",
        "bio": "",
        "language": "en",
        "timezone": "UTC",
        "date_format": "YYYY-MM-DD",
        "rows_per_page": 20,
    }


class UserSettings(db.Model):
    """Per-user settings and preferences.

    One row per user.  Stores a JSON blob with typed sub-keys.
    The service layer validates before writing; the model itself is
    intentionally thin — it only holds data and provides helpers.
    """

    __tablename__ = "user_settings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    settings = db.Column(db.JSON, nullable=False, default=_default_settings)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=now_utc,
        onupdate=now_utc,
        nullable=False,
    )

    # ── Relationships ──
    user = db.relationship("User", backref=db.backref("settings", uselist=False, lazy="joined"))

    # ── Helpers ────────────────────────────────────────────────────

    def get(self, key: str, default=None):
        """Get a single setting value with fallback to default."""
        s = self.settings or _default_settings()
        return s.get(key, _default_settings().get(key, default))

    def get_all(self) -> dict:
        """Return a merged dict: defaults + stored overrides."""
        defaults = _default_settings()
        stored = self.settings or {}
        defaults.update(stored)
        return defaults

    def get_section(self, section: str) -> dict:
        """Return settings for a specific section (appearance, generation_defaults, etc.)."""
        all_settings = self.get_all()
        return {k: v for k, v in all_settings.items() if k.startswith(section.replace("default_", "")) or _key_belongs_to_section(k, section)}

    def set_many(self, updates: dict) -> None:
        """Merge updates into the stored settings dict."""
        if self.settings is None:
            self.settings = {}
        self.settings.update(updates)
        self.updated_at = now_utc()

    def reset_to_defaults(self) -> None:
        """Reset all settings to factory defaults."""
        self.settings = _default_settings()
        self.updated_at = now_utc()

    def reset_section(self, section: str) -> None:
        """Reset a specific section to defaults."""
        defaults = _default_settings()
        if self.settings is None:
            self.settings = {}
        for key, value in defaults.items():
            if _key_belongs_to_section(key, section):
                self.settings[key] = value
        self.updated_at = now_utc()

    def to_dict(self) -> dict:
        """Full serialization."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "settings": self.get_all(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_public_dict(self) -> dict:
        """Public-safe serialization — no internal IDs."""
        return {
            "settings": self.get_all(),
        }

    def __repr__(self) -> str:
        return f"<UserSettings user_id={self.user_id}>"


# ── Private helpers ────────────────────────────────────────────────

_SECTION_MAP = {
    "appearance": (
        "theme", "compact_mode", "animations_enabled", "reduce_motion",
    ),
    "generation_defaults": (
        "default_model", "default_style", "default_ratio",
        "default_output_count", "default_quality",
        "auto_enhance", "show_negative_prompt", "show_seed", "show_advanced",
    ),
    "privacy": (
        "default_image_visibility", "allow_sharing",
        "show_profile_publicly", "show_activity_publicly", "watermark_enabled",
    ),
    "notifications": (
        "notify_generation_complete", "notify_generation_failed",
        "notify_system_updates", "notify_tips_tricks",
        "email_notifications", "toast_duration",
    ),
    "account": (
        "display_name", "bio", "language", "timezone",
        "date_format", "rows_per_page",
    ),
}


def _key_belongs_to_section(key: str, section: str) -> bool:
    """Check if a settings key belongs to the given section."""
    keys = _SECTION_MAP.get(section, ())
    return key in keys


def get_valid_values(setting_key: str) -> tuple:
    """Return valid values for a setting key, or empty tuple if any value is allowed."""
    mapping = {
        "theme": VALID_THEMES,
        "default_style": VALID_STYLES,
        "default_ratio": VALID_RATIOS,
        "default_quality": VALID_QUALITIES,
        "default_image_visibility": VALID_PRIVACY_LEVELS,
        "default_output_count": VALID_OUTPUT_COUNTS,
    }
    return mapping.get(setting_key, ())
