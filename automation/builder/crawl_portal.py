"""
AURA - UPES Portal Category Crawler

Run this ONCE to discover all departments, categories, and subcategories
from the MyUPES service request form. Saves everything to:
    automation/upes_categories.json

Usage:
    python -m automation.builder.crawl_portal

The crawler will:
1. Open the portal login page
2. Wait for you to log in (you solve CAPTCHA)
3. Navigate to Service Request -> Create Request
4. Click each Department, read its Categories, click each Category, read its Sub Categories
5. Save the full tree to upes_categories.json
"""

import json
import pathlib
import sys
import os
from dotenv import load_dotenv

load_dotenv()

OUTPUT_FILE = pathlib.Path(__file__).parent.parent.parent / "automation" / "upes_categories.json"
PORTAL_URL  = "https://myupes-beta.upes.ac.in/oneportal/app/auth/login"
SESSION_FILE = pathlib.Path(__file__).parent.parent.parent / "automation" / "myupes_session.json"


def crawl():
    from playwright.sync_api import sync_playwright

    print("=" * 60)
    print("  UPES Portal Category Crawler")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        # Use saved session if available
        if SESSION_FILE.exists():
            print(f"[Crawler] Loading saved session from {SESSION_FILE}...")
            context = browser.new_context(storage_state=str(SESSION_FILE))
        else:
            context = browser.new_context()

        page = context.new_page()

        # ── Login ────────────────────────────────────────────────────────────
        if SESSION_FILE.exists():
            page.goto("https://myupes-beta.upes.ac.in/oneportal/app/dashboard")
            page.wait_for_timeout(3000)
            if "login" in page.url.lower():
                print("[Crawler] Session expired — please log in manually.")
                SESSION_FILE.unlink(missing_ok=True)
                page.goto(PORTAL_URL)
                _wait_for_login(page, context)
            else:
                print("[Crawler] ✅ Already logged in!")
        else:
            page.goto(PORTAL_URL)
            page.wait_for_load_state("networkidle")
            _wait_for_login(page, context)

        # ── Navigate to Create Request form ──────────────────────────────────
        print("[Crawler] Navigating to Service Requests...")
        try:
            page.locator("a[href*='servicerequest']").first.click(timeout=5000)
        except Exception:
            page.get_by_text("Service Request", exact=False).first.click(timeout=5000)
        page.wait_for_timeout(2000)

        print("[Crawler] Opening Create Request...")
        for btn in ["Create Request", "New Request", "Add Request"]:
            try:
                page.get_by_role("button", name=btn).first.click(timeout=3000)
                break
            except:
                continue
        page.wait_for_timeout(2000)

        # ── Step 1: Read all Departments ─────────────────────────────────────
        print("\n[Crawler] Reading all Departments...")
        departments = _read_dropdown_options(page, "Select Department")
        print(f"[Crawler] Found {len(departments)} departments: {departments}")

        full_tree = {}

        for dept in departments:
            print(f"\n[Crawler] ── Department: {dept}")
            full_tree[dept] = {}

            # Select this department
            _select_option(page, "Select Department", dept)

            # ── Step 2: Read Categories for this Department ───────────────────
            categories = _read_dropdown_options(page, "Select Category")
            print(f"[Crawler]    Categories: {categories}")

            for cat in categories:
                print(f"[Crawler]    ── Category: {cat}")
                full_tree[dept][cat] = []

                # Select this category
                _select_option(page, "Select Category", cat)

                # ── Step 3: Read Sub Categories ───────────────────────────────
                subcats = _read_dropdown_options(page, "Select Sub Category")
                print(f"[Crawler]       Sub Categories: {subcats}")
                full_tree[dept][cat] = subcats

                # Reset category for next iteration
                _select_option(page, "Select Category", "Select Category")
                page.wait_for_timeout(1000)

            # Reset department for next iteration
            _select_option(page, "Select Department", "Select Department")
            page.wait_for_timeout(1500)

        browser.close()

        # ── Save result ───────────────────────────────────────────────────────
        OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(full_tree, f, indent=2, ensure_ascii=False)

        print(f"\n{'=' * 60}")
        print(f"✅ Categories saved to: {OUTPUT_FILE}")
        print(f"{'=' * 60}")
        _print_tree(full_tree)
        return full_tree


def _wait_for_login(page, context):
    """Waits up to 90s for manual login, then saves session."""
    print("\n[Crawler] Please log in manually (solve CAPTCHA and click Login)...")
    print("[Crawler] Waiting up to 90 seconds...")
    try:
        page.wait_for_selector("a[href*='servicerequest']", timeout=90000)
        context.storage_state(path=str(SESSION_FILE))
        print("[Crawler] Logged in! Session saved.")
    except Exception:
        print("[Crawler] Login timed out.")
        sys.exit(1)


def _read_dropdown_options(page, placeholder: str) -> list[str]:
    """
    Opens a Kendo dropdown and reads all visible options.
    Returns list of option text values.
    """
    try:
        # Click to open the dropdown
        page.locator("span.k-input-inner").filter(has_text=placeholder).first.click(force=True, timeout=5000)
        page.wait_for_timeout(1500)

        # Read all visible list items
        items = page.locator("li.k-list-item:visible, li[role='option']:visible").all()
        options = []
        for item in items:
            text = item.inner_text().strip()
            if text and text not in ("", placeholder):
                options.append(text)

        # Close dropdown
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
        return options

    except Exception as e:
        print(f"[Crawler] ⚠️ Could not read '{placeholder}': {e}")
        return []


def _select_option(page, placeholder: str, value: str):
    """Selects a specific option from a Kendo dropdown."""
    try:
        page.locator("span.k-input-inner").filter(has_text=placeholder).first.click(force=True, timeout=5000)
        page.wait_for_timeout(1200)

        if value in ("Select Department", "Select Category", "Select Sub Category"):
            # Just close — selecting a placeholder isn't meaningful
            page.keyboard.press("Escape")
            return

        try:
            page.locator("li:visible").filter(has_text=value).first.click(timeout=3000)
        except:
            page.get_by_text(value, exact=True).last.click(timeout=3000)

        page.wait_for_timeout(3000)  # Wait for next dropdown to populate
    except Exception as e:
        print(f"[Crawler] ⚠️ Could not select '{value}' in '{placeholder}': {e}")


def _print_tree(tree: dict):
    """Pretty prints the category tree."""
    for dept, cats in tree.items():
        print(f"\n📁 {dept}")
        for cat, subcats in cats.items():
            print(f"   📂 {cat}")
            for sub in subcats:
                print(f"      📄 {sub}")


if __name__ == "__main__":
    crawl()
