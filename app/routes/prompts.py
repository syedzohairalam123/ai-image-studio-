"""Prompt Library API routes."""

import random
from flask import jsonify, request
from flask_login import current_user, login_required

from app.extensions import db
from app.models.saved_prompt import SavedPrompt
from app.routes import api_bp
from app.services.prompt_service import enhance_prompt, BUILTIN_TEMPLATES
from app.services.ai_provider import get_provider, list_providers


# ---- Prompt Enhancement ----

@api_bp.route("/prompts/enhance", methods=["POST"])
@login_required
def enhance():
    """Enhance a simple prompt into a structured, detailed prompt.

    POST body: { "prompt": "...", "style": "auto" }
    """
    data = request.get_json(silent=True) or {}
    original = (data.get("prompt") or "").strip()
    style = (data.get("style") or "auto").strip()

    if not original:
        return jsonify({"error": "Prompt is required"}), 400

    result = enhance_prompt(original, style=style)
    return jsonify(result)


# ---- Provider Capabilities ----

@api_bp.route("/prompts/capabilities", methods=["GET"])
@login_required
def provider_capabilities():
    """Return capabilities for the configured provider (seed, negative_prompt, etc.)."""
    provider_name = request.args.get("provider", "stub")

    try:
        provider = get_provider(provider_name)
        caps = provider.get_capabilities()
        return jsonify({
            "provider": provider.name,
            "display_name": provider.display_name,
            "capabilities": caps.to_dict(),
        })
    except ValueError:
        # Fallback: return stub capabilities
        return jsonify({
            "provider": "stub",
            "display_name": "Stub",
            "capabilities": {
                "seed": True,
                "negative_prompt": True,
                "text_to_image": True,
            },
        })


# ---- Prompt Templates ----

@api_bp.route("/prompts/templates", methods=["GET"])
@login_required
def list_templates():
    """List built-in prompt templates."""
    return jsonify({"templates": BUILTIN_TEMPLATES})


# ---- Prompt Library CRUD ----

