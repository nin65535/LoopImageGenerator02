"""Verify a running development or built UI with installed Chrome."""

import argparse

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(args.url)
            expect(page.get_by_role("heading", name="LoopImageGenerator V2")).to_be_visible()
            expect(page.get_by_role("status")).to_have_attribute("data-state", "connected")
            response = page.request.get(f"{args.url.rstrip('/')}/api/health")
            assert response.ok and response.json()["status"] == "ok"
            assert not errors, errors
            print(f"Chrome React display and browser-to-API connection: OK ({args.url})")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
