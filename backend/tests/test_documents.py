"""Document uploads: private storage, permission-checked downloads, type/size checks."""

import hashlib
import io
import os
import uuid
import zipfile
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.approvals import services
from apps.audit import events
from apps.audit.models import AuditEvent
from apps.core import documents
from apps.core.models import Document
from tests.approvals_helpers import chain, new_department
from tests.conftest import csrf_token, post

pytestmark = pytest.mark.django_db

PARENT = "approvals.ApprovalRequest"
DOCS = "/api/v1/documents/"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


def docx_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w/>")
    return buffer.getvalue()


def upload(client, parent_id, name="invoice.pdf", content=PDF, **extra):
    data = {
        "parent_type": PARENT,
        "parent_id": str(parent_id),
        "file": SimpleUploadedFile(name, content),
        **extra,
    }
    return client.post(DOCS, data, format="multipart", HTTP_X_CSRFTOKEN=csrf_token(client))


def listing(client, parent_id):
    return client.get(DOCS, {"parent_type": PARENT, "parent_id": str(parent_id)})


@pytest.fixture
def world(staff):
    dept = new_department()
    requester, rc = staff("SOCIAL_WELFARE_OFFICER", department=dept, username="rita")
    head, hc = staff("FINANCE_OFFICER", department=dept, username="harry")
    dept.head = head
    dept.save()
    chain(dept, ("DEPARTMENT_HEAD",))
    other_dept = new_department("STO-X", "Stores X")
    outsider, oc = staff("STOREKEEPER", department=other_dept, username="olga")
    row, _ = services.create_draft(
        requester, {"title": "Books", "description": "t", "amount_tzs": 1000}
    )
    return {
        "requester": requester,
        "rc": rc,
        "head": head,
        "hc": hc,
        "outsider": outsider,
        "oc": oc,
        "request": row,
    }


def stored_files():
    root = Path(documents.storage_root())
    return [p for p in root.rglob("*") if p.is_file()]


# --- Happy path ------------------------------


def test_requester_attaches_a_file_and_it_is_stored_privately(world, settings):
    response = upload(world["rc"], world["request"].pk)
    assert response.status_code == 201, response.content
    data = response.json()
    assert data["name"] == "invoice.pdf" and data["classification"] == "CONFIDENTIAL"
    assert "storage_key" not in data and "sha256" not in data
    row = Document.objects.get()
    assert row.sha256 == hashlib.sha256(PDF).hexdigest()
    assert row.size_bytes == len(PDF)
    on_disk = Path(documents._path_for(row.storage_key))
    assert on_disk.read_bytes() == PDF
    assert on_disk.name == row.storage_key and "invoice" not in str(on_disk)
    # Outside anything the web server serves.
    root = Path(settings.TCOS_PRIVATE_STORAGE_ROOT).resolve()
    assert root not in Path(settings.STATIC_ROOT or "/nonexistent").resolve().parents
    assert not str(root).startswith(str(Path(settings.BASE_DIR / "static")))
    assert oct(on_disk.stat().st_mode & 0o777) == "0o600"
    event = AuditEvent.objects.get(event_type=events.DOCUMENT_UPLOADED)
    assert event.actor_id == world["requester"].pk
    assert event.metadata["sha256"] == row.sha256
    assert row.storage_key not in str(event.metadata) + str(event.changes)


