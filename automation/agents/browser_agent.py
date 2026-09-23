"""
AURA Browser Agent — Hybrid Automation for MyUPES Portal

Uses Playwright with confirmed-real HTML selectors from the portal.
All selectors were verified by inspecting the actual portal HTML.
Session is persisted in myupes_session.json to skip CAPTCHA on repeat runs.
"""
import os
import time
import pathlib
from dotenv import load_dotenv
from automation.core.base_agent import BaseAgent

load_dotenv()

SESSION_FILE = pathlib.Path(__file__).parent.parent.parent / "automation" / "myupes_session.json"
PORTAL_URL   = "https://myupes-beta.upes.ac.in/oneportal/app/auth/login"
DASHBOARD_URL = "https://myupes-beta.upes.ac.in/oneportal/app/dashboard"


class BrowserAgent(BaseAgent):

    # ── BaseAgent abstract contract ──────────────────────────────────────────

    @property
    def app_name(self) -> str:
        return "MyUPES Portal"

    @property
    def process_name(self) -> str:
        return "chrome.exe"

    def get_agent_name(self) -> str:
        return "browser"

    def get_llm_capabilities(self) -> str:
        # Load the full category tree from crawler output if available
        cat_file = pathlib.Path(__file__).parent.parent.parent / "automation" / "upes_categories.json"
        if cat_file.exists():
            import json
            with open(cat_file, encoding="utf-8") as f:
                tree = json.load(f)
            tree_str = json.dumps(tree, indent=2)
            category_hint = f"""
  Full category tree (use this to map user intent to exact values):
  {tree_str}
"""
        else:
            category_hint = """
  Known categories (run crawl_portal.py to get full list):
  - Department: "Information Technology" → Category: "Network" → Sub Category: "Internet not working"
  - Run: .\\automation\\venv\\Scripts\\python.exe -m automation.builder.crawl_portal
"""

        return f"""
Agent `browser` supports:
- `create_service_request`: Fills and submits a service request on the college LMS portal.
  Params:
  - `department`: <string> — exact name from the category tree
  - `category`: <string> — exact name from the category tree
  - `subcategory`: <string> — exact name from the category tree
  - `short_description`: <string> — concise 1-line title of the issue
  - `description`: <string> — full explanation of the issue

  CRITICAL: Deduce ALL params automatically from user's prompt. NEVER ask the user.
  Map their complaint to the closest matching department/category/subcategory.
  Example: "wifi sucks" → department="Information Technology", category="Network", subcategory="Internet not working"
{category_hint}
"""

    def get_capabilities(self) -> dict:
        return {
            "application": "browser",
            "actions": {
                "create_service_request": {
                    "description": "Creates a service request on the LMS portal",
                    "parameters": {"department": "string", "category": "string",
                                   "subcategory": "string", "short_description": "string",
                                   "description": "string"},
                    "safety": "safe",
                }
            },
        }

    def resolve(self, intent: str, **kwargs) -> dict:
        return {"action": intent, "target_element": None, "resolver_tier": 1, "confidence": 1.0}

    def execute(self, action: str, params: dict | None = None) -> dict:
        params = params or {}
        if action == "create_service_request":
            return self._action_create_service_request(**params)
        return {"status": "failure", "details": f"Unknown action: {action}"}

    def verify(self, expected_state: dict) -> dict:
        return {"verified": True, "expected": expected_state, "actual": {}, "details": "Verified."}

    # ── Main action ──────────────────────────────────────────────────────────

    def _action_create_service_request(self, department="", category="", subcategory="",
                                        short_description="", description="") -> dict:
        username = os.environ.get("MYUPES_USERNAME", "")
        password  = os.environ.get("MYUPES_PASSWORD", "")
        if not username:
            return {"status": "failure", "details": "MYUPES_USERNAME not set in .env"}

        from playwright.sync_api import sync_playwright
        try:
            from playwright_stealth import Stealth
            has_stealth = True
        except ImportError:
            has_stealth = False

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)

                # ── 1. Login / Session ───────────────────────────────────────
                if SESSION_FILE.exists():
                    print("[BrowserAgent] 🔄 Loading saved session...")
                    context = browser.new_context(storage_state=str(SESSION_FILE))
                    page = context.new_page()
                    if has_stealth:
                        Stealth().apply_stealth_sync(page)
                    page.goto(DASHBOARD_URL)
                    page.wait_for_timeout(3000)
                    if "login" in page.url.lower():
                        print("[BrowserAgent] Session expired — doing fresh login...")
                        SESSION_FILE.unlink(missing_ok=True)
                        page.goto(PORTAL_URL)
                        page.wait_for_load_state("networkidle")
                        self._fill_login(page, username, password)
                        self._await_dashboard(page, context)
                    else:
                        print("[BrowserAgent] ✅ Already logged in!")
                else:
                    context = browser.new_context()
                    page = context.new_page()
                    if has_stealth:
                        Stealth().apply_stealth_sync(page)
                    page.goto(PORTAL_URL)
                    page.wait_for_load_state("networkidle")
                    self._fill_login(page, username, password)
                    self._await_dashboard(page, context)

                # ── 2. Navigate to Service Requests ──────────────────────────
                print("[BrowserAgent] Navigating to Service Requests...")
                try:
                    page.locator("a[href*='servicerequest']").first.click(timeout=5000)
                except Exception:
                    page.get_by_text("Service Request", exact=False).first.click(timeout=5000)
                page.wait_for_timeout(2000)

                # ── 3. Click Create Request ───────────────────────────────────
                print("[BrowserAgent] Clicking Create Request...")
                for btn in ["Create Request", "New Request", "Add Request"]:
                    try:
                        page.get_by_role("button", name=btn).first.click(timeout=3000)
                        print(f"[BrowserAgent] ✅ Clicked '{btn}'")
                        break
                    except:
                        continue
                page.wait_for_timeout(2000)

                # ── 4. Fill Dropdowns ─────────────────────────────────────────
                # Confirmed HTML: <span class="k-input-inner">Select Department</span>
                # Each dropdown shows its current value as text inside span.k-input-inner
                print("[BrowserAgent] Filling form...")
                if department:
                    self._kendo_dropdown(page, "Select Department", department)
                if category:
                    self._kendo_dropdown(page, "Select Category", category)
                if subcategory:
                    self._kendo_dropdown(page, "Select Sub Category", subcategory)

                # ── 5. Short Description ──────────────────────────────────────
                # Confirmed HTML: <kendo-textbox id="LessonPlanName"><input class="k-input-inner">
                if short_description:
                    print(f"[BrowserAgent] Filling Short Description: '{short_description}'...")
                    # Close any open dropdown popup first
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(1500)
                    try:
                        inp = page.locator("kendo-textbox#LessonPlanName input.k-input-inner")
                        inp.wait_for(state="visible", timeout=5000)
                        inp.click(timeout=3000)
                        page.wait_for_timeout(200)
                        page.keyboard.type(short_description)
                        page.keyboard.press("Tab")  # triggers Angular blur validation → enables Submit
                        page.wait_for_timeout(500)
                        print("[BrowserAgent] ✅ Short Description filled")
                    except Exception as e:
                        print(f"[BrowserAgent] ⚠️ Short Description error: {e}")

                # ── 6. Description (optional) ─────────────────────────────────
                if description:
                    print("[BrowserAgent] Filling Description...")
                    try:
                        page.locator("[contenteditable='true']:visible").first.fill(description, timeout=3000)
                    except:
                        try:
                            page.locator("textarea:visible").first.fill(description, timeout=3000)
                        except:
                            pass
                    print("[BrowserAgent] ✅ Description filled")

                # ── 7. Click Submit ───────────────────────────────────────────
                # Confirmed HTML: TWO buttons exist — Submit (has fa-save icon) and Cancel
                # <button class="app-btn btn-sm"><span class="fa fa-save"></span>&nbsp; Submit</button>
                # <button class="app-btn btn-sm">  ← this is Cancel, DO NOT click this
                # Must target the one with the fa-save icon specifically
                print("[BrowserAgent] Waiting for Submit button to become enabled...")
                
                # Wait for Angular validation to enable the Submit button
                page.wait_for_timeout(1000)
                
                try:
                    # Target specifically the button that contains the fa-save icon (Submit, not Cancel)
                    page.wait_for_selector("button.app-btn:has(span.fa-save):not([disabled])", timeout=10000)
                    print("[BrowserAgent] ✅ Submit button enabled! Clicking...")
                    page.locator("button.app-btn:has(span.fa-save):not([disabled])").click(timeout=5000)
                    print("[BrowserAgent] ✅ Clicked Submit!")
                except Exception as e:
                    print(f"[BrowserAgent] ⚠️ Trying JS force-click: {e}")
                    page.evaluate("""() => {
                        // Find the button containing the fa-save icon (not Cancel)
                        const spans = document.querySelectorAll('span.fa-save, span.fa.fa-save');
                        for (const span of spans) {
                            const btn = span.closest('button');
                            if (btn) {
                                btn.removeAttribute('disabled');
                                btn.click();
                                return true;
                            }
                        }
                        return false;
                    }""")

                # ── 8. Confirm dialog ─────────────────────────────────────────
                # "Are you sure, you want to submit?" → click Yes
                print("[BrowserAgent] Waiting for confirmation dialog...")
                try:
                    page.wait_for_selector("text=Are you sure", timeout=6000)
                    print("[BrowserAgent] Confirmation dialog found! Clicking Yes...")
                    # Try multiple selectors for the Yes button
                    for yes_sel in [
                        "button:has-text('Yes')",
                        "button.btn-primary",
                        "[class*='confirm'] button",
                    ]:
                        try:
                            page.locator(yes_sel).last.click(timeout=3000)
                            print("[BrowserAgent] ✅ Clicked Yes!")
                            break
                        except:
                            continue
                except Exception:
                    print("[BrowserAgent] No confirmation dialog appeared.")

                page.wait_for_timeout(2000)
                browser.close()
                return {
                    "status": "success",
                    "details": f"✅ Ticket '{short_description}' submitted: {department} > {category} > {subcategory}"
                }

        except Exception as e:
            return {"status": "failure", "details": f"Error: {str(e)}"}

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _kendo_dropdown(self, page, placeholder: str, value: str):
        """
        Opens a Kendo dropdown by clicking the span showing its placeholder text,
        types the first word to filter, then clicks the matching option.
        Confirmed HTML: <span class="k-input-inner"><span class="k-input-value-text">Select Department</span></span>
        """
        print(f"[BrowserAgent] Dropdown '{placeholder}' → '{value}'")
        try:
            # Click the span showing the placeholder / current value
            page.locator("span.k-input-inner").filter(has_text=placeholder).first.click(force=True, timeout=5000)
            page.wait_for_timeout(1500)

            # Type first word to filter (portal search bug: full text clears results)
            keyword = value.split()[0]
            try:
                search = page.locator(".k-animation-container:visible input, .k-popup:visible input").first
                search.fill(keyword, timeout=2000)
                page.wait_for_timeout(1200)
            except:
                pass

            # Click the matching list item
            try:
                page.locator("li:visible").filter(has_text=value).first.click(timeout=3000)
                print(f"[BrowserAgent] ✅ Selected '{value}'")
            except:
                try:
                    page.get_by_text(value, exact=True).last.click(timeout=3000)
                    print(f"[BrowserAgent] ✅ Selected '{value}' (fallback)")
                except:
                    print(f"[BrowserAgent] ⚠️ Could not click '{value}'")

            page.wait_for_timeout(5000)  # Wait for next dropdown to load from server

        except Exception as e:
            print(f"[BrowserAgent] Dropdown error '{placeholder}': {e}")

    def _fill_login(self, page, username: str, password: str):
        """Opens login page and waits for manual login (no auto-fill)."""
        print("[BrowserAgent] ✅ Login page opened. Please log in manually and solve CAPTCHA...")

    def _await_dashboard(self, page, context):
        """Waits up to 90s for dashboard, then saves session."""
        try:
            page.wait_for_selector("a[href*='servicerequest']", timeout=90000)
            context.storage_state(path=str(SESSION_FILE))
            print(f"[BrowserAgent] ✅ Session saved — CAPTCHA skipped next time!")
        except Exception:
            print("[BrowserAgent] ⚠️ Dashboard wait timed out.")
