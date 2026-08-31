from app.extensions import db
from app.utils import now_utc


class SavedPrompt(db.Model):
    __tablename__ = "saved_prompts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    negative_prompt = db.Column(db.Text, nullable=True)
    tags = db.Column(db.JSON, nullable=True, default=list)
    style = db.Column(db.String(50), nullable=True)
    is_favorite = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_template = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            "tags": self.tags or [],
            "style": self.style,
            "is_favorite": self.is_favorite,
            "is_template": self.is_template,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<SavedPrompt {self.id} '{self.title}'>"
