#!/usr/bin/env python3
"""Exercise the deployed CodeFlow UI in real Chromium and save QA evidence.

Requires Python Playwright and its Chromium browser. BASE_URL selects the site;
PLAYWRIGHT_CHROMIUM_EXECUTABLE can select an existing local Chromium executable.
QA_ARTIFACTS_DIR selects the evidence directory. QA_IGNORE_HTTPS_ERRORS=1 is an
explicit local proxy workaround; certificate verification is enabled by default.
"""

import asyncio
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from playwright.async_api import async_playwright, expect


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get("QA_ARTIFACTS_DIR", "qa-artifacts")).resolve()
BASE_URL = os.environ.get("BASE_URL", "https://yuxiaoli.github.io/codeflow/")
REPO_URL = "https://github.com/octocat/Hello-World/"
TIMEOUT_MS = 60_000


def site_url(**parameters):
    url = urlsplit(BASE_URL)
    return urlunsplit((url.scheme, url.netloc, url.path or "/", urlencode(parameters), ""))


def fixture_zip():
    source = ROOT / "tests/fixtures/golden-world"
    target = ARTIFACTS / "golden-world.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, "golden-world/" + path.relative_to(source).as_posix())
    return target


async def save_download(download, name):
    destination = ARTIFACTS / f"{name}-{download.suggested_filename}"
    await download.save_as(destination)
    assert await download.failure() is None, "Browser download failed"
    assert destination.stat().st_size > 0, "Browser downloaded an empty file"
    return destination


async def wait_for_auto_download(page, downloads, evidence):
    deadline = asyncio.get_running_loop().time() + TIMEOUT_MS / 1000
    while asyncio.get_running_loop().time() < deadline:
        if downloads:
            return downloads[0]
        warning = page.get_by_role("button", name=re.compile(r"^Continue anyway", re.I))
        if await warning.count() and await warning.first.is_visible():
            await warning.first.click()
            evidence["continued_rate_warning"] = True
        await page.wait_for_timeout(250)
    raise AssertionError("Automatic export did not download within 60 seconds")


async def network_analysis(page, downloads, evidence, name):
    response = await page.goto(
        site_url(repo=REPO_URL, analyze="1", export="json"),
        wait_until="domcontentloaded",
    )
    assert response and response.status == 200, "Live page did not return HTTP 200"
    await expect(page.locator('input[aria-label="Repository URL"]').last).to_have_value(REPO_URL)
    download = await wait_for_auto_download(page, downloads, evidence)
    assert download.suggested_filename == "codeflow-analysis.json"
    artifact = await save_download(download, name)
    analysis = json.loads(artifact.read_text())
    assert analysis["stats"]["files"] == 1, "Live GitHub analysis has an unexpected file count"
    assert [file["path"] for file in analysis["files"]] == ["README"]
    assert analysis["stats"]["skipped"] == 0, "Live GitHub analysis is partial"
    assert analysis["connections"] == []
    await expect(page.locator("svg .nc")).to_have_count(1)
    api = evidence["github_responses"]
    assert any("/git/trees/" in item["url"] for item in api), "GitHub tree was not fetched"
    assert any("/contents/README" in item["url"] for item in api), "GitHub source was not fetched"
    assert all(item["status"] == 200 for item in api), f"GitHub API failures: {api}"
    evidence.update({"stats": analysis["stats"], "auto_export": str(artifact)})
    await page.screenshot(path=ARTIFACTS / f"{name}.png", full_page=True)


