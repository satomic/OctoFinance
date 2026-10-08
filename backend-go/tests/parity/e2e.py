#!/usr/bin/env python3
"""Headed browser end-to-end test of the OctoFinance UI against one backend.

usage: e2e.py <base-url> <data-dir> <mock-port> <label>

Uses the installed Google Chrome (headed, slowed down so the run is watchable).
Scenario:
  1. first-run account setup (data dir without auth.json)
  2. every admin dashboard tab renders without errors
  3. Sync Data runs to completion (against the mock GitHub API)
  4. Settings modal opens and lists the PAT
  5. AI chat: a question answered through tool calls
  6. a regular GitHub user submits a budget request in the portal
  7. the admin approves it; the mock GitHub API receives the budget write
Screenshots go to ./shots/<label>/.
"""
import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect

BASE, DATA, MOCK, LABEL = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
SHOTS = os.path.join(os.environ.get("PARITY_RUNS", "/tmp/octofinance-parity"), "shots", LABEL)
os.makedirs(SHOTS, exist_ok=True)
USER = "real-akimoto-akira"
results = []


def step(name):
    def deco(fn):
        def run(*a):
            t = time.time()
            try:
                fn(*a)
                results.append((name, "PASS", f"{time.time() - t:.1f}s"))
                print(f"PASS  {name}", flush=True)
            except Exception as e:  # noqa
                results.append((name, "FAIL", str(e).splitlines()[0][:200]))
                print(f"FAIL  {name}: {e}", flush=True)
        return run
    return deco


def shot(page, name):
    page.screenshot(path=os.path.join(SHOTS, f"{name}.png"), full_page=False)


def mock_calls():
    with urllib.request.urlopen(f"http://127.0.0.1:{MOCK}/__calls") as r:
        return json.load(r)


