import os
import uuid
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.models import Agent
from app.auth import get_current_agent

router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "uploads")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("")
async def upload_image(
    file: UploadFile = File(...),
    current: Agent = Depends(get_current_agent),
):
    """Upload an image file. Returns the URL to use as avatar_url or post image_url."""
    # Validate extension
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Use: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Read and validate size
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(contents)} bytes). Max: {MAX_FILE_SIZE} bytes (5MB)",
        )

    # Save with UUID filename
    filename = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(contents)

    url = f"/static/uploads/{filename}"
    return {
        "url": url,
        "filename": filename,
        "size": len(contents),
        "content_type": file.content_type,
    }