def test_download_returns_the_exact_bytes_with_safe_headers_and_is_audited(world):
    doc_id = upload(world["rc"], world["request"].pk).json()["id"]
    response = world["rc"].get(f"{DOCS}{doc_id}/download/")
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == PDF
    assert "attachment" in response["Content-Disposition"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response["Cache-Control"]
    assert AuditEvent.objects.filter(event_type=events.DOCUMENT_DOWNLOADED).count() == 1


def test_attachments_appear_in_the_request_detail_for_those_who_can_see_it(world):
    upload(world["rc"], world["request"].pk)
    detail = world["rc"].get(f"/api/v1/approvals/requests/{world['request'].pk}/").json()
    assert [a["name"] for a in detail["attachments"]] == ["invoice.pdf"]
    assert detail["attachments"][0]["can_archive"] is True


def test_listing_and_each_download_follow_the_request_visibility(world):
    doc_id = upload(world["rc"], world["request"].pk).json()["id"]
    # A draft is private to its requester: the head cannot see it, so neither its files.
    assert listing(world["hc"], world["request"].pk).status_code == 404
    assert world["hc"].get(f"{DOCS}{doc_id}/download/").status_code == 404
    services.submit(world["requester"], world["request"].pk)
    assert listing(world["hc"], world["request"].pk).status_code == 200
    assert world["hc"].get(f"{DOCS}{doc_id}/download/").status_code == 200


# --- Who may not ------------------------------


def test_anonymous_and_outsiders_get_nothing(world, new_client):
    doc_id = upload(world["rc"], world["request"].pk).json()["id"]
    anon = new_client()
    assert anon.get(f"{DOCS}{doc_id}/download/").status_code in (401, 403)
    assert listing(anon, world["request"].pk).status_code in (401, 403)
    assert upload(anon, world["request"].pk).status_code in (401, 403)
    # Signed in but without access to the record: indistinguishable from "does not exist".
    gone = world["oc"].get(f"{DOCS}{doc_id}/download/")
    missing = world["oc"].get(f"{DOCS}{uuid.uuid4()}/download/")
    assert gone.status_code == missing.status_code == 404
    assert gone.json() == missing.json()
    assert listing(world["oc"], world["request"].pk).status_code == 404
    assert upload(world["oc"], world["request"].pk).status_code == 404
    assert AuditEvent.objects.filter(event_type=events.DOCUMENT_DOWNLOADED).count() == 0


def test_only_the_requester_may_attach_and_only_while_the_request_is_open(world):
    services.submit(world["requester"], world["request"].pk)
    assert upload(world["hc"], world["request"].pk).status_code == 403  # can see, cannot add
    assert upload(world["rc"], world["request"].pk).status_code == 201  # still open


def test_cannot_attach_to_a_closed_request(world):
    services.submit(world["requester"], world["request"].pk)
    services.cancel(world["requester"], world["request"].pk, "changed my mind")
    assert upload(world["rc"], world["request"].pk).status_code == 403


def test_a_blocked_account_cannot_use_documents(world):
    from apps.accounts.models import User

    User.objects.filter(pk=world["requester"].pk).update(must_change_password=True)
    assert upload(world["rc"], world["request"].pk).status_code == 403


# --- Type, size, content ------------------------------


@pytest.mark.parametrize(
    "name",
    ["run.exe", "page.html", "script.js", "noextension", "archive.zip", "shell.php", "x.svg"],
)
def test_disallowed_types_are_refused_and_nothing_is_stored(world, name):
    response = upload(world["rc"], world["request"].pk, name=name, content=b"data")
    assert response.status_code == 400
    assert not Document.objects.exists() and stored_files() == []
    assert AuditEvent.objects.filter(event_type=events.DOCUMENT_REFUSED).count() == 1


def test_double_extension_and_case_tricks(world):
    assert (
        upload(world["rc"], world["request"].pk, name="evil.pdf.exe", content=PDF).status_code
        == 400
    )
    assert (
        upload(world["rc"], world["request"].pk, name="REPORT.PDF", content=PDF).status_code == 201
    )


def test_content_must_match_the_type(world):
    # An executable renamed to .pdf, a PNG called .jpg, a non-zip called .docx.
    assert (
        upload(world["rc"], world["request"].pk, "a.pdf", b"MZ\x90\x00 fake exe").status_code == 400
    )
    assert upload(world["rc"], world["request"].pk, "a.jpg", PNG).status_code == 400
    assert upload(world["rc"], world["request"].pk, "a.docx", b"not a zip").status_code == 400
    assert upload(world["rc"], world["request"].pk, "a.docx", docx_bytes()).status_code == 201
    assert upload(world["rc"], world["request"].pk, "a.png", PNG).status_code == 201
    assert upload(world["rc"], world["request"].pk, "a.txt", "héllo".encode()).status_code == 201
    assert upload(world["rc"], world["request"].pk, "b.txt", b"bin\x00ary").status_code == 400
    assert len(stored_files()) == Document.objects.count() == 3


def test_the_browser_declared_type_is_ignored(world):
    data = {
        "parent_type": PARENT,
        "parent_id": str(world["request"].pk),
        "file": SimpleUploadedFile("a.pdf", b"<html>x</html>", content_type="application/pdf"),
    }
    client = world["rc"]
    response = client.post(DOCS, data, format="multipart", HTTP_X_CSRFTOKEN=csrf_token(client))
    assert response.status_code == 400


def test_size_limit_is_enforced_and_configurable(world, settings):
    settings.TCOS_UPLOAD_MAX_BYTES = 100
    big = PDF + b"x" * 200
    assert upload(world["rc"], world["request"].pk, content=big).status_code == 400
    assert stored_files() == []
    settings.TCOS_UPLOAD_MAX_BYTES = 10_000
    assert upload(world["rc"], world["request"].pk, content=big).status_code == 201


def test_empty_files_and_too_many_files_are_refused(world, monkeypatch):
    assert upload(world["rc"], world["request"].pk, content=b"").status_code == 400
    monkeypatch.setitem(documents.PARENTS, PARENT, _with_max(documents.PARENTS[PARENT], 2))
    assert upload(world["rc"], world["request"].pk).status_code == 201
    assert upload(world["rc"], world["request"].pk, "b.pdf").status_code == 201
    assert upload(world["rc"], world["request"].pk, "c.pdf").status_code == 400


def _with_max(policy, number):
    import dataclasses

    return dataclasses.replace(policy, max_files=number)


def test_allowed_types_are_configurable(world, settings):
    settings.TCOS_UPLOAD_ALLOWED_TYPES = ["png"]
    assert upload(world["rc"], world["request"].pk).status_code == 400
    assert upload(world["rc"], world["request"].pk, "a.png", PNG).status_code == 201


def test_classification_is_checked(world):
    ok = upload(world["rc"], world["request"].pk, classification="NORMAL")
    assert ok.json()["classification"] == "NORMAL"
    bad = upload(world["rc"], world["request"].pk, "b.pdf", classification="CHILD_SENSITIVE")
    assert bad.status_code == 400  # not allowed on approval requests
    assert (
        upload(world["rc"], world["request"].pk, "c.pdf", classification="SECRET").status_code
        == 400
    )


# --- Names, paths, URL guessing ------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd.pdf",
        "..\\..\\windows\\evil.pdf",
        "/etc/cron.d/x.pdf",
        "a/b/c.pdf",
        "x\x00.pdf",
    ],
)
def test_path_traversal_in_the_name_changes_nothing_on_disk(world, name):
    response = upload(world["rc"], world["request"].pk, name=name)
    if response.status_code == 201:
        row = Document.objects.get()
        assert "/" not in row.original_name and "\\" not in row.original_name
        path = documents._path_for(row.storage_key)
        assert Path(documents.storage_root()) in path.parents
        assert row.storage_key.isalnum() and len(row.storage_key) == 32
    else:
        assert stored_files() == []
    assert not Path("/etc/cron.d/x.pdf").exists()


