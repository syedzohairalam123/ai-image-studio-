from app.extensions import db
from app.utils import now_utc


class StylePreset(db.Model):
    __tablename__ = "style_presets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False, default="custom")
    style = db.Column(db.String(50), nullable=True)
    negative_prompt = db.Column(db.Text, nullable=True)
    prompt_prefix = db.Column(db.Text, nullable=True)
    prompt_suffix = db.Column(db.Text, nullable=True)
    settings = db.Column(db.JSON, nullable=True, default=dict)
    is_default = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "category": self.category,
            "style": self.style,
            "negative_prompt": self.negative_prompt,
            "prompt_prefix": self.prompt_prefix,
            "prompt_suffix": self.prompt_suffix,
            "settings": self.settings or {},
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<StylePreset {self.id} '{self.name}'>"
