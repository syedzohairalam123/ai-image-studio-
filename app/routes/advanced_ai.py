"""
Advanced AI API Routes - Image-to-Image, Inpainting, Style Transfer, etc.
"""
import os
import tempfile
from pathlib import Path

from flask import request, jsonify, send_file
from flask_login import login_required, current_user

from app.routes import api_bp
from app.services.advanced_ai_service import get_advanced_ai_service
from app.services.storage_service import StorageService
from app.config import BASE_DIR
from app.extensions import db
from app.models.image import Image
from app.models.generation import Generation
from app.utils import now_utc, generate_filename


# ============================================================
# SHARED SAVE HELPER
#
# BUGFIX: every handler in this file used to do
#   storage = StorageService()                              # missing required upload_folder arg -> TypeError
#   ...
#   storage.get_image_path(source_image.filename, 'generations')   # method doesn't exist -> AttributeError
#   storage.save_image(tmp_path, filename, 'generations')          # method doesn't exist -> AttributeError
#   Image(..., format='PNG', parameters={...})                     # neither is a real column,
#                                                                    # and required file_path was never set -> TypeError/IntegrityError
# which meant every single one of these 9 image-producing endpoints crashed
# unconditionally with a 500 error before ever reaching a real response.
# This helper centralizes the *correct* save path (matching how
# generation_service.py / editor_service.py already do it) so all handlers
# below share one tested code path instead of repeating (and re-breaking) it.
# ============================================================

def _save_advanced_result(pil_image, operation: str, extra_meta: dict = None) -> dict:
    """Persist a PIL result image (+ a real thumbnail) for the current user.

    Returns a dict with filename/file_path/thumb_path/file_size/width/height
    ready to hand straight to the Image(...) constructor.
    """
    storage = StorageService(str(BASE_DIR / "uploads" / "generations" / str(current_user.id)))

    if pil_image.mode not in ("RGB", "RGBA"):
        pil_image = pil_image.convert("RGB")

    import io
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG", optimize=True)
    png_bytes = buf.getvalue()

    filename = generate_filename(f"{operation}.png", prefix=operation)
    saved = storage.save_bytes(png_bytes, filename, subfolder="images")

    # Real thumbnail (not just the full-size image re-served) so gallery /
    # history grids don't have to download full-resolution art just to show
    # a 200px preview tile.
    thumb_path = None
    try:
        thumb = pil_image.copy()
        thumb.thumbnail((400, 400), Image.LANCZOS if hasattr(Image, "LANCZOS") else Image.BICUBIC)
        thumb_buf = io.BytesIO()
        (thumb.convert("RGB") if thumb.mode == "RGBA" else thumb).save(thumb_buf, format="JPEG", quality=85, optimize=True)
        thumb_saved = storage.save_bytes(thumb_buf.getvalue(), f"thumb_{filename}", subfolder="thumbnails")
        thumb_path = thumb_saved["file_path"]
    except Exception:
        thumb_path = None

    return {
        "filename": saved["filename"],
        "file_path": saved["file_path"],
        "thumb_path": thumb_path,
        "file_size": saved["file_size"],
        "width": pil_image.width,
        "height": pil_image.height,
        "meta": {"operation": operation, **(extra_meta or {})},
    }


def _create_advanced_image(generation: Generation, saved: dict) -> Image:
    """Build the Image row from a _save_advanced_result() dict using the
    Image model's *actual* columns (file_path / meta), not the nonexistent
    format/parameters kwargs the old code passed."""
    image = Image(
        user_id=current_user.id,
        generation_id=generation.id,
        filename=saved["filename"],
        original_filename=saved["filename"],
        file_path=saved["file_path"],
        thumb_path=saved["thumb_path"],
        width=saved["width"],
        height=saved["height"],
        file_size=saved["file_size"],
        format="png",
        meta=saved["meta"],
    )
    db.session.add(image)
    return image


