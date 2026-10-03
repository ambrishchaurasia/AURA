"""Offline checks for the MyUPES portal session layer (no browser)."""
import contextlib
import json
import os
import time
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


def test_nudge_needs_live_response_and_no_auth_url():
    class Page:
        def __init__(self, url, status=None):
            self.url, self.status, self.handlers, self.paths = url, status, [], []
        def on(self, _e, h): self.handlers.append(h)
        def remove_listener(self, _e, h): self.handlers.remove(h)
        def evaluate(self, _js, path):
            self.paths.append(path)
            if self.status:
                for h in self.handlers:
                    h(types.SimpleNamespace(status=self.status, request=types.SimpleNamespace(resource_type="xhr")))
        def wait_for_timeout(self, _ms): pass

    alive = Page(f"https://{ps.HOST}{ps.SCHEDULE_ROUTE}", 200)
    assert ps._nudge(alive) and alive.paths == [ps.DASHBOARD_ROUTE] and not alive.handlers
    assert not ps._nudge(Page(f"https://{ps.HOST}/oneportal/app/auth/login", 200))
    assert not ps._nudge(Page(f"https://{ps.HOST}{ps.DASHBOARD_ROUTE}"))  # no request seen

def test_nudge_from_dashboard_visits_schedule_and_ends_on_dashboard():
    class Page:
        def __init__(self): self.url, self.paths, self.h = f"https://{ps.HOST}{ps.DASHBOARD_ROUTE}", [], []
        def on(self, _e, h): self.h.append(h)
        def remove_listener(self, _e, h): self.h.remove(h)
        def evaluate(self, _js, path):
            self.paths.append(path)
            for h in self.h:
                h(types.SimpleNamespace(status=200, request=types.SimpleNamespace(resource_type="fetch")))
        def wait_for_timeout(self, _ms): pass

    page = Page()
    assert ps._nudge(page) and page.paths == [ps.SCHEDULE_ROUTE, ps.DASHBOARD_ROUTE]


def test_route_raises_login_required_when_bounced_to_auth():
    class Page:
        url = f"https://{ps.HOST}{ps.DASHBOARD_ROUTE}"
        def evaluate(self, _js, path): self.url = f"https://{ps.HOST}/oneportal/app/auth/login"
        def wait_for_timeout(self, _ms): pass

    with pytest.raises(ps.LoginRequired):
        ps.route(Page(), ps.SCHEDULE_ROUTE)


def test_tab_lock_busy_stale_and_released(data_dir):
    lock = data_dir / "myupes_tab.lock"
    with ps._tab_lock():
        assert lock.exists()
        with pytest.raises(ps.PortalBusy):
            with ps._tab_lock():
                pass
        assert lock.exists()  # the busy attempt must not release the holder's lock
    assert not lock.exists()
    lock.write_text("")
    old = time.time() - 600
    os.utime(lock, (old, old))
    with ps._tab_lock():  # stale: taken over
        assert lock.exists()
    assert not lock.exists()
    with pytest.raises(RuntimeError):
        with ps._tab_lock():
            raise RuntimeError("boom")
    assert not lock.exists()


def test_keep_alive_when_busy_returns_status_without_nudging(monkeypatch):
    monkeypatch.setattr(ps, "sync_playwright", lambda: contextlib.nullcontext())
    nudged = []
    monkeypatch.setattr(ps, "_nudge", lambda page: nudged.append(1))
    with ps._tab_lock():
        assert "browser_running" in ps.keep_alive() and not nudged
