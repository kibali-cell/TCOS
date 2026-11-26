"""Private document storage: upload checks, storage, download and archive.

Rules (CLAUDE.md rule 7, SCHEMA "document"):
* Files live under ``TCOS_PRIVATE_STORAGE_ROOT``, never under a static or public path, in
  names made of random characters. The name the person gave is kept only as display text.
* The type is decided by the file's extension AND its first bytes; what the browser claims is
  ignored. Only the configured types are accepted, up to the configured size.
* A SHA-256 is recorded at upload and checked at every download.
* Who may see or add a file is decided by the record it is attached to (a "parent policy"
  registered by that module), never by the file.
* Upload, download, archive and refusals are audited.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import secrets
import zipfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.exceptions import ValidationError as ApiValidationError

from apps.audit import events as audit_events
from apps.audit.service import record as audit

from . import scanning
from .models import Document

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain",
}
MAX_ZIP_ENTRIES = 2000
MAX_ZIP_UNCOMPRESSED = 200 * 1024 * 1024
CHUNK = 64 * 1024


@dataclass
class ParentPolicy:
    """What a module says about files attached to its records."""

    can_view: callable  # (user, parent_id) -> bool
    can_attach: callable  # (user, parent_id) -> bool
    can_archive: callable  # (user, document) -> bool
    classifications: tuple = ("NORMAL", "CONFIDENTIAL")
    default_classification: str = "CONFIDENTIAL"
    max_files: int = 10


PARENTS: dict[str, ParentPolicy] = {}


def register_parent(parent_type: str, policy: ParentPolicy) -> None:
    PARENTS[parent_type] = policy


def _policy(parent_type: str) -> ParentPolicy:
    policy = PARENTS.get(parent_type or "")
    if policy is None:
        raise NotFound()
    return policy


# --- Storage ------------------------------------------------------------------------------


def storage_root() -> Path:
    root = Path(settings.TCOS_PRIVATE_STORAGE_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _path_for(key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        raise ValueError("Bad storage key.")
    root = storage_root()
    path = (root / key[:2] / key[2:4] / key).resolve()
    if root not in path.parents:  # belt and braces: the key can only be hex, but check anyway
        raise ValueError("Path escapes storage.")
    return path


def display_name(raw: str) -> str:
    """A safe name to show and to offer on download. Never used to build a path."""
    name = (raw or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return name[:200]


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


# --- Content checks --------------------------------------------------------------------------


def _check_content(ext: str, head: bytes, data: bytes | None, path: Path) -> None:
    if ext == "pdf" and not head.startswith(b"%PDF-"):
        raise ValueError("pdf")
    if ext == "png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("png")
    if ext in ("jpg", "jpeg") and not head.startswith(b"\xff\xd8\xff"):
        raise ValueError("jpeg")
    if ext in ("docx", "xlsx"):
        if not head.startswith(b"PK\x03\x04"):
            raise ValueError("office")
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                names = {i.filename for i in infos}
                if (
                    len(infos) > MAX_ZIP_ENTRIES
                    or sum(i.file_size for i in infos) > MAX_ZIP_UNCOMPRESSED
                ):
                    raise ValueError("zip too large")
                folder = "word/" if ext == "docx" else "xl/"
                if "[Content_Types].xml" not in names or not any(
                    n.startswith(folder) for n in names
                ):
                    raise ValueError("not an office file")
        except zipfile.BadZipFile as exc:
            raise ValueError("bad zip") from exc
    if ext == "txt":
        with open(path, "rb") as handle:
            body = handle.read()
        if b"\x00" in body:
            raise ValueError("binary")
        try:
            body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("encoding") from exc


def _refuse(user, parent_type, parent_id, name, why: str, message: str):
    audit(
        audit_events.DOCUMENT_REFUSED,
        actor=user,
        success=False,
        object_type=parent_type,
        object_id=parent_id,
        metadata={"name": name[:100], "why": why},
    )
    raise ApiValidationError({"file": [message]})


# --- Upload -------------------------------------------------------------------------------------


def upload(user, parent_type: str, parent_id, uploaded_file, classification: str = "") -> Document:
    policy = _policy(parent_type)
    if not policy.can_view(user, parent_id):
        raise NotFound()  # cannot see the record, so it does not exist for them
    if not policy.can_attach(user, parent_id):
        raise PermissionDenied("You cannot add files to this record.", "cannot_attach")
    classification = classification or policy.default_classification
    if classification not in policy.classifications:
        raise ApiValidationError({"classification": ["This classification is not allowed here."]})
    if (
        Document.objects.filter(
            parent_type=parent_type, parent_id=parent_id, is_archived=False
        ).count()
        >= policy.max_files
    ):
        raise ApiValidationError({"file": [f"At most {policy.max_files} files can be attached."]})

    name = display_name(getattr(uploaded_file, "name", ""))
    ext = _extension(name)
    allowed = [t.lower() for t in settings.TCOS_UPLOAD_ALLOWED_TYPES]
    if not name or ext not in allowed or ext not in CONTENT_TYPES:
        _refuse(
            user,
            parent_type,
            parent_id,
            name or "(none)",
            "type",
            f"This file type is not allowed. Allowed: {', '.join(sorted(allowed))}.",
        )
    limit = settings.TCOS_UPLOAD_MAX_BYTES
    if uploaded_file.size > limit:
        _refuse(
            user,
            parent_type,
            parent_id,
            name,
            "size",
            f"The file is too large (the limit is {limit // (1024 * 1024)} MB).",
        )
    if uploaded_file.size == 0:
        _refuse(user, parent_type, parent_id, name, "empty", "The file is empty.")

    key = secrets.token_hex(16)
    final = _path_for(key)
    final.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = final.with_suffix(".part")
    digest = hashlib.sha256()
    size = 0
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        with os.fdopen(os.open(temp, flags, 0o600), "wb") as out:
            for chunk in uploaded_file.chunks(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise OverflowError
                digest.update(chunk)
                out.write(chunk)
        try:
            with open(temp, "rb") as handle:
                _check_content(ext, handle.read(16), None, temp)
        except ValueError:
            _refuse(
                user,
                parent_type,
                parent_id,
                name,
                "content",
                "The file's contents do not match its type, so it was not accepted.",
            )
        try:
            scan = scanning.scan_file(temp)
        except scanning.ScannerError:
            scan = "ERROR"
        if scan == scanning.INFECTED:
            _refuse(
                user,
                parent_type,
                parent_id,
                name,
                "infected",
                "The file was rejected by the virus scanner.",
            )
        if settings.TCOS_REQUIRE_VIRUS_SCAN and scan != scanning.CLEAN:
            _refuse(
                user,
                parent_type,
                parent_id,
                name,
                "scan_unavailable",
                "Files cannot be accepted right now because virus scanning is not available.",
            )
        os.replace(temp, final)
    except OverflowError:
        _remove(temp)
        _refuse(user, parent_type, parent_id, name, "size", "The file is too large.")
    except BaseException:
        _remove(temp)
        raise

    try:
        with transaction.atomic():
            document = Document.objects.create(
                parent_type=parent_type,
                parent_id=parent_id,
                original_name=name,
                content_type=CONTENT_TYPES[ext],
                size_bytes=size,
                sha256=digest.hexdigest(),
                storage_key=key,
                classification=classification,
                scan_status=scan if scan in ("CLEAN", "NOT_SCANNED") else "NOT_SCANNED",
                uploaded_by=user,
            )
            audit(
                audit_events.DOCUMENT_UPLOADED,
                actor=user,
                object_type="core.Document",
                object_id=document.pk,
                metadata={
                    "parent_type": parent_type,
                    "parent_id": str(parent_id),
                    "name": name,
                    "size": size,
                    "sha256": document.sha256,
                    "classification": classification,
                    "scan": document.scan_status,
                },
            )
    except BaseException:
        _remove(final)
        raise
    return document


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


# --- Read, download, archive ---------------------------------------------------------------


def list_for(user, parent_type: str, parent_id) -> list[Document]:
    policy = _policy(parent_type)
    if not policy.can_view(user, parent_id):
        raise NotFound()
    return list(
        Document.objects.filter(
            parent_type=parent_type, parent_id=parent_id, is_archived=False
        ).select_related("uploaded_by")
    )


def get_for_download(user, document_id) -> tuple[Document, io.BufferedReader]:
    """Open a file for a person allowed to see its record. Checks integrity first."""
    document = Document.objects.filter(pk=document_id, is_archived=False).first()
    if document is None:
        raise NotFound()
    policy = PARENTS.get(document.parent_type)
    if policy is None or not policy.can_view(user, document.parent_id):
        raise NotFound()
    path = _path_for(document.storage_key)
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            while chunk := handle.read(CHUNK):
                digest.update(chunk)
    except OSError as exc:
        raise NotFound() from exc
    if digest.hexdigest() != document.sha256:
        audit(
            audit_events.DOCUMENT_DOWNLOADED,
            actor=user,
            success=False,
            object_type="core.Document",
            object_id=document.pk,
            metadata={"why": "checksum mismatch"},
        )
        raise ApiValidationError({"detail": ["This file is damaged and cannot be downloaded."]})
    audit(
        audit_events.DOCUMENT_DOWNLOADED,
        actor=user,
        object_type="core.Document",
        object_id=document.pk,
        metadata={
            "parent_type": document.parent_type,
            "parent_id": str(document.parent_id),
            "classification": document.classification,
        },
    )
    return document, open(path, "rb")  # noqa: SIM115 - closed by the response


@transaction.atomic
def archive(user, document_id) -> Document:
    document = (
        Document.objects.select_for_update().filter(pk=document_id, is_archived=False).first()
    )
    if document is None:
        raise NotFound()
    policy = PARENTS.get(document.parent_type)
    if policy is None or not policy.can_view(user, document.parent_id):
        raise NotFound()
    if not policy.can_archive(user, document):
        raise PermissionDenied("You cannot remove this file.", "cannot_archive")
    document.is_archived = True
    document.archived_at = timezone.now()
    document.archived_by = user
    document.version += 1
    document.save(update_fields=["is_archived", "archived_at", "archived_by", "version"])
    audit(
        audit_events.DOCUMENT_ARCHIVED,
        actor=user,
        object_type="core.Document",
        object_id=document.pk,
        metadata={"name": document.original_name, "sha256": document.sha256},
    )
    return document


def payload(document: Document, user=None) -> dict:
    policy = PARENTS.get(document.parent_type)
    return {
        "id": str(document.pk),
        "name": document.original_name,
        "content_type": document.content_type,
        "size_bytes": document.size_bytes,
        "classification": document.classification,
        "scan_status": document.scan_status,
        "uploaded_by": document.uploaded_by.full_name if document.uploaded_by_id else None,
        "uploaded_at": document.uploaded_at,
        "can_archive": bool(user and policy and policy.can_archive(user, document)),
    }
