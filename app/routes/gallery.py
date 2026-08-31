"""Gallery API routes — search, filter, sort, multi-select, bulk operations, collections, tags."""

from pathlib import Path

from flask import jsonify, request, send_file
from flask_login import current_user, login_required

from app.extensions import db
from app.models.image import Image
from app.models.tag import Tag
from app.models.collection import Collection
from app.routes import api_bp
from app.services.gallery_service import (
    query_gallery,
    bulk_favorite,
    bulk_delete,
    bulk_add_to_collection,
    bulk_add_tags,
    get_filter_options,
    update_image,
)
from app.services.collection_service import (
    list_collections,
    get_collection,
    create_collection,
    update_collection,
    delete_collection,
    add_image_to_collection,
    remove_image_from_collection,
    get_collection_images,
    reorder_collection,
)


# ============================================================
# GALLERY
# ============================================================


@api_bp.route("/gallery", methods=["GET"])
@login_required
def gallery_list():
    """List images with search, filter, sort, and pagination.

    Query params:
      page, per_page  – pagination
      search          – search title, prompt, filename, tags
      style           – filter by generation style
      model           – filter by generation model
      favorite        – "true" for favorites only
      collection_id   – filter by collection
      tag_id          – filter by tag
      date_from       – ISO date (inclusive)
      date_to         – ISO date (inclusive)
      sort            – newest, oldest, az, favorite
    """
    result = query_gallery(
        user_id=current_user.id,
        search=request.args.get("search", "").strip(),
        style=request.args.get("style", "").strip(),
        model=request.args.get("model", "").strip(),
        favorite=request.args.get("favorite", "").strip().lower(),
        collection_id=request.args.get("collection_id", type=int),
        tag_id=request.args.get("tag_id", type=int),
        date_from=request.args.get("date_from", "").strip(),
        date_to=request.args.get("date_to", "").strip(),
        sort=request.args.get("sort", "newest").strip().lower(),
        page=request.args.get("page", 1, type=int),
        per_page=request.args.get("per_page", 20, type=int),
    )

    filters = get_filter_options(current_user.id)

    return jsonify({
        "images": result["items"],
        "total": result["total"],
        "page": result["page"],
        "pages": result["pages"],
        "per_page": result["per_page"],
        "has_next": result["has_next"],
        "has_prev": result["has_prev"],
        "filters": filters,
    })


@api_bp.route("/gallery/filters", methods=["GET"])
@login_required
def gallery_filters():
    """Get available filter options for the gallery."""
    return jsonify(get_filter_options(current_user.id))


# ============================================================
# BULK OPERATIONS
# ============================================================


@api_bp.route("/gallery/bulk/favorite", methods=["POST"])
@login_required
def gallery_bulk_favorite():
    """Bulk set/unset favorite on multiple images.

    POST body: { "image_ids": [1,2,3], "favorite": true }
    """
    data = request.get_json(silent=True) or {}
    image_ids = data.get("image_ids") or []
    favorite = data.get("favorite", True)

    if not image_ids:
        return jsonify({"error": "No image IDs provided"}), 400

    if not isinstance(image_ids, list):
        return jsonify({"error": "image_ids must be a list"}), 400

    count = bulk_favorite(current_user.id, image_ids, favorite)
    return jsonify({"status": "success", "affected": count})


@api_bp.route("/gallery/bulk/delete", methods=["POST"])
@login_required
def gallery_bulk_delete():
    """Soft-delete multiple images.

    POST body: { "image_ids": [1,2,3] }
    """
    data = request.get_json(silent=True) or {}
    image_ids = data.get("image_ids") or []

    if not image_ids:
        return jsonify({"error": "No image IDs provided"}), 400

    if not isinstance(image_ids, list):
        return jsonify({"error": "image_ids must be a list"}), 400

    count = bulk_delete(current_user.id, image_ids)
    return jsonify({"status": "success", "affected": count})


@api_bp.route("/gallery/bulk/collection", methods=["POST"])
@login_required
def gallery_bulk_add_to_collection():
    """Add multiple images to a collection.

    POST body: { "image_ids": [1,2,3], "collection_id": 5 }
    """
    data = request.get_json(silent=True) or {}
    image_ids = data.get("image_ids") or []
    collection_id = data.get("collection_id")

    if not image_ids:
        return jsonify({"error": "No image IDs provided"}), 400

    if not collection_id:
        return jsonify({"error": "collection_id is required"}), 400

    try:
        count = bulk_add_to_collection(current_user.id, image_ids, int(collection_id))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"status": "success", "added": count})


@api_bp.route("/gallery/bulk/tags", methods=["POST"])
@login_required
def gallery_bulk_add_tags():
    """Add tags to multiple images.

    POST body: { "image_ids": [1,2,3], "tags": ["landscape", "sunset"] }
    """
    data = request.get_json(silent=True) or {}
    image_ids = data.get("image_ids") or []
    tag_names = data.get("tags") or []

    if not image_ids:
        return jsonify({"error": "No image IDs provided"}), 400

    if not tag_names:
        return jsonify({"error": "No tags provided"}), 400

    count = bulk_add_tags(current_user.id, image_ids, tag_names)
    return jsonify({"status": "success", "tagged": count})