def add_user_session(token):
    p = os.path.join(DATA, "auth_sessions.json")
    s = json.load(open(p)) if os.path.exists(p) else {}
    s[token] = {"login": USER, "name": USER, "avatar_url": "", "auth_type": "github",
                "is_admin": False, "github_id": 4242, "created_at": time.time()}
    json.dump(s, open(p, "w"), indent=2)


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="chrome", headless=False, slow_mo=250,
                                 args=["--window-size=1500,950"])
    ctx = browser.new_context(viewport={"width": 1480, "height": 860}, locale="en-US")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    @step("1. first-run setup creates the admin account")
    def setup():
        page.goto(BASE)
        expect(page.get_by_text("Create your account to get started")).to_be_visible(timeout=20000)
        page.get_by_placeholder("Username").fill("e2e-admin")
        pw_inputs = page.locator("input[type=password]")
        for i in range(pw_inputs.count()):
            pw_inputs.nth(i).fill("E2e-Passw0rd!")
        shot(page, "01-setup")
        page.get_by_role("button", name="Create Account").click()
        expect(page.get_by_role("button", name="Dashboard")).to_be_visible(timeout=20000)
        shot(page, "02-logged-in")
    setup()

    @step("2. all admin dashboard tabs render")
    def tabs():
        page.get_by_role("button", name="Dashboard").click()
        for label in ["Usage Metrics", "AI Usage", "Usage Report", "Cost Centers", "Unassigned Users",
                      "Enterprise Teams", "Budgets", "Requests"]:
            page.locator(".dashboard-tab-bar").get_by_role("button", name=label, exact=True).click()
            page.wait_for_load_state("networkidle")
            time.sleep(1.2)
            body = page.locator("body").inner_text()
            assert "Traceback" not in body and "Internal Server Error" not in body, f"{label}: server error shown"
            shot(page, "03-tab-" + label.lower().replace(" ", "-"))
        assert not errors, f"JS errors: {errors[:3]}"
    tabs()

    @step("3. Sync Data completes")
    def sync():
        before = len(mock_calls())
        page.get_by_role("button", name="Sync Data").click()
        shot(page, "04-syncing")
        # against the mock API the sync can finish before "Syncing..." is observable:
        # wait until the button is idle again and GitHub was actually called
        time.sleep(2)
        expect(page.get_by_role("button", name="Sync Data")).to_be_visible(timeout=180000)
        assert len(mock_calls()) > before, "Sync Data made no GitHub API calls"
        shot(page, "05-synced")
        paths = {c["path"] for c in mock_calls()}
        assert any(p.endswith("/copilot/billing/seats") for p in paths), "no seat fetch reached GitHub mock"
    sync()

    @step("4. Settings lists the configured PAT")
    def settings():
        page.get_by_role("button", name="Settings").click()
        expect(page.get_by_text("my-pat").first).to_be_visible(timeout=15000)
        shot(page, "06-settings")
        page.locator(".settings-close-btn").click()
        expect(page.locator(".settings-modal-overlay")).to_have_count(0, timeout=5000)
    settings()

    @step("5. AI chat answers using tools")
    def chat():
        sess_root = os.path.join(DATA, "sessions")
        started = time.time()
        page.get_by_role("button", name="Chat", exact=True).click()
        page.locator("button.session-new-btn").click()  # fresh conversation, no prior history
        time.sleep(1.5)
        box = page.locator("textarea.chat-input")
        box.fill("Using your tools, list the cost centers of enterprise 'satomic' with their member counts. "
                 "Answer as a short markdown table.")
        shot(page, "07-chat-question")
        page.get_by_role("button", name="Send").click()
        # streaming done when the Send button is back (Stop is shown while streaming)
        expect(page.get_by_role("button", name="Stop")).to_be_visible(timeout=30000)
        expect(page.get_by_role("button", name="Send")).to_be_visible(timeout=300000)
        time.sleep(1)
        shot(page, "08-chat-answer")
        text = page.locator(".chat-messages, .messages, main").first.inner_text()
        assert "|" in text or "cost" in text.lower(), "no answer rendered"
        calls = []
        for s in os.listdir(sess_root):
            f = os.path.join(sess_root, s, "tool_calls.jsonl")
            if os.path.exists(f) and os.path.getmtime(f) >= started:
                for l in open(f):
                    if l.strip() and json.loads(l).get("timestamp", 0) / 1000 >= started:
                        calls.append(json.loads(l)["tool_name"] or "?")
        assert calls, "no tool call was recorded"
        print("      tools used:", sorted(set(calls)), flush=True)
    chat()

    @step("6. regular user submits a budget request")
    def user_request():
        add_user_session("e2e-user")
        uctx = browser.new_context(viewport={"width": 1480, "height": 860}, locale="en-US")
        uctx.add_cookies([{"name": "octofinance_session", "value": "e2e-user", "url": BASE}])
        up = uctx.new_page()
        up.goto(BASE)
        expect(up.get_by_text("My Copilot Usage").first).to_be_visible(timeout=20000)
        time.sleep(1.5)
        shot(up, "09-user-portal")
        up.get_by_role("button", name="Requests").first.click() if up.get_by_role("button", name="Requests").count() else None
        up.locator("input[placeholder='100']").first.fill("123")
        up.locator("textarea").first.fill("E2E test: need more AI credits for a migration project")
        up.get_by_role("button", name="Submit Request").click()
        expect(up.get_by_text("Request submitted").first).to_be_visible(timeout=15000)
        shot(up, "10-user-request-submitted")
        uctx.close()
    user_request()

    @step("7. admin approves; budget is written to GitHub")
    def approve():
        before = len(mock_calls())
        page.get_by_role("button", name="Dashboard").click()
        page.locator(".dashboard-tab-bar").get_by_role("button", name="Requests", exact=True).click()
        expect(page.get_by_text(USER).first).to_be_visible(timeout=15000)
        shot(page, "11-admin-requests")
        page.get_by_role("button", name="Approve").first.click()
        confirm = page.get_by_role("button", name="Approve")
        if confirm.count() > 1:  # a confirmation step with its own Approve button
            confirm.last.click()
        time.sleep(4)
        shot(page, "12-approved")
        writes = [c for c in mock_calls()[before:] if c["method"] in ("POST", "PATCH") and "budgets" in c["path"]]
        assert writes, "no budget write reached the GitHub mock"
        print("      GitHub write:", writes[-1]["method"], writes[-1]["path"], json.dumps(writes[-1]["body"])[:160], flush=True)
    approve()

    time.sleep(2)
    browser.close()

print(f"\n=== E2E [{LABEL}] {BASE} ===")
for name, status, info in results:
    print(f"{status:5} {name}  ({info})")
sys.exit(0 if all(s == "PASS" for _, s, _ in results) else 1)
