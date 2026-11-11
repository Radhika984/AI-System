"""Browser end-to-end checks for the faculty console (headless Chromium via Playwright).

    pip install playwright==1.48.0 && python -m playwright install chromium
    cd frontend && npm ci && cd ..
    python tests/e2e/run_e2e.py            # screenshots -> tests/e2e/out/ (gitignored)
    E2E_PASSCODE=<canary> E2E_KEEP_LOGS=1 python tests/e2e/run_e2e.py   # leak scan: keeps logs in out/logs/

Self-contained: starts the FastAPI app on a throwaway STATE_DIR with a random reviewer
passcode, starts the Vite dev server proxying to it, runs every check, builds a snapshot
bundle whose API is unreachable and checks read-only mode, then stops everything.
Never touches data/ or the real state/ directory. Exit code 0 = all checks passed.
Not collected by pytest (needs a browser + Node); run it explicitly.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("E2E_OUT", ROOT / "tests" / "e2e" / "out"))
WIN = os.name == "nt"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, timeout: float = 60) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    return False


def start(cmd: list[str], cwd: Path, env: dict, log: Path) -> subprocess.Popen:
    f = open(log, "w", encoding="utf-8")
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT, shell=WIN and cmd[0] == "npx")


def stop(p: subprocess.Popen | None) -> None:
    if p and p.poll() is None:
        if WIN:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
        else:
            p.terminate()
            p.wait(10)


def api_json(base: str, path: str):
    return json.load(urllib.request.urlopen(base + path, timeout=10))


def browser_checks(ui: str, api: str, passcode: str) -> None:
    from playwright.sync_api import sync_playwright

    queue = api_json(api, "/api/queue")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        page_errors: list[str] = []
        pg.on("pageerror", lambda e: page_errors.append(str(e)))
        pg.goto(ui)
        pg.wait_for_selector("text=Why this recommendation?", timeout=60000)
        pg.screenshot(path=OUT / "01_queue_and_first_case.png")

        # every case renders
        pg.locator("nav button", has_text="All").first.click()
        rendered = 0
        for i in range(len(queue)):
            pg.locator("nav ul li button").nth(i).click()
            pg.wait_for_selector("text=Original question", timeout=15000)
            rendered += 1
        check("all cases render", rendered == len(queue) == 39, f"{rendered}/{len(queue)}")
        pg.locator("nav button", has_text="half life period").first.click()
        pg.wait_for_selector("text=What the student receives")
        check("native MathML present", pg.evaluate("document.querySelectorAll('math').length") > 0)
        check("no page errors while browsing", not page_errors, "; ".join(page_errors)[:200])

        # B1: no passcode -> view only, nothing posted
        n0 = len(api_json(api, "/api/audit"))
        pg.locator("nav button", has_text="To review").first.click()
        pg.locator("nav ul li button").nth(0).click()
        pg.wait_for_selector("text=What the student receives")
        check("view-only without passcode", pg.locator("text=View only. Enter the").count() == 1
              and pg.get_by_role("button", name="Reject").count() == 0)
        pg.keyboard.press("a")
        pg.wait_for_timeout(600)
        check("keyboard approve ignored without passcode", len(api_json(api, "/api/audit")) == n0)

        # B1: wrong passcode -> server refuses, UI says so, nothing changes
        pg.fill("input[aria-label='Your name for the audit log']", "E2E Reviewer")
        pg.fill("input[aria-label='Reviewer passcode']", "definitely-wrong")
        pg.get_by_role("button", name="Reject").click()
        pg.wait_for_selector("text=Reviewer passcode is incorrect", timeout=10000)
        check("wrong passcode rejected by server", len(api_json(api, "/api/audit")) == n0)
        pg.screenshot(path=OUT / "02_wrong_passcode.png")

        # correct passcode -> approve via keyboard on rank 1, auto-advance
        pg.fill("input[aria-label='Reviewer passcode']", passcode)
        pg.locator("nav button", has_text="To review").first.click()
        pg.locator("nav ul li button").nth(0).click()
        pg.wait_for_selector("text=What the student receives")
        first_head = pg.locator("article h2").first.inner_text()
        pg.locator("body").click(position={"x": 700, "y": 300})
        pg.keyboard.press("a")
        pg.wait_for_timeout(1500)
        check("passcode never rendered into page HTML", passcode not in pg.content())
        a = api_json(api, "/api/audit")
        check("approve with passcode audited", a[0]["action"] == "approve" and a[0]["actor"] == "E2E Reviewer")
        advanced_to = pg.locator("article h2").first.inner_text()
        check("auto-advance after decision", advanced_to != first_head, f"{first_head!r} -> {advanced_to!r}")

        # edit: guard error surfaced, then a valid faculty edit
        pg.locator("nav button", has_text="All").first.click()
        pg.locator("nav button", has_text="Two options are identical").first.click()
        pg.wait_for_selector("text=What the student receives")
        pg.get_by_role("button", name="Edit").click()
        pg.locator("textarea").nth(0).fill("this text is not in the question")
        pg.locator("textarea").nth(1).fill("x")
        pg.get_by_role("button", name="Validate & apply").click()
        pg.wait_for_timeout(800)
        check("guard error shown for bad edit", pg.locator("text=exactly once").count() > 0)
        pg.locator("textarea").nth(0).fill("(C) 0 W")
        pg.locator("textarea").nth(1).fill("(C) 500 W")
        pg.get_by_role("button", name="Validate & apply").click()
        pg.wait_for_timeout(1500)
        a = api_json(api, "/api/audit")
        check("faculty edit applied + audited", a[0]["action"] == "edit" and a[0]["edit"]["replace"] == "(C) 500 W")

        # reject an auto-applied key -> reverted
        pg.locator("nav button", has_text="density of a gas").first.click()
        pg.wait_for_selector("text=What the student receives")
        pg.get_by_role("button", name="Reject").click()
        pg.wait_for_timeout(1500)
        case = api_json(api, "/api/cases/68e870ef42c06737d6e565c4")
        acts = [e["action"] for e in api_json(api, "/api/audit")[:2]]
        check("reject reverts auto-apply", case["live_answer"] == "A" and acts == ["reject", "revert_auto_apply"], str(acts))

        pg.get_by_role("button", name="Audit log").click()
        pg.wait_for_selector("text=Audit log (all questions)")
        pg.screenshot(path=OUT / "03_audit_drawer.png")
        pg.keyboard.press("Escape")

        # mobile
        m = b.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
        m.goto(ui)
        m.wait_for_selector("nav", timeout=30000)
        m.screenshot(path=OUT / "04_mobile_queue.png")
        sw = m.evaluate("document.documentElement.scrollWidth")
        check("mobile: no horizontal scroll", sw <= 390, f"scrollWidth={sw}")
        b.close()


def snapshot_check(port: int) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(f"http://127.0.0.1:{port}/")
        pg.wait_for_selector("text=Read-only snapshot.", timeout=60000)
        pg.wait_for_selector("text=Why this recommendation?", timeout=30000)
        pg.screenshot(path=OUT / "05_snapshot_mode.png")
        no_buttons = pg.get_by_role("button", name="Reject").count() == 0
        check("snapshot mode: banner + actions disabled", no_buttons and pg.locator("text=actions are disabled").count() > 0)
        b.close()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    data_before = hashlib.sha256((ROOT / "data" / "questions.json").read_bytes()).hexdigest()
    tmp = Path(tempfile.mkdtemp(prefix="rf-e2e-"))
    passcode = os.environ.get("E2E_PASSCODE") or secrets.token_urlsafe(12)  # E2E_PASSCODE: canary for leak scans
    api_port, ui_port, prev_port = free_port(), free_port(), free_port()
    api, ui = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{ui_port}/"
    env = {**os.environ, "STATE_DIR": str(tmp / "state"), "REVIEWER_PASSCODE": passcode,
           "ADMIN_RESET_TOKEN": "", "API_PROXY": api}
    procs = []
    try:
        procs.append(start([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(api_port)],
                           ROOT / "backend", env, tmp / "api.log"))
        procs.append(start(["npx", "vite", "--port", str(ui_port), "--strictPort", "--host", "127.0.0.1"],
                           ROOT / "frontend", env, tmp / "vite.log"))
        check("API starts", wait_http(api + "/health"))
        check("console starts", wait_http(ui))
        browser_checks(ui, api, passcode)

        dist = tmp / "dist_snapshot"
        r = subprocess.run(["npx", "vite", "build", "--outDir", str(dist), "--emptyOutDir"], cwd=ROOT / "frontend",
                           env={**env, "VITE_API_BASE": "http://127.0.0.1:9"}, capture_output=True, text=True, shell=WIN)
        check("snapshot build (unreachable API)", r.returncode == 0, r.stderr[-200:] if r.returncode else "")
        procs.append(start(["npx", "vite", "preview", "--outDir", str(dist), "--port", str(prev_port), "--strictPort",
                            "--host", "127.0.0.1"], ROOT / "frontend", env, tmp / "preview.log"))
        if wait_http(f"http://127.0.0.1:{prev_port}/"):
            snapshot_check(prev_port)
    except Exception as e:  # noqa: BLE001 - report any harness failure as a FAIL
        check("harness", False, repr(e)[:300])
    finally:
        for p in procs:
            stop(p)
        if os.environ.get("E2E_KEEP_LOGS") == "1":  # keep server logs + audit for leak scans
            keep = OUT / "logs"
            keep.mkdir(parents=True, exist_ok=True)
            for f in ("api.log", "vite.log", "preview.log", "state/audit.jsonl", "state/patches.json"):
                if (tmp / f).exists():
                    shutil.copy(tmp / f, keep / Path(f).name)
        shutil.rmtree(tmp, ignore_errors=True)
    check("original data unchanged", hashlib.sha256((ROOT / "data" / "questions.json").read_bytes()).hexdigest() == data_before)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} e2e checks passed; screenshots in {OUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
