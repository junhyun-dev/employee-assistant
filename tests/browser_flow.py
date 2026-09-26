from __future__ import annotations

import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def assert_evidence_actions(page, *, show_all: bool, return_to_answer: bool) -> None:
    expected = {
        "[data-show-all-evidence]": show_all,
        "[data-return-to-answer]": return_to_answer,
    }
    for selector, should_show in expected.items():
        button = page.locator(selector)
        assert (button.get_attribute("hidden") is None) is should_show
        assert button.is_visible() is should_show
        assert (button.bounding_box() is not None) is should_show
        display = button.evaluate("element => getComputedStyle(element).display")
        assert (display != "none") is should_show, {selector: display}

    page.locator("[data-evidence-view-title]").focus()
    page.keyboard.press("Tab")
    active = page.evaluate(
        """() => ({
          showAll: document.activeElement.matches('[data-show-all-evidence]'),
          returnToAnswer: document.activeElement.matches('[data-return-to-answer]')
        })"""
    )
    if show_all:
        assert active == {"showAll": True, "returnToAnswer": False}
    elif return_to_answer:
        assert active == {"showAll": False, "returnToAnswer": True}
    else:
        assert active == {"showAll": False, "returnToAnswer": False}


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
        assert_evidence_actions(page, show_all=False, return_to_answer=False)

        monitor_evidence_button = page.locator(
            '#conversationView [data-open-answer-evidence="monitor"]:visible'
        ).first
        monitor_evidence_button.click()
        assert "모니터 답에 사용한 참고 문서" in page.locator(
            "[data-evidence-view-title]"
        ).inner_text()
        answer_source_cards = page.locator(
            '.panel-content[data-panel-content="evidence"] .state-only:visible .source-card'
        )
        assert answer_source_cards.count() == 2
        answer_source_text = [text.lower() for text in answer_source_cards.all_inner_texts()]
        assert any("equipment" in text for text in answer_source_text)
        assert any("approved-wfh-computer" in text for text in answer_source_text)
        assert all("laptops-insurance-repairs" not in text for text in answer_source_text)
        assert_evidence_actions(page, show_all=True, return_to_answer=True)
        page.locator("[data-show-all-evidence]").click()
        assert "전체 문서" in page.locator("[data-evidence-view-title]").inner_text()
        assert answer_source_cards.count() == 3
        assert_evidence_actions(page, show_all=False, return_to_answer=True)
        page.locator("[data-return-to-answer]").click()
        page.wait_for_timeout(250)
        assert page.evaluate(
            "() => document.activeElement === document.querySelector('#conversationView [data-open-answer-evidence=\"monitor\"]')"
        )
        assert_evidence_actions(page, show_all=False, return_to_answer=False)

        laptop_evidence_button = page.locator(
            '#conversationView [data-open-answer-evidence="laptop"]:visible'
        ).first
        laptop_evidence_button.click()
        assert "노트북 답에 사용한 참고 문서" in page.locator(
            "[data-evidence-view-title]"
        ).inner_text()
        assert answer_source_cards.count() == 1
        assert "laptops-insurance-repairs" in answer_source_cards.first.inner_text().lower()
        page.screenshot(path=args.output / "answer-evidence-a.png", full_page=True)
        page.locator("[data-return-to-answer]").click()

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
        assert "새 제안:" in page.locator('#conversationItDraft + [data-proposal-note="it"]').inner_text()
        page.locator('#conversationItDraft ~ .card-actions [data-reset-draft="it"]').click()
        proposal_dialog = page.locator("#proposalReviewDialog")
        assert proposal_dialog.is_visible()
        assert page.locator("#proposalReviewCurrent").inner_text() == edited
        assert "2년 10개월째" in page.locator("#proposalReviewProposed").inner_text()
        assert it_area.input_value() == edited
        page.screenshot(path=args.output / "proposal-review-a.png", full_page=True)
        page.keyboard.press("Escape")
        assert not proposal_dialog.is_visible()
        assert it_area.input_value() == edited
        page.locator('#conversationItDraft ~ .card-actions [data-reset-draft="it"]').click()
        page.locator("[data-proposal-review-confirm]").click()
        assert "2년 10개월" in it_area.input_value()
        assert "4년째" not in it_area.input_value()
        current_manual_edit = it_area.input_value() + "\n현재 조건에서 직접 고친 문장입니다."
        it_area.fill(current_manual_edit)
        page.locator('#conversationItDraft ~ .card-actions [data-copy-draft="it"]').click()
        assert not page.locator("#copyReviewDialog").is_visible()
        assert page.evaluate("navigator.clipboard.readText()") == it_area.input_value()

        preserved = current_manual_edit + "\n근거가 빠져도 남을 편집입니다."
        it_area.fill(preserved)
        page.locator(
            '#conversationView [data-open-answer-evidence="laptop"]:visible'
        ).first.click()
        assert "노트북 답에 사용한 참고 문서" in page.locator(
            "[data-evidence-view-title]"
        ).inner_text()
        page.locator('[data-demo-state-button="missing"]').click()
        page.locator('body[data-demo-state="missing"]').wait_for()
        assert "전체 문서" in page.locator("[data-evidence-view-title]").inner_text()
        assert_evidence_actions(page, show_all=False, return_to_answer=False)
        assert page.locator(
            '#conversationView [data-open-answer-evidence="laptop"]:visible'
        ).count() == 0
        page.locator(
            '#conversationView [data-open-answer-evidence="monitor"]:visible'
        ).first.click()
        assert "모니터 답에 사용한 참고 문서" in page.locator(
            "[data-evidence-view-title]"
        ).inner_text()
        assert answer_source_cards.count() == 2
        assert all(
            "laptops-insurance-repairs" not in text
            for text in [item.lower() for item in answer_source_cards.all_inner_texts()]
        )
        page.screenshot(path=args.output / "answer-evidence-missing.png", full_page=True)
        page.locator("[data-return-to-answer]").click()
        page.locator('[data-panel-tab="draft"]').click()
        missing_monitor_area = page.locator("#conversationMissingMonitorDraft")
        assert missing_monitor_area.is_visible()
        page.evaluate("navigator.clipboard.writeText('before-monitor-copy')")
        page.locator('#conversationView [data-copy-draft="monitor"]:visible').click()
        assert not page.locator("#copyReviewDialog").is_visible()
        assert page.evaluate("navigator.clipboard.readText()") == missing_monitor_area.input_value()
        missing_monitor_before = missing_monitor_area.input_value()
        page.locator('#conversationView [data-reset-draft="monitor"]:visible').click()
        assert page.locator("#proposalReviewDialog").is_visible()
        assert page.locator("#proposalReviewCurrent").inner_text() == missing_monitor_before
        page.locator("[data-proposal-review-cancel]").click()
        assert missing_monitor_area.input_value() == missing_monitor_before
        assert page.locator('#conversationView [data-reset-draft="it"]:visible').count() == 0
        page.locator('[data-demo-state-button="normal"]').click()
        page.locator('body[data-demo-state="normal"]').wait_for()
        page.locator('[data-draft-tab="it"]').first.click()
        assert it_area.input_value() == preserved
        page.locator('[data-panel-tab="evidence"]').click()

        stage["name"] = "expected-network-failure"
        page.route("**/api/workspace", lambda route: route.abort())
        page.locator('[data-demo-state-button="loading"]').click()
        page.locator('body[data-demo-state="error"]').wait_for()
        assert page.locator("#connectionNotice").is_visible()
        assert "전체 문서" in page.locator("[data-evidence-view-title]").inner_text()
        assert_evidence_actions(page, show_all=False, return_to_answer=False)
        page.locator('[data-panel-tab="draft"]').click()
        assert it_area.input_value() == preserved
        assert it_area.is_visible()
        assert page.locator('#conversationView [data-reset-draft="it"]:visible').is_disabled()
        page.evaluate("navigator.clipboard.writeText('before-error-review')")
        page.locator('#conversationItDraft ~ .card-actions [data-copy-draft="it"]').click()
        copy_dialog = page.locator("#copyReviewDialog")
        assert copy_dialog.is_visible()
        assert "최근 문서 확인 요청의 결과를 받지 못했습니다" in page.locator(
            "#copyReviewReasons"
        ).inner_text()
        assert page.evaluate("navigator.clipboard.readText()") == "before-error-review"
        page.screenshot(path=args.output / "copy-review-error.png", full_page=True)
        page.evaluate("""
          Object.defineProperty(navigator.clipboard, "writeText", {
            configurable: true,
            value: function () { return Promise.reject(new Error("blocked-for-test")); }
          });
        """)
        page.locator("[data-copy-review-confirm]").click()
        assert "글 전체를 선택" in page.locator("#toast").inner_text()
        selection = page.evaluate("""
          var area = document.querySelector('#conversationItDraft');
          ({ active: document.activeElement === area,
             start: area.selectionStart, end: area.selectionEnd, length: area.value.length });
        """)
        assert selection == {
            "active": True,
            "start": 0,
            "end": selection["length"],
            "length": selection["length"],
        }
        assert page.evaluate("navigator.clipboard.readText()") == "before-error-review"
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
        assert "최신 요청" in page.locator('#conversationItDraft + [data-proposal-note="it"]').inner_text()
        assert "오래된 요청" not in page.locator('#conversationItDraft + [data-proposal-note="it"]').inner_text()
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
        workflow_laptop_evidence = page.locator(
            '#workflowView [data-open-answer-evidence="laptop"]'
        )
        workflow_it_before = it_area.input_value()
        workflow_laptop_evidence.click()
        assert page.locator("#conversationView").is_visible()
        assert "노트북 답에 사용한 참고 문서" in page.locator(
            "[data-evidence-view-title]"
        ).inner_text()
        page.screenshot(path=args.output / "answer-evidence-from-b.png", full_page=True)
        page.locator("[data-return-to-answer]").click()
        page.wait_for_timeout(250)
        assert page.locator("#workflowView").is_visible()
        assert page.locator('#workflowView [data-step-panel="3"]').is_visible()
        assert page.evaluate(
            "() => document.activeElement === document.querySelector('#workflowView [data-open-answer-evidence=\"laptop\"]')"
        )
        assert it_area.input_value() == workflow_it_before
        page.screenshot(path=args.output / "b-results-boundary.png", full_page=True)
        page.locator('[data-demo-state-button="missing"]').click()
        page.locator('body[data-demo-state="missing"]').wait_for()

        revision_page = browser.new_page(viewport={"width": 1440, "height": 1000})
        revision_errors: list[str] = []
        revision_failed_urls: list[str] = []
        revision_requested_urls: list[str] = []
        revision_page.on(
            "console",
            lambda message: revision_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        revision_page.on(
            "response",
            lambda response: revision_failed_urls.append(
                f"{response.status} {response.request.resource_type} {response.url}"
            )
            if response.status >= 400
            else None,
        )
        revision_page.on("request", lambda request: revision_requested_urls.append(request.url))
        revision_page.goto(args.base_url, wait_until="networkidle")
        revision_page.bring_to_front()
        revision_page.context.grant_permissions(
            ["clipboard-read", "clipboard-write"], origin=args.base_url
        )
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
            '#conversationItDraft ~ .card-actions [data-reset-draft="it"]'
        )

        revision_field.fill("4년")
        revision_button.click()
        revision_page.locator('body[data-demo-state="normal"]').wait_for()
        revision_apply.click()
        revision_page.locator("#proposalReviewDialog").wait_for()
        revision_page.locator("[data-proposal-review-confirm]").click()
        applied_four_year_text = revision_area.input_value()
        assert "4년째" in applied_four_year_text
        edited_four_year_text = (
            applied_four_year_text
            + "\n매주 화요일 오전은 회의라 다른 시간에 점검을 부탁드립니다."
        )
        revision_area.fill(edited_four_year_text)

        revision_page.evaluate("navigator.clipboard.writeText('before-stale-copy')")
        revision_field.fill("2년 10개월")
        assert revision_page.locator("#inputChangedNotice").is_visible()
        assert revision_apply.is_disabled()
        assert "입력한 내용이 이 제안을 만든 뒤 바뀌었습니다" in revision_page.locator(
            '#conversationItDraft + [data-proposal-note="it"]'
        ).inner_text()
        assert revision_area.input_value() == edited_four_year_text
        revision_page.locator('#conversationItDraft ~ .card-actions [data-copy-draft="it"]').click()
        revision_dialog = revision_page.locator("#copyReviewDialog")
        assert revision_dialog.is_visible()
        assert "입력한 내용이 이 글의 바탕이 된 제안 이후 바뀌었습니다" in revision_page.locator(
            "#copyReviewReasons"
        ).inner_text()
        assert "재직 2년 10개월" in revision_page.locator("#copyReviewFacts").inner_text()
        assert revision_page.locator("#copyReviewDraft").inner_text() == edited_four_year_text
        assert revision_page.evaluate("navigator.clipboard.readText()") == "before-stale-copy"
        revision_page.screenshot(path=args.output / "copy-review-a.png", full_page=True)
        revision_page.locator("[data-copy-review-cancel]").click()
        assert not revision_dialog.is_visible()
        assert revision_area.input_value() == edited_four_year_text
        assert revision_field.input_value() == "2년 10개월"
        assert revision_page.evaluate("navigator.clipboard.readText()") == "before-stale-copy"

        revision_page.locator('[data-mode="workflow"]').click()
        revision_page.locator('#workflowView [data-step="4"]').click()
        revision_page.locator('#workflowView [data-draft-tab="it"]').first.click()
        revision_page.locator('#workflowItDraft ~ .card-actions [data-copy-draft="it"]').click()
        assert revision_dialog.is_visible()
        revision_page.screenshot(path=args.output / "copy-review-b.png", full_page=True)
        revision_page.evaluate("""
          var area = document.querySelector('#workflowItDraft');
          area.value += "\\n확인창을 연 뒤 바꾼 문장입니다.";
          area.dispatchEvent(new Event("input", { bubbles: true }));
        """)
        changed_while_open = edited_four_year_text + "\n확인창을 연 뒤 바꾼 문장입니다."
        assert revision_page.locator("[data-copy-review-confirm]").is_disabled()
        assert "확인창을 연 뒤" in revision_page.locator("#copyReviewStatus").inner_text()
        assert revision_page.evaluate("navigator.clipboard.readText()") == "before-stale-copy"
        revision_page.locator("[data-copy-review-cancel]").click()
        assert revision_area.input_value() == changed_while_open

        revision_page.locator('#workflowItDraft ~ .card-actions [data-copy-draft="it"]').click()
        revision_page.locator("[data-copy-review-confirm]").click()
        assert revision_page.evaluate("navigator.clipboard.readText()") == changed_while_open

        revision_page.locator('#workflowView [data-apply-conditions]:visible').click()
        revision_page.locator('body[data-demo-state="normal"]').wait_for()
        assert revision_area.input_value() == changed_while_open
        revision_page.locator('#workflowView [data-reset-draft="it"]:visible').click()
        proposal_dialog = revision_page.locator("#proposalReviewDialog")
        assert proposal_dialog.is_visible()
        assert revision_page.locator("#proposalReviewCurrent").text_content() == changed_while_open
        proposed_current_text = revision_page.locator("#proposalReviewProposed").text_content()
        assert "2년 10개월째" in proposed_current_text
        assert "4년째" not in proposed_current_text
        assert "매주 화요일 오전" not in proposed_current_text
        removed_text = "".join(
            revision_page.locator("#proposalReviewCurrent .proposal-diff-removed").all_text_contents()
        )
        added_text = "".join(
            revision_page.locator("#proposalReviewProposed .proposal-diff-added").all_text_contents()
        )
        assert "4년째" in removed_text
        assert "매주 화요일 오전은 회의라 다른 시간에 점검을 부탁드립니다." in removed_text
        assert "확인 부탁드립니다." not in removed_text
        assert "2년 10개월째" in added_text
        assert "취소선" in revision_page.locator("#proposalReviewDiffSummary").inner_text()
        assert revision_area.input_value() == changed_while_open
        revision_page.screenshot(path=args.output / "proposal-review-b.png", full_page=True)
        revision_page.locator("[data-proposal-review-cancel]").click()
        assert revision_area.input_value() == changed_while_open

        revision_page.locator('#workflowView [data-reset-draft="it"]:visible').click()
        revision_page.evaluate("""
          var area = document.querySelector('#workflowItDraft');
          area.value += "\\n비교창을 연 뒤 더 고친 문장입니다.";
          area.dispatchEvent(new Event("input", { bubbles: true }));
        """)
        changed_during_proposal_review = changed_while_open + "\n비교창을 연 뒤 더 고친 문장입니다."
        assert revision_page.locator("[data-proposal-review-confirm]").is_disabled()
        assert "비교창을 연 뒤" in revision_page.locator("#proposalReviewStatus").inner_text()
        revision_page.locator("[data-proposal-review-cancel]").click()
        assert revision_area.input_value() == changed_during_proposal_review

        revision_page.locator('#workflowView [data-reset-draft="it"]:visible').click()
        assert revision_page.locator("#proposalReviewCurrent").inner_text() == changed_during_proposal_review
        assert revision_page.locator("#proposalReviewProposed").inner_text() == proposed_current_text
        revision_page.locator("[data-proposal-review-confirm]").click()
        applied_current_text = revision_area.input_value()
        assert applied_current_text == proposed_current_text
        assert "2년 10개월째" in applied_current_text
        assert "4년째" not in applied_current_text
        revision_page.locator('#workflowItDraft ~ .card-actions [data-copy-draft="it"]').click()
        assert not revision_dialog.is_visible()
        assert revision_page.evaluate("navigator.clipboard.readText()") == applied_current_text

        # A comparison is only valid for the exact input, draft and search
        # result that were shown. Neither input edits nor a newer response may
        # authorize the old confirmation.
        revision_page.locator('#workflowView [data-reset-draft="it"]:visible').click()
        assert revision_page.locator("#proposalReviewCurrent").inner_text() == revision_page.locator(
            "#proposalReviewProposed"
        ).inner_text()
        assert "문자가 같습니다" in revision_page.locator(
            "#proposalReviewDiffSummary"
        ).inner_text()
        assert revision_page.locator("#proposalReviewCurrent .proposal-diff-removed").count() == 0
        assert revision_page.locator("#proposalReviewProposed .proposal-diff-added").count() == 0
        revision_page.evaluate("""
          var field = document.querySelector('#conversationView [data-field="tenure"]');
          field.value = "2년 11개월";
          field.dispatchEvent(new Event("input", { bubbles: true }));
        """)
        assert revision_page.locator("[data-proposal-review-confirm]").is_disabled()
        revision_page.locator("[data-proposal-review-cancel]").click()
        assert revision_area.input_value() == applied_current_text

        revision_page.locator('#workflowView [data-apply-conditions]:visible').click()
        revision_page.locator('body[data-demo-state="normal"]').wait_for()
        revision_page.locator('#workflowView [data-reset-draft="it"]:visible').click()
        revision_page.evaluate(
            "() => document.querySelector('[data-demo-state-button=\"missing\"]').click()"
        )
        revision_page.locator('body[data-demo-state="missing"]').wait_for()
        assert revision_page.locator("[data-proposal-review-confirm]").is_disabled()
        assert "검색 결과 또는 제안이 바뀌었습니다" in revision_page.locator(
            "#proposalReviewStatus"
        ).inner_text()
        revision_page.locator("[data-proposal-review-cancel]").click()
        assert revision_area.input_value() == applied_current_text
        assert revision_page.locator('#workflowView [data-reset-draft="it"]:visible').count() == 0
        monitor_compare = revision_page.locator(
            '#workflowView [data-reset-draft="monitor"]:visible'
        )
        assert monitor_compare.is_enabled()
        monitor_compare.click()
        assert "모니터 문의 글" in revision_page.locator("#proposalReviewTitle").inner_text()
        revision_page.locator("[data-proposal-review-cancel]").click()
        revision_page.locator('[data-demo-state-button="normal"]').click()
        revision_page.locator('body[data-demo-state="normal"]').wait_for()
        revision_page.locator('#workflowView [data-draft-tab="it"]:visible').click()

        revision_page.evaluate("""
          var field = document.querySelector('#conversationView [data-field="tenure"]');
          var button = document.querySelector('#conversationView [data-apply-conditions]');
          window.__employeeAssistantFetch = window.fetch.bind(window);
          window.fetch = function () { return new Promise(function () {}); };
          field.value = "5년";
          field.dispatchEvent(new Event("input", { bubbles: true }));
          button.click();
          field.value = "1년";
          field.dispatchEvent(new Event("input", { bubbles: true }));
        """)
        revision_page.locator('body[data-demo-state="loading"]').wait_for()
        assert revision_apply.is_disabled()
        assert revision_page.locator("#workflowItDraft").is_visible()
        revision_page.evaluate("navigator.clipboard.writeText('before-pending-review')")
        revision_page.locator('#workflowItDraft ~ .card-actions [data-copy-draft="it"]').click()
        assert revision_dialog.is_visible()
        pending_reasons = revision_page.locator("#copyReviewReasons").inner_text()
        assert "문서를 다시 확인하는 중입니다" in pending_reasons, pending_reasons
        assert revision_page.evaluate("navigator.clipboard.readText()") == "before-pending-review"
        revision_page.screenshot(path=args.output / "copy-review-pending.png", full_page=True)
        revision_page.locator("[data-copy-review-cancel]").click()
        assert revision_page.locator("#inputChangedNotice").is_visible()
        assert revision_apply.is_disabled()
        assert revision_area.input_value() == applied_current_text
        revision_page.evaluate("() => { window.fetch = window.__employeeAssistantFetch; }")
        revision_page.locator('#workflowView [data-apply-conditions]:visible').click()
        revision_page.locator('body[data-demo-state="normal"]').wait_for()
        assert revision_area.input_value() == applied_current_text
        revision_page.screenshot(path=args.output / "input-changed.png", full_page=True)
        assert not revision_errors, {
            "console": revision_errors,
            "http": revision_failed_urls,
            "requests": revision_requested_urls,
        }
        assert not revision_failed_urls, revision_failed_urls
        revision_page.close()

        clean = browser.new_page(viewport={"width": 1440, "height": 1000})
        clean.goto(args.base_url, wait_until="networkidle")
        clean.locator('body[data-demo-state="normal"]').wait_for()
        clean.locator('[data-mode="workflow"]').click()
        clean.locator('#workflowView [data-step="3"]').click()
        clean.locator(
            '#workflowView [data-open-answer-evidence="laptop"]'
        ).click()
        clean.screenshot(
            path=args.output / "answer-evidence-from-b-clean.png", full_page=True
        )
        clean.locator("[data-return-to-answer]").click()
        clean.locator('#workflowView [data-step="4"]').click()
        clean.screenshot(path=args.output / "b-normal.png", full_page=True)
        clean.locator('[data-demo-state-button="missing"]').click()
        clean.locator('body[data-demo-state="missing"]').wait_for()
        clean.screenshot(path=args.output / "b-missing.png", full_page=True)
        clean.close()

        unresolved = browser.new_page(viewport={"width": 1100, "height": 900})
        unresolved_errors: list[str] = []
        unresolved.on(
            "console",
            lambda message: unresolved_errors.append(message.text)
            if message.type == "error"
            else None,
        )

        def add_known_but_unretrieved_id(route):
            response = route.fetch()
            body = response.json()
            body["result"]["branches"]["laptop"]["answer"]["evidence_ids"].append(
                "repairs-company-issued"
            )
            route.fulfill(response=response, json=body)

        unresolved.route(
            "**/api/workspace", add_known_but_unretrieved_id, times=1
        )
        unresolved.goto(args.base_url, wait_until="networkidle")
        unresolved.locator('body[data-demo-state="normal"]').wait_for()
        unresolved.locator(
            '#conversationView [data-open-answer-evidence="laptop"]:visible'
        ).click()
        unresolved_panel = unresolved.locator(
            '.panel-content[data-panel-content="evidence"] .state-normal:visible'
        )
        assert "답과 참고 문서 연결 미확인" in unresolved_panel.inner_text()
        assert "laptops-insurance-repairs" in unresolved_panel.inner_text().lower()
        assert "repairs-company-issued" not in unresolved_panel.inner_text().lower()
        assert not unresolved_errors, unresolved_errors
        unresolved.close()

        # The local comparison preserves both complete snapshots and
        # distinguishes edge cases without interpreting their meaning.
        diff_edges = page.evaluate(
            r"""
            () => {
              const compare = window.EmployeeAssistantTextDiff.compare;
              const cases = {
                whitespace: compare('같은 글 ', '같은 글\n'),
                duplicate: compare('반복\n반복\n끝', '반복\n끝\n반복'),
                empty: compare('', '새 문장'),
                identical: compare('그대로🙂', '그대로🙂'),
                long: compare('가'.repeat(8100), '나'.repeat(8100))
              };
              const repeatedEnding = compare(
                '정책 확인 부탁드립니다.\n매주 화요일 오전은 회의라 다른 시간에 점검을 부탁드립니다.',
                '정책 확인 부탁드립니다.'
              );
              const joined = result => ({
                status: result.status,
                current: result.current.map(segment => segment.text).join(''),
                proposed: result.proposed.map(segment => segment.text).join('')
              });
              const result = Object.fromEntries(
                Object.entries(cases).map(([key, value]) => [key, joined(value)])
              );
              result.repeatedEnding = {
                status: repeatedEnding.status,
                unchanged: repeatedEnding.current
                  .filter(segment => segment.kind === 'equal')
                  .map(segment => segment.text).join(''),
                removed: repeatedEnding.current
                  .filter(segment => segment.kind === 'removed')
                  .map(segment => segment.text).join('')
              };
              return result;
            }
            """
        )
        assert diff_edges["whitespace"] == {
            "status": "changed", "current": "같은 글 ", "proposed": "같은 글\n"
        }
        assert diff_edges["duplicate"] == {
            "status": "changed", "current": "반복\n반복\n끝", "proposed": "반복\n끝\n반복"
        }
        assert diff_edges["empty"] == {
            "status": "changed", "current": "", "proposed": "새 문장"
        }
        assert diff_edges["identical"] == {
            "status": "identical", "current": "그대로🙂", "proposed": "그대로🙂"
        }
        assert diff_edges["long"] == {
            "status": "fallback", "current": "가" * 8100, "proposed": "나" * 8100
        }
        assert diff_edges["repeatedEnding"] == {
            "status": "changed",
            "unchanged": "정책 확인 부탁드립니다.",
            "removed": "\n매주 화요일 오전은 회의라 다른 시간에 점검을 부탁드립니다.",
        }

        edge_page = browser.new_page(viewport={"width": 1100, "height": 900})
        edge_page.goto(args.base_url, wait_until="networkidle")
        edge_page.locator('body[data-demo-state="normal"]').wait_for()
        edge_page.locator('[data-open-panel="draft"]').first.click()
        edge_page.locator('[data-draft-tab="it"]').first.click()
        edge_area = edge_page.locator("#conversationItDraft")
        xss_like_text = '<img src=x onerror="window.__proposalXss=true"> 🙂\n<script>window.__proposalXss=true</script>'
        edge_area.fill(xss_like_text)
        edge_page.locator('#conversationItDraft ~ .card-actions [data-reset-draft="it"]').click()
        assert edge_page.locator("#proposalReviewCurrent").text_content() == xss_like_text
        assert edge_page.locator("#proposalReviewCurrent img").count() == 0
        assert edge_page.locator("#proposalReviewCurrent script").count() == 0
        assert edge_page.evaluate("() => window.__proposalXss") is None
        edge_page.locator("[data-proposal-review-cancel]").click()

        long_text = "길" * 8100 + "\n끝"
        edge_area.fill(long_text)
        edge_page.locator('#conversationItDraft ~ .card-actions [data-reset-draft="it"]').click()
        assert edge_page.locator("#proposalReviewCurrent").text_content() == long_text
        assert "세부 차이 표시는 생략" in edge_page.locator(
            "#proposalReviewDiffSummary"
        ).inner_text()
        assert edge_page.locator("#proposalReviewCurrent .proposal-diff-removed").count() == 0
        assert edge_page.locator("#proposalReviewProposed .proposal-diff-added").count() == 0
        edge_page.screenshot(path=args.output / "proposal-review-long-fallback.png", full_page=True)
        edge_page.close()

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        mobile.goto(args.base_url, wait_until="networkidle")
        mobile.locator('body[data-demo-state="normal"]').wait_for()
        mobile.locator(
            '#conversationView [data-open-answer-evidence="laptop"]:visible'
        ).click()
        mobile.locator("[data-evidence-view-title]").wait_for()
        evidence_overflow = mobile.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert evidence_overflow <= 0, evidence_overflow
        mobile.screenshot(path=args.output / "answer-evidence-mobile.png", full_page=True)
        mobile.locator("[data-return-to-answer]").click()
        mobile.locator('[data-open-panel="draft"]').first.click()
        mobile.locator('[data-draft-tab="it"]').first.click()
        mobile.locator('#conversationView [data-field="tenure"]').fill("4년")
        mobile.locator('#conversationItDraft ~ .card-actions [data-copy-draft="it"]').click()
        mobile.locator("#copyReviewDialog").wait_for()
        overflow = mobile.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 0, overflow
        mobile.screenshot(path=args.output / "copy-review-mobile.png", full_page=True)
        mobile.locator("[data-copy-review-cancel]").click()
        mobile.locator('#conversationView [data-apply-conditions]').first.click()
        mobile.locator('body[data-demo-state="normal"]').wait_for()
        mobile.locator('#conversationItDraft ~ .card-actions [data-reset-draft="it"]').click()
        mobile.locator("[data-proposal-review-confirm]").click()
        mobile_it = mobile.locator("#conversationItDraft")
        mobile_manual_sentence = "매주 화요일 오전은 회의라 다른 시간에 점검을 부탁드립니다."
        mobile_it.fill(mobile_it.input_value() + "\n" + mobile_manual_sentence)
        mobile.locator('#conversationView [data-field="tenure"]').fill("2년 10개월")
        mobile.locator('#conversationView [data-apply-conditions]').first.click()
        mobile.locator('body[data-demo-state="normal"]').wait_for()
        mobile.locator('#conversationItDraft ~ .card-actions [data-reset-draft="it"]').click()
        mobile.locator("#proposalReviewDialog").wait_for()
        mobile.locator("#proposalReviewCurrent").focus()
        assert mobile.evaluate(
            "() => document.activeElement === document.querySelector('#proposalReviewCurrent')"
        )
        mobile.keyboard.press("Tab")
        assert mobile.evaluate(
            "() => document.activeElement === document.querySelector('#proposalReviewProposed')"
        )
        current_box = mobile.locator("#proposalReviewCurrent").bounding_box()
        proposed_box = mobile.locator("#proposalReviewProposed").bounding_box()
        assert current_box is not None and proposed_box is not None
        assert proposed_box["y"] >= current_box["y"] + current_box["height"], {
            "current": current_box,
            "proposed": proposed_box,
        }
        proposal_overflow = mobile.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert proposal_overflow <= 0, proposal_overflow
        assert mobile.locator("#proposalReviewDiffSummary").is_visible()
        assert mobile.locator("#proposalReviewCurrent .proposal-diff-removed").count() > 0
        assert mobile.locator("#proposalReviewProposed .proposal-diff-added").count() > 0
        mobile_removed = "".join(
            mobile.locator("#proposalReviewCurrent .proposal-diff-removed").all_text_contents()
        )
        assert mobile_manual_sentence in mobile_removed
        assert "확인 부탁드립니다." not in mobile_removed
        mobile.screenshot(path=args.output / "proposal-review-mobile.png", full_page=True)
        mobile.close()

        assert not console_errors, {"console": console_errors, "http": failed_urls}
        assert not failed_urls, failed_urls
        assert all(url.startswith(args.base_url) for url in requested_urls), requested_urls
        browser.close()
        print("browser flow: PASS")


if __name__ == "__main__":
    main()
