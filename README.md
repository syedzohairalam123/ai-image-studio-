# AI Image Studio

A production-style AI Image Generator / Creative Studio web application.

## Architecture Overview

```
ai-image-studio/
├── app/
│   ├── __init__.py              # Flask application factory
│   ├── config.py                # Environment-driven configuration
│   ├── extensions.py            # Flask extension instances (db, migrate, login)
│   ├── errors.py                # Centralized error handling
│   ├── logging.py               # Structured request logging
│   ├── utils.py                 # Common utilities
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── user.py
│   │   ├── generation.py
│   │   ├── image.py
│   │   ├── image_version.py     # Edit-history versions per image
│   │   ├── style_preset.py
│   │   ├── collection.py, saved_prompt.py, user_settings.py
│   │   └── audit_log.py, content_report.py
│   ├── routes/                  # API and view routes
│   │   ├── health.py            # Health check endpoint
│   │   ├── api.py               # Core generation/image API endpoints
│   │   ├── views.py             # Server-rendered pages (dashboard, etc.)
│   │   ├── auth.py, admin.py, moderation.py, settings.py, sharing.py
│   │   ├── editor.py            # Local + AI image editing
│   │   ├── advanced_ai.py       # Image-to-image, inpainting, outpainting,
│   │   │                        # style transfer, face enhance, super-res,
│   │   │                        # smart crop, color correction, analyze,
│   │   │                        # variations (10 endpoints)
│   │   ├── utilities.py         # Upscale, background removal, describe
│   │   ├── explore.py, creative.py, analytics.py
│   ├── services/                # Business logic layer
│   │   ├── ai_provider.py       # Abstract AI provider + registry
│   │   ├── storage_service.py   # File storage abstraction
│   │   ├── procedural_art.py    # Local generative art engine (see below)
│   │   ├── advanced_ai_service.py, editor_service.py, utilities_service.py
│   │   ├── generation_service.py, analytics_service.py, sharing_service.py
│   │   ├── explore_service.py, moderation_service.py, admin_service.py
│   │   └── providers/           # pillow_upscale_provider.py, rembg_provider.py
│   ├── static/                  # CSS, JavaScript, images
│   │   ├── css/                 # variables/base/components.css + enhance.css
│   │   ├── js/                  # app.js, editor.js, advanced-ui.js,
│   │   │                        # enhance.js, hero-scene.js
│   │   ├── js/vendor/           # self-hosted three.js + Chart.js
│   │   └── img/categories/      # generated style-preview thumbnails
│   └── templates/               # Jinja2 HTML templates (one per page)
├── migrations/                  # Flask-Migrate / Alembic migrations
├── tests/                       # Pytest test suite (600+ tests)
├── .env.example                 # Environment variable template
├── requirements.txt             # Python dependencies
└── run.py                       # Development server entry point
```

## Tech Stack

| Layer        | Technology                          |
|-------------|-------------------------------------|
| Backend     | Flask 3.1, Python 3.12+             |
| Database    | SQLAlchemy + Flask-Migrate (SQLite dev, PostgreSQL prod) |
| Auth        | Flask-Login (session-based)         |
| Validation  | Marshmallow                         |
| AI Provider | Abstract provider pattern (real AI via Pollinations by default, offline stub fallback, pluggable) |
| Image/CV    | Pillow, numpy, scipy, OpenCV (headless) |
| Background removal | rembg (ONNX), with Pillow-based fallback |
| Frontend 3D/animation | three.js (self-hosted, WebGL hero scene) |
| Frontend charts | Chart.js (self-hosted, real DB-backed dashboard chart) |
| QR codes    | `qrcode` (share-page QR, generated on the fly) |
| Testing     | Pytest, pytest-flask                |

## AI Image Generation: Providers

The app ships with two generation providers and a clean abstraction
(`app/services/ai_provider.py`) for adding more (OpenAI DALL-E, Stability
AI, Replicate, etc. — implement `AIProvider.text_to_image()` and register
it, no other code changes needed).

### `pollinations` (default)