# ============================================================
# SINGLE IMAGE OPERATIONS
# ============================================================


@api_bp.route("/gallery/images/<int:image_id>", methods=["PATCH"])
@login_required
def gallery_update_image(image_id):
    """Update image metadata (title, tags).

    PATCH body: { "title": "...", "tags": ["tag1", "tag2"] }
    """
    data = request.get_json(silent=True) or {}

    try:
        image = update_image(current_user.id, image_id, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({
        "status": "success",
        "image": image.to_dict(),
    })


# ============================================================
# COLLECTIONS
# ============================================================


@api_bp.route("/collections", methods=["GET"])
@login_required
def collections_list():
    """List all collections for the current user."""
    collections = list_collections(current_user.id)
    return jsonify({"collections": collections})


@api_bp.route("/collections", methods=["POST"])
@login_required
def collections_create():
    """Create a new collection.

    POST body: { "name": "...", "description": "...", "cover_image_id": 123 }
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    cover_image_id = data.get("cover_image_id")

    try:
        collection = create_collection(
            user_id=current_user.id,
            name=name,
            description=description,
            cover_image_id=cover_image_id,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"status": "success", "collection": collection.to_dict()}), 201


@api_bp.route("/collections/<int:collection_id>", methods=["GET"])
@login_required
def collections_detail(collection_id):
    """Get a single collection with its images."""
    try:
        collection = get_collection(current_user.id, collection_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    images = get_collection_images(current_user.id, collection_id)

    data = collection.to_dict()
    data["images"] = images

    return jsonify({"collection": data})


@api_bp.route("/collections/<int:collection_id>", methods=["PATCH"])
@login_required
def collections_update(collection_id):
    """Update collection name, description, or cover.

    PATCH body: { "name": "...", "description": "...", "cover_image_id": 123 }
    """
    data = request.get_json(silent=True) or {}

    try:
        collection = update_collection(current_user.id, collection_id, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"status": "success", "collection": collection.to_dict()})


@api_bp.route("/collections/<int:collection_id>", methods=["DELETE"])
@login_required
def collections_delete(collection_id):
    """Soft-delete a collection (images are NOT deleted)."""
    try:
        delete_collection(current_user.id, collection_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    return jsonify({"status": "success", "message": "Collection deleted"})


@api_bp.route("/collections/<int:collection_id>/images", methods=["POST"])
@login_required
def collections_add_image(collection_id):
    """Add an image to a collection.

    POST body: { "image_id": 123 }
    """
    data = request.get_json(silent=True) or {}
    image_id = data.get("image_id")

    if not image_id:
        return jsonify({"error": "image_id is required"}), 400

    try:
        add_image_to_collection(current_user.id, collection_id, int(image_id))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"status": "success", "message": "Image added to collection"})


@api_bp.route("/collections/<int:collection_id>/images/<int:image_id>", methods=["DELETE"])
@login_required
def collections_remove_image(collection_id, image_id):
    """Remove an image from a collection."""
    try:
        remove_image_from_collection(current_user.id, collection_id, image_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

    return jsonify({"status": "success", "message": "Image removed from collection"})


@api_bp.route("/collections/<int:collection_id>/reorder", methods=["PUT"])
@login_required
def collections_reorder(collection_id):
    """Reorder images within a collection.

    PUT body: { "image_ids": [3, 1, 2] }
    """
    data = request.get_json(silent=True) or {}
    image_ids = data.get("image_ids") or []

    if not image_ids:
        return jsonify({"error": "image_ids is required"}), 400

    try:
        reorder_collection(current_user.id, collection_id, image_ids)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify({"status": "success", "message": "Collection reordered"})


# ============================================================
# TAGS
# ============================================================


@api_bp.route("/tags", methods=["GET"])
@login_required
def tags_list():
    """List all tags for the current user."""
    tags = Tag.query.filter_by(user_id=current_user.id).order_by(Tag.name.asc()).all()
    return jsonify({"tags": [t.to_dict() for t in tags]})


@api_bp.route("/tags", methods=["POST"])
@login_required
def tags_create():
    """Create a new tag.

    POST body: { "name": "landscape", "color": "#FF5733" }
    """
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip().lower()
    color = (data.get("color") or "").strip() or None

    if not name:
        return jsonify({"error": "Tag name is required"}), 400

    if len(name) > 100:
        return jsonify({"error": "Tag name must be 100 characters or fewer"}), 400

    # Check for duplicate
    existing = Tag.query.filter_by(user_id=current_user.id, name=name).first()
    if existing:
        return jsonify({"status": "success", "tag": existing.to_dict()})

    tag = Tag(user_id=current_user.id, name=name, color=color)
    db.session.add(tag)
    db.session.commit()

    return jsonify({"status": "success", "tag": tag.to_dict()}), 201


@api_bp.route("/tags/<int:tag_id>", methods=["DELETE"])
@login_required
def tags_delete(tag_id):
    """Delete a tag (removes from all images)."""
    tag = Tag.query.filter_by(id=tag_id, user_id=current_user.id).first()
    if not tag:
        return jsonify({"error": "Tag not found"}), 404

    db.session.delete(tag)
    db.session.commit()

    return jsonify({"status": "success", "message": "Tag deleted"})