async def local_zip_analysis(page, downloads, evidence, archive):
    response = await page.goto(site_url(export="diagram"), wait_until="domcontentloaded")
    assert response and response.status == 200, "Live page did not return HTTP 200"
    async with page.expect_file_chooser() as chooser:
        await page.get_by_role("button", name="Open ZIP archive", exact=True).last.click()
    await (await chooser.value).set_files(archive)
    download = await wait_for_auto_download(page, downloads, evidence)
    assert download.suggested_filename == "codeflow-architecture.svg"
    artifact = await save_download(download, "fixture-auto")
    svg = ET.fromstring(artifact.read_bytes())
    assert svg.tag == "{http://www.w3.org/2000/svg}svg", "Diagram export is not an SVG"
    assert len(list(svg.iter())) > 5, "Diagram export contains no meaningful drawing"
    visualization = page.get_by_role("combobox", name="Visualization type")
    await expect(visualization).to_have_value("architecture")
    await expect(page.locator(".mermaid-render svg")).to_be_visible()
    await page.screenshot(path=ARTIFACTS / "fixture-diagram.png", full_page=True)

    await visualization.select_option("code")
    card = page.locator('[data-code-card="src/math.js"]')
    await card.locator(".code-card-name").click()
    await expect(card).to_have_class(re.compile(r"\bprimary\b"))
    source_lines = await card.locator(".file-preview-text").all_inner_texts()
    rendered = "\n".join(line.rstrip() for line in source_lines).rstrip()
    original = (ROOT / "tests/fixtures/golden-world/src/math.js").read_text()
    expected_source = "\n".join(line.rstrip() for line in original.splitlines()).rstrip()
    assert rendered == expected_source, "Code view changed the visible source text"
    assert "class=" not in rendered, "Code view leaked highlighting markup into source"
    await page.screenshot(path=ARTIFACTS / "fixture-code.png", full_page=True)

    await visualization.select_option("graph")
    await expect(page.locator("svg .nc")).to_have_count(6)
    await page.get_by_role("button", name="Export analysis", exact=True).last.click()
    async with page.expect_download() as manual_download:
        await page.get_by_text("Raw JSON", exact=True).click()
    raw_artifact = await save_download(await manual_download.value, "fixture-manual")
    analysis = json.loads(raw_artifact.read_text())
    for metric, expected in {"files": 6, "functions": 7, "connections": 6, "loc": 44}.items():
        assert analysis["stats"][metric] == expected, f"Fixture metric {metric} is incorrect"
    expected_paths = sorted(
        path.relative_to(ROOT / "tests/fixtures/golden-world").as_posix()
        for path in (ROOT / "tests/fixtures/golden-world").rglob("*") if path.is_file()
    )
    assert sorted(file["path"] for file in analysis["files"]) == expected_paths
    assert len(analysis["connections"]) == 6
    await page.screenshot(path=ARTIFACTS / "fixture-graph.png", full_page=True)
    evidence.update({
        "stats": analysis["stats"], "auto_diagram": str(artifact),
        "manual_json": str(raw_artifact), "code_source_matches_fixture": True,
    })


async def run_case(browser, name, viewport, action):
    evidence = {"status": "failed", "page_errors": [], "request_failures": [],
                "console_errors": [], "github_responses": []}
    context = await browser.new_context(
        viewport=viewport, accept_downloads=True,
        ignore_https_errors=os.environ.get("QA_IGNORE_HTTPS_ERRORS") == "1",
    )
    context.set_default_timeout(TIMEOUT_MS)
    page = await context.new_page()
    downloads = []
    page.on("download", lambda download: downloads.append(download))
    page.on("pageerror", lambda error: evidence["page_errors"].append(str(error)))
    page.on("requestfailed", lambda request: evidence["request_failures"].append(
        {"url": request.url, "failure": request.failure}))
    page.on("console", lambda message: evidence["console_errors"].append(message.text)
            if message.type == "error" else None)
    page.on("response", lambda response: evidence["github_responses"].append(
        {"url": response.url, "status": response.status})
            if "api.github.com" in response.url else None)
    try:
        await action(page, downloads, evidence)
        assert not evidence["page_errors"], f"JavaScript errors: {evidence['page_errors']}"
        assert not evidence["request_failures"], f"Failed requests: {evidence['request_failures']}"
        evidence["status"] = "passed"
    except Exception as error:
        evidence["error"] = str(error)
        try:
            await page.screenshot(path=ARTIFACTS / f"{name}-failure.png", full_page=True)
            evidence["body_excerpt"] = (await page.locator("body").inner_text())[:6000]
        except Exception as artifact_error:
            evidence["artifact_error"] = str(artifact_error)
    finally:
        evidence["final_url"] = page.url
        await context.close()
    print(f"{name}: {evidence['status']}", flush=True)
    return name, evidence


async def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    archive = fixture_zip()
    async with async_playwright() as playwright:
        options = {"headless": True, "args": ["--no-sandbox"]}
        executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
        if executable:
            options["executable_path"] = executable
        browser = await playwright.chromium.launch(**options)
        try:
            cases = await asyncio.gather(
                run_case(browser, "desktop", {"width": 1440, "height": 1000},
                         lambda page, downloads, evidence: network_analysis(page, downloads, evidence, "desktop")),
                run_case(browser, "mobile", {"width": 390, "height": 844},
                         lambda page, downloads, evidence: network_analysis(page, downloads, evidence, "mobile")),
                run_case(browser, "fixture", {"width": 1440, "height": 1000},
                         lambda page, downloads, evidence: local_zip_analysis(page, downloads, evidence, archive)),
            )
        finally:
            await browser.close()
    results = {"base_url": BASE_URL, "cases": dict(cases)}
    (ARTIFACTS / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    failed = [name for name, evidence in cases if evidence["status"] != "passed"]
    if failed:
        raise SystemExit(f"Live browser QA failed: {', '.join(failed)}; see {ARTIFACTS / 'results.json'}")
    print(f"All live browser checks passed; evidence: {ARTIFACTS / 'results.json'}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
