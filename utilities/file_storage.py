import uuid
from pathlib import Path

from fastapi import UploadFile

BASE_STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage"


def save_upload_file(upload_file: UploadFile, subdir: str) -> tuple[str, str]:
    """
    Saves an UploadFile to storage/<subdir>/ under a random file name and
    returns (stored_file_path, extension). extension is returned without
    the leading dot.
    """
    extension = Path(upload_file.filename or "").suffix.lstrip(".").lower()
    stored_name = f"{uuid.uuid4().hex}.{extension}" if extension else uuid.uuid4().hex

    target_dir = BASE_STORAGE_DIR / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / stored_name
    with target_path.open("wb") as out_file:
        while chunk := upload_file.file.read(1024 * 1024):
            out_file.write(chunk)

    return str(target_path), extension


def delete_file(file_path: str) -> None:
    path = Path(file_path)
    if path.exists():
        path.unlink()
