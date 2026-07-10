"""Case file attachment tests: upload, list, download, delete, graph nodes."""
import pytest

from app import cases, files, graph


@pytest.fixture
def _db(client):
    # `client` wipes + inits the DB and starts the queue.
    return client


async def test_upload_list_download_delete(auth_client):
    c = await auth_client.post("/api/cases", json={"title": "Op Files", "subject": "johndoe",
                                                   "subject_type": "username"})
    cid = c.json()["id"]

    up = await auth_client.post(f"/api/cases/{cid}/files", files=[
        ("uploads", ("evidence.png", b"\x89PNG\r\nfake", "image/png")),
        ("uploads", ("notes.txt", b"handle johndoe", "text/plain")),
    ])
    assert up.status_code == 200
    saved = up.json()["files"]
    assert len(saved) == 2
    assert saved[0]["sha256"] and saved[0]["size"] == len(b"\x89PNG\r\nfake")

    lst = await auth_client.get(f"/api/cases/{cid}/files")
    assert len(lst.json()) == 2

    # counts surface the attachment total
    counts = (await auth_client.get(f"/api/cases/{cid}")).json()["counts"]
    assert counts["files"] == 2

    # exact bytes come back, forced as an attachment download
    fid = saved[0]["id"]
    dl = await auth_client.get(f"/api/cases/{cid}/files/{fid}/download")
    assert dl.status_code == 200
    assert dl.content == b"\x89PNG\r\nfake"
    assert dl.headers["content-type"] == "application/octet-stream"

    d = await auth_client.delete(f"/api/cases/{cid}/files/{fid}")
    assert d.status_code == 200
    assert len((await auth_client.get(f"/api/cases/{cid}/files")).json()) == 1


async def test_empty_upload_rejected(auth_client):
    cid = (await auth_client.post("/api/cases", json={"title": "x"})).json()["id"]
    r = await auth_client.post(f"/api/cases/{cid}/files",
                               files=[("uploads", ("z.txt", b"", "text/plain"))])
    assert r.status_code == 422


async def test_files_appear_on_graph(_db):
    c = cases.create_case(subject="target1", subject_type="username")
    files.save(c["id"], "screenshot.png", b"bytes", "image/png")
    g = graph.build_for_case(c["id"])
    file_nodes = [n for n in g["nodes"] if n["group"] == "file"]
    assert len(file_nodes) == 1
    assert file_nodes[0]["label"] == "screenshot.png"
    assert any(e["relation"] == "attached" for e in g["edges"])


async def test_cross_case_download_guard(auth_client):
    cid = (await auth_client.post("/api/cases", json={"title": "a"})).json()["id"]
    up = await auth_client.post(f"/api/cases/{cid}/files",
                                files=[("uploads", ("f.txt", b"data", "text/plain"))])
    fid = up.json()["files"][0]["id"]
    # The same file id under a different case must not resolve.
    r = await auth_client.get(f"/api/cases/999999/files/{fid}/download")
    assert r.status_code == 404


async def test_delete_case_purges_files(_db):
    c = cases.create_case(subject="target2", subject_type="username")
    meta = files.save(c["id"], "doc.pdf", b"pdfbytes", "application/pdf")
    assert files.path_for(c["id"], meta["id"]) is not None
    cases.delete_case(c["id"])
    assert files.list_files(c["id"]) == []
