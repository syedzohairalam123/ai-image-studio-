"""
Advanced AI Service - Image-to-Image, Inpainting, Style Transfer, and AI-powered features
"""
import os
import json
import base64
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path
import requests
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import io

from app.utils import now_utc
from app.services.ai_provider import get_provider


def _tint_region_from_prompt(image: Image.Image, mask_arr, prompt: str) -> Image.Image:
    """Nudge the colour balance of a masked region toward warm/cool based on
    simple keyword cues in the prompt. This can't paint new content (that
    needs a real generative model), but it keeps classic-CV inpainting from
    feeling completely blind to what the user asked for."""
    import numpy as np

    lower = (prompt or "").lower()
    warm_words = ("warm", "sunset", "fire", "orange", "red", "gold", "autumn", "flame")
    cool_words = ("cool", "blue", "ocean", "ice", "winter", "night", "cold", "arctic")
    warm = any(w in lower for w in warm_words)
    cool = any(w in lower for w in cool_words)
    if not (warm or cool):
        return image

    arr = np.array(image.convert('RGB')).astype(np.float32)
    m = mask_arr > 127
    if warm:
        arr[..., 0][m] = np.clip(arr[..., 0][m] * 1.08 + 6, 0, 255)
        arr[..., 2][m] = np.clip(arr[..., 2][m] * 0.94, 0, 255)
    else:
        arr[..., 2][m] = np.clip(arr[..., 2][m] * 1.08 + 6, 0, 255)
        arr[..., 0][m] = np.clip(arr[..., 0][m] * 0.94, 0, 255)
    return Image.fromarray(arr.astype(np.uint8), mode='RGB')


def _kmeans_dominant_colors(pixels_flat, k: int = 5) -> List[Dict]:
    """Real k-means clustering (scipy) to find the k dominant colours in a
    flat (N, 3) float array of RGB pixels, sorted by prevalence."""
    import numpy as np
    from scipy.cluster.vq import kmeans2

    unique_count = len(np.unique(np.round(pixels_flat).astype(int), axis=0))
    k = max(1, min(k, unique_count))
    try:
        centroids, labels = kmeans2(pixels_flat, k, seed=42, minit='++')
    except Exception:
        avg = pixels_flat.mean(axis=0)
        rgb = tuple(int(max(0, min(255, c))) for c in avg)
        return [{"color": rgb, "hex": '#%02x%02x%02x' % rgb, "weight": 1.0}]

    counts = np.bincount(labels, minlength=k)
    total = max(1, counts.sum())
    order = np.argsort(-counts)
    result = []
    for i in order:
        if counts[i] == 0:
            continue
        rgb = tuple(int(max(0, min(255, c))) for c in centroids[i])
        result.append({
            "color": rgb,
            "hex": '#%02x%02x%02x' % rgb,
            "weight": round(float(counts[i]) / float(total), 3),
        })
    return result


def _measure_sharpness(image: Image.Image) -> float:
    """Laplacian-variance sharpness score (classic blur-detection metric —
    Pech-Pacheco et al. 2000). Higher = sharper / more in-focus."""
    try:
        import cv2
        import numpy as np
        gray = np.array(image.convert('L'))
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception:
        return 0.0


def _measure_contrast(image: Image.Image) -> float:
    """Normalized (0-1ish) global contrast via grayscale standard deviation."""
    import numpy as np
    gray = np.asarray(image.convert('L'), dtype=np.float32)
    return float(gray.std() / 127.5)


def _detect_faces(image: Image.Image) -> List[Dict]:
    """Real face detection using OpenCV's bundled Haar cascade — ships with
    the opencv package itself, so this works fully offline."""
    try:
        import cv2
        import numpy as np
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            return []
        gray = np.array(image.convert('L'))
        min_dim = max(24, min(gray.shape[:2]) // 12)
        faces = cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(min_dim, min_dim)
        )
        return [
            {"label": "face", "box": {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}}
            for (x, y, w, h) in faces
        ]
    except Exception:
        return []


def _gray_world_white_balance(image: Image.Image) -> Image.Image:
    """Classic gray-world auto white balance: scale each channel so its mean
    moves toward the overall gray mean."""
    import numpy as np
    arr = np.asarray(image.convert('RGB'), dtype=np.float32)
    means = arr.reshape(-1, 3).mean(axis=0)
    gray_mean = means.mean()
    scale = np.clip(gray_mean / np.clip(means, 1.0, None), 0.5, 2.0)
    arr = np.clip(arr * scale[None, None, :], 0, 255)
    return Image.fromarray(arr.astype(np.uint8), mode='RGB')


