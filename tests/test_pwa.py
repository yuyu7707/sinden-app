def test_manifest_is_public_and_valid(client_anon):
    res = client_anon.get("/manifest.webmanifest")
    assert res.status_code == 200
    assert res.headers["Content-Type"].startswith("application/manifest+json")
    data = res.get_json()
    assert data["display"] == "standalone"
    assert data["start_url"] == "/"
    assert {i["sizes"] for i in data["icons"]} == {"192x192", "512x512"}


def test_icons_are_served(client_anon):
    for name in ("icon-192.png", "icon-512.png", "apple-touch-icon.png"):
        res = client_anon.get(f"/static/icons/{name}")
        assert res.status_code == 200
        assert res.headers["Content-Type"] == "image/png"


def test_pages_link_the_manifest(client_anon):
    html = client_anon.get("/login").get_data(as_text=True)
    assert 'rel="manifest"' in html
    assert 'rel="apple-touch-icon"' in html


def test_no_service_worker(client_anon):
    assert client_anon.get("/sw.js").status_code == 404


def test_logged_out_pages_use_the_anon_header(client_anon, aoi, login_as):
    assert "site-header anon" in client_anon.get("/login").get_data(as_text=True)
    html = login_as(aoi).get("/").get_data(as_text=True)
    assert "site-header anon" not in html
