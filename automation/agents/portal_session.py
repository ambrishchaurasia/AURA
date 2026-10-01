"""
Shared MyUPES portal session, kept alive as one signed-in browser.

The MyUPES sign-in lives only in the page's memory: any full page load (reload or goto) in the signed-in
tab throws it back to the login page, and no cookie or storage copy restores it, so nothing is saved to disk. `login` starts a normal Chrome/Edge that stays running; the
person signs in there and every later run attaches to that same tab over CDP. Nothing here types
credentials or solves the CAPTCHA: it only waits for the person.

    python -m automation.agents.portal_session login|status|keepalive|stop
"""
from __future__ import annotations
import json
import os
import pathlib
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

LOGIN_URL = "https://myupes-beta.upes.ac.in/oneportal/app/auth/login"
DASHBOARD_URL = "https://myupes-beta.upes.ac.in/oneportal/app/dashboard"
HOST = "myupes-beta.upes.ac.in"


def _dir() -> pathlib.Path:
    path = pathlib.Path(os.environ.get("AURA_DATA_DIR") or pathlib.Path(os.environ["LOCALAPPDATA"]) / "AURA")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _status_file() -> pathlib.Path:
    return _dir() / "myupes_status.json"


class LoginRequired(Exception):
    def __init__(self, message="MyUPES sign-in needed. Run the `login` action once and sign in in the window that opens."):
        super().__init__(message)


# ── Status (plain JSON, no secrets) ──────────────────────────────────────────

def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_status() -> dict:
    try:
        return json.loads(_status_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"authenticated": False, "last_login": None, "last_ok": None, "expired_at": None}


def _record(ok: bool, login: bool = False) -> None:
    s, now = _read_status(), _now()
    if ok:
        s.update(authenticated=True, last_ok=now, expired_at=None)
        if login:
            s["last_login"] = now
    else:
        if s.get("authenticated"):
            s["expired_at"] = now
        s["authenticated"] = False
    tmp = _status_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2), encoding="utf-8")
    os.replace(tmp, _status_file())


def status() -> dict:
    s = _read_status()
    if s.get("last_login"):
        end = datetime.fromisoformat(s["expired_at"]) if s.get("expired_at") else datetime.now().astimezone()
        s["session_age_hours"] = round((end - datetime.fromisoformat(s["last_login"])).total_seconds() / 3600, 2)
    s["browser_running"] = _live_port() is not None
    return s


def _toast() -> None:
    # ponytail: borrows PowerShell's registered AppID so the toast shows; register an AURA AppID if branding matters.
    script = ("[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
              "[Windows.UI.Notifications.ToastNotification,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
              "$x=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent('ToastText02');"
              "$t=$x.GetElementsByTagName('text');"
              "$t[0].AppendChild($x.CreateTextNode('MyUPES needs sign-in'))|Out-Null;"
              "$t[1].AppendChild($x.CreateTextNode('Run the AURA login action once.'))|Out-Null;"
              "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe').Show([Windows.UI.Notifications.ToastNotification]::new($x))")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], creationflags=0x08000000, timeout=20,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ── Browser session ──────────────────────────────────────────────────────────

def is_authenticated(page) -> bool:
    if urlparse(page.url).hostname != HOST or "/auth/" in page.url:
        return False
    if urlparse(page.url).path.startswith(("/connectportal/", "/oneportal/app/")):
        return True
    try:
        return page.locator("a[href*='servicerequest']").count() > 0
    except Exception:
        return False


def _browser_exe() -> str:
    env = os.environ.get
    for base, rel in [(env("PROGRAMFILES"), r"Google\Chrome\Application\chrome.exe"),
                      (env("PROGRAMFILES(X86)"), r"Google\Chrome\Application\chrome.exe"),
                      (env("LOCALAPPDATA"), r"Google\Chrome\Application\chrome.exe"),
                      (env("PROGRAMFILES(X86)"), r"Microsoft\Edge\Application\msedge.exe"),
                      (env("PROGRAMFILES"), r"Microsoft\Edge\Application\msedge.exe")]:
        if base and os.path.exists(os.path.join(base, rel)):
            return os.path.join(base, rel)
    raise LoginRequired("Chrome or Edge is needed for sign-in.")


def _signed_in_target(targets) -> bool:
    return any(t.get("type") == "page" and urlparse(t.get("url", "")).hostname == HOST and "/auth/" not in t["url"]
               for t in targets)