def test_storage_paths_cannot_be_built_from_anything_but_a_random_key():
    for bad in ["../x", "a" * 31, "A" * 32, "../" + "a" * 29, "g" * 32, ""]:
        with pytest.raises(ValueError):
            documents._path_for(bad)


def test_keys_are_random_and_not_guessable(world):
    keys = set()
    for i in range(5):
        upload(world["rc"], world["request"].pk, f"f{i}.pdf")
    keys = set(Document.objects.values_list("storage_key", flat=True))
    assert len(keys) == 5
    assert all(len(k) == 32 for k in keys)


def test_urls_cannot_be_guessed_or_reached_around_the_api(world, client):
    doc_id = upload(world["rc"], world["request"].pk).json()["id"]
    key = Document.objects.get().storage_key
    for path in [
        f"/media/{key}",
        f"/static/{key}",
        f"/private_files/{key[:2]}/{key[2:4]}/{key}",
        f"/api/v1/documents/{key}/download/",
        f"/api/v1/documents/{doc_id}/",
        f"/api/v1/documents/../{doc_id}/download/",
    ]:
        assert client.get(path).status_code in (301, 404, 405, 403), path
    # Sequential ids do not exist: ids are random UUIDs.
    for guess in (1, 2, "1", "abc"):
        assert world["oc"].get(f"{DOCS}{guess}/download/").status_code == 404


def test_the_display_name_is_cleaned():
    assert documents.display_name("../../a/b\\c.pdf") == "c.pdf"
    assert documents.display_name("  .hidden ") == "hidden"
    assert documents.display_name("x\x07y.pdf") == "xy.pdf"
    assert len(documents.display_name("a" * 500 + ".pdf")) == 200


# --- Integrity, archive, scanning ------------------------------


