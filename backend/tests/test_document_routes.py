"""
Document endpoints.

Only the document router is mounted, not the whole app: main.py pulls in the
media router, whose optional heavyweight parsers are not needed to exercise
upload and delete.
"""

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.document_routes as document_routes
from auth_middleware import get_current_user
from config import MAX_FILE_SIZE_BYTES
from conftest import FakeQuery, FakeSupabase


class FakeStorage:
    def __init__(self):
        self.uploaded = []
        self.removed = []

    def from_(self, bucket):
        return self

    def upload(self, path, file, file_options=None):
        self.uploaded.append(path)

    def remove(self, paths):
        self.removed.extend(paths)


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(document_routes.router, prefix="/api/documents")
    app.dependency_overrides[get_current_user] = lambda: type(
        "U", (), {"id": "user-1", "email": "a@b.com"}
    )()

    storage = FakeStorage()

    def install(tables):
        supabase = FakeSupabase(tables=tables)
        supabase.storage = storage
        monkeypatch.setattr(document_routes, "supabase", supabase)
        return supabase

    with TestClient(app) as c:
        c.install = install
        c.storage = storage
        yield c


def test_upload_rejects_unsupported_extension_without_reading_the_body(client):
    client.install({})
    response = client.post(
        "/api/documents/upload", files={"file": ("payload.exe", b"MZ...", "application/octet-stream")}
    )
    assert response.status_code == 400
    assert "not supported" in response.json()["detail"]


def test_upload_rejects_a_file_over_the_size_limit(client):
    client.install({"documents": FakeQuery([{"id": "doc-1"}])})
    oversized = b"x" * (MAX_FILE_SIZE_BYTES + 1024)

    response = client.post(
        "/api/documents/upload",
        files={"file": ("huge.txt", io.BytesIO(oversized), "text/plain")},
    )

    assert response.status_code == 413
    # Nothing reached storage.
    assert client.storage.uploaded == []


def test_upload_never_buffers_more_than_the_limit(client, monkeypatch):
    """
    Regression guard: the handler must ask for a bounded number of bytes rather
    than pulling an arbitrarily large body into memory before validating it.
    """
    from starlette.datastructures import UploadFile as StarletteUploadFile

    requested = {}
    real_read = StarletteUploadFile.read

    async def spy_read(self, size=-1):
        requested["size"] = size
        return await real_read(self, size)

    monkeypatch.setattr(StarletteUploadFile, "read", spy_read)
    client.install({"documents": FakeQuery([{"id": "doc-1"}])})

    client.post("/api/documents/upload", files={"file": ("small.txt", b"hello", "text/plain")})

    assert requested["size"] == MAX_FILE_SIZE_BYTES + 1


def test_delete_removes_chunks_as_well_as_the_document(client):
    docs = FakeQuery([{"id": "doc-1", "storage_path": "user-1/doc-1.pdf", "user_id": "user-1"}])
    chunks = FakeQuery([])
    supabase = client.install({"documents": docs, "chunks": chunks})

    response = client.delete("/api/documents/doc-1")

    assert response.status_code == 204
    # Orphaned chunks stay searchable, so the chunk delete is not optional.
    assert "chunks" in supabase.table_calls
    assert any(name == "delete" for name, _ in chunks.calls)
    # And it is scoped to the owner.
    assert ("eq", ("user_id", "user-1")) in chunks.calls


def test_delete_removes_the_stored_file(client):
    docs = FakeQuery([{"id": "doc-1", "storage_path": "user-1/doc-1.pdf", "user_id": "user-1"}])
    client.install({"documents": docs, "chunks": FakeQuery([])})

    client.delete("/api/documents/doc-1")

    assert client.storage.removed == ["user-1/doc-1.pdf"]


def test_delete_404s_for_a_document_owned_by_someone_else(client):
    client.install({"documents": FakeQuery([]), "chunks": FakeQuery([])})

    response = client.delete("/api/documents/doc-1")

    assert response.status_code == 404