def _browser_file() -> pathlib.Path:
    return _dir() / "myupes_browser.json"


def _targets(port):
    with urlopen(f"http://127.0.0.1:{port}/json", timeout=5) as r:
        return json.load(r)


def _live_port():
    try:
        port = json.loads(_browser_file().read_text(encoding="utf-8"))["port"]
    except (OSError, ValueError, KeyError):
        return None
    try:
        urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2).close()
        return port
    except OSError:
        _browser_file().unlink(missing_ok=True)
        return None


def _start_browser() -> int:
    exe = _browser_exe()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([exe, f"--remote-debugging-port={port}", f"--user-data-dir={_dir() / 'login-profile'}",
                             "--no-first-run", "--no-default-browser-check", LOGIN_URL],
                            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                            close_fds=True)  # detached so the browser outlives this process
    _browser_file().write_text(json.dumps({"port": port, "pid": proc.pid}), encoding="utf-8")
    return port


def _portal_page(browser):
    return next((pg for pg in browser.contexts[0].pages if urlparse(pg.url).hostname == HOST), None)


def _human_login(playwright, timeout):
    """Sign-in in the user's own browser, with nothing attached until the portal shows a signed-in page.
    The browser is always left running."""
    port = _live_port()
    if port is None:
        port = _start_browser()
    else:
        try:
            has_tab = any(urlparse(t.get("url", "")).hostname == HOST for t in _targets(port) if t.get("type") == "page")
        except (OSError, ValueError):
            has_tab = True
        if not has_tab:
            urlopen(Request(f"http://127.0.0.1:{port}/json/new?{LOGIN_URL}", method="PUT"), timeout=5).close()
    print("[Portal] Sign in to MyUPES in the browser window, then leave that window open (minimise it). Do not refresh or close it.")
    deadline = time.monotonic() + timeout
    while True:
        while True:
            try:
                seen = _signed_in_target(_targets(port))
            except (OSError, ValueError):
                seen = False
            if seen:
                break
            if time.monotonic() > deadline:
                raise LoginRequired("Sign-in was not completed in time.")
            time.sleep(2)
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        while True:
            page = _portal_page(browser)
            if page and is_authenticated(page):
                break
            if time.monotonic() > deadline:
                raise LoginRequired("Sign-in was not completed in time.")
            time.sleep(2)
        # The portal may bounce the first sign-in after a few seconds; never reload, a full page load signs the tab out.
        page.wait_for_timeout(10000)
        if is_authenticated(page):
            break
        print("[Portal] The portal asked for sign-in again; please sign in once more...")
    _record(True, login=True)
    return browser, page


@contextmanager
def open_portal(playwright, *, interactive=False, login_timeout=600):
    """Yield the already signed-in portal tab; raise LoginRequired if a human sign-in is needed and not allowed/completed.
    Callers must move around with in-app clicks only, never `page.goto` / `page.reload`."""
    # ponytail: one shared tab, no locking; add a lock file if two actions ever run at once.
    page = None
    port = _live_port()
    if port is not None:
        page = _portal_page(playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}"))
    if page and is_authenticated(page):
        _record(True)
    elif not interactive:
        _record(False)
        raise LoginRequired()
    else:
        page = _human_login(playwright, login_timeout)[1]
    yield page  # the browser and tab stay open; Playwright just disconnects when it stops


def keep_alive() -> dict:
    was_ok = _read_status().get("authenticated", False)
    try:
        with sync_playwright() as p, open_portal(p):
            pass
    except LoginRequired:
        if was_ok:  # toast only on the alive -> dead transition
            _toast()
    return status()


def stop() -> None:
    if _live_port() is not None:
        try:
            os.kill(json.loads(_browser_file().read_text(encoding="utf-8"))["pid"], signal.SIGTERM)
        except (OSError, ValueError, KeyError):
            pass
    _browser_file().unlink(missing_ok=True)
    _record(False)


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    if cmd == "login":
        try:
            with sync_playwright() as p, open_portal(p, interactive=True):
                pass
        except LoginRequired as e:
            print(e)
            return 1
    elif cmd == "keepalive":
        result = keep_alive()
        print(json.dumps(result, indent=2))
        return 0 if result["authenticated"] else 1
    elif cmd == "stop":
        stop()
    elif cmd != "status":
        print("usage: python -m automation.agents.portal_session login|status|keepalive|stop")
        return 2
    print(json.dumps(status(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