def _get_owned_source_image(source_image_id):
    """Look up a source image owned by the current user, or None."""
    if not source_image_id:
        return None
    return Image.query.filter_by(
        id=source_image_id, user_id=current_user.id, is_deleted=False
    ).first()


@api_bp.route("/advanced/image-to-image", methods=["POST"])
@login_required
def advanced_image_to_image():
    """Transform an existing image using AI based on text prompt."""
    try:
        # Get parameters
        source_image_id = request.form.get('source_image_id')
        prompt = request.form.get('prompt', '')
        strength = float(request.form.get('strength', 0.7))
        style = request.form.get('style', 'auto')

        if not source_image_id:
            return jsonify({'error': 'Source image ID required'}), 400

        if not prompt:
            return jsonify({'error': 'Prompt required'}), 400

        # Get source image
        source_image = _get_owned_source_image(source_image_id)

        if not source_image:
            return jsonify({'error': 'Source image not found'}), 404

        # Get image path — the Image model already stores the absolute path,
        # no need to reconstruct it via filename guessing.
        source_path = source_image.file_path

        if not source_path or not os.path.exists(source_path):
            return jsonify({'error': 'Source image file not found'}), 404

        # Perform image-to-image transformation
        ai_service = get_advanced_ai_service()
        result = ai_service.image_to_image(
            source_image_path=source_path,
            prompt=prompt,
            strength=strength,
            style=style
        )

        if not result['success']:
            return jsonify({'error': result['error']}), 500

        # Save result image
        result_image = result['result_image']
        saved = _save_advanced_result(result_image, 'image_to_image', {
            'source_image_id': source_image_id,
            'strength': strength,
            'style': style,
        })

        # Create database record
        new_generation = Generation(
            user_id=current_user.id,
            prompt=f"Image-to-Image: {prompt}",
            provider='advanced_ai',
            model='image_to_image',
            parameters={
                'operation': 'image_to_image',
                'source_image_id': source_image_id,
                'strength': strength,
                'style': style,
                **result['metadata']
            },
            status='completed',
            completed_at=now_utc()
        )
        db.session.add(new_generation)
        db.session.flush()

        new_image = _create_advanced_image(new_generation, saved)
        db.session.commit()

        return jsonify({
            'success': True,
            'image_id': new_image.id,
            'generation_id': new_generation.id,
            'filename': saved['filename'],
            'metadata': result['metadata']
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route("/advanced/inpainting", methods=["POST"])
@login_required
def advanced_inpainting():
    """Fill in masked areas of an image using AI."""
    try:
        # Get parameters
        source_image_id = request.form.get('source_image_id')
        prompt = request.form.get('prompt', '')

        if 'mask' not in request.files:
            return jsonify({'error': 'Mask image required'}), 400

        mask_file = request.files['mask']

        if not source_image_id:
            return jsonify({'error': 'Source image ID required'}), 400

        if not prompt:
            return jsonify({'error': 'Prompt required'}), 400

        # Get source image
        source_image = _get_owned_source_image(source_image_id)

        if not source_image:
            return jsonify({'error': 'Source image not found'}), 404

        source_path = source_image.file_path

        if not source_path or not os.path.exists(source_path):
            return jsonify({'error': 'Source image file not found'}), 404

        # Save mask temporarily (this is a real short-lived scratch file, so
        # tempfile is the right tool — it's the *output* save that was broken)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            mask_file.save(tmp)
            mask_path = tmp.name

        try:
            # Perform inpainting
            ai_service = get_advanced_ai_service()
            result = ai_service.inpainting(
                source_image_path=source_path,
                mask_path=mask_path,
                prompt=prompt
            )

            if not result['success']:
                return jsonify({'error': result['error']}), 500

            result_image = result['result_image']
            saved = _save_advanced_result(result_image, 'inpainting', {
                'source_image_id': source_image_id,
            })

            new_generation = Generation(
                user_id=current_user.id,
                prompt=f"Inpainting: {prompt}",
                provider='advanced_ai',
                model='inpainting',
                parameters={
                    'operation': 'inpainting',
                    'source_image_id': source_image_id,
                    **result['metadata']
                },
                status='completed',
                completed_at=now_utc()
            )
            db.session.add(new_generation)
            db.session.flush()

            new_image = _create_advanced_image(new_generation, saved)
            db.session.commit()

            return jsonify({
                'success': True,
                'image_id': new_image.id,
                'generation_id': new_generation.id,
                'filename': saved['filename'],
                'metadata': result['metadata']
            })

        finally:
            if os.path.exists(mask_path):
                os.unlink(mask_path)

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route("/advanced/style-transfer", methods=["POST"])
@login_required
def advanced_style_transfer():
    """Apply artistic style to an image."""
    try:
        # Get parameters
        source_image_id = request.form.get('source_image_id')
        style_reference = request.form.get('style_reference', '')
        style_strength = float(request.form.get('style_strength', 0.8))

        # Check if style reference is a file upload or preset name
        cleanup_style = False
        if 'style_image' in request.files and request.files['style_image'].filename:
            style_file = request.files['style_image']
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
                style_file.save(tmp)
                style_reference = tmp.name
                cleanup_style = True

        if not source_image_id:
            return jsonify({'error': 'Source image ID required'}), 400

        if not style_reference:
            return jsonify({'error': 'Style reference required'}), 400

        # Get source image
        source_image = _get_owned_source_image(source_image_id)

        if not source_image:
            return jsonify({'error': 'Source image not found'}), 404

        source_path = source_image.file_path

        if not source_path or not os.path.exists(source_path):
            return jsonify({'error': 'Source image file not found'}), 404

        try:
            # Perform style transfer
            ai_service = get_advanced_ai_service()
            result = ai_service.style_transfer(
                source_image_path=source_path,
                style_reference=style_reference,
                style_strength=style_strength
            )

            if not result['success']:
                return jsonify({'error': result['error']}), 500

            result_image = result['result_image']
            saved = _save_advanced_result(result_image, 'style_transfer', {
                'source_image_id': source_image_id,
                'style_reference': style_reference if not cleanup_style else 'uploaded',
                'style_strength': style_strength,
            })

            new_generation = Generation(
                user_id=current_user.id,
                prompt=f"Style Transfer: {style_reference if not cleanup_style else 'custom upload'}",
                provider='advanced_ai',
                model='style_transfer',
                parameters={
                    'operation': 'style_transfer',
                    'source_image_id': source_image_id,
                    'style_strength': style_strength,
                    **result['metadata']
                },
                status='completed',
                completed_at=now_utc()
            )
            db.session.add(new_generation)
            db.session.flush()

            new_image = _create_advanced_image(new_generation, saved)
            db.session.commit()

            return jsonify({
                'success': True,
                'image_id': new_image.id,
                'generation_id': new_generation.id,
                'filename': saved['filename'],
                'metadata': result['metadata']
            })

        finally:
            if cleanup_style and os.path.exists(style_reference):
                os.unlink(style_reference)

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route("/advanced/outpainting", methods=["POST"])
@login_required
def advanced_outpainting():
    """Extend image boundaries using AI."""
    try:
        # Get parameters
        source_image_id = request.form.get('source_image_id')
        direction = request.form.get('direction', 'all')
        prompt = request.form.get('prompt', 'Extend image naturally')
        extend_pixels = int(request.form.get('extend_pixels', 256))

        if not source_image_id:
            return jsonify({'error': 'Source image ID required'}), 400

        # Get source image
        source_image = _get_owned_source_image(source_image_id)

        if not source_image:
            return jsonify({'error': 'Source image not found'}), 404

        source_path = source_image.file_path

        if not source_path or not os.path.exists(source_path):
            return jsonify({'error': 'Source image file not found'}), 404

        # Perform outpainting
        ai_service = get_advanced_ai_service()
        result = ai_service.outpainting(
            source_image_path=source_path,
            direction=direction,
            prompt=prompt,
            extend_pixels=extend_pixels
        )

        if not result['success']:
            return jsonify({'error': result['error']}), 500

        result_image = result['result_image']
        saved = _save_advanced_result(result_image, 'outpainting', {
            'source_image_id': source_image_id,
            'direction': direction,
            'extend_pixels': extend_pixels,
        })

        new_generation = Generation(
            user_id=current_user.id,
            prompt=f"Outpainting: {direction} - {prompt}",
            provider='advanced_ai',
            model='outpainting',
            parameters={
                'operation': 'outpainting',
                'source_image_id': source_image_id,
                **result['metadata']
            },
            status='completed',
            completed_at=now_utc()
        )
        db.session.add(new_generation)
        db.session.flush()

        new_image = _create_advanced_image(new_generation, saved)
        db.session.commit()

        return jsonify({
            'success': True,
            'image_id': new_image.id,
            'generation_id': new_generation.id,
            'filename': saved['filename'],
            'metadata': result['metadata']
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route("/advanced/face-enhance", methods=["POST"])
@login_required
def advanced_face_enhance():
    """Enhance faces in image using AI."""
    try:
        # Get parameters
        source_image_id = request.form.get('source_image_id')
        enhancement_level = request.form.get('enhancement_level', 'medium')

        if not source_image_id:
            return jsonify({'error': 'Source image ID required'}), 400

        # Get source image
        source_image = _get_owned_source_image(source_image_id)

        if not source_image:
            return jsonify({'error': 'Source image not found'}), 404

        source_path = source_image.file_path

        if not source_path or not os.path.exists(source_path):
            return jsonify({'error': 'Source image file not found'}), 404

        # Perform face enhancement
        ai_service = get_advanced_ai_service()
        result = ai_service.face_enhancement(
            image_path=source_path,
            enhancement_level=enhancement_level
        )

        if not result['success']:
            return jsonify({'error': result['error']}), 500

        result_image = result['result_image']
        saved = _save_advanced_result(result_image, 'face_enhancement', {
            'source_image_id': source_image_id,
            'enhancement_level': enhancement_level,
        })

        new_generation = Generation(
            user_id=current_user.id,
            prompt=f"Face Enhancement: {enhancement_level}",
            provider='advanced_ai',
            model='face_enhancement',
            parameters={
                'operation': 'face_enhancement',
                'source_image_id': source_image_id,
                **result['metadata']
            },
            status='completed',
            completed_at=now_utc()
        )
        db.session.add(new_generation)
        db.session.flush()

        new_image = _create_advanced_image(new_generation, saved)
        db.session.commit()

        return jsonify({
            'success': True,
            'image_id': new_image.id,
            'generation_id': new_generation.id,
            'filename': saved['filename'],
            'metadata': result['metadata']
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route("/advanced/super-resolution", methods=["POST"])
@login_required
def advanced_super_resolution():
    """Upscale image using AI super-resolution."""
    try:
        # Get parameters
        source_image_id = request.form.get('source_image_id')
        scale_factor = int(request.form.get('scale_factor', 2))

        if not source_image_id:
            return jsonify({'error': 'Source image ID required'}), 400

        if scale_factor not in [2, 4]:
            return jsonify({'error': 'Scale factor must be 2 or 4'}), 400

        # Get source image
        source_image = _get_owned_source_image(source_image_id)

        if not source_image:
            return jsonify({'error': 'Source image not found'}), 404

        source_path = source_image.file_path

        if not source_path or not os.path.exists(source_path):
            return jsonify({'error': 'Source image file not found'}), 404

        # Perform super-resolution
        ai_service = get_advanced_ai_service()
        result = ai_service.super_resolution(
            image_path=source_path,
            scale_factor=scale_factor
        )

        if not result['success']:
            return jsonify({'error': result['error']}), 500

        result_image = result['result_image']
        saved = _save_advanced_result(result_image, 'super_resolution', {
            'source_image_id': source_image_id,
            'scale_factor': scale_factor,
        })

        new_generation = Generation(
            user_id=current_user.id,
            prompt=f"Super Resolution: {scale_factor}x",
            provider='advanced_ai',
            model='super_resolution',
            parameters={
                'operation': 'super_resolution',
                'source_image_id': source_image_id,
                **result['metadata']
            },
            status='completed',
            completed_at=now_utc()
        )
        db.session.add(new_generation)
        db.session.flush()

        new_image = _create_advanced_image(new_generation, saved)
        db.session.commit()

        return jsonify({
            'success': True,
            'image_id': new_image.id,
            'generation_id': new_generation.id,
            'filename': saved['filename'],
            'metadata': result['metadata']
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route("/advanced/smart-crop", methods=["POST"])
@login_required
def advanced_smart_crop():
    """Intelligently crop image to target aspect ratio."""
    try:
        # Get parameters
        source_image_id = request.form.get('source_image_id')
        target_aspect = request.form.get('target_aspect', '1:1')

        if not source_image_id:
            return jsonify({'error': 'Source image ID required'}), 400

        # Get source image
        source_image = _get_owned_source_image(source_image_id)

        if not source_image:
            return jsonify({'error': 'Source image not found'}), 404

        source_path = source_image.file_path

        if not source_path or not os.path.exists(source_path):
            return jsonify({'error': 'Source image file not found'}), 404

        # Perform smart crop
        ai_service = get_advanced_ai_service()
        result = ai_service.smart_crop(
            image_path=source_path,
            target_aspect=target_aspect
        )

        if not result['success']:
            return jsonify({'error': result['error']}), 500

        result_image = result['result_image']
        saved = _save_advanced_result(result_image, 'smart_crop', {
            'source_image_id': source_image_id,
            'target_aspect': target_aspect,
            'crop_coords': result['metadata'].get('crop_coords'),
        })

        new_generation = Generation(
            user_id=current_user.id,
            prompt=f"Smart Crop: {target_aspect}",
            provider='advanced_ai',
            model='smart_crop',
            parameters={
                'operation': 'smart_crop',
                'source_image_id': source_image_id,
                **result['metadata']
            },
            status='completed',
            completed_at=now_utc()
        )
        db.session.add(new_generation)
        db.session.flush()

        new_image = _create_advanced_image(new_generation, saved)
        db.session.commit()

        return jsonify({
            'success': True,
            'image_id': new_image.id,
            'generation_id': new_generation.id,
            'filename': saved['filename'],
            'metadata': result['metadata']
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route("/advanced/color-correction", methods=["POST"])
@login_required
def advanced_color_correction():
    """Apply AI-powered color correction."""
    try:
        # Get parameters
        source_image_id = request.form.get('source_image_id')
        correction_type = request.form.get('correction_type', 'auto')

        if not source_image_id:
            return jsonify({'error': 'Source image ID required'}), 400

        # Get source image
        source_image = _get_owned_source_image(source_image_id)

        if not source_image:
            return jsonify({'error': 'Source image not found'}), 404

        source_path = source_image.file_path

        if not source_path or not os.path.exists(source_path):
            return jsonify({'error': 'Source image file not found'}), 404

        # Perform color correction
        ai_service = get_advanced_ai_service()
        result = ai_service.color_correction(
            image_path=source_path,
            correction_type=correction_type
        )

        if not result['success']:
            return jsonify({'error': result['error']}), 500

        result_image = result['result_image']
        saved = _save_advanced_result(result_image, 'color_correction', {
            'source_image_id': source_image_id,
            'correction_type': correction_type,
        })

        new_generation = Generation(
            user_id=current_user.id,
            prompt=f"Color Correction: {correction_type}",
            provider='advanced_ai',
            model='color_correction',
            parameters={
                'operation': 'color_correction',
                'source_image_id': source_image_id,
                **result['metadata']
            },
            status='completed',
            completed_at=now_utc()
        )
        db.session.add(new_generation)
        db.session.flush()

        new_image = _create_advanced_image(new_generation, saved)
        db.session.commit()

        return jsonify({
            'success': True,
            'image_id': new_image.id,
            'generation_id': new_generation.id,
            'filename': saved['filename'],
            'metadata': result['metadata']
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route("/advanced/analyze", methods=["POST"])
@login_required
def advanced_analyze():
    """Analyze image content using AI."""
    try:
        # Get parameters
        source_image_id = request.form.get('source_image_id')

        if not source_image_id:
            return jsonify({'error': 'Source image ID required'}), 400

        # Get source image
        source_image = _get_owned_source_image(source_image_id)

        if not source_image:
            return jsonify({'error': 'Source image not found'}), 404

        source_path = source_image.file_path

        if not source_path or not os.path.exists(source_path):
            return jsonify({'error': 'Source image file not found'}), 404

        # Perform analysis
        ai_service = get_advanced_ai_service()
        result = ai_service.analyze_image_content(source_path)

        if not result['success']:
            return jsonify({'error': result['error']}), 500

        return jsonify({
            'success': True,
            'analysis': result['analysis'],
            'timestamp': result['timestamp']
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route("/advanced/variations", methods=["POST"])
@login_required
def advanced_variations():
    """Generate multiple variations of an image."""
    try:
        # Get parameters
        source_image_id = request.form.get('source_image_id')
        num_variations = int(request.form.get('num_variations', 4))
        variation_strength = float(request.form.get('variation_strength', 0.3))

        if not source_image_id:
            return jsonify({'error': 'Source image ID required'}), 400

        if num_variations < 1 or num_variations > 8:
            return jsonify({'error': 'Number of variations must be between 1 and 8'}), 400

        # Get source image
        source_image = _get_owned_source_image(source_image_id)

        if not source_image:
            return jsonify({'error': 'Source image not found'}), 404

        source_path = source_image.file_path

        if not source_path or not os.path.exists(source_path):
            return jsonify({'error': 'Source image file not found'}), 404

        # Generate variations
        ai_service = get_advanced_ai_service()
        result = ai_service.generate_variations(
            image_path=source_path,
            num_variations=num_variations,
            variation_strength=variation_strength
        )

        if not result['success']:
            return jsonify({'error': result['error']}), 500

        # Create generation record
        new_generation = Generation(
            user_id=current_user.id,
            prompt=f"Variations of image {source_image_id}",
            provider='advanced_ai',
            model='variations',
            parameters={
                'operation': 'variations',
                'source_image_id': source_image_id,
                'num_variations': num_variations,
                'variation_strength': variation_strength,
                **result['metadata']
            },
            status='completed',
            completed_at=now_utc()
        )
        db.session.add(new_generation)
        db.session.flush()

        saved_images = []
        for i, variation_image in enumerate(result['variations']):
            saved = _save_advanced_result(variation_image, 'variation', {
                'source_image_id': source_image_id,
                'index': i,
            })
            new_image = _create_advanced_image(new_generation, saved)
            db.session.flush()
            saved_images.append({
                'image_id': new_image.id,
                'filename': saved['filename']
            })

        db.session.commit()

        return jsonify({
            'success': True,
            'generation_id': new_generation.id,
            'images': saved_images,
            'metadata': result['metadata']
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@api_bp.route("/advanced/capabilities", methods=["GET"])
@login_required
def advanced_capabilities():
    """Get available advanced AI capabilities."""
    try:
        ai_service = get_advanced_ai_service()
        return jsonify({
            'success': True,
            'capabilities': ai_service.supported_operations,
            'active_provider': ai_service.provider.name,
            'provider_capabilities': ai_service.provider.get_capabilities().to_dict(),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
