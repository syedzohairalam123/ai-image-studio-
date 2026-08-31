import os
import re
import uuid
from pathlib import Path

from werkzeug.utils import secure_filename

from app.utils import generate_filename


class StorageService:
    """Handles file storage on local filesystem with security hardening."""

    def __init__(self, upload_folder: str):
        self.upload_folder = Path(upload_folder)
        self.upload_folder.mkdir(parents=True, exist_ok=True)

    def _validate_path(self, file_path: Path) -> None:
        """Ensure the resolved path stays within the upload folder.

        Raises ValueError on path traversal attempts.
        """
        try:
            resolved = file_path.resolve()
            upload_root = self.upload_folder.resolve()
            if not resolved.is_relative_to(upload_root):
                raise ValueError(f"Path traversal blocked: {file_path}")
        except (ValueError, OSError) as e:
            if "traversal" in str(e):
                raise
            raise ValueError(f"Invalid file path: {file_path}")

    def save_file(self, file_storage, subfolder="", prefix="") -> dict:
        """Save an uploaded file and return metadata.

        SECURITY: Never trusts the original filename.
        Always generates a safe UUID-based filename.
        """
        if not file_storage or not file_storage.filename:
            raise ValueError("No file provided")

        filename = generate_filename(file_storage.filename, prefix=prefix)
        target_dir = self.upload_folder / subfolder if subfolder else self.upload_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / filename

        # Path traversal check
        self._validate_path(file_path)

        file_storage.save(str(file_path))
        file_size = file_path.stat().st_size

        return {
            "filename": filename,
            "file_path": str(file_path),
            "relative_path": str(file_path.relative_to(self.upload_folder)),
            "file_size": file_size,
        }

    def save_bytes(self, data: bytes, filename: str, subfolder="") -> dict:
        """Save raw bytes to a file.

        SECURITY: Generates a safe filename, never uses input directly.
        """
        safe_name = generate_filename(filename)
        target_dir = self.upload_folder / subfolder if subfolder else self.upload_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / safe_name

        # Path traversal check
        self._validate_path(file_path)

        file_path.write_bytes(data)
        return {
            "filename": safe_name,
            "file_path": str(file_path),
            "relative_path": str(file_path.relative_to(self.upload_folder)),
            "file_size": len(data),
        }

    def delete_file(self, file_path: str) -> bool:
        """Delete a file. Returns True if deleted.

        SECURITY: Validates path before deletion.
        """
        path = Path(file_path)
        self._validate_path(path)
        if path.exists() and path.is_file():
            path.unlink()
            return True
        return False

    def file_exists(self, file_path: str) -> bool:
        """Check if a file exists.

        SECURITY: Validates path before checking.
        """
        path = Path(file_path)
        try:
            self._validate_path(path)
        except ValueError:
            return False
        return path.exists()
