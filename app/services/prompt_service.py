"""Prompt enhancement service — expands simple prompts into structured, detailed prompts."""


# Enhancement dimension templates
_DIMENSION_TEMPLATES = {
    "subject": {
        "keywords": [],
        "expand": [
            "a detailed subject",
            "a well-defined focal point",
            "a prominent subject",
        ],
    },
    "environment": {
        "keywords": ["city", "forest", "ocean", "mountain", "desert", "space", "garden", "street", "room", "castle"],
        "templates": {
            "city": "urban cityscape with towering skyscrapers",
            "forest": "dense lush forest with towering trees",
            "ocean": "vast open ocean stretching to the horizon",
            "mountain": "majestic mountain range with snow-capped peaks",
            "desert": "vast desert with rolling sand dunes",
            "space": "deep space with stars and nebulae",
            "garden": "beautiful botanical garden with vibrant flowers",
            "street": "bustling street scene with ambient details",
            "room": "interior room with carefully arranged furnishings",
            "castle": "imposing medieval castle with stone walls",
        },
    },
    "composition": {
        "templates": [
            "well-balanced composition",
            "rule of thirds framing",
            "dynamic diagonal composition",
            "symmetrical centered composition",
            "dramatic leading lines drawing the eye",
        ],
    },
    "lighting": {
        "templates": [
            "golden hour warm lighting",
            "soft diffused natural light",
            "dramatic volumetric lighting",
            "cinematic rim lighting",
            "moody low-key lighting with deep shadows",
            "bright even studio lighting",
            "ethereal backlighting with lens flare",
        ],
    },
    "camera": {
        "templates": [
            "wide angle perspective",
            "macro close-up detail",
            "aerial drone perspective",
            "eye-level natural perspective",
            "low angle dramatic perspective",
            "shallow depth of field with bokeh background",
        ],
    },
    "mood": {
        "templates": [
            "serene and tranquil atmosphere",
            "epic and awe-inspiring mood",
            "mysterious and enigmatic ambiance",
            "cheerful and vibrant energy",
            "melancholic and contemplative tone",
            "intense and powerful feeling",
        ],
    },
    "detail": {
        "templates": [
            "intricate fine details throughout",
            "highly detailed textures and surfaces",
            "sharp focus with crisp edges",
            "subtle atmospheric haze for depth",
            "rich color palette with vibrant saturation",
        ],
    },
}

# Style-specific enhancement modifiers
_STYLE_MODIFIERS = {
    "photo": "photorealistic, shot on Canon EOS R5, 35mm lens, f/2.8 aperture, RAW photo",
    "art": "digital art, trending on ArtStation, concept art, highly detailed illustration",
    "paint": "oil painting, thick brushstrokes, classical technique, rich textures",
    "anime": "anime style, cel-shaded, vibrant colors, Studio Ghibli inspired",
    "3d": "3D render, octane render, ray tracing, subsurface scattering, PBR materials",
    "pixel": "pixel art, 16-bit retro style, crisp pixels, nostalgic aesthetic",
    "minimal": "minimalist design, clean lines, simple geometric shapes, negative space",
    "auto": "",
}


def enhance_prompt(original_prompt: str, style: str = "auto") -> dict:
    """Enhance a simple prompt into a structured, detailed prompt.

    Returns dict with:
      - original: the original prompt
      - enhanced: the enhanced prompt string
      - dimensions: dict of enhancement dimensions used
      - style_modifier: the style-specific modifier applied
    """
    original_prompt = original_prompt.strip()
    if not original_prompt:
        return {
            "original": original_prompt,
            "enhanced": original_prompt,
            "dimensions": {},
            "style_modifier": "",
        }

    prompt_lower = original_prompt.lower()
    dimensions_used = {}

    # Detect which dimensions apply based on keywords
    for dim_name, dim_config in _DIMENSION_TEMPLATES.items():
        if dim_name == "subject":
            # Subject is always relevant — skip auto-expansion to avoid redundancy
            continue

        if dim_name == "environment":
            # Check if any environment keyword is in the prompt
            detected_env = None
            for kw in dim_config["keywords"]:
                if kw in prompt_lower:
                    detected_env = kw
                    break
            if detected_env:
                dimensions_used[dim_name] = dim_config["templates"].get(detected_env, "")
        elif dim_name == "style":
            pass  # Handled separately via style modifier
        else:
            # For composition, lighting, camera, mood, detail — pick one template each
            import random
            templates = dim_config.get("templates", [])
            if templates:
                dimensions_used[dim_name] = random.choice(templates)

    # Build enhanced prompt
    parts = [original_prompt]

    # Add detected dimensions (skip ones already in the prompt)
    for dim_name, value in dimensions_used.items():
        if value and _not_redundant(value, prompt_lower):
            parts.append(value)

    # Add style modifier
    style_mod = _STYLE_MODIFIERS.get(style, "")
    if style_mod:
        parts.append(style_mod)

    enhanced = ", ".join(parts)

    return {
        "original": original_prompt,
        "enhanced": enhanced,
        "dimensions": dimensions_used,
        "style_modifier": style_mod,
    }


