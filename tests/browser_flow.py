from __future__ import annotations

import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8767")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("test-results/browser-flow"),
        help="screenshot directory (default: test-results/browser-flow)",
    )
    parser.add_argument(
        "--browser-executable",
        type=Path,
        help="optional Chromium-compatible executable; defaults to Playwright Chromium",
    )
    args = parser.parse_args()
    if args.browser_executable is not None and not args.browser_executable.is_file():
        parser.error(f"browser executable does not exist: {args.browser_executable}")
    args.output.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        executable_path = (
            str(args.browser_executable) if args.browser_executable is not None else None
        )
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        console_errors: list[str] = []
        failed_urls: list[str] = []
        requested_urls: list[str] = []
        stage = {"name": "initial-load"}
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("response", lambda response: failed_urls.append(f"{stage['name']}: {response.status} {response.url}") if response.status >= 400 else None)
        page.on("request", lambda request: requested_urls.append(request.url))
        page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=args.base_url)
        page.goto(args.base_url, wait_until="networkidle")
        page.locator('body[data-demo-state="normal"]').wait_for()
        page.screenshot(path=args.output / "a-normal.png", full_page=True)

        page.locator('[data-open-panel="draft"]').first.click()
        page.locator('[data-draft-tab="it"]').first.click()
        it_area = page.locator("#conversationItDraft")
        original = it_area.input_value()
        edited = original + "\n직접 추가한 질문입니다."
        it_area.fill(edited)

        page.locator('#conversationView [data-field="tenure"]').fill("2년 10개월")
        page.locator('#conversationView [data-field="symptom"]').fill("오늘부터 영상 통화 중")
        page.locator('#conversationView [data-field="purchase"]').select_option("not-purchased")
        page.locator('#conversationView [data-apply-conditions]').first.click()
        page.locator('body[data-demo-state="normal"]').wait_for()
        assert it_area.input_value() == edited
        assert "새 제안:" in page.locator('#conversationView [data-proposal-note="it"]').inner_text()
        page.locator('#conversationView [data-reset-draft="it"]').click()
        assert "2년 10개월" in it_area.input_value()
        assert "4년째" not in it_area.input_value()
        page.locator('#conversationView [data-copy-draft="it"]').click()
        assert page.evaluate("navigator.clipboard.readText()") == it_area.input_value()

        preserved = it_area.input_value() + "\n근거가 빠져도 남을 편집입니다."
        it_area.fill(preserved)
        page.locator('[data-demo-state-button="missing"]').click()
        page.locator('body[data-demo-state="missing"]').wait_for()
        assert page.locator("#conversationMissingMonitorDraft").is_visible()
        page.locator('[data-demo-state-button="normal"]').click()
        page.locator('body[data-demo-state="normal"]').wait_for()
        page.locator('[data-draft-tab="it"]').first.click()
        assert it_area.input_value() == preserved

        stage["name"] = "expected-network-failure"
        page.route("**/api/workspace", lambda route: route.abort())
        page.locator('[data-demo-state-button="loading"]').click()
        page.locator('body[data-demo-state="error"]').wait_for()
        assert page.locator("#connectionNotice").is_visible()
        assert it_area.input_value() == preserved
        page.unroute("**/api/workspace")
        stage["name"] = "network-recovery"
        page.locator("#connectionNotice [data-retry]").click()
        page.locator('body[data-demo-state="normal"]').wait_for()
        console_errors[:] = [message for message in console_errors if "ERR_FAILED" not in message]

        stage["name"] = "request-order"
        def delay_first(route):
            response = route.fetch()
            time.sleep(0.5)
            route.fulfill(response=response)

        page.route("**/api/workspace", delay_first, times=1)
        page.evaluate("""
          var field = document.querySelector('#conversationView [data-field="tenure"]');
          var button = document.querySelector('#conversationView [data-apply-conditions]');
          field.value = "오래된 요청";
          field.dispatchEvent(new Event("input", { bubbles: true }));
          button.click();
          field.value = "최신 요청";
          field.dispatchEvent(new Event("input", { bubbles: true }));
          button.click();
        """)
        page.locator('body[data-demo-state="normal"]').wait_for()
        page.wait_for_timeout(650)
        assert "최신 요청" in page.locator('#conversationView [data-proposal-note="it"]').inner_text()
        assert "오래된 요청" not in page.locator('#conversationView [data-proposal-note="it"]').inner_text()
        page.unroute("**/api/workspace")

        stage["name"] = "html-escaping"
        marker = '\"><img id="injected-node" src=x onerror="window.hacked=1">'
        page.locator('#conversationView [data-field="symptom"]').fill(marker)
        page.locator('#conversationView [data-apply-conditions]').first.click()
        page.locator('body[data-demo-state="normal"]').wait_for()
        assert page.locator("#injected-node").count() == 0
        assert page.evaluate("window.hacked === undefined")
        assert marker in page.locator("#conversationView [data-stated-facts]").inner_text()

        stage["name"] = "workflow-layout"
        page.locator('[data-mode="workflow"]').click()
        assert page.locator("#workflowView").is_visible()
        page.locator('#workflowView [data-step="3"]').click()
        workflow_results = page.locator("#workflowView .result-list li")
        assert workflow_results.count() == 3
        assert "같은 신청으로 묶을 수 있는지" in workflow_results.nth(2).inner_text()
        assert "확인하지 못했습니다" in workflow_results.nth(2).inner_text()
        page.screenshot(path=args.output / "b-results-boundary.png", full_page=True)
        page.locator('[data-demo-state-button="missing"]').click()
        page.locator('body[data-demo-state="missing"]').wait_for()

        revision_page = browser.new_page(viewport={"width": 1440, "height": 1000})
        revision_errors: list[str] = []
        revision_page.on(
            "console",
            lambda message: revision_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        revision_page.goto(args.base_url, wait_until="networkidle")
        revision_page.locator('body[data-demo-state="normal"]').wait_for()
        revision_page.locator('[data-open-panel="draft"]').first.click()
        revision_page.locator('[data-draft-tab="it"]').first.click()
        revision_area = revision_page.locator("#conversationItDraft")
        revision_field = revision_page.locator(
            '#conversationView [data-field="tenure"]'
        )
        revision_button = revision_page.locator(
            '#conversationView [data-apply-conditions]'
        ).first
        revision_apply = revision_page.locator(
            '#conversationView [data-reset-draft="it"]'
        )

        revision_field.fill("4년")
        revision_button.click()
        revision_page.locator('body[data-demo-state="normal"]').wait_for()
        revision_apply.click()
        applied_four_year_text = revision_area.input_value()
        assert "4년째" in applied_four_year_text

        revision_field.fill("2년 10개월")
        assert revision_page.locator("#inputChangedNotice").is_visible()
        assert revision_apply.is_disabled()
        assert "입력한 내용이 이 제안을 만든 뒤 바뀌었습니다" in revision_page.locator(
            '#conversationView [data-proposal-note="it"]'
        ).inner_text()
        assert revision_area.input_value() == applied_four_year_text

        def delay_pending_response(route):
            response = route.fetch()
            time.sleep(0.5)
            route.fulfill(response=response)

        revision_page.route("**/api/workspace", delay_pending_response, times=1)
        revision_page.evaluate("""
          var field = document.querySelector('#conversationView [data-field="tenure"]');
          var button = document.querySelector('#conversationView [data-apply-conditions]');
          field.value = "4년";
          field.dispatchEvent(new Event("input", { bubbles: true }));
          button.click();
          field.value = "2년 10개월";
          field.dispatchEvent(new Event("input", { bubbles: true }));
        """)
        revision_page.locator('body[data-demo-state="normal"]').wait_for()
        assert revision_page.locator("#inputChangedNotice").is_visible()
        assert revision_apply.is_disabled()
        assert revision_area.input_value() == applied_four_year_text
        assert "4년째" in applied_four_year_text
        assert "2년 10개월" not in applied_four_year_text
        revision_page.screenshot(path=args.output / "input-changed.png", full_page=True)
        revision_page.unroute("**/api/workspace")
        assert not revision_errors, revision_errors
        revision_page.close()

        clean = browser.new_page(viewport={"width": 1440, "height": 1000})
        clean.goto(args.base_url, wait_until="networkidle")
        clean.locator('body[data-demo-state="normal"]').wait_for()
        clean.locator('[data-mode="workflow"]').click()
        clean.screenshot(path=args.output / "b-normal.png", full_page=True)
        clean.locator('[data-demo-state-button="missing"]').click()
        clean.locator('body[data-demo-state="missing"]').wait_for()
        clean.screenshot(path=args.output / "b-missing.png", full_page=True)
        clean.close()

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.goto(args.base_url, wait_until="networkidle")
        mobile.locator('body[data-demo-state="normal"]').wait_for()
        overflow = mobile.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 0, overflow
        mobile.screenshot(path=args.output / "mobile.png", full_page=True)
        mobile.close()

        assert not console_errors, {"console": console_errors, "http": failed_urls}
        assert not failed_urls, failed_urls
        assert all(url.startswith(args.base_url) for url in requested_urls), requested_urls
        browser.close()
        print("browser flow: PASS")


if __name__ == "__main__":
    main()
