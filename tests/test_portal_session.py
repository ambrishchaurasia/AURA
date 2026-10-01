"""Offline checks for the MyUPES portal session layer (no browser)."""
import contextlib
import json
import types

import pytest

from automation.agents import portal_session as ps


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AURA_DATA_DIR", str(tmp_path))
    return tmp_path


def test_status_transitions_and_toast_only_once(monkeypatch):
    toasts = []
    monkeypatch.setattr(ps, "_toast", lambda: toasts.append(1))

    @contextlib.contextmanager
    def dead(_p, **_kw):
        ps._record(False)
        raise ps.LoginRequired()
        yield

    monkeypatch.setattr(ps, "sync_playwright", lambda: contextlib.nullcontext())
    ps._record(True, login=True)
    assert ps.status()["authenticated"] and "session_age_hours" in ps.status()
    monkeypatch.setattr(ps, "open_portal", dead)
    assert ps.keep_alive()["expired_at"] and len(toasts) == 1
    ps.keep_alive()
    assert len(toasts) == 1  # repeated dead checks stay silent


def test_is_authenticated_needs_portal_host_no_auth_path_and_nav_link():
    def page(url, nav=True):
        locator = lambda selector: types.SimpleNamespace(count=lambda: int(nav))
        return types.SimpleNamespace(url=url, locator=locator)

    other = f"https://{ps.HOST}/other"
    assert ps.is_authenticated(page(ps.DASHBOARD_URL, nav=False))  # inner page, no nav link
    assert ps.is_authenticated(page(f"https://{ps.HOST}/connectportal/user/student/home/dashboard", nav=False))
    assert ps.is_authenticated(page(other))
    assert not ps.is_authenticated(page(other, nav=False))
    assert not ps.is_authenticated(page(ps.LOGIN_URL))
    assert not ps.is_authenticated(page("https://evil.example/oneportal/app/dashboard"))


def test_signed_in_target_matches_only_portal_pages_outside_auth():
    def t(url, type="page"):
        return {"type": type, "url": url}

    assert ps._signed_in_target([t(ps.DASHBOARD_URL)])
    assert not ps._signed_in_target([t(ps.LOGIN_URL)])
    assert not ps._signed_in_target([t(ps.DASHBOARD_URL, "service_worker")])
    assert not ps._signed_in_target([t("https://evil.example/oneportal/app/dashboard")])


def test_live_port_removes_stale_file(data_dir):
    assert ps._live_port() is None
    (data_dir / "myupes_browser.json").write_text(json.dumps({"port": 1, "pid": 1}))
    assert ps._live_port() is None and not (data_dir / "myupes_browser.json").exists()


def test_portal_page_picks_first_portal_tab():
    pg = lambda url: types.SimpleNamespace(url=url)
    other, mine = pg("https://example.com/"), pg(ps.DASHBOARD_URL)
    browser = types.SimpleNamespace(contexts=[types.SimpleNamespace(pages=[other, mine])])
    assert ps._portal_page(browser) is mine
    browser.contexts[0].pages = [other]
    assert ps._portal_page(browser) is None
