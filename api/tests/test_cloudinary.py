"""Cloudinary storage (phase E), against a fake Cloudinary: no network and no account are used.

What is proven here: the signature algorithm (against Cloudinary's published example), that the secret never reaches the
browser, the sign -> register -> analyse -> stitch -> upload flow through the real API, that a failed final upload never
stops the match from being finalised, and the multipart upload of a large file. What is NOT proven: a real Cloudinary
account (limits, URL shape, eventual consistency): that needs credentials in .env.
"""
import json
from pathlib import Path

import httpx
import pytest

from api.config import settings
from api.services import live_hub
from api.services import storage_cloudinary as sc
from api.tests.test_live_session import env, new_session, wait_for  # noqa: F401  (the module-scoped fixture and helpers)

CREDS = {"cloudinary_cloud": "democloud", "cloudinary_key": "key123", "cloudinary_secret": "s3cret"}


def test_the_signature_matches_cloudinarys_published_example():
    # https://cloudinary.com/documentation/authentication_signatures : secret "abcd"
    params = {"eager": "w_400,h_300,c_pad|w_260,h_200,c_crop", "public_id": "sample_image", "timestamp": 1315060510}
    assert sc.sign_params(params, "abcd") == "bfd09f95f331f558cbd1320e67aa8d488770583e"


def test_file_and_key_fields_are_never_signed():
    base = {"public_id": "a", "timestamp": 1}
    assert sc.sign_params({**base, "file": "x", "api_key": "k", "cloud_name": "c", "resource_type": "video"}, "z") == sc.sign_params(base, "z")


def test_sign_gives_the_browser_a_signature_but_never_the_secret():
    st = sc.CloudinaryStorage("democloud", "key123", "s3cret")
    out = st.sign("s_abc", 3)
    assert out["upload_url"] == "https://api.cloudinary.com/v1_1/democloud/video/upload" and out["file_field"] == "file"
    f = out["fields"]
    assert f["public_id"] == "rallyos/s_abc/chunk_0003" and f["api_key"] == "key123"
    assert "s3cret" not in json.dumps(out)
    signed = {k: v for k, v in f.items() if k not in ("api_key", "signature")}
    assert f["signature"] == sc.sign_params(signed, "s3cret")                       # the server can recompute it: it is genuine
    with pytest.raises(ValueError):
        st.sign("s_abc", None)                                                       # a chunk upload needs its number


def test_missing_credentials_fall_back_to_local_storage(monkeypatch):
    from api.services.storage import LocalStorage, get_storage

    monkeypatch.setattr(settings, "storage", "cloudinary")
    monkeypatch.setattr(settings, "cloudinary_secret", "")
    assert isinstance(get_storage(), LocalStorage)


def test_a_large_file_goes_up_in_parts_with_content_range(tmp_path, monkeypatch):
    f = tmp_path / "big.mp4"
    f.write_bytes(b"x" * 2500)
    monkeypatch.setattr(sc, "LARGE_FILE", 1000)
    monkeypatch.setattr(sc, "PART", 1000)
    seen = []

    def fake_post(url, data=None, files=None, headers=None, timeout=None):
        seen.append((headers or {}).get("Content-Range"))
        last = headers["Content-Range"].endswith("2499/2500")
        return httpx.Response(200, json={"secure_url": "https://res.cloudinary.com/democloud/video/upload/v1/big.mp4"} if last else {"done": False})

    monkeypatch.setattr(httpx, "post", fake_post)
    url = sc.CloudinaryStorage("democloud", "k", "s").upload_file(f, "rallyos/s/match")
    assert seen == ["bytes 0-999/2500", "bytes 1000-1999/2500", "bytes 2000-2499/2500"] and url.endswith("big.mp4")


def test_a_cloudinary_error_is_reported_with_its_message(tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(401, json={"error": {"message": "Invalid Signature"}}))
    with pytest.raises(RuntimeError, match="Invalid Signature"):
        sc.CloudinaryStorage("democloud", "k", "s").upload_file(f, "p")


def _cloud_session(env, monkeypatch, upload_post):
    for k, v in {"storage": "cloudinary", **CREDS}.items():
        monkeypatch.setattr(settings, k, v)
    monkeypatch.setattr(settings, "chunk_url_hosts", ["res.cloudinary.com"])
    c, metas = env["client"], env["metas"]
    by_url = {f"https://res.cloudinary.com/democloud/video/upload/v1/rallyos/c{m.seq}.avi": Path(m.path).read_bytes() for m in metas}
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(200, content=by_url[url]))
    monkeypatch.setattr(httpx, "post", upload_post)
    r = c.post("/v1/live/sessions", json={"sport": "badminton", "corners": __import__("test_live_stream").TAPS, "chunk_seconds": 2.0})
    assert r.status_code == 201 and r.json()["storage"] == "cloudinary"
    sid = r.json()["session_id"]
    for m in metas:                                                   # what the browser does: sign, upload to Cloudinary, register
        sign = c.post(f"/v1/live/sessions/{sid}/sign", params={"seq": m.seq}).json()
        assert sign["mode"] == "cloudinary" and sign["fields"]["public_id"] == f"rallyos/{sid}/chunk_{m.seq:04d}"
        url = f"https://res.cloudinary.com/democloud/video/upload/v1/rallyos/c{m.seq}.avi"
        assert c.post(f"/v1/live/sessions/{sid}/chunks/register", json={"seq": m.seq, "url": url, "t0": m.t0, "duration": m.duration}).status_code == 200
    c.post(f"/v1/live/sessions/{sid}/stop", json={"last_seq": metas[-1].seq})
    return sid


def test_chunks_via_cloudinary_then_the_stitched_video_is_uploaded_and_recorded(env, monkeypatch):
    uploads = []

    def ok_post(url, data=None, files=None, headers=None, timeout=None):
        uploads.append((url, data["public_id"], len(files["file"][1])))
        return httpx.Response(200, json={"secure_url": "https://res.cloudinary.com/democloud/video/upload/v1/rallyos/match.mp4"})

    sid = _cloud_session(env, monkeypatch, ok_post)
    fin = wait_for(sid, "finalised")[0]
    assert uploads and uploads[0][0].endswith("/v1_1/democloud/video/upload") and uploads[0][1] == f"rallyos/{sid}/match" and uploads[0][2] > 1000
    assert "cdn_uploaded" in [e["type"] for e in live_hub.get_session(sid).all()]
    match = env["client"].get(f"/v1/matches/{fin['match_id']}").json()
    assert match["schema_version"] == "1.1" and match["video"]["cdn_src"].endswith("match.mp4")
    assert match["live"]["cdn"] == {"provider": "cloudinary", "uploaded": True}
    assert match["video"]["src"].startswith("/media/")                    # the laptop's copy stays the source of truth


def test_a_failed_final_upload_does_not_stop_the_match_from_finalising(env, monkeypatch):
    sid = _cloud_session(env, monkeypatch, lambda *a, **k: httpx.Response(401, json={"error": {"message": "Invalid Signature"}}))
    fin = wait_for(sid, "finalised")[0]
    t = [e["type"] for e in live_hub.get_session(sid).all()]
    assert "cdn_failed" in t and "cdn_uploaded" not in t
    match = env["client"].get(f"/v1/matches/{fin['match_id']}").json()
    assert match["live"]["cdn"]["uploaded"] is False and "Invalid Signature" in match["live"]["cdn"]["error"]
    assert "cdn_src" not in match["video"] and match["live"]["chunks"] == len(env["metas"])