@api_bp.route("/prompts", methods=["GET"])
@login_required
def list_prompts():
    """List saved prompts with filtering, search, and pagination."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    search = request.args.get("search", "").strip()
    favorite = request.args.get("favorite", "").strip().lower()
    tag = request.args.get("tag", "").strip()
    sort = request.args.get("sort", "newest").strip().lower()

    query = SavedPrompt.query.filter_by(user_id=current_user.id, is_template=False)

    if search:
        query = query.filter(
            db.or_(
                SavedPrompt.title.ilike(f"%{search}%"),
                SavedPrompt.prompt.ilike(f"%{search}%"),
            )
        )

    if favorite == "true":
        query = query.filter_by(is_favorite=True)

    if tag:
        # Filter by tag in JSON array
        query = query.filter(SavedPrompt.tags.contains(tag))

    if sort == "oldest":
        query = query.order_by(SavedPrompt.created_at.asc())
    elif sort == "title":
        query = query.order_by(SavedPrompt.title.asc())
    else:
        query = query.order_by(SavedPrompt.created_at.desc())

    # Paginate
    per_page = min(max(1, per_page), 100)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    prompts = [p.to_dict() for p in pagination.items]

    # Collect all unique tags for the user
    all_prompts = SavedPrompt.query.filter_by(user_id=current_user.id, is_template=False).all()
    all_tags = set()
    for p in all_prompts:
        if p.tags:
            all_tags.update(p.tags)

    return jsonify({
        "prompts": prompts,
        "total": pagination.total,
        "page": pagination.page,
        "pages": pagination.pages,
        "has_next": pagination.has_next,
        "has_prev": pagination.has_prev,
        "all_tags": sorted(all_tags),
    })


@api_bp.route("/prompts", methods=["POST"])
@login_required
def create_prompt():
    """Create a new saved prompt.

    POST body: { "title": "...", "prompt": "...", "negative_prompt": "...",
                  "tags": [...], "style": "..." }
    """
    data = request.get_json(silent=True) or {}

    title = (data.get("title") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    negative_prompt = (data.get("negative_prompt") or "").strip() or None
    tags = data.get("tags") or []
    style = (data.get("style") or "").strip() or None

    if not title:
        return jsonify({"error": "Title is required"}), 400
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400
    if len(title) > 255:
        return jsonify({"error": "Title must be 255 characters or fewer"}), 400
    if not isinstance(tags, list):
        return jsonify({"error": "Tags must be a list"}), 400

    saved = SavedPrompt(
        user_id=current_user.id,
        title=title,
        prompt=prompt,
        negative_prompt=negative_prompt,
        tags=tags,
        style=style,
    )
    db.session.add(saved)
    db.session.commit()

    return jsonify(saved.to_dict()), 201


@api_bp.route("/prompts/<int:prompt_id>", methods=["GET"])
@login_required
def get_prompt(prompt_id):
    """Get a single saved prompt."""
    saved = SavedPrompt.query.filter_by(id=prompt_id, user_id=current_user.id).first()
    if not saved:
        return jsonify({"error": "Prompt not found"}), 404
    return jsonify(saved.to_dict())


@api_bp.route("/prompts/<int:prompt_id>", methods=["PUT"])
@login_required
def update_prompt(prompt_id):
    """Update a saved prompt."""
    saved = SavedPrompt.query.filter_by(id=prompt_id, user_id=current_user.id).first()
    if not saved:
        return jsonify({"error": "Prompt not found"}), 404

    data = request.get_json(silent=True) or {}

    if "title" in data:
        title = (data["title"] or "").strip()
        if not title:
            return jsonify({"error": "Title cannot be empty"}), 400
        if len(title) > 255:
            return jsonify({"error": "Title must be 255 characters or fewer"}), 400
        saved.title = title

    if "prompt" in data:
        prompt = (data["prompt"] or "").strip()
        if not prompt:
            return jsonify({"error": "Prompt cannot be empty"}), 400
        saved.prompt = prompt

    if "negative_prompt" in data:
        saved.negative_prompt = (data["negative_prompt"] or "").strip() or None

    if "tags" in data:
        tags = data["tags"]
        if not isinstance(tags, list):
            return jsonify({"error": "Tags must be a list"}), 400
        saved.tags = tags

    if "style" in data:
        saved.style = (data["style"] or "").strip() or None

    db.session.commit()
    return jsonify(saved.to_dict())


@api_bp.route("/prompts/<int:prompt_id>", methods=["DELETE"])
@login_required
def delete_prompt(prompt_id):
    """Delete a saved prompt."""
    saved = SavedPrompt.query.filter_by(id=prompt_id, user_id=current_user.id).first()
    if not saved:
        return jsonify({"error": "Prompt not found"}), 404

    db.session.delete(saved)
    db.session.commit()

    return jsonify({"status": "success", "message": "Prompt deleted"})


@api_bp.route("/prompts/<int:prompt_id>/favorite", methods=["POST"])
@login_required
def toggle_prompt_favorite(prompt_id):
    """Toggle favorite status of a saved prompt."""
    saved = SavedPrompt.query.filter_by(id=prompt_id, user_id=current_user.id).first()
    if not saved:
        return jsonify({"error": "Prompt not found"}), 404

    saved.is_favorite = not saved.is_favorite
    db.session.commit()

    return jsonify({"status": "success", "is_favorite": saved.is_favorite})


@api_bp.route("/prompts/<int:prompt_id>/duplicate", methods=["POST"])
@login_required
def duplicate_prompt(prompt_id):
    """Duplicate a saved prompt."""
    original = SavedPrompt.query.filter_by(id=prompt_id, user_id=current_user.id).first()
    if not original:
        return jsonify({"error": "Prompt not found"}), 404

    duplicate = SavedPrompt(
        user_id=current_user.id,
        title=f"{original.title} (copy)",
        prompt=original.prompt,
        negative_prompt=original.negative_prompt,
        tags=list(original.tags) if original.tags else [],
        style=original.style,
        is_favorite=False,
    )
    db.session.add(duplicate)
    db.session.commit()

    return jsonify(duplicate.to_dict()), 201


# ---- Recent Prompts ----

@api_bp.route("/prompts/recent", methods=["GET"])
@login_required
def recent_prompts():
    """Get recent unique prompts from the user's generation history."""
    from app.models.generation import Generation

    limit = request.args.get("limit", 10, type=int)
    limit = min(max(1, limit), 50)

    # Get recent unique prompts
    generations = (
        Generation.query
        .filter_by(user_id=current_user.id)
        .order_by(Generation.created_at.desc())
        .limit(100)
        .all()
    )

    seen = set()
    recent = []
    for gen in generations:
        if gen.prompt and gen.prompt not in seen:
            seen.add(gen.prompt)
            recent.append({
                "prompt": gen.prompt,
                "style": (gen.parameters or {}).get("style"),
                "created_at": gen.created_at.isoformat() if gen.created_at else None,
            })
            if len(recent) >= limit:
                break

    return jsonify({"prompts": recent})


# ---- Random Seed ----

@api_bp.route("/prompts/random-seed", methods=["GET"])
@login_required
def random_seed():
    """Generate a random seed number."""
    seed = random.randint(0, 2147483647)
    return jsonify({"seed": seed})