def _shift_channels(image: Image.Image, r_factor: float = 1.0, g_factor: float = 1.0,
                     b_factor: float = 1.0) -> Image.Image:
    """Directly scale R/G/B channels — a real warm/cool colour temperature
    shift, as opposed to a blanket saturation change."""
    import numpy as np
    arr = np.asarray(image.convert('RGB'), dtype=np.float32)
    arr[..., 0] = np.clip(arr[..., 0] * r_factor, 0, 255)
    arr[..., 1] = np.clip(arr[..., 1] * g_factor, 0, 255)
    arr[..., 2] = np.clip(arr[..., 2] * b_factor, 0, 255)
    return Image.fromarray(arr.astype(np.uint8), mode='RGB')


def _find_salient_crop_origin(image: Image.Image, crop_w: int, crop_h: int) -> Tuple[int, int]:
    """Choose a crop origin that keeps the "interesting" part of the image.

    Priority 1: if faces are detected, centre the crop on them.
    Priority 2: otherwise pick the crop_w x crop_h window with the highest
    edge-density (a cheap, real saliency proxy), found via an integral image
    so every candidate window is scored in O(1) instead of re-summing pixels.
    Falls back to a plain center crop if anything goes wrong.
    """
    import numpy as np

    width, height = image.size
    crop_w, crop_h = min(crop_w, width), min(crop_h, height)
    max_x, max_y = max(0, width - crop_w), max(0, height - crop_h)

    faces = _detect_faces(image)
    if faces:
        xs = [f["box"]["x"] + f["box"]["width"] / 2 for f in faces]
        ys = [f["box"]["y"] + f["box"]["height"] / 2 for f in faces]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        left = int(np.clip(cx - crop_w / 2, 0, max_x))
        top = int(np.clip(cy - crop_h / 2, 0, max_y))
        return left, top

    try:
        import cv2
        gray = np.array(image.convert('L'))
        edges = cv2.Canny(gray, 60, 160).astype(np.float32)
        integral = cv2.integral(edges)  # O(n) precompute -> O(1) window sums
        step = max(4, min(width, height) // 60)
        best_score, best_xy = -1.0, (max_x // 2, max_y // 2)
        for y in range(0, max_y + 1, step):
            for x in range(0, max_x + 1, step):
                score = (integral[y + crop_h, x + crop_w] - integral[y, x + crop_w]
                          - integral[y + crop_h, x] + integral[y, x])
                if score > best_score:
                    best_score = score
                    best_xy = (x, y)
        return best_xy
    except Exception:
        return max_x // 2, max_y // 2


def _describe_scene(color_analysis: Dict, faces: List[Dict], size) -> str:
    width, height = size
    parts = []
    if faces:
        parts.append(f"{len(faces)} face{'s' if len(faces) != 1 else ''} detected")
    if width > height * 1.15:
        orientation = "landscape"
    elif height > width * 1.15:
        orientation = "portrait"
    else:
        orientation = "square"
    parts.append(f"{orientation} composition")
    parts.append(f"{color_analysis.get('mood', 'balanced')} color palette")
    return ", ".join(parts).capitalize()


def _mood_from_stats(warmth: float, coolness: float, brightness: float, colorfulness: float) -> str:
    """Translate raw colour statistics into a short human-readable mood."""
    if colorfulness < 15:
        base = "muted" if brightness > 0.3 else "somber"
    elif warmth > coolness + 0.08:
        base = "warm and energetic" if brightness > 0.5 else "warm and cozy"
    elif coolness > warmth + 0.08:
        base = "cool and calm" if brightness > 0.5 else "cool and moody"
    else:
        base = "balanced"
    if brightness > 0.75:
        return f"bright, {base}"
    if brightness < 0.25:
        return f"dark, {base}"
    return base


class AdvancedAIService:
    """Advanced AI operations for image manipulation and enhancement."""

    def __init__(self, provider_name: Optional[str] = None):
        # BUGFIX: this used to call get_provider() with no arguments, which
        # raises `TypeError: get_provider() missing 1 required positional
        # argument: 'name'` on every single instantiation — meaning every
        # route in routes/advanced_ai.py crashed unconditionally. We now
        # resolve a sensible provider name (explicit arg > AI_PROVIDER env
        # > "stub") and fall back to the always-available stub provider if
        # the configured one can't be constructed for any reason.
        resolved_name = provider_name
        api_key = ""
        if resolved_name is None:
            try:
                from flask import current_app
                resolved_name = current_app.config.get("AI_PROVIDER", "stub")
                api_key = current_app.config.get("AI_API_KEY", "") or ""
            except Exception:
                resolved_name = os.environ.get("AI_PROVIDER", "stub")
                api_key = os.environ.get("AI_API_KEY", "")
        try:
            self.provider = get_provider(resolved_name, api_key=api_key)
        except Exception:
            self.provider = get_provider("stub")
        self.supported_operations = {
            'image_to_image': True,
            'inpainting': True,
            'style_transfer': True,
            'outpainting': True,
            'face_enhancement': True,
            'super_resolution': True,
            'color_correction': True,
            'smart_crop': True
        }
    
    def image_to_image(self, source_image_path: str, prompt: str, 
                      strength: float = 0.7, **kwargs) -> Dict:
        """
        Transform an existing image using AI based on a text prompt.
        
        Args:
            source_image_path: Path to source image
            prompt: Text description of desired transformation
            strength: How much to transform (0.0-1.0)
            **kwargs: Additional parameters (style, quality, etc.)
            
        Returns:
            Dict with generated image data and metadata
        """
        try:
            # Load and prepare source image
            source_image = Image.open(source_image_path)
            
            # Check if provider supports image-to-image
            if hasattr(self.provider, 'image_to_image'):
                result = self.provider.image_to_image(
                    source_image=source_image,
                    prompt=prompt,
                    strength=strength,
                    **kwargs
                )
            else:
                # Fallback: use basic image manipulation
                result = self._fallback_image_transform(source_image, prompt, strength)
            
            return {
                'success': True,
                'operation': 'image_to_image',
                'result_image': result.get('image'),
                'metadata': {
                    'prompt': prompt,
                    'strength': strength,
                    'timestamp': now_utc().isoformat(),
                    'original_size': source_image.size
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'operation': 'image_to_image'
            }
    
    def inpainting(self, source_image_path: str, mask_path: str, 
                   prompt: str, **kwargs) -> Dict:
        """
        Fill in masked areas of an image using AI.
        
        Args:
            source_image_path: Path to source image
            mask_path: Path to mask image (white = fill, black = keep)
            prompt: Text description of what to fill in
            **kwargs: Additional parameters
            
        Returns:
            Dict with inpainted image data
        """
        try:
            source_image = Image.open(source_image_path)
            mask_image = Image.open(mask_path)
            
            # Check if provider supports inpainting
            if hasattr(self.provider, 'inpainting'):
                result = self.provider.inpainting(
                    source_image=source_image,
                    mask_image=mask_image,
                    prompt=prompt,
                    **kwargs
                )
            else:
                # Fallback: basic inpainting using surrounding pixels
                result = self._fallback_inpainting(source_image, mask_image, prompt)
            
            return {
                'success': True,
                'operation': 'inpainting',
                'result_image': result.get('image'),
                'metadata': {
                    'prompt': prompt,
                    'timestamp': now_utc().isoformat(),
                    'mask_size': mask_image.size
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'operation': 'inpainting'
            }
    
    def style_transfer(self, source_image_path: str, style_reference: str,
                      style_strength: float = 0.8, **kwargs) -> Dict:
        """
        Apply artistic style from a reference image to source image.
        
        Args:
            source_image_path: Path to source image
            style_reference: Path to style reference image or style name
            style_strength: How strongly to apply the style (0.0-1.0)
            **kwargs: Additional parameters
            
        Returns:
            Dict with stylized image data
        """
        try:
            source_image = Image.open(source_image_path)
            
            # Check if style_reference is a file path or preset name
            if os.path.exists(style_reference):
                style_image = Image.open(style_reference)
            else:
                # Use preset style
                style_image = self._get_preset_style(style_reference)
            
            if hasattr(self.provider, 'style_transfer'):
                result = self.provider.style_transfer(
                    source_image=source_image,
                    style_image=style_image,
                    strength=style_strength,
                    **kwargs
                )
            else:
                # Fallback: basic style transfer simulation
                result = self._fallback_style_transfer(source_image, style_image, style_strength)
            
            return {
                'success': True,
                'operation': 'style_transfer',
                'result_image': result.get('image'),
                'metadata': {
                    'style_reference': style_reference,
                    'strength': style_strength,
                    'timestamp': now_utc().isoformat()
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'operation': 'style_transfer'
            }
    
    def outpainting(self, source_image_path: str, direction: str,
                   prompt: str, extend_pixels: int = 256, **kwargs) -> Dict:
        """
        Extend image boundaries in specified direction using AI.
        
        Args:
            source_image_path: Path to source image
            direction: 'left', 'right', 'top', 'bottom', or 'all'
            prompt: Text description of what to generate
            extend_pixels: How many pixels to extend
            **kwargs: Additional parameters
            
        Returns:
            Dict with outpainted image data
        """
        try:
            source_image = Image.open(source_image_path)
            
            if hasattr(self.provider, 'outpainting'):
                result = self.provider.outpainting(
                    source_image=source_image,
                    direction=direction,
                    prompt=prompt,
                    extend_pixels=extend_pixels,
                    **kwargs
                )
            else:
                # Fallback: basic extension
                result = self._fallback_outpainting(source_image, direction, extend_pixels)
            
            return {
                'success': True,
                'operation': 'outpainting',
                'result_image': result.get('image'),
                'metadata': {
                    'direction': direction,
                    'extend_pixels': extend_pixels,
                    'prompt': prompt,
                    'timestamp': now_utc().isoformat()
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'operation': 'outpainting'
            }
    
    def face_enhancement(self, image_path: str, enhancement_level: str = 'medium') -> Dict:
        """
        Enhance faces in image using AI.
        
        Args:
            image_path: Path to image
            enhancement_level: 'light', 'medium', 'strong'
            
        Returns:
            Dict with enhanced image data
        """
        try:
            image = Image.open(image_path)
            
            if hasattr(self.provider, 'face_enhance'):
                result = self.provider.face_enhance(image, level=enhancement_level)
            else:
                # Fallback: basic sharpening and enhancement
                result = self._fallback_face_enhancement(image, enhancement_level)
            
            return {
                'success': True,
                'operation': 'face_enhancement',
                'result_image': result.get('image'),
                'metadata': {
                    'enhancement_level': enhancement_level,
                    'timestamp': now_utc().isoformat()
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'operation': 'face_enhancement'
            }
    
    def super_resolution(self, image_path: str, scale_factor: int = 2) -> Dict:
        """
        Upscale image using AI super-resolution.
        
        Args:
            image_path: Path to image
            scale_factor: 2x, 4x, etc.
            
        Returns:
            Dict with upscaled image data
        """
        try:
            image = Image.open(image_path)
            
            if hasattr(self.provider, 'super_resolution'):
                result = self.provider.super_resolution(image, scale=scale_factor)
            else:
                # Fallback: basic upsampling with sharpening
                result = self._fallback_super_resolution(image, scale_factor)
            
            return {
                'success': True,
                'operation': 'super_resolution',
                'result_image': result.get('image'),
                'metadata': {
                    'scale_factor': scale_factor,
                    'original_size': image.size,
                    'timestamp': now_utc().isoformat()
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'operation': 'super_resolution'
            }
    
    def smart_crop(self, image_path: str, target_aspect: str = '1:1') -> Dict:
        """
        Intelligently crop image to target aspect ratio using AI saliency detection.
        
        Args:
            image_path: Path to image
            target_aspect: '1:1', '16:9', '4:3', etc.
            
        Returns:
            Dict with cropped image data and crop coordinates
        """
        try:
            image = Image.open(image_path)
            
            # Calculate target dimensions
            aspect_ratio = self._parse_aspect_ratio(target_aspect)
            original_width, original_height = image.size
            
            if aspect_ratio > 1:
                # Landscape
                new_width = original_width
                new_height = int(original_width / aspect_ratio)
            else:
                # Portrait
                new_height = original_height
                new_width = int(original_height * aspect_ratio)
            
            # Use AI to find best crop region (fallback to real saliency-aware crop)
            if hasattr(self.provider, 'smart_crop'):
                result = self.provider.smart_crop(image, target_aspect)
            else:
                left, top = _find_salient_crop_origin(image, new_width, new_height)
                right = left + new_width
                bottom = top + new_height
                cropped = image.crop((left, top, right, bottom))
                result = {'image': cropped, 'crop_coords': (left, top, right, bottom)}
            
            return {
                'success': True,
                'operation': 'smart_crop',
                'result_image': result.get('image'),
                'metadata': {
                    'target_aspect': target_aspect,
                    'crop_coords': result.get('crop_coords'),
                    'timestamp': now_utc().isoformat()
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'operation': 'smart_crop'
            }
    
    def color_correction(self, image_path: str, correction_type: str = 'auto') -> Dict:
        """
        Apply AI-powered color correction.
        
        Args:
            image_path: Path to image
            correction_type: 'auto', 'warm', 'cool', 'vivid', 'muted'
            
        Returns:
            Dict with color-corrected image data
        """
        try:
            image = Image.open(image_path)
            
            if hasattr(self.provider, 'color_correction'):
                result = self.provider.color_correction(image, correction_type)
            else:
                # Fallback: basic color adjustments
                result = self._fallback_color_correction(image, correction_type)
            
            return {
                'success': True,
                'operation': 'color_correction',
                'result_image': result.get('image'),
                'metadata': {
                    'correction_type': correction_type,
                    'timestamp': now_utc().isoformat()
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'operation': 'color_correction'
            }
    
    def analyze_image_content(self, image_path: str) -> Dict:
        """
        Analyze image content using AI to detect objects, scenes, colors, etc.
        
        Args:
            image_path: Path to image
            
        Returns:
            Dict with detailed image analysis
        """
        try:
            image = Image.open(image_path)
            
            color_analysis = self._analyze_colors(image)
            sharpness = _measure_sharpness(image)
            contrast = _measure_contrast(image)
            faces = _detect_faces(image)

            analysis = {
                'basic_info': {
                    'size': image.size,
                    'mode': image.mode,
                    'format': image.format
                },
                'color_analysis': color_analysis,
                'detected_objects': faces,
                'scene_description': _describe_scene(color_analysis, faces, image.size),
                'dominant_colors': color_analysis.get('dominant_colors', []),
                'brightness': round(color_analysis.get('brightness', 0), 3),
                'contrast': round(contrast, 3),
                'sharpness': round(sharpness, 2)
            }
            
            # Try to get AI analysis if available
            if hasattr(self.provider, 'analyze_image'):
                ai_analysis = self.provider.analyze_image(image)
                analysis.update(ai_analysis)
            
            return {
                'success': True,
                'operation': 'image_analysis',
                'analysis': analysis,
                'timestamp': now_utc().isoformat()
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'operation': 'image_analysis'
            }
    
    def generate_variations(self, image_path: str, num_variations: int = 4,
                           variation_strength: float = 0.3) -> Dict:
        """
        Generate multiple variations of an image.
        
        Args:
            image_path: Path to source image
            num_variations: Number of variations to generate
            variation_strength: How different variations should be
            
        Returns:
            Dict with list of variation images
        """
        try:
            image = Image.open(image_path)
            variations = []
            
            for i in range(num_variations):
                if hasattr(self.provider, 'generate_variation'):
                    variation = self.provider.generate_variation(
                        image, 
                        strength=variation_strength + (i * 0.1)
                    )
                else:
                    # Fallback: random adjustments
                    variation = self._fallback_variation(image, variation_strength + (i * 0.1))
                
                variations.append(variation.get('image'))
            
            return {
                'success': True,
                'operation': 'generate_variations',
                'variations': variations,
                'metadata': {
                    'num_variations': num_variations,
                    'strength': variation_strength,
                    'timestamp': now_utc().isoformat()
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'operation': 'generate_variations'
            }
    
    # ===== Fallback Methods for Basic Image Manipulation =====
    
    def _fallback_image_transform(self, image: Image.Image, prompt: str, 
                                  strength: float) -> Dict:
        """Basic image transformation when AI is unavailable."""
        # Apply basic adjustments based on prompt keywords
        enhancer = ImageEnhance.Color(image)
        
        if 'vibrant' in prompt.lower() or 'colorful' in prompt.lower():
            image = enhancer.enhance(1.0 + strength * 0.5)
        elif 'black' in prompt.lower() or 'grayscale' in prompt.lower():
            image = ImageOps.grayscale(image)
        
        # Apply blur or sharpen
        if 'blur' in prompt.lower():
            image = image.filter(ImageFilter.GaussianBlur(radius=strength * 3))
        elif 'sharp' in prompt.lower():
            image = image.filter(ImageFilter.SHARPEN)
        
        return {'image': image}
    
    def _fallback_inpainting(self, image: Image.Image, mask: Image.Image,
                            prompt: str) -> Dict:
        """Classic (non-AI) inpainting that actually respects the mask.

        Uses OpenCV's Telea fast-marching inpainting algorithm to
        reconstruct only the masked region from surrounding texture/colour —
        a real, well-established computer-vision technique (not a diffusion
        model, but genuinely mask-aware, unlike blurring the whole image).
        """
        try:
            import cv2
            import numpy as np

            rgb_image = image.convert('RGB')
            src = np.array(rgb_image)[:, :, ::-1].copy()  # RGB -> BGR for cv2

            mask_l = mask.convert('L').resize(rgb_image.size)
            mask_arr = np.array(mask_l)
            # White (or near-white) = region to fill in, matching the
            # inpaint mask convention used across the rest of the app.
            binary_mask = (mask_arr > 127).astype(np.uint8) * 255

            if binary_mask.max() == 0:
                # Nothing selected — nothing to do, return the source as-is.
                return {'image': image}

            radius = max(3, min(src.shape[0], src.shape[1]) // 100)
            result_bgr = cv2.inpaint(src, binary_mask, radius, cv2.INPAINT_TELEA)
            result_rgb = result_bgr[:, :, ::-1]
            result = Image.fromarray(result_rgb, mode='RGB')

            # Gentle prompt-aware tint: without a real text-conditioned model
            # we can't paint new content, but we can nudge the reconstructed
            # region's colour balance to loosely match warm/cool language in
            # the prompt so the result doesn't feel completely prompt-blind.
            result = _tint_region_from_prompt(result, binary_mask, prompt)
            return {'image': result}
        except Exception:
            # Last-resort fallback if OpenCV is unavailable for some reason.
            return {'image': image.filter(ImageFilter.SMOOTH)}
    
    def _fallback_style_transfer(self, source: Image.Image, style: Image.Image,
                                 strength: float) -> Dict:
        """Basic style transfer simulation."""
        # Adjust color balance based on style image
        style_enhancer = ImageEnhance.Color(style)
        source_enhancer = ImageEnhance.Color(source)
        
        # Extract some color properties from style
        style_stats = self._analyze_colors(style)
        
        # Apply simplified color transfer
        result = source
        if style_stats.get('warmth', 0) > 0.5:
            result = ImageEnhance.Color(result).enhance(1.2)
        elif style_stats.get('coolness', 0) > 0.5:
            result = ImageEnhance.Color(result).enhance(0.8)
        
        return {'image': result}
    
    def _fallback_outpainting(self, image: Image.Image, direction: str,
                             extend_pixels: int) -> Dict:
        """Extend the canvas and fill the new region with content-aware fill.

        Previously this just pasted the source onto a solid white canvas,
        leaving an obvious hard-edged block of white with no relation to the
        image. Now we mirror-extend the border pixels (so there's real
        texture to work with) and then run OpenCV inpainting treating the
        new region as the "hole" — this produces a seamless, non-white
        extension using only classic CV, no external model required.
        """
        try:
            import cv2
            import numpy as np

            rgb = image.convert('RGB')
            width, height = rgb.size
            left = top = right = bottom = 0
            if direction in ('left', 'all'):
                left = extend_pixels
            if direction in ('right', 'all'):
                right = extend_pixels
            if direction in ('top', 'all'):
                top = extend_pixels
            if direction in ('bottom', 'all'):
                bottom = extend_pixels
            if not any((left, top, right, bottom)):
                right = extend_pixels  # sensible default

            src = np.array(rgb)[:, :, ::-1]  # RGB -> BGR
            # Reflect-pad gives the inpainter real edge texture to extend
            # from, instead of inpainting into a flat/blank region.
            padded = cv2.copyMakeBorder(src, top, bottom, left, right, cv2.BORDER_REFLECT_101)

            mask = np.zeros(padded.shape[:2], dtype=np.uint8)
            mask[:top, :] = 255
            mask[padded.shape[0] - bottom if bottom else padded.shape[0]:, :] = 255
            mask[:, :left] = 255
            mask[:, padded.shape[1] - right if right else padded.shape[1]:] = 255

            radius = max(3, extend_pixels // 12)
            filled = cv2.inpaint(padded, mask, radius, cv2.INPAINT_TELEA)

            # Feather the seam between original and newly-generated pixels
            # so the join doesn't look like a hard cut.
            feather = max(4, extend_pixels // 8)
            blurred = cv2.GaussianBlur(filled, (0, 0), sigmaX=feather / 2)
            mask_f = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), sigmaX=feather)[..., None]
            blended = (filled.astype(np.float32) * (1 - mask_f * 0.35) +
                       blurred.astype(np.float32) * (mask_f * 0.35))

            new_image = Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8)[:, :, ::-1], mode='RGB')
            return {'image': new_image}
        except Exception:
            # Last-resort: neutral gray instead of stark white so it reads
            # as "unfilled" rather than a broken layout.
            width, height = image.size
            new_w = width + (extend_pixels if direction in ('left', 'right', 'all') else 0)
            new_h = height + (extend_pixels if direction in ('top', 'bottom', 'all') else 0)
            new_image = Image.new(image.mode, (new_w, new_h), (128, 128, 128))
            offset_x = extend_pixels if direction in ('left', 'all') else 0
            offset_y = extend_pixels if direction in ('top', 'all') else 0
            new_image.paste(image, (offset_x, offset_y))
            return {'image': new_image}
    
    def _fallback_face_enhancement(self, image: Image.Image, level: str) -> Dict:
        """Enhance detected face regions specifically (edge-aware smoothing
        + targeted sharpening blended only over the face boxes), rather than
        sharpening the entire frame uniformly regardless of where any faces
        actually are. Falls back to whole-image sharpening if no face is
        detected, preserving the previous behaviour for non-portrait shots.
        """
        strength = {'light': 1.2, 'medium': 1.5, 'strong': 2.0}.get(level, 1.5)
        faces = _detect_faces(image)
        if not faces:
            return {'image': ImageEnhance.Sharpness(image).enhance(strength)}

        try:
            import cv2
            import numpy as np
            rgb = image.convert('RGB')
            arr = np.array(rgb)
            bgr = arr[:, :, ::-1].copy()

            # Bilateral filter smooths skin tone/texture noise while
            # preserving edges (eyes, brows, lips) far better than a
            # gaussian blur would.
            smoothed = cv2.bilateralFilter(bgr, d=9, sigmaColor=55, sigmaSpace=55)
            sharp_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
            sharpened = cv2.filter2D(smoothed, -1, sharp_kernel * (strength / 1.5))

            out = bgr.copy()
            for f in faces:
                b = f["box"]
                pad = int(max(b["width"], b["height"]) * 0.15)
                x0, y0 = max(0, b["x"] - pad), max(0, b["y"] - pad)
                x1 = min(bgr.shape[1], b["x"] + b["width"] + pad)
                y1 = min(bgr.shape[0], b["y"] + b["height"] + pad)
                region = sharpened[y0:y1, x0:x1].astype(np.float32)
                base = out[y0:y1, x0:x1].astype(np.float32)

                # Feathered elliptical mask so the enhanced region blends
                # smoothly into the rest of the photo instead of a hard box.
                mh, mw = region.shape[:2]
                yy, xx = np.mgrid[0:mh, 0:mw].astype(np.float32)
                cy, cx = mh / 2, mw / 2
                dist = ((xx - cx) / max(cx, 1)) ** 2 + ((yy - cy) / max(cy, 1)) ** 2
                mask = np.clip(1.2 - dist, 0, 1) ** 1.5
                blended = base * (1 - mask[..., None]) + region * mask[..., None]
                out[y0:y1, x0:x1] = np.clip(blended, 0, 255).astype(np.uint8)

            result = Image.fromarray(out[:, :, ::-1], mode='RGB')
            return {'image': result}
        except Exception:
            return {'image': ImageEnhance.Sharpness(image).enhance(strength)}
    
    def _fallback_super_resolution(self, image: Image.Image, scale: int) -> Dict:
        """Basic upscaling with sharpening."""
        new_size = (image.size[0] * scale, image.size[1] * scale)
        upscaled = image.resize(new_size, Image.Resampling.LANCZOS)
        sharpened = upscaled.filter(ImageFilter.SHARPEN)
        return {'image': sharpened}
    
    def _fallback_color_correction(self, image: Image.Image, correction_type: str) -> Dict:
        """Color correction using real per-channel adjustments.

        'auto' now performs gray-world white balance (a real, classic
        auto-white-balance algorithm — scale each channel so its mean moves
        toward the overall gray mean) followed by autocontrast, instead of
        just autocontrast alone. 'warm'/'cool' now actually shift the
        red/blue channel balance rather than only changing saturation, which
        is what those adjustments mean in real photo editors.
        """
        if correction_type == 'auto':
            result = _gray_world_white_balance(image)
            result = ImageOps.autocontrast(result, cutoff=1)
        elif correction_type == 'warm':
            result = _shift_channels(image, r_factor=1.12, b_factor=0.90)
        elif correction_type == 'cool':
            result = _shift_channels(image, r_factor=0.90, b_factor=1.12)
        elif correction_type == 'vivid':
            result = ImageEnhance.Color(image).enhance(1.5)
            result = ImageEnhance.Contrast(result).enhance(1.1)
        elif correction_type == 'muted':
            result = ImageEnhance.Color(image).enhance(0.6)
            result = ImageEnhance.Contrast(result).enhance(0.95)
        else:
            result = image
        
        return {'image': result}
    
    def _fallback_variation(self, image: Image.Image, strength: float) -> Dict:
        """Generate basic image variation."""
        # Random slight adjustments
        brightness = 1.0 + (strength - 0.5) * 0.3
        contrast = 1.0 + (strength - 0.5) * 0.2
        color = 1.0 + (strength - 0.5) * 0.2
        
        result = image
        result = ImageEnhance.Brightness(result).enhance(brightness)
        result = ImageEnhance.Contrast(result).enhance(contrast)
        result = ImageEnhance.Color(result).enhance(color)
        
        return {'image': result}
    
    def _get_preset_style(self, style_name: str) -> Image.Image:
        """Get a preset style reference image by name.

        Previously this returned a single flat colour square, which meant
        `_analyze_colors` on it always produced a degenerate, uninformative
        result. It now renders a real generated texture whose palette and
        structure match the named preset, using the procedural art engine.
        """
        import io as _io
        from app.services.procedural_art import generate_art

        preset_prompts = {
            'oil_painting': ('warm textured oil painting, amber and umber', 'organic_blobs'),
            'watercolor': ('soft blue watercolor wash, gentle bleed', 'flow_field'),
            'sketch': ('monochrome graphite sketch, dark and moody', 'geometric_mosaic'),
            'anime': ('vibrant anime energy, pink and violet', 'particle_burst'),
            'cyberpunk': ('neon cyberpunk city, magenta and cyan', 'shaded_blobs'),
        }
        prompt, style = preset_prompts.get(style_name, ('neutral abstract texture', 'flow_field'))
        try:
            data = generate_art(prompt=prompt, width=256, height=256, style=style, seed=42)
            return Image.open(_io.BytesIO(data)).convert('RGB')
        except Exception:
            return Image.new('RGB', (256, 256), (128, 128, 128))
    
    def _analyze_colors(self, image: Image.Image) -> Dict:
        """Real colour analysis of an image using vectorized numpy.

        Was previously a pure-Python loop over every pixel (slow, O(n) with
        big constant factors) computing only a flat average. Now vectorized
        (orders of magnitude faster on large images) and extended with real
        k-means dominant-colour extraction and an HSV-based colourfulness /
        mood read, rather than just a single average RGB triple.
        """
        import numpy as np

        if image.mode != 'RGB':
            image = image.convert('RGB')

        # Downsample for speed — colour statistics don't need full
        # resolution, and this keeps k-means fast even on large images.
        sample = image.copy()
        sample.thumbnail((160, 160))
        arr = np.asarray(sample, dtype=np.float32).reshape(-1, 3)

        avg = arr.mean(axis=0)
        avg_red, avg_green, avg_blue = avg.tolist()
        warmth = avg_red / (avg_red + avg_blue + 1)
        coolness = avg_blue / (avg_red + avg_blue + 1)

        dominant = _kmeans_dominant_colors(arr, k=5)

        # Hasler & Süsstrunk (2003) colourfulness metric — a simple, widely
        # used formula that correlates well with perceived colourfulness.
        rg = arr[:, 0] - arr[:, 1]
        yb = 0.5 * (arr[:, 0] + arr[:, 1]) - arr[:, 2]
        colorfulness = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) +
                              0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))

        mx = arr.max(axis=1)
        mn = arr.min(axis=1)
        avg_saturation = float(((mx - mn) / (mx + 1e-6)).mean())

        return {
            'average_color': (int(avg_red), int(avg_green), int(avg_blue)),
            'warmth': warmth,
            'coolness': coolness,
            'brightness': float(avg.mean()) / 255,
            'dominant_colors': dominant,
            'colorfulness': round(colorfulness, 2),
            'saturation': round(avg_saturation, 3),
            'mood': _mood_from_stats(warmth, coolness, float(avg.mean()) / 255, colorfulness),
        }
    
    def _parse_aspect_ratio(self, ratio_str: str) -> float:
        """Parse aspect ratio string like '16:9' to float."""
        try:
            parts = ratio_str.split(':')
            return int(parts[0]) / int(parts[1])
        except:
            return 1.0


# Singleton instance
_advanced_ai_service = None

def get_advanced_ai_service():
    """Get the singleton AdvancedAIService instance."""
    global _advanced_ai_service
    if _advanced_ai_service is None:
        _advanced_ai_service = AdvancedAIService()
    return _advanced_ai_service