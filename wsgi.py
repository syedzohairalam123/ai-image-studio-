"""Vercel auto-detects this file as a Python entrypoint (wsgi.py).

Vercel's Python framework preset looks for wsgi.py at the project root,
detects Flask from requirements.txt, and exposes the top-level `app`
variable as a WSGI serverless function.  No `builds` or `rewrites` in
vercel.json are needed — Vercel handles routing automatically.
"""

import os
import sys

# Ensure the project root is on sys.path so that `import app` resolves
# correctly when Vercel builds the serverless function.
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Force production settings on Vercel
os.environ.setdefault("FLASK_ENV", "production")

try:
    from app import create_app
    app = create_app()
except Exception as e:
    # If app creation fails, return a diagnostic JSON response instead of
    # a bare 500 so the developer can see what went wrong in the browser.
    from flask import Flask, jsonify
    app = Flask(__name__)

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def catch_all(path):
        return jsonify({
            "error": "Application initialization failed",
            "details": str(e),
            "hint": "Check Vercel → Functions → Logs for the full traceback",
        }), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
