"""Vercel Serverless Function entry point.

Vercel's Python runtime looks for an `app` variable (WSGI/ASGI application)
or a handler function in `api/index.py`.  We expose the Flask WSGI app
directly so that Vercel can proxy every incoming request through it.
"""

import os
import sys

# Ensure the project root is on sys.path so that `import app` resolves
# correctly when Vercel builds the serverless function.
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Force production settings on Vercel
os.environ.setdefault("FLASK_ENV", "production")

try:
    from app import create_app
    app = create_app()
except Exception as e:
    # If app creation fails, create a minimal app that returns error info
    # This prevents 404s when the app fails to initialize
    from flask import Flask, jsonify
    app = Flask(__name__)
    
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def catch_all(path):
        return jsonify({
            "error": "Application initialization failed",
            "details": str(e),
            "hint": "Check Vercel function logs for more details"
        }), 500

# Vercel also supports a handler(request, response) pattern, but exposing
# `app` as a module-level WSGI application is the simplest and most
# reliable approach for Flask.