def test_a_tampered_file_is_refused_on_download(world):
    doc_id = upload(world["rc"], world["request"].pk).json()["id"]
    path = documents._path_for(Document.objects.get().storage_key)
    os.chmod(path, 0o600)
    path.write_bytes(PDF + b"tampered")
    response = world["rc"].get(f"{DOCS}{doc_id}/download/")
    assert response.status_code == 400
    assert AuditEvent.objects.filter(event_type=events.DOCUMENT_DOWNLOADED, success=False).exists()


def test_a_missing_file_is_a_clean_404(world):
    doc_id = upload(world["rc"], world["request"].pk).json()["id"]
    documents._path_for(Document.objects.get().storage_key).unlink()
    assert world["rc"].get(f"{DOCS}{doc_id}/download/").status_code == 404


def test_archiving_hides_the_file_keeps_the_record_and_is_audited(world):
    doc_id = upload(world["rc"], world["request"].pk).json()["id"]
    assert post(world["rc"], f"{DOCS}{doc_id}/archive/").status_code == 200
    row = Document.objects.get()
    assert row.is_archived and row.archived_by_id == world["requester"].pk
    assert listing(world["rc"], world["request"].pk).json()["results"] == []
    assert world["rc"].get(f"{DOCS}{doc_id}/download/").status_code == 404
    assert documents._path_for(row.storage_key).exists()  # never destroyed
    assert AuditEvent.objects.filter(event_type=events.DOCUMENT_ARCHIVED).count() == 1


def test_files_cannot_be_removed_once_the_request_is_submitted_or_by_others(world):
    doc_id = upload(world["rc"], world["request"].pk).json()["id"]
    services.submit(world["requester"], world["request"].pk)
    assert post(world["rc"], f"{DOCS}{doc_id}/archive/").status_code == 403
    assert post(world["hc"], f"{DOCS}{doc_id}/archive/").status_code == 403
    assert post(world["oc"], f"{DOCS}{doc_id}/archive/").status_code == 404
    assert not Document.objects.get().is_archived


def test_scan_hook_is_a_stub_that_says_so_and_an_infected_file_is_refused(
    world, monkeypatch, settings
):
    upload(world["rc"], world["request"].pk)
    assert Document.objects.get().scan_status == "NOT_SCANNED"
    from apps.core import scanning

    monkeypatch.setattr(scanning, "scan_file", lambda path: scanning.INFECTED)
    assert upload(world["rc"], world["request"].pk, "b.pdf").status_code == 400
    assert Document.objects.count() == 1
    # When scanning is required and not available, uploads stop rather than skip the check.
    monkeypatch.setattr(scanning, "scan_file", lambda path: scanning.NOT_SCANNED)
    settings.TCOS_REQUIRE_VIRUS_SCAN = True
    assert upload(world["rc"], world["request"].pk, "c.pdf").status_code == 400
    monkeypatch.setattr(scanning, "scan_file", lambda path: scanning.CLEAN)
    ok = upload(world["rc"], world["request"].pk, "d.pdf")
    assert ok.status_code == 201 and ok.json()["scan_status"] == "CLEAN"
    assert stored_files().__len__() == Document.objects.count() == 2


def test_a_database_failure_leaves_no_orphan_file(world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(Document.objects, "create", boom)
    with pytest.raises(RuntimeError):
        documents.upload(
            world["requester"],
            PARENT,
            world["request"].pk,
            SimpleUploadedFile("a.pdf", PDF),
        )
    assert stored_files() == []


def test_unknown_parent_types_do_not_exist(world):
    client = world["rc"]
    data = {
        "parent_type": "children.Child",
        "parent_id": str(uuid.uuid4()),
        "file": SimpleUploadedFile("a.pdf", PDF),
    }
    assert (
        client.post(DOCS, data, format="multipart", HTTP_X_CSRFTOKEN=csrf_token(client)).status_code
        == 404
    )
    assert client.get(DOCS, {"parent_type": "nope", "parent_id": "x"}).status_code == 404


def test_upload_needs_csrf(world):
    client = world["rc"]
    data = {
        "parent_type": PARENT,
        "parent_id": str(world["request"].pk),
        "file": SimpleUploadedFile("a.pdf", PDF),
    }
    assert client.post(DOCS, data, format="multipart").status_code == 403


def test_the_private_storage_is_not_under_any_public_setting(settings):
    root = Path(settings.TCOS_PRIVATE_STORAGE_ROOT).resolve()
    for public in (getattr(settings, "STATIC_ROOT", None), getattr(settings, "MEDIA_ROOT", None)):
        if public:
            p = Path(public).resolve()
            assert root != p and p not in root.parents and root not in p.parents