def _not_redundant(text: str, prompt_lower: str) -> bool:
    """Check if a dimension text would add value (not already present)."""
    # Simple check — if key words from the dimension are already in the prompt, skip
    key_words = [w for w in text.lower().split() if len(w) > 4]
    overlap = sum(1 for w in key_words if w in prompt_lower)
    return overlap < len(key_words) * 0.5


# ============================================================
# Built-in Prompt Templates
# ============================================================

BUILTIN_TEMPLATES = [
    {
        "id": "portrait",
        "title": "Portrait",
        "prompt": "A detailed portrait of a person with natural skin tones, expressive eyes, soft studio lighting, shallow depth of field, sharp focus on face",
        "negative_prompt": "blurry, distorted face, asymmetric features, unnatural skin",
        "style": "photo",
        "tags": ["portrait", "people", "photography"],
    },
    {
        "id": "product",
        "title": "Product Shot",
        "prompt": "Professional product photography of an object on a clean white background, studio lighting, sharp focus, high detail, commercial quality",
        "negative_prompt": "cluttered background, shadows, reflections, low quality",
        "style": "photo",
        "tags": ["product", "commercial", "photography"],
    },
    {
        "id": "landscape",
        "title": "Landscape",
        "prompt": "Breathtaking landscape panorama with dramatic sky, golden hour lighting, vivid colors, high detail, 8K resolution",
        "negative_prompt": "flat lighting, dull colors, blurry, artifacts",
        "style": "photo",
        "tags": ["landscape", "nature", "scenery"],
    },
    {
        "id": "architecture",
        "title": "Architecture",
        "prompt": "Stunning architectural design with clean lines, dramatic perspective, natural lighting, detailed textures, modern or classical style",
        "negative_prompt": "distorted lines, blurry, low detail, noise",
        "style": "3d",
        "tags": ["architecture", "building", "design"],
    },
    {
        "id": "character",
        "title": "Character Design",
        "prompt": "Detailed character design with expressive pose, unique costume, vibrant color palette, full body view, concept art style",
        "negative_prompt": "generic, bland, low detail, distorted anatomy",
        "style": "art",
        "tags": ["character", "concept", "fantasy"],
    },
    {
        "id": "poster",
        "title": "Poster",
        "prompt": "Eye-catching poster design with bold typography, strong visual hierarchy, vibrant colors, professional layout, print quality",
        "negative_prompt": "cluttered, hard to read, low contrast, amateur",
        "style": "art",
        "tags": ["poster", "graphic design", "print"],
    },
    {
        "id": "cinematic",
        "title": "Cinematic",
        "prompt": "Cinematic scene with dramatic lighting, film grain, anamorphic lens flare, color grading, wide aspect ratio, movie still quality",
        "negative_prompt": "flat lighting, no atmosphere, amateur, low quality",
        "style": "photo",
        "tags": ["cinematic", "film", "movie"],
    },
    {
        "id": "fantasy",
        "title": "Fantasy",
        "prompt": "Epic fantasy scene with magical atmosphere, ethereal glow, mystical creatures, enchanted landscape, dramatic clouds, painterly style",
        "negative_prompt": "modern, realistic, mundane, low detail",
        "style": "art",
        "tags": ["fantasy", "magic", "medieval"],
    },
    {
        "id": "sci_fi",
        "title": "Science Fiction",
        "prompt": "Futuristic sci-fi scene with advanced technology, neon lights, holographic displays, cyberpunk atmosphere, detailed mechanical parts",
        "negative_prompt": "primitive, outdated, low tech, blurry",
        "style": "3d",
        "tags": ["sci-fi", "futuristic", "cyberpunk"],
    },
    {
        "id": "thumbnail",
        "title": "Thumbnail",
        "prompt": "Eye-catching thumbnail with bold colors, clear focal point, minimal text area, high contrast, vibrant and attention-grabbing",
        "negative_prompt": "busy, cluttered, low contrast, boring",
        "style": "art",
        "tags": ["thumbnail", "youtube", "social media"],
    },
]
