import os
import sys

# Ensure the project root is on sys.path so that `import app` resolves
# correctly when Vercel builds the serverless function.
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Force production settings on Vercel
os.environ.setdefault("FLASK_ENV", "production")

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
