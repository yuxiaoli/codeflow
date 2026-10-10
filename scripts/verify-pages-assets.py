"""Wait for this checkout's Pages HTML, then verify every vendored runtime asset."""

import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = os.environ.get("BASE_URL", "https://yuxiaoli.github.io/codeflow/").rstrip("/") + "/"
EXPECTED_SHA = os.environ.get("GITHUB_SHA") or subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
).strip()
ARTIFACTS = Path(os.environ.get("QA_ARTIFACTS_DIR", "qa-artifacts"))
ARTIFACTS.mkdir(parents=True, exist_ok=True)


def fetch(path):
    request = urllib.request.Request(
        BASE_URL + path + "?pages-qa=" + EXPECTED_SHA,
        headers={"Cache-Control": "no-cache"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read()


def main():
    checkout_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    assert checkout_sha == EXPECTED_SHA, "QA checkout must match the triggering commit"
    expected_html = (ROOT / "index.html").read_bytes()
    deadline = time.monotonic() + 300
    last_failure = "Pages has not returned this checkout's HTML"
    while time.monotonic() < deadline:
        try:
            status, html = fetch("index.html")
            if status == 200 and html == expected_html:
                break
            last_failure = "Pages HTML differs from the triggering commit"
        except (urllib.error.URLError, TimeoutError) as error:
            last_failure = str(error)
        time.sleep(5)
    else:
        raise AssertionError("Pages did not settle to " + EXPECTED_SHA + ": " + last_failure)

    manifest = json.loads((ROOT / "vendor/manifest.json").read_text())
    assets = [{"file": "index.html", "sha256": hashlib.sha256(expected_html).hexdigest()}]
    assets += [{"file": "vendor/" + asset["file"], "sha256": asset["sha256"]} for asset in manifest["assets"]]

    def check(asset):
        status, data = fetch(asset["file"])
        actual = hashlib.sha256(data).hexdigest()
        return {"path": asset["file"], "status": status, "bytes": len(data),
                "sha256": actual, "matches_commit": actual == asset["sha256"]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check, assets))
    report = {"commit": EXPECTED_SHA, "url": BASE_URL, "checks": results,
              "all_passed": all(item["status"] == 200 and item["matches_commit"] for item in results)}
    (ARTIFACTS / "pages-assets.json").write_text(json.dumps(report, indent=2))
    assert report["all_passed"], "Published runtime assets differ from this checkout"
    print(f"Verified exact HTML and {len(results) - 1} runtime assets for {EXPECTED_SHA}")


if __name__ == "__main__":
    main()
