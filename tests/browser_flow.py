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
        initial_answer = page.locator("#conversationView [data-answer-text]").inner_text()
        for expected in (
            "승인 WFH 장비 목록에 모니터와 모니터 스탠드",
            "연간 500 USD(또는 현지 통화 상당액)",
            "직전 한 해 전체 재직 조건",
            "모든 모니터 구입 경로에 동일하게 적용되는지",
            "개인의 적용 경로·잔액·실제 처리",
        ):
            assert expected in initial_answer
        initial_monitor_draft = page.locator("#conversationMonitorDraft").input_value()
        assert initial_monitor_draft.startswith("재택근무용 모니터 구입을 검토 중입니다.")
        assert "[신규/기존 직원" not in initial_monitor_draft
        assert "저는 이고" not in initial_monitor_draft
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

        # The employee chooses the laptop inquiry goal explicitly. Both goals
        # retain the same policy answer, while the IT request text changes.
        # Changing the goal creates a new proposal and never overwrites edits.
        goal_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        goal_page = goal_context.new_page()
        goal_page.goto(args.base_url, wait_until="networkidle")
        goal_page.locator('body[data-demo-state="normal"]').wait_for()
        replacement_radio = goal_page.locator(
            '#conversationView [data-laptop-inquiry-goal][value="replacement_process"]'
        )
        before_radio = goal_page.locator(
            '#conversationView [data-laptop-inquiry-goal][value="before_replacement"]'
        )
        assert replacement_radio.is_checked()
        assert not before_radio.is_checked()
        replacement_answer = goal_page.locator("[data-answer-text]").first.inner_text()
        goal_page.locator('#conversationView [data-field="tenure"]').fill("2년 10개월")
        goal_page.locator('#conversationView [data-field="symptom"]').fill(
            "어제부터 문서 편집 중"
        )
        goal_page.locator('#conversationView [data-field="purchase"]').select_option(
            "not-purchased"
        )
        goal_page.locator('#conversationView [data-apply-conditions]').first.click()
        goal_page.locator('body[data-demo-state="normal"]').wait_for()
        displayed_question = goal_page.locator(
            '#conversationView [data-question-text]'
        ).inner_text()
        assert "느려진 회사 노트북" in displayed_question
        assert "지난주부터" not in displayed_question
        assert "어제부터" not in displayed_question
        goal_page.locator('[data-open-panel="draft"]').first.click()
        goal_page.locator('[data-draft-tab="it"]').first.click()
        goal_it = goal_page.locator("#conversationItDraft")
        goal_page.locator(
            '#conversationItDraft ~ .card-actions [data-reset-draft="it"]'
        ).click()
        goal_page.locator("[data-proposal-review-confirm]").click()
        replacement_draft = goal_it.input_value()
        assert "3년 refresh 조건" in replacement_draft
        edited_replacement = replacement_draft + "\n직원이 직접 남긴 일정 요청입니다."
        goal_it.fill(edited_replacement)
        monitor_before_goal_change = goal_page.locator(
            "#conversationMonitorDraft"
        ).input_value()

        goal_page.locator(
            '#conversationItDraft ~ .card-actions [data-reset-draft="it"]'
        ).click()
        goal_page.evaluate(
            """
            () => {
              const field = document.querySelector('#conversationView [data-laptop-inquiry-goal][value="before_replacement"]');
              field.checked = true;
              field.dispatchEvent(new Event('change', { bubbles: true }));
            }
            """
        )
        goal_page.locator('body[data-demo-state="normal"]').wait_for()
        assert goal_page.locator("[data-proposal-review-confirm]").is_disabled()
        assert goal_it.input_value() == edited_replacement
        goal_page.locator("[data-proposal-review-cancel]").click()
        assert before_radio.is_checked()
        assert goal_page.locator(
            '#workflowView [data-laptop-inquiry-goal][value="before_replacement"]'
        ).is_checked()
        assert goal_page.locator("[data-answer-text]").first.inner_text() == replacement_answer
        assert goal_page.locator("#conversationMonitorDraft").input_value() == monitor_before_goal_change

        # Copy review shows the selected goal as its own snapshot value. A
        # later goal change invalidates confirmation without rewriting either
        # the displayed snapshot or the draft that would have been copied.
        goal_page.locator(
            '#conversationItDraft ~ .card-actions [data-copy-draft="it"]'
        ).click()
        goal_copy_dialog = goal_page.locator("#copyReviewDialog")
        assert goal_copy_dialog.is_visible()
        assert goal_page.locator("#copyReviewGoal").inner_text() == "모니터와 노트북 둘 다 · 교체를 정하기 전 확인 문의"
        assert goal_page.locator("#copyReviewDraft").inner_text() == edited_replacement
        with goal_page.expect_response("**/api/workspace"):
            goal_page.evaluate(
                """
                () => {
                  const field = document.querySelector('#conversationView [data-laptop-inquiry-goal][value="replacement_process"]');
                  field.checked = true;
                  field.dispatchEvent(new Event('change', { bubbles: true }));
                }
                """
            )
        assert goal_page.locator("[data-copy-review-confirm]").is_disabled()
        assert goal_page.locator("#copyReviewGoal").inner_text() == "모니터와 노트북 둘 다 · 교체를 정하기 전 확인 문의"
        assert goal_page.locator("#copyReviewDraft").inner_text() == edited_replacement
        goal_page.locator("[data-copy-review-cancel]").click()
        with goal_page.expect_response("**/api/workspace"):
            before_radio.check()
        assert goal_it.input_value() == edited_replacement

        goal_page.locator(
            '#conversationItDraft ~ .card-actions [data-reset-draft="it"]'
        ).click()
        before_proposal = goal_page.locator("#proposalReviewProposed").text_content()
        assert "교체 여부를 정하기 전에" in before_proposal
        assert "어떤 정보를 더 드려야 하는지" in before_proposal
        assert "새 기기를 구매하지 않았습니다" in before_proposal
        assert goal_it.input_value() == edited_replacement
        goal_page.screenshot(path=args.output / "inquiry-goal-a-review.png", full_page=True)
        goal_page.locator("[data-proposal-review-confirm]").click()
        assert goal_it.input_value() == before_proposal
        assert "3년 refresh 조건" not in goal_it.input_value()
        conversation_context = goal_page.locator(
            '#conversationView .origin-list[aria-label="문의 글 주변에서 확인할 정보"]'
        )
        assert conversation_context.is_visible()
        assert "현재 선택" in conversation_context.inner_text()
        assert "교체를 정하기 전 확인 문의" in conversation_context.inner_text()
        assert "현재 글 반영 여부는 직접 확인" in conversation_context.inner_text()

        goal_page.locator('[data-mode="workflow"]').click()
        goal_page.locator('#workflowView [data-step="1"]').click()
        assert goal_page.locator(
            '#workflowView [data-laptop-inquiry-goal][value="before_replacement"]'
        ).is_checked()
        assert "교체를 정하기 전에" in goal_page.locator(
            '#workflowView [data-question-text]'
        ).inner_text()
        assert "현재 글 반영 여부는 직접 확인" in goal_page.locator(
            '#workflowView .origin-list[aria-label="문의 글 주변에서 확인할 정보"]'
        ).inner_text()
        goal_page.screenshot(path=args.output / "inquiry-goal-b.png", full_page=True)

        goal_page.locator('[data-demo-state-button="missing"]').click()
        goal_page.locator('body[data-demo-state="missing"]').wait_for()
        assert goal_page.locator("#workflowMissingMonitorDraft").input_value() == monitor_before_goal_change
        assert goal_page.locator(
            '#workflowView [data-reset-draft="it"]:visible'
        ).count() == 0
        assert goal_page.locator(
            '#workflowView [data-laptop-inquiry-goal][value="before_replacement"]'
        ).is_checked()
        goal_page.locator('[data-demo-state-button="normal"]').click()
        goal_page.locator('body[data-demo-state="normal"]').wait_for()

        def delay_goal_response(route):
            response = route.fetch()
            time.sleep(0.45)
            route.fulfill(response=response)

        goal_page.route("**/api/workspace", delay_goal_response, times=1)
        workflow_replacement_radio = goal_page.locator(
            '#workflowView [data-laptop-inquiry-goal][value="replacement_process"]'
        )
        workflow_before_radio = goal_page.locator(
            '#workflowView [data-laptop-inquiry-goal][value="before_replacement"]'
        )
        workflow_replacement_radio.check()
        workflow_before_radio.check()
        goal_page.locator('body[data-demo-state="normal"]').wait_for()
        goal_page.wait_for_timeout(550)
        assert before_radio.is_checked()
        goal_page.locator('[data-mode="conversation"]').click()
        goal_page.locator('[data-panel-tab="draft"]').click()
        goal_page.locator('[data-draft-tab="it"]').first.click()
        goal_page.locator(
            '#conversationItDraft ~ .card-actions [data-reset-draft="it"]'
        ).click()
        final_goal_proposal = goal_page.locator("#proposalReviewProposed").text_content()
        assert "교체 여부를 정하기 전에" in final_goal_proposal
        assert "3년 refresh 조건" not in final_goal_proposal
        goal_page.locator("[data-proposal-review-cancel]").click()
        goal_page.unroute("**/api/workspace")

        goal_page.set_viewport_size({"width": 390, "height": 844})
        goal_page.locator("#conversationView .inquiry-goal").first.scroll_into_view_if_needed()
        overflow = goal_page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, overflow
        assert before_radio.is_visible()
        goal_page.screenshot(path=args.output / "inquiry-goal-mobile.png", full_page=True)
        goal_context.close()

        # The employee explicitly selects which of the two existing inquiry
        # branches to prepare. Unselected work is neither searched nor shown as
        # missing, while both employee-edited drafts stay in memory for reselection.
        scope_context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            permissions=["clipboard-read", "clipboard-write"],
        )
        scope_page = scope_context.new_page()
        scope_page.goto(args.base_url, wait_until="networkidle")
        scope_page.locator('body[data-demo-state="normal"]').wait_for()
        assert scope_page.locator(
            '#conversationView [data-inquiry-scope][value="both"]'
        ).is_checked()
        scope_page.locator('[data-open-panel="draft"]').first.click()
        scope_page.locator('[data-draft-tab="it"]:visible').click()
        scope_it = scope_page.locator("#conversationItDraft")
        scope_it.fill(scope_it.input_value() + "\n선택을 바꿔도 보존할 노트북 문장")
        scope_page.locator('[data-draft-tab="monitor"]:visible').click()
        scope_monitor = scope_page.locator("#conversationMonitorDraft")
        scope_monitor.fill(scope_monitor.input_value() + "\n선택을 바꿔도 보존할 모니터 문장")
        edited_scope_it = scope_it.input_value()
        edited_scope_monitor = scope_monitor.input_value()

        scope_page.locator('[data-draft-tab="it"]:visible').click()
        scope_page.locator('#conversationView [data-field="tenure"]').fill("2년 10개월")
        scope_page.evaluate("navigator.clipboard.writeText('before-scope-copy')")
        scope_page.locator('[data-copy-draft="it"]:visible').click()
        assert scope_page.locator("#copyReviewDialog").is_visible()
        with scope_page.expect_response("**/api/workspace"):
            scope_page.evaluate(
                """
                () => {
                  const field = document.querySelector('#conversationView [data-inquiry-scope][value="monitor"]');
                  field.checked = true;
                  field.dispatchEvent(new Event('change', { bubbles: true }));
                }
                """
            )
        assert scope_page.locator("[data-copy-review-confirm]").is_disabled()
        assert "입력·문의 글·검색 상태가 바뀌었습니다" in scope_page.locator(
            "#copyReviewStatus"
        ).inner_text()
        assert scope_page.locator("#copyReviewGoal").inner_text().startswith(
            "모니터와 노트북 둘 다"
        )
        assert scope_page.locator("#copyReviewDraft").inner_text() == edited_scope_it
        scope_page.evaluate(
            """
            () => {
              const confirm = document.querySelector('[data-copy-review-confirm]');
              confirm.disabled = false;
              confirm.click();
            }
            """
        )
        assert scope_page.locator("#copyReviewDialog").is_visible()
        assert scope_page.evaluate("navigator.clipboard.readText()") == "before-scope-copy"
        scope_page.locator("[data-copy-review-cancel]").click()

        assert scope_page.locator('[data-draft-tab="it"]:visible').count() == 0
        assert scope_page.locator('[data-draft-tab="monitor"]:visible').count() == 1
        assert scope_monitor.is_visible()
        assert scope_monitor.input_value() == edited_scope_monitor
        assert scope_page.locator("[data-current-inquiry-label]").inner_text() == "모니터 문의"
        assert scope_page.locator(
            '#conversationView [data-current-inquiry-context]'
        ).inner_text() == "장비 정책 / 모니터 문의"
        assert scope_page.locator(
            '#conversationView [data-open-answer-evidence="laptop"]:visible'
        ).count() == 0
        assert scope_page.locator(
            '#conversationView [data-laptop-inquiry-goal]:visible'
        ).count() == 0
        assert "IT 문의 글은 보관 중" in scope_page.locator(
            '#conversationView [data-unselected-draft-note]:visible'
        ).inner_text()

        # Monitor-only hides laptop input/goal summaries in both layouts. The
        # monitor copy review also does not present laptop facts as inputs used
        # to compose the monitor draft.
        scope_page.locator('[data-copy-draft="monitor"]:visible').click()
        assert scope_page.locator("#copyReviewDialog").is_visible()
        assert scope_page.locator("#copyReviewGoal").inner_text() == "모니터만"
        assert scope_page.locator("#copyReviewFactsTitle").inner_text() == "모니터 새 제안 안내"
        monitor_copy_facts = scope_page.locator("#copyReviewFacts").inner_text()
        assert "노트북용 입력을 자동 반영하지 않습니다" in monitor_copy_facts
        assert "직접 수정한 내용은 복사할 글에서 확인" in monitor_copy_facts
        assert "2년 10개월" not in monitor_copy_facts
        assert scope_page.evaluate("navigator.clipboard.readText()") == "before-scope-copy"
        scope_page.locator("[data-copy-review-cancel]").click()

        scope_page.locator('[data-mode="workflow"]').click()
        laptop_summary_rows = scope_page.locator("#workflowView [data-laptop-summary]")
        assert laptop_summary_rows.count() == 2
        for index in range(laptop_summary_rows.count()):
            row = laptop_summary_rows.nth(index)
            assert row.is_hidden()
            assert row.evaluate("node => getComputedStyle(node).display") == "none"
            assert row.bounding_box() is None
        assert scope_page.locator("#workflowView [data-summary-personal-label]").inner_text() == (
            "개인 적용·처리"
        )
        monitor_summary_note = scope_page.locator(
            "#workflowView [data-summary-note]"
        ).inner_text()
        assert "남은 수당" in monitor_summary_note
        assert "세 정보를 모두" not in monitor_summary_note
        scope_page.locator('[data-mode="conversation"]').click()
        scope_page.screenshot(
            path=args.output / "inquiry-scope-monitor-a.png", full_page=True
        )

        # Excluding laptop evidence does not turn monitor-only into a missing
        # state because the laptop branch is explicitly not selected.
        with scope_page.expect_response("**/api/workspace"):
            scope_page.locator('[data-demo-state-button="missing"]').click()
        scope_page.locator('body[data-demo-state="normal"]').wait_for()
        assert scope_page.locator(
            '#conversationView [data-reset-draft="monitor"]:visible'
        ).is_enabled()
        assert scope_page.locator(
            '#conversationView [data-reset-draft="it"]:visible'
        ).count() == 0
        with scope_page.expect_response("**/api/workspace"):
            scope_page.locator('[data-demo-state-button="normal"]').click()
        scope_page.locator('body[data-demo-state="normal"]').wait_for()

        # A slower response for an older scope cannot replace the later scope.
        def delay_scope_response(route):
            response = route.fetch()
            time.sleep(0.45)
            route.fulfill(response=response)

        scope_page.route("**/api/workspace", delay_scope_response, times=1)
        scope_page.locator(
            '#conversationView [data-inquiry-scope][value="laptop"]'
        ).check()
        scope_page.locator(
            '#conversationView [data-inquiry-scope][value="both"]'
        ).check()
        scope_page.locator('body[data-demo-state="normal"]').wait_for()
        scope_page.wait_for_timeout(550)
        assert scope_page.locator(
            '#conversationView [data-inquiry-scope][value="both"]'
        ).is_checked()
        assert scope_page.locator('[data-draft-tab="it"]:visible').count() == 1
        assert scope_page.locator('[data-draft-tab="monitor"]:visible').count() == 1
        assert scope_it.input_value() == edited_scope_it
        assert scope_monitor.input_value() == edited_scope_monitor
        scope_page.unroute("**/api/workspace")

        scope_page.locator('[data-draft-tab="it"]:visible').click()
        scope_page.locator('[data-reset-draft="it"]:visible').click()
        assert scope_page.locator("#proposalReviewDialog").is_visible()
        with scope_page.expect_response("**/api/workspace"):
            scope_page.evaluate(
                """
                () => {
                  const field = document.querySelector('#conversationView [data-inquiry-scope][value="monitor"]');
                  field.checked = true;
                  field.dispatchEvent(new Event('change', { bubbles: true }));
                }
                """
            )
        assert scope_page.locator("[data-proposal-review-confirm]").is_disabled()
        scope_page.evaluate(
            """
            () => {
              const confirm = document.querySelector('[data-proposal-review-confirm]');
              confirm.disabled = false;
              confirm.click();
            }
            """
        )
        assert scope_page.locator("#proposalReviewDialog").is_visible()
        assert scope_it.input_value() == edited_scope_it
        scope_page.locator("[data-proposal-review-cancel]").click()
        with scope_page.expect_response("**/api/workspace"):
            scope_page.locator(
                '#conversationView [data-inquiry-scope][value="both"]'
            ).check()

        # Laptop-only searches and displays only that selected branch. The
        # monitor draft remains stored and returns unchanged when both is chosen.
        scope_page.locator('[data-mode="workflow"]').click()
        scope_page.locator('#workflowView [data-step="1"]:visible').click()
        with scope_page.expect_response("**/api/workspace"):
            scope_page.locator(
                '#workflowView [data-inquiry-scope][value="laptop"]'
            ).check()
        assert scope_page.locator('#workflowView [data-step="2"]:visible').count() == 1
        assert scope_page.locator("[data-current-inquiry-label]").inner_text() == "노트북 문의"
        assert scope_page.locator("#workflowView [data-scope-intro]").inner_text().startswith(
            "느려진 회사 노트북"
        )
        assert scope_page.locator(
            '#workflowView [data-open-answer-evidence="monitor"]:visible'
        ).count() == 0
        scope_page.locator('#workflowView [data-step="3"]:visible').click()
        scope_page.locator(
            '#workflowView [data-open-answer-evidence="laptop"]:visible'
        ).click()
        scope_sources = scope_page.locator(
            '.panel-content[data-panel-content="evidence"] .state-only:visible .source-card'
        )
        assert scope_sources.count() == 1
        assert "laptops-insurance-repairs" in scope_sources.first.inner_text().lower()
        scope_page.locator("[data-return-to-answer]").click()
        scope_page.locator('#workflowView [data-step="4"]:visible').click()
        assert scope_page.locator('#workflowView [data-draft-tab="monitor"]:visible').count() == 0
        assert scope_page.locator('#workflowItDraft').is_visible()
        assert scope_page.locator('#workflowItDraft').input_value() == edited_scope_it
        scope_page.screenshot(
            path=args.output / "inquiry-scope-laptop-b.png", full_page=True
        )

        scope_page.set_viewport_size({"width": 390, "height": 844})
        scope_page.locator('#workflowView [data-step="1"]:visible').click()
        scope_page.locator('#workflowView [data-inquiry-scope][value="laptop"]').scroll_into_view_if_needed()
        assert scope_page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        ) <= 0
        scope_page.screenshot(path=args.output / "inquiry-scope-laptop-mobile.png", full_page=True)
        scope_context.close()

        # Missing facts do not become bracket placeholders or invented facts.
        # Explicit unknown remains a distinct employee statement, while rule
        # proposals never overwrite the employee's current edit automatically.
        minimal_context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            permissions=["clipboard-read", "clipboard-write"],
        )
        minimal_page = minimal_context.new_page()
        minimal_page.goto(args.base_url, wait_until="networkidle")
        minimal_page.locator('body[data-demo-state="normal"]').wait_for()
        with minimal_page.expect_response("**/api/workspace"):
            minimal_page.locator(
                '#conversationView [data-laptop-inquiry-goal][value="before_replacement"]'
            ).check()
        minimal_page.locator('#conversationView [data-field="symptom"]').fill(
            "오늘 화상회의 중"
        )
        with minimal_page.expect_response("**/api/workspace"):
            minimal_page.locator(
                '#conversationView [data-apply-conditions]'
            ).first.click()
        minimal_page.locator('[data-open-panel="draft"]').first.click()
        minimal_page.locator('[data-draft-tab="it"]').first.click()
        minimal_it = minimal_page.locator("#conversationItDraft")
        minimal_compare = minimal_page.locator(
            '#conversationItDraft ~ .card-actions [data-reset-draft="it"]'
        )
        minimal_compare.click()
        symptom_only_proposal = minimal_page.locator(
            "#proposalReviewProposed"
        ).text_content()
        assert symptom_only_proposal == (
            "회사 노트북이 오늘 화상회의 중 느려졌습니다. 교체 여부를 정하기 전에, "
            "증상을 확인하려면 어떤 정보를 더 드려야 하는지와 다음 문의 절차를 안내 "
            "부탁드립니다."
        )
        assert "[" not in symptom_only_proposal
        assert "구매" not in symptom_only_proposal
        minimal_page.locator("[data-proposal-review-confirm]").click()
        input_guide = minimal_page.locator(
            "#conversationView .condition-input-guide"
        )
        assert "오늘 화상회의 중 느려짐" in input_guide.inner_text()
        assert "재직 기간 · 구매 상태" in input_guide.inner_text()
        assert "필수 항목으로 확인된 것은 아닙니다" in input_guide.inner_text()
        assert minimal_page.locator(
            "#conversationView [data-condition-count]"
        ).inner_text() == "1/3 입력"
        minimal_page.screenshot(
            path=args.output / "minimal-symptom-only.png", full_page=True
        )

        purchase_field = minimal_page.locator(
            '#conversationView [data-field="purchase"]'
        )
        purchase_field.select_option("unknown")
        with minimal_page.expect_response("**/api/workspace"):
            minimal_page.locator(
                '#conversationView [data-apply-conditions]'
            ).first.click()
        minimal_compare.click()
        unknown_proposal = minimal_page.locator(
            "#proposalReviewProposed"
        ).text_content()
        assert minimal_it.input_value() == symptom_only_proposal
        assert "새 기기 구매 여부는 아직 확인하지 못했습니다." in unknown_proposal
        assert "구매 상태" not in minimal_page.locator(
            "#conversationView .condition-input-guide [data-missing-facts]"
        ).inner_text()
        assert minimal_page.locator(
            "#conversationView [data-condition-count]"
        ).inner_text() == "2/3 입력"
        minimal_page.locator("[data-proposal-review-confirm]").click()

        purchase_field.select_option("not-purchased")
        with minimal_page.expect_response("**/api/workspace"):
            minimal_page.locator(
                '#conversationView [data-apply-conditions]'
            ).first.click()
        minimal_compare.click()
        minimal_page.locator("[data-proposal-review-confirm]").click()
        known_text = minimal_it.input_value()
        assert "새 기기를 구매하지 않았습니다." in known_text
        edited_known_text = known_text + "\n직원이 직접 덧붙인 확인 요청입니다."
        minimal_it.fill(edited_known_text)

        purchase_field.select_option("unknown")
        with minimal_page.expect_response("**/api/workspace"):
            minimal_page.locator(
                '#conversationView [data-apply-conditions]'
            ).first.click()
        minimal_compare.click()
        assert minimal_page.locator("#proposalReviewCurrent").text_content() == edited_known_text
        assert "아직 확인하지 못했습니다" in minimal_page.locator(
            "#proposalReviewProposed"
        ).text_content()
        minimal_page.locator("[data-proposal-review-cancel]").click()
        assert minimal_it.input_value() == edited_known_text

        purchase_field.select_option("")
        minimal_page.locator('#conversationView [data-field="tenure"]').fill("   ")
        minimal_page.locator('#conversationView [data-field="symptom"]').fill(" \t ")
        with minimal_page.expect_response("**/api/workspace"):
            minimal_page.locator(
                '#conversationView [data-apply-conditions]'
            ).first.click()
        minimal_compare.click()
        blank_before_proposal = minimal_page.locator(
            "#proposalReviewProposed"
        ).text_content()
        assert minimal_it.input_value() == edited_known_text
        assert blank_before_proposal.startswith("회사 노트북이 느려져 문의드립니다.")
        assert "[" not in blank_before_proposal
        assert "구매" not in blank_before_proposal
        minimal_page.locator("[data-proposal-review-confirm]").click()
        assert minimal_page.locator(
            "#conversationView [data-condition-count]"
        ).inner_text() == "0/3 입력"
        assert minimal_page.locator(
            "#conversationView .condition-input-guide [data-stated-facts]"
        ).inner_text() == "아직 없음"
        assert all(
            label in minimal_page.locator(
                "#conversationView .condition-input-guide [data-missing-facts]"
            ).inner_text()
            for label in ("재직 기간", "느려진 시점·상황", "구매 상태")
        )

        with minimal_page.expect_response("**/api/workspace"):
            minimal_page.locator(
                '#conversationView [data-laptop-inquiry-goal][value="replacement_process"]'
            ).check()
        minimal_compare.click()
        blank_replacement_proposal = minimal_page.locator(
            "#proposalReviewProposed"
        ).text_content()
        assert blank_replacement_proposal.startswith("회사 노트북이 느려져 문의드립니다.")
        assert "3년 refresh 조건" in blank_replacement_proposal
        assert "[" not in blank_replacement_proposal
        minimal_page.locator("[data-proposal-review-confirm]").click()
        assert minimal_it.input_value() == blank_replacement_proposal
        minimal_page.locator(
            '#conversationItDraft ~ .card-actions [data-copy-draft="it"]'
        ).click()
        assert minimal_page.evaluate("navigator.clipboard.readText()") == blank_replacement_proposal

        monitor_before_minimal_missing = minimal_page.locator(
            "#conversationMonitorDraft"
        ).input_value()
        minimal_page.locator('[data-demo-state-button="missing"]').click()
        minimal_page.locator('body[data-demo-state="missing"]').wait_for()
        assert minimal_page.locator(
            "#conversationMissingMonitorDraft"
        ).input_value() == monitor_before_minimal_missing
        assert minimal_page.locator(
            '#conversationView [data-reset-draft="it"]:visible'
        ).count() == 0
        minimal_page.locator('[data-demo-state-button="normal"]').click()
        minimal_page.locator('body[data-demo-state="normal"]').wait_for()

        minimal_page.locator('[data-mode="workflow"]').click()
        minimal_page.locator('#workflowView [data-step="2"]').click()
        workflow_guide = minimal_page.locator(
            "#workflowView .condition-input-guide"
        )
        assert workflow_guide.is_visible()
        assert "아직 없음" in workflow_guide.inner_text()
        assert "필수 항목으로 확인된 것은 아닙니다" in workflow_guide.inner_text()
        minimal_page.screenshot(
            path=args.output / "minimal-blank-workflow.png", full_page=True
        )
        minimal_page.set_viewport_size({"width": 390, "height": 844})
        workflow_guide.scroll_into_view_if_needed()
        assert minimal_page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        ) <= 0
        minimal_page.screenshot(
            path=args.output / "minimal-blank-mobile.png", full_page=True
        )
        minimal_context.close()

        # Monitor policy facts and the employee's personal eligibility stay
        # separate. Laptop-only facts do not enter the monitor draft, while
        # direct edits remain until the employee explicitly adopts a proposal.
        monitor_context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            permissions=["clipboard-read", "clipboard-write"],
        )
        monitor_page = monitor_context.new_page()
        monitor_page.goto(args.base_url, wait_until="networkidle")
        monitor_page.locator('body[data-demo-state="normal"]').wait_for()
        monitor_default = monitor_page.locator("#conversationMonitorDraft").input_value()
        assert monitor_default == monitor_page.locator("#workflowMonitorDraft").input_value()
        assert monitor_default.startswith("재택근무용 모니터 구입을 검토 중입니다.")
        assert "Stipend/Allowance" in monitor_default
        assert "[" not in monitor_default
        assert "직원 정보:" not in monitor_default

        monitor_page.locator('[data-panel-tab="draft"]').click()
        monitor_area = monitor_page.locator("#conversationMonitorDraft")
        edited_monitor = monitor_default + "\n직원이 직접 추가한 모니터 사용 목적입니다."
        monitor_area.fill(edited_monitor)
        monitor_page.locator('#conversationView [data-field="tenure"]').fill("2년 10개월")
        monitor_page.locator('#conversationView [data-field="purchase"]').select_option("purchased")
        with monitor_page.expect_response("**/api/workspace"):
            monitor_page.locator(
                '#conversationView [data-apply-conditions]'
            ).first.click()
        assert monitor_area.input_value() == edited_monitor
        monitor_page.locator(
            '#conversationMonitorDraft ~ .card-actions [data-reset-draft="monitor"]'
        ).click()
        assert monitor_page.locator("#proposalReviewCurrent").text_content() == edited_monitor
        proposed_monitor = monitor_page.locator("#proposalReviewProposed").text_content()
        assert proposed_monitor == monitor_default
        assert "2년 10개월" not in proposed_monitor
        assert "이미 구매" not in proposed_monitor
        monitor_page.locator("[data-proposal-review-cancel]").click()
        assert monitor_area.input_value() == edited_monitor

        monitor_page.locator(
            '#conversationMonitorDraft ~ .card-actions [data-reset-draft="monitor"]'
        ).click()
        monitor_page.locator("[data-proposal-review-confirm]").click()
        assert monitor_area.input_value() == monitor_default
        monitor_area.fill(edited_monitor)
        monitor_page.locator('[data-mode="workflow"]').click()
        monitor_page.locator('#workflowView [data-step="4"]').click()
        assert monitor_page.locator("#workflowMonitorDraft").input_value() == edited_monitor
        monitor_page.screenshot(
            path=args.output / "monitor-minimal-workflow.png", full_page=True
        )

        monitor_page.locator('[data-demo-state-button="missing"]').click()
        monitor_page.locator('body[data-demo-state="missing"]').wait_for()
        missing_monitor = monitor_page.locator("#workflowMissingMonitorDraft")
        assert missing_monitor.is_visible()
        assert missing_monitor.input_value() == edited_monitor
        assert "직전 한 해 전체 재직 조건" in monitor_page.locator(
            "[data-missing-monitor-answer]"
        ).first.inner_text()
        assert monitor_page.locator(
            '#workflowView [data-reset-draft="it"]:visible'
        ).count() == 0
        monitor_page.evaluate("navigator.clipboard.writeText('before-monitor-copy')")
        monitor_page.locator(
            '#workflowView [data-copy-draft="monitor"]:visible'
        ).click()
        assert monitor_page.evaluate("navigator.clipboard.readText()") == edited_monitor

        monitor_page.set_viewport_size({"width": 390, "height": 844})
        missing_monitor.scroll_into_view_if_needed()
        assert monitor_page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        ) <= 0
        monitor_page.screenshot(
            path=args.output / "monitor-minimal-missing-mobile.png", full_page=True
        )
        monitor_context.close()

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
        assert marker in page.locator(
            "#conversationView [data-stated-facts]"
        ).first.inner_text()

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