**Real AI image generation** — understands the prompt and renders what it
describes ("a cat" produces an actual cat), via the free, open-source
[Pollinations.ai](https://pollinations.ai) service (Flux models). No
signup or API key required; it works out of the box as long as the
machine running the app has normal internet access.

Style chips in the Create page map to Flux model variants (`photo` →
`flux-realism`, `anime` → `flux-anime`, `3d` → `flux-3d`, `pixel` →
`turbo`, etc.), and negative prompts / seeds are passed straight through.

**Resilient by design**: if the request fails for any reason (offline
machine, the service being briefly down, a strict firewall), that specific
image automatically falls back to the local procedural engine below
instead of the whole generation failing — check an image's metadata
(`engine: "pollinations"` vs `"procedural_fallback"`) to see which path
produced it.

Want a paid provider instead (typically higher quality/reliability)? Set
`AI_PROVIDER` in `.env` to that provider's name and `AI_API_KEY` to its key
— the same abstraction handles OpenAI/Stability/Replicate-style providers
once implemented.

### `stub` (fully offline fallback)

Set `AI_PROVIDER=stub` in `.env` to disable the internet-dependent
provider entirely (e.g. for offline development). `app/services/
procedural_art.py` is a small local generative-art engine built on numpy/
scipy/Pillow: domain-warped fractal noise, true Voronoi mosaics via
`scipy.spatial.cKDTree`, metaball fields, and a mini Lambertian/specular
lighting model for the "3d" style, with a colour palette derived from
colour-theory rules and keywords in the prompt. Results are deterministic
per `(prompt, style, seed)`. **It has no semantic understanding of the
prompt** — it produces real but abstract generative art, not recognizable
objects or scenes; it's a graphics algorithm, not a trained image model.
This same engine renders the style category preview thumbnails on the
Styles/homepage.

### Advanced AI operations

`/api/v1/advanced/*` (image-to-image, inpainting, outpainting, style
transfer, face enhancement, super-resolution, smart crop, color
correction, content analysis, variations) use classic, real computer-vision
techniques — OpenCV Telea inpainting, gray-world white balance,
Haar-cascade face detection, edge-density-based saliency for smart crop —
rather than no-ops.

## Local Setup

### 1. Clone & install

```bash
git clone <repo-url>
cd ai-image-studio
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your settings (at minimum, set SECRET_KEY)
```

### 3. Initialize database

Fresh install (creates every table, including the current schema):

```bash
python -c "from app import create_app; from app.extensions import db; app = create_app(); app.app_context().push(); db.create_all(); print('Database created')"
```

Existing install (applies migrations, e.g. the `format` column added to
`images`):

```bash
export FLASK_APP=run.py
flask db upgrade
```

### 4. Run development server

```bash
python run.py
```

The app runs at `http://localhost:5000`.

### 5. Run tests

```bash
python -m pytest tests/ -v
```

## Environment Variables

| Variable            | Default                    | Description                     |
|--------------------|-----------------------------|---------------------------------|
| `SECRET_KEY`       | `dev-secret-key...`         | Flask secret key (change in prod)|
| `DATABASE_URL`     | `sqlite:///ai_studio.db`    | Database connection string      |
| `AI_PROVIDER`      | `pollinations`               | Active AI provider name (`stub` for fully offline) |
| `AI_API_KEY`       |                             | API key for the AI provider     |
| `MAX_CONTENT_LENGTH` | `10485760` (10MB)         | Max upload size in bytes        |
| `UPLOAD_FOLDER`    | `uploads`                   | File upload directory           |
| `LOG_LEVEL`        | `INFO`                      | Logging level                   |
| `FLASK_ENV`        | `development`               | `development`/`testing`/`production` |

## API Endpoints

The table below is a starting map, not exhaustive — see `app/routes/` for
the full set (each file is one blueprint, one feature area).

| Method | Path                              | Description                          |
|--------|------------------------------------|---------------------------------------|
| GET    | `/api/v1/health`                  | Health check                          |
| GET    | `/api/v1/status`                  | API status & providers                |
| POST   | `/api/v1/generate`                | Text-to-image generation              |
| GET    | `/api/v1/images/<id>/thumbnail`   | Serve an image thumbnail              |
| POST   | `/api/v1/editor/local`            | Local edit (crop/filters/adjustments) |
| POST   | `/api/v1/editor/ai-edit`          | AI edit (inpaint/outpaint/retexture)  |
| POST   | `/api/v1/advanced/image-to-image` | Prompt-guided image transformation    |
| POST   | `/api/v1/advanced/inpainting`     | Mask-based inpainting (OpenCV Telea)  |
| POST   | `/api/v1/advanced/outpainting`    | Canvas extension                      |
| POST   | `/api/v1/advanced/style-transfer` | Apply a style preset or reference     |
| POST   | `/api/v1/advanced/face-enhance`   | Face-region enhancement               |
| POST   | `/api/v1/advanced/super-resolution` | 2x/4x upscale                       |
| POST   | `/api/v1/advanced/smart-crop`     | Saliency/face-aware crop              |
| POST   | `/api/v1/advanced/color-correction` | Auto/warm/cool/vivid/muted grading  |
| POST   | `/api/v1/advanced/analyze`        | Real pixel analysis (colors, mood, faces) |
| POST   | `/api/v1/advanced/variations`     | Generate N variations of an image     |
| GET    | `/api/v1/advanced/capabilities`   | Active provider + supported ops       |
| GET    | `/share/<token>`                  | Public share page                     |
| GET    | `/share/<token>/qrcode.png`       | QR code for the share page            |

## Feature Overview

Auth & account · Dashboard with a real 14-day activity chart · Text-to-image
generation · Image editor (14+ local filters, AI-assisted edits, version
history) · Gallery, History, Favorites, Collections · Saved Prompts library ·
Explore (community feed by style category) · Style presets with generated
preview art · Utilities (upscale, background removal, color correction,
image description) · Sharing (public links, QR codes, privacy controls) ·
Admin & moderation tools · Settings.

## Recent Enhancements

- **Real AI image generation** (`pollinations` provider, now the default) —
  the app generates what the prompt actually describes ("a cat" → an actual
  cat) via the free Pollinations.ai service, with automatic graceful
  fallback to the local procedural engine per-image if the network call
  fails. Fully mocked test coverage in `tests/test_pollinations_provider.py`
  since a test suite shouldn't depend on a third-party service being up.
- **Fixed a critical provider-wiring bug**: `/api/v1/generate` ignored the
  app's configured `AI_PROVIDER` entirely and always used a hardcoded
  `"stub"` default — meaning changing the provider in `.env` silently had
  no effect on the main generation endpoint (it worked for the Advanced AI
  endpoints, just not this one). Now resolves from app config as expected.
- **Editor: upload your own image** — there was no way to bring a personal
  photo into the editor; added an always-visible Upload button (toolbar +
  empty state) wired to the existing (already-secure) upload endpoint.
- **Fixed a text-overflow bug** in the dashboard's prompt suggestions
  (long text was being forced onto one line by the shared `.btn` style)
  and gave that section a proper redesign with working "click to use"
  behavior.
- **Replaced 8 emoji placeholder icons** on the homepage's style-example
  grid with real generated preview images.
- **Fixed 10 previously-crashing "Advanced AI" endpoints** — a provider
  initialization bug and a storage/model field mismatch meant every call to
  `/api/v1/advanced/*` returned a 500. Both are fixed and now have full test
  coverage (`tests/test_advanced_ai.py`), which didn't exist before.
- **Fixed a real/optional-provider registration deadlock** that silently
  disabled the Pillow upscale and rembg background-removal providers on
  every startup while adding a flat 16s delay. Both providers now register
  correctly in ~2–3s.
- **Real procedural art engine** (`procedural_art.py`) replacing the flat
  placeholder gradient the stub provider used to return.
- **14 new local editor filters**: blur, sharpen, grayscale, sepia, invert,
  vignette, duotone, edge detection, pixelate, posterize, warmth, gamma,
  vibrance, denoise — alongside the original crop/resize/rotate/flip/
  brightness/contrast/saturation.
- **Real pixel analysis** for inpainting (mask-aware OpenCV Telea instead of
  a whole-image blur), outpainting (reflect-pad + inpaint blend instead of a
  solid white fill), color analysis (k-means dominant colors, colourfulness,
  mood), smart crop (face detection + edge-density saliency instead of a
  plain center crop), and image description (previously ignored the image's
  actual pixels entirely).
- **3D/animated UI layer** (`enhance.css`, `enhance.js`, `hero-scene.js`): a
  WebGL ambient hero background, real 3D tilt-on-hover cards, scroll-reveal
  animations, a Cmd/Ctrl+K command palette, and per-user avatar gradients —
  all self-hosted (three.js, Chart.js vendored locally) to respect the
  existing strict Content-Security-Policy.
- **Real dashboard activity chart** (Chart.js, backed by actual per-day
  generation counts) and **real image thumbnails** in the recent-generations
  grid, replacing a static emoji placeholder.
- **QR codes for share links** — new feature end-to-end (service, route,
  template, tests).
- **Fixed a test-suite isolation bug** where a shared rate-limiter state
  caused ~70 unrelated tests to fail with cascading 429s.
- Fully additive: nothing existing was removed — every change either fixed
  a crash/bug or extended existing functionality.

## AI Provider System

Providers are pluggable via the abstract `AIProvider` class — see "AI Image
Generation: Providers" above for the full picture (`pollinations` real AI
by default, `stub` as a fully-offline fallback).

```python
from app.services.ai_provider import get_provider

provider = get_provider("pollinations")  # or "stub" for fully offline
result = provider.text_to_image("a sunset over the ocean")
```

## License

MIT
