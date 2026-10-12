"""End-to-end: the compiled web UI in a real browser (Playwright + Chromium), served by kgdemo.server.

Skipped when web/dist is not built or Playwright's Chromium is not installed.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest

from kgdemo.server import WEB_DIST, app

playwright_api = pytest.importorskip("playwright.sync_api")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url(graph):
    if not (WEB_DIST / "index.html").is_file():
        pytest.skip("web UI not built (cd web && npm install && npm run build)")
    import uvicorn
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def page(base_url):
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:          # browser binaries not installed
            pytest.skip(f"Chromium not available: {exc}")
        pg = browser.new_page(viewport={"width": 1440, "height": 900})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" else None)
        yield pg
        browser.close()


def _graph_heights(page) -> list[int]:
    return page.evaluate("() => [...document.querySelectorAll('div')].filter(d => d._cyreg)"
                         ".map(d => d._cyreg.cy.height())")


def test_walk_the_demo(page, base_url):
    page.goto(base_url + "/")
    page.wait_for_load_state("networkidle")
    assert "Hartwell Family Trust" in page.inner_text("h1")
    # presenter keys move between steps (client-side navigation must not crash)
    page.keyboard.press("ArrowRight")
    page.wait_for_url("**/data")
    page.wait_for_selector("text=Client relationships")
    page.get_by_role("button", name="Documents").click()
    page.wait_for_selector("text=Douglas Whitfield, Meredith Calloway")

    page.keyboard.press("ArrowRight")
    page.wait_for_url("**/model")
    page.wait_for_function("() => [...document.querySelectorAll('div')].some(d => d._cyreg)")
    assert all(h > 300 for h in _graph_heights(page))          # the ontology diagram has a real canvas
    page.get_by_role("button", name="Keyword search vs meaning").click()
    page.wait_for_selector("text=Found only through the semantic model")

    page.goto(base_url + "/extract")
    page.get_by_role("button", name="Extract", exact=True).click()
    page.wait_for_selector("text=Relationships, each checked against the ontology")
    assert "ATTENDED" in page.inner_text("body")
    page.wait_for_selector("text=Open in Neo4j Browser")
    assert all(h > 300 for h in _graph_heights(page))

    page.goto(base_url + "/queries")
    link = page.get_by_role("link", name="Open in Neo4j Browser")
    assert "cmd=edit&arg=" in link.get_attribute("href")
    page.wait_for_selector("text=rows")
    page.get_by_role("button", name="Look-through theme exposure by client").click()
    page.wait_for_selector("text=Hartwell Family Trust")

    page.goto(base_url + "/graph-rag")
    page.get_by_role("button", name="Ask", exact=True).click()
    page.wait_for_selector("text=What each approach could see", timeout=60000)
    page.get_by_role("button", name="Show the traversal").click()
    page.wait_for_selector("text=The Cypher behind it")
    page.get_by_role("button", name="Look-through exposure, fund by fund").click()
    assert "'C-001'" in page.locator("pre code").last.inner_text()
    page.locator("button", has_text="DOC-").first.click()
    page.wait_for_selector('[role="dialog"]')
    page.keyboard.press("Escape")

    page.goto(base_url + "/value")
    page.wait_for_selector("text=Institutional knowledge")
    assert page.errors == []
