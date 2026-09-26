from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright


DB_NAME = "employee-assistant-local-drafts"


def open_it_draft(page: Page) -> Page:
    page.locator('[data-open-panel="draft"]').first.click()
    page.locator('[data-draft-tab="it"]').first.click()
    return page


def wait_ready(page: Page) -> None:
    page.locator('body[data-demo-state="normal"]').wait_for()
    page.locator("#draftStorageStatus:not([data-state='checking'])").wait_for()


def restore_saved(page: Page) -> None:
    page.locator("[data-restore-draft]").click()
    page.locator("#restoreDraftDialog").wait_for()
    page.locator("[data-restore-confirm]").click()
    page.locator("#restoreDraftDialog").wait_for(state="hidden")
    page.locator("#draftStorageStatus", has_text="저장본을 불러왔습니다").wait_for()
    page.locator('body[data-demo-state="normal"]').wait_for()


def new_page(context: BrowserContext, base_url: str) -> Page:
    page = context.new_page()
    page.goto(base_url, wait_until="networkidle")
    wait_ready(page)
    return page


def reload_without_beforeunload(page: Page) -> None:
    dialogs: list[str] = []

    def handle_dialog(dialog) -> None:
        dialogs.append(dialog.type)
        dialog.accept()

    page.on("dialog", handle_dialog)
    try:
        page.reload(wait_until="networkidle")
    finally:
        page.remove_listener("dialog", handle_dialog)
    assert dialogs == [], dialogs


def dismiss_beforeunload_reload(page: Page) -> None:
    dialogs: list[str] = []

    def handle_dialog(dialog) -> None:
        dialogs.append(dialog.type)
        dialog.dismiss()

    page.on("dialog", handle_dialog)
    try:
        page.evaluate("() => window.location.reload()")
    finally:
        page.remove_listener("dialog", handle_dialog)
    assert dialogs == ["beforeunload"], dialogs


def accept_beforeunload_reload(page: Page) -> None:
    dialogs: list[str] = []

    def handle_dialog(dialog) -> None:
        dialogs.append(dialog.type)
        dialog.accept()

    page.on("dialog", handle_dialog)
    try:
        page.reload(wait_until="networkidle")
    finally:
        page.remove_listener("dialog", handle_dialog)
    assert dialogs == ["beforeunload"], dialogs


def write_raw_record(page: Page, record: dict) -> None:
    page.evaluate(
        """
        async ({ dbName, record }) => {
          const db = await new Promise((resolve, reject) => {
            const request = indexedDB.open(dbName, 1);
            request.onupgradeneeded = () => {
              if (!request.result.objectStoreNames.contains('drafts')) {
                request.result.createObjectStore('drafts', { keyPath: 'id' });
              }
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });
          await new Promise((resolve, reject) => {
            const tx = db.transaction('drafts', 'readwrite');
            tx.objectStore('drafts').put(record);
            tx.oncomplete = resolve;
            tx.onerror = () => reject(tx.error);
            tx.onabort = () => reject(tx.error);
          });
          db.close();
        }
        """,
        {"dbName": DB_NAME, "record": record},
    )


def read_raw_record(page: Page) -> dict:
    return page.evaluate(
        """
        async (dbName) => {
          const db = await new Promise((resolve, reject) => {
            const request = indexedDB.open(dbName, 1);
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });
          const record = await new Promise((resolve, reject) => {
            const tx = db.transaction('drafts', 'readonly');
            const request = tx.objectStore('drafts').get('active-draft');
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });
          db.close();
          return record;
        }
        """,
        DB_NAME,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8767")
    parser.add_argument(
        "--output", type=Path, default=Path("test-results/draft-resume-flow")
    )
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    if args.browser_executable is not None and not args.browser_executable.is_file():
        parser.error(f"browser executable does not exist: {args.browser_executable}")
    args.output.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=str(args.browser_executable) if args.browser_executable else None,
        )
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.grant_permissions(
            ["clipboard-read", "clipboard-write"], origin=args.base_url
        )
        page = new_page(context, args.base_url)
        errors: list[str] = []
        page.on(
            "console",
            lambda message: errors.append(message.text)
            if message.type == "error"
            else None,
        )

        # Reading, changing layouts, and returning to the exact initial content
        # do not request a leave confirmation. Only content that would be lost
        # registers beforeunload, and the native dialog may be dismissed or
        # accepted without changing the explicit-save contract.
        leave_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        leave_context.grant_permissions(
            ["clipboard-read", "clipboard-write"], origin=args.base_url
        )
        leave_page = new_page(leave_context, args.base_url)
        leave_page.locator('[data-mode="workflow"]').click()
        leave_page.locator('#workflowView [data-step="3"]').click()
        leave_page.locator('[data-mode="conversation"]').click()
        leave_page.locator(
            '#conversationView [data-open-answer-evidence="monitor"]:visible'
        ).click()
        leave_page.locator("[data-show-all-evidence]").click()
        leave_page.locator("[data-return-to-answer]").click()
        reload_without_beforeunload(leave_page)

        leave_tenure = leave_page.locator('#conversationView [data-field="tenure"]')
        leave_tenure.fill("4년")
        leave_tenure.fill("")
        reload_without_beforeunload(leave_page)

        leave_tenure = leave_page.locator('#conversationView [data-field="tenure"]')
        leave_tenure.fill("4년")
        open_it_draft(leave_page)
        leave_it = leave_page.locator("#conversationItDraft")
        leave_it.fill(leave_it.input_value() + "\n떠나기 전에 확인할 미저장 문장")
        dismiss_beforeunload_reload(leave_page)
        assert leave_tenure.input_value() == "4년"
        assert leave_it.input_value().endswith("떠나기 전에 확인할 미저장 문장")
        leave_page.screenshot(path=args.output / "leave-warning-dismissed.png", full_page=True)

        leave_page.locator('#conversationView [data-copy-draft="it"]:visible').click()
        if leave_page.locator("#copyReviewDialog").is_visible():
            leave_page.locator("[data-copy-review-confirm]").click()
        dismiss_beforeunload_reload(leave_page)
        assert leave_it.input_value().endswith("떠나기 전에 확인할 미저장 문장")

        leave_page.evaluate(
            """
            () => {
              const original = window.EmployeeAssistantDraftStore.save;
              window.EmployeeAssistantDraftStore.save = function (revision, payload) {
                return new Promise(function (resolve, reject) {
                  setTimeout(function () { original(revision, payload).then(resolve, reject); }, 350);
                });
              };
            }
            """
        )
        leave_page.locator("[data-save-draft]").click()
        leave_it.fill(leave_it.input_value() + "\n저장 요청 뒤에 추가한 문장")
        dismiss_beforeunload_reload(leave_page)
        leave_page.locator("#toast", has_text="저장은 완료됐지만").wait_for()
        dismiss_beforeunload_reload(leave_page)
        leave_page.locator("[data-save-draft]").click()
        leave_page.locator("#draftStorageStatus", has_text="마지막 저장본과 같습니다").wait_for()
        reload_without_beforeunload(leave_page)
        wait_ready(leave_page)
        restore_saved(leave_page)
        reload_without_beforeunload(leave_page)
        wait_ready(leave_page)
        restore_saved(leave_page)

        leave_it = leave_page.locator("#conversationItDraft")
        leave_it.fill(leave_it.input_value() + "\n저장 실패 뒤에도 지킬 문장")
        leave_page.evaluate(
            """
            () => {
              window.EmployeeAssistantDraftStore.save = function () {
                var error = new Error('forced failure');
                error.code = 'write_failed';
                return Promise.reject(error);
              };
            }
            """
        )
        leave_page.locator("[data-save-draft]").click()
        leave_page.locator("#draftStorageStatus[data-state='error']").wait_for()
        dismiss_beforeunload_reload(leave_page)
        assert leave_it.input_value().endswith("저장 실패 뒤에도 지킬 문장")
        accept_beforeunload_reload(leave_page)
        wait_ready(leave_page)
        restore_saved(leave_page)
        leave_page.locator("[data-new-inquiry]").click()
        leave_page.locator("[data-new-inquiry-confirm]").click()
        leave_page.locator('body[data-demo-state="normal"]').wait_for()
        reload_without_beforeunload(leave_page)
        leave_context.close()

        # A search response that succeeds only after an explicit restore is not
        # the source of that restored draft. It must not promote personal text
        # to the reproducible initial example and hide loss after saved deletion.
        initial_failure_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        initial_failure = new_page(initial_failure_context, args.base_url)
        open_it_draft(initial_failure)
        important_draft = "직접 편집한 중요한 문의 글"
        initial_failure.locator("#conversationItDraft").fill(important_draft)
        initial_failure.locator("[data-save-draft]").click()
        initial_failure.locator(
            "#draftStorageStatus", has_text="마지막 저장본과 같습니다"
        ).wait_for()
        initial_failure.route("**/api/workspace", lambda route: route.abort(), times=1)
        reload_without_beforeunload(initial_failure)
        initial_failure.locator('body[data-demo-state="error"]').wait_for()
        initial_failure.locator(
            "#draftStorageStatus:not([data-state='checking'])"
        ).wait_for()
        restore_saved(initial_failure)
        assert initial_failure.locator("#conversationItDraft").input_value() == important_draft
        initial_failure.locator("[data-delete-saved]").click()
        initial_failure.locator("[data-delete-confirm]").click()
        initial_failure.locator(
            "#draftStorageStatus", has_text="임시 저장본이 없습니다"
        ).wait_for()
        initial_failure.screenshot(
            path=args.output / "restored-after-initial-failure-delete.png", full_page=True
        )
        assert initial_failure.evaluate(
            """
            () => {
              const event = new Event('beforeunload', { cancelable: true });
              window.dispatchEvent(event);
              return event.defaultPrevented;
            }
            """
        )
        dismiss_beforeunload_reload(initial_failure)
        assert initial_failure.locator("#conversationItDraft").input_value() == important_draft
        accept_beforeunload_reload(initial_failure)
        wait_ready(initial_failure)
        assert initial_failure.locator("#conversationItDraft").input_value() != important_draft
        assert initial_failure.locator("[data-restore-draft]").is_disabled()
        initial_failure_context.close()

        open_it_draft(page)
        tenure = page.locator('#conversationView [data-field="tenure"]')
        symptom = page.locator('#conversationView [data-field="symptom"]')
        purchase = page.locator('#conversationView [data-field="purchase"]')
        tenure.fill("4년")
        symptom.fill("지난주부터 화상회의 중")
        purchase.select_option("not-purchased")
        page.locator('#conversationView [data-apply-conditions]').first.click()
        page.locator('body[data-demo-state="normal"]').wait_for()
        page.locator('#conversationView [data-reset-draft="it"]:visible').click()
        page.locator("#proposalReviewDialog").wait_for()
        page.locator("[data-proposal-review-confirm]").click()
        it_area = page.locator("#conversationItDraft")
        four_year_draft = it_area.input_value() + "\n직접 고친 확인 문장입니다."
        it_area.fill(four_year_draft)
        tenure.fill("2년 10개월")
        saved_monitor = page.locator("#conversationMonitorDraft").input_value()
        saved_it = it_area.input_value()

        page.locator("[data-save-draft]").click()
        page.locator("#draftStorageStatus", has_text="마지막 저장본과 같습니다").wait_for()
        assert "마지막 저장본과 같습니다" in page.locator(
            "#draftStorageStatus"
        ).inner_text()
        stored_record = read_raw_record(page)
        assert set(stored_record) == {
            "id", "kind", "schema_version", "revision", "saved_at", "expires_at", "payload"
        }
        assert set(stored_record["payload"]) == {
            "inquiry_type", "employee_input", "drafts", "edit_meta", "ui"
        }
        assert int(
            page.evaluate(
                "([savedAt, expiresAt]) => Date.parse(expiresAt) - Date.parse(savedAt)",
                [stored_record["saved_at"], stored_record["expires_at"]],
            )
        ) == 24 * 60 * 60 * 1000
        it_area.fill(saved_it + "\n저장 버튼 뒤의 미저장 문장입니다.")
        assert "마지막 저장 뒤 변경은 사라집니다" in page.locator(
            "#draftStorageStatus"
        ).inner_text()
        page.screenshot(path=args.output / "saved-with-unsaved-change.png", full_page=True)

        accept_beforeunload_reload(page)
        wait_ready(page)
        assert page.locator("[data-save-draft]").is_disabled()
        assert "자동으로 열거나 덮어쓰지 않습니다" in page.locator(
            "#draftStorageStatus"
        ).inner_text()
        assert page.locator("#conversationItDraft").input_value() != saved_it
        page.locator("[data-restore-draft]").click()
        page.locator("#restoreDraftDialog").wait_for()
        page.screenshot(path=args.output / "restore-confirmation.png", full_page=True)
        page.locator("[data-restore-confirm]").click()
        page.locator("#restoreDraftDialog").wait_for(state="hidden")
        page.locator("#draftStorageStatus", has_text="저장본을 불러왔습니다").wait_for()
        page.locator('body[data-demo-state="normal"]').wait_for()
        assert page.locator("#conversationItDraft").is_visible()
        assert page.evaluate("document.activeElement && document.activeElement.id") == "conversationItDraft"
        assert page.locator('#conversationView [data-field="tenure"]').input_value() == "2년 10개월"
        assert page.locator("#conversationMonitorDraft").input_value() == saved_monitor
        assert page.locator("#conversationItDraft").input_value() == saved_it
        assert "임시 저장에서 불러온 글" in page.locator(
            '#conversationView [data-proposal-note="it"]:visible'
        ).inner_text()
        page.locator('#conversationView [data-copy-draft="it"]:visible').click()
        assert page.locator("#copyReviewDialog").is_visible()
        assert "임시 저장에서 불러온 글" in page.locator(
            "#copyReviewReasons"
        ).inner_text()
        page.locator("[data-copy-review-cancel]").click()
        page.screenshot(path=args.output / "restored-a.png", full_page=True)

        # Comparing or applying a current proposal changes only the in-memory
        # editing state. The explicitly saved record remains the same until the
        # employee saves again.
        stored_before_proposal_review = read_raw_record(page)
        page.locator('#conversationView [data-reset-draft="it"]:visible').click()
        assert page.locator("#proposalReviewDialog").is_visible()
        assert page.locator("#proposalReviewCurrent").text_content() == saved_it
        restored_proposal = page.locator("#proposalReviewProposed").text_content()
        assert "2년 10개월째" in restored_proposal
        assert page.locator("#proposalReviewCurrent .proposal-diff-removed").count() > 0
        assert page.locator("#proposalReviewProposed .proposal-diff-added").count() > 0
        page.locator("[data-proposal-review-cancel]").click()
        assert page.locator("#conversationItDraft").input_value() == saved_it
        assert read_raw_record(page) == stored_before_proposal_review
        page.locator('#conversationView [data-reset-draft="it"]:visible').click()
        page.locator("[data-proposal-review-confirm]").click()
        assert page.locator("#conversationItDraft").input_value() == restored_proposal
        assert read_raw_record(page) == stored_before_proposal_review
        assert "저장 이후 입력이나 글이 바뀌었습니다" in page.locator(
            "#draftStorageStatus"
        ).inner_text()

        # A saved B layout returns to its editing step. Canceling restore keeps
        # whichever B step the employee was currently reading.
        b_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        b_page = new_page(b_context, args.base_url)
        b_page.locator('[data-mode="workflow"]').click()
        b_page.locator('#workflowView [data-step="4"]').click()
        b_page.locator('#workflowView [data-draft-tab="it"]:visible').click()
        b_saved_it = b_page.locator("#workflowItDraft").input_value() + "\nB 배치에서 직접 고친 글"
        b_page.locator("#workflowItDraft").fill(b_saved_it)
        b_page.locator("[data-save-draft]").click()
        b_page.locator("#draftStorageStatus", has_text="마지막 저장본과 같습니다").wait_for()
        reload_without_beforeunload(b_page)
        wait_ready(b_page)
        b_page.locator('[data-mode="workflow"]').click()
        b_page.locator('#workflowView [data-step="2"]').click()
        assert b_page.locator('#workflowView [data-step-panel="2"]').is_visible()
        b_page.locator("[data-restore-draft]").click()
        b_page.locator("#restoreDraftDialog").wait_for()
        b_page.locator("[data-restore-cancel]").click()
        assert b_page.locator('#workflowView [data-step-panel="2"]').is_visible()
        b_page.locator('#workflowView [data-step="3"]').click()
        assert b_page.locator('#workflowView [data-step-panel="3"]').is_visible()
        restore_saved(b_page)
        assert b_page.locator('#workflowView [data-step-panel="4"]').is_visible()
        assert b_page.locator("#workflowItDraft").is_visible()
        assert b_page.locator("#workflowItDraft").input_value() == b_saved_it
        assert b_page.evaluate("document.activeElement && document.activeElement.id") == "workflowItDraft"
        b_page.screenshot(path=args.output / "restored-b-direct.png", full_page=True)
        b_context.close()

        # On a narrow screen the restored editor itself, not only its surrounding
        # panel, is focused and scrolled into the viewport.
        mobile_restore_context = browser.new_context(viewport={"width": 390, "height": 844})
        mobile_restore = new_page(mobile_restore_context, args.base_url)
        open_it_draft(mobile_restore)
        mobile_saved_it = mobile_restore.locator("#conversationItDraft").input_value() + "\n모바일 복원 글"
        mobile_restore.locator("#conversationItDraft").fill(mobile_saved_it)
        mobile_restore.locator("[data-save-draft]").click()
        mobile_restore.locator("#draftStorageStatus", has_text="마지막 저장본과 같습니다").wait_for()
        reload_without_beforeunload(mobile_restore)
        wait_ready(mobile_restore)
        restore_saved(mobile_restore)
        mobile_restore.wait_for_function(
            "() => document.activeElement && document.activeElement.id === 'conversationItDraft'"
        )
        mobile_restore.wait_for_function(
            """
            () => {
              const node = document.querySelector('#conversationItDraft');
              const rect = node.getBoundingClientRect();
              return rect.top >= 0 && rect.bottom <= window.innerHeight;
            }
            """
        )
        mobile_rect = mobile_restore.locator("#conversationItDraft").evaluate(
            "node => ({ top: node.getBoundingClientRect().top, bottom: node.getBoundingClientRect().bottom, height: innerHeight })"
        )
        mobile_restore.screenshot(path=args.output / "restored-mobile-editor.png", full_page=True)
        assert 0 <= mobile_rect["top"] < mobile_rect["bottom"] <= mobile_rect["height"], mobile_rect
        assert mobile_restore.locator("#conversationItDraft").input_value() == mobile_saved_it
        mobile_restore_context.close()

        # The evidence refresh after restore may only reposition the restored
        # editor while the employee is still there. Moving to an input and
        # typing during a delayed response keeps that input focused.
        accept_beforeunload_reload(page)
        wait_ready(page)
        page.evaluate(
            """
            () => {
              const originalFetch = window.fetch.bind(window);
              window.fetch = function () {
                const args = arguments;
                return originalFetch(...args).then(function (response) {
                  return new Promise(function (resolve) {
                    setTimeout(function () { resolve(response); }, 500);
                  });
                });
              };
            }
            """
        )
        page.locator("[data-restore-draft]").click()
        page.locator("#restoreDraftDialog").wait_for()
        page.locator("[data-restore-confirm]").click()
        page.locator("#restoreDraftDialog").wait_for(state="hidden")
        page.locator("#draftStorageStatus", has_text="저장본을 불러왔습니다").wait_for()
        delayed_tenure = page.locator('#conversationView [data-field="tenure"]')
        delayed_tenure.fill("재검색 중에 고친 재직 기간")
        page.locator('body[data-demo-state="normal"]').wait_for()
        page.wait_for_timeout(550)
        assert delayed_tenure.input_value() == "재검색 중에 고친 재직 기간"
        assert page.evaluate(
            "() => document.activeElement === document.querySelector('#conversationView [data-field=\"tenure\"]')"
        )

        page.close()
        page = new_page(context, args.base_url)
        restore_saved(page)
        assert page.locator("#conversationItDraft").is_visible()
        assert page.locator("#conversationItDraft").input_value() == saved_it
        page.locator('[data-mode="workflow"]').click()
        page.locator('#workflowView [data-step="4"]').click()
        page.locator('#workflowView [data-draft-tab="it"]:visible').click()
        page.screenshot(path=args.output / "restored-b.png", full_page=True)

        page.locator('[data-demo-state-button="missing"]').click()
        page.locator('body[data-demo-state="missing"]').wait_for()
        page.locator('#workflowView [data-draft-tab="it"]:visible').click()
        restored_missing = page.locator("#workflowMissingItDraft")
        assert restored_missing.is_visible()
        assert restored_missing.input_value() == saved_it
        page.locator('#workflowView [data-copy-draft="it"]:visible').click()
        assert page.locator("#copyReviewDialog").is_visible()
        page.locator("[data-copy-review-cancel]").click()
        page.screenshot(path=args.output / "restored-missing-evidence.png", full_page=True)

        page.route("**/api/workspace", lambda route: route.abort())
        page.locator('[data-demo-state-button="loading"]').click()
        page.locator('body[data-demo-state="error"]').wait_for()
        assert restored_missing.is_visible()
        assert restored_missing.input_value() == saved_it
        page.unroute("**/api/workspace")
        page.locator("#connectionNotice [data-retry]").click()
        page.locator('body[data-demo-state="normal"]').wait_for()

        # Two tabs explicitly adopt the same record. Only the first competing save wins.
        page_a = page
        page_b = new_page(context, args.base_url)
        restore_saved(page_b)
        open_it_draft(page_b)
        page_a.locator('[data-mode="conversation"]').click()
        open_it_draft(page_a)
        page_a.locator("#conversationItDraft").fill(saved_it + "\nA 탭 저장")
        page_a.locator("[data-save-draft]").click()
        page_a.locator("#toast", has_text="임시 저장했습니다").wait_for()
        page_b.locator("#conversationItDraft").fill(saved_it + "\nB 탭의 보존할 글")
        page_b.locator("[data-save-draft]").click()
        page_b.locator("#draftStorageStatus", has_text="다른 탭").wait_for()
        assert page_b.locator("#conversationItDraft").input_value().endswith("B 탭의 보존할 글")
        assert page_b.locator("[data-save-draft]").is_disabled()

        # Explicitly restore the winning record, then reject resurrection after another tab deletes it.
        restore_saved(page_b)
        page_a.locator("[data-delete-saved]").click()
        page_a.locator("[data-delete-confirm]").click()
        page_a.locator("#draftStorageStatus", has_text="임시 저장본이 없습니다").wait_for()
        page_b.locator("#conversationItDraft").fill(
            page_b.locator("#conversationItDraft").input_value() + "\n삭제 뒤 옛 탭 글"
        )
        page_b.locator("[data-save-draft]").click()
        page_b.locator("#draftStorageStatus", has_text="다른 탭").wait_for()
        assert page_b.locator("[data-save-draft]").is_disabled()
        assert "오래된 글을 새 저장본으로 되살리지 않습니다" in page_b.locator(
            "#draftStorageStatus"
        ).inner_text() or "다른 탭에서 저장본이 먼저 바뀌어" in page_b.locator(
            "#draftStorageStatus"
        ).inner_text()

        # A new inquiry adopts the empty revision, but a stale delete dialog cannot delete a later save.
        page_b.locator("[data-new-inquiry]").click()
        page_b.locator("[data-new-inquiry-confirm]").click()
        page_b.locator('body[data-demo-state="normal"]').wait_for()
        page_b.locator("[data-save-draft]").click()
        page_b.locator("#draftStorageStatus", has_text="마지막 저장본과 같습니다").wait_for()
        accept_beforeunload_reload(page_a)
        wait_ready(page_a)
        restore_saved(page_a)
        page_a.locator("[data-delete-saved]").click()
        assert page_a.locator("#deleteSavedDialog").is_visible()
        open_it_draft(page_b)
        page_b.locator("#conversationItDraft").fill(
            page_b.locator("#conversationItDraft").input_value() + "\n더 새 저장본"
        )
        page_b.locator("[data-save-draft]").click()
        page_b.locator("#draftStorageStatus", has_text="마지막 저장본과 같습니다").wait_for()
        page_a.locator("[data-delete-confirm]").click()
        page_a.locator("#draftStorageStatus", has_text="다른 탭").wait_for()
        assert page_a.locator("#deleteSavedDialog").is_hidden()

        # A delayed restore never overwrites edits made while the storage read is pending.
        reload_without_beforeunload(page_a)
        wait_ready(page_a)
        page_a.evaluate(
            """
            () => {
            window.__draftStoreLoad = window.EmployeeAssistantDraftStore.load;
            window.EmployeeAssistantDraftStore.load = function (revision) {
              return new Promise(function (resolve, reject) {
                setTimeout(function () {
                  window.__draftStoreLoad(revision).then(resolve, reject);
                }, 350);
              });
            };
            }
            """
        )
        page_a.locator("[data-restore-draft]").click()
        page_a.locator("[data-restore-confirm]").click()
        page_a.locator('#conversationView [data-field="tenure"]').fill("복원 중 새 입력")
        page_a.wait_for_timeout(500)
        assert page_a.locator('#conversationView [data-field="tenure"]').input_value() == "복원 중 새 입력"
        assert "덮어쓰지 않았습니다" in page_a.locator("#toast").inner_text()

        # Storage failure leaves the in-memory draft available and does not claim success.
        page_a.evaluate(
            """
            () => {
            window.EmployeeAssistantDraftStore.save = function () {
              var error = new Error('forced failure');
              error.code = 'write_failed';
              return Promise.reject(error);
            };
            }
            """
        )
        page_a.locator("[data-delete-saved]").click()
        page_a.locator("[data-delete-confirm]").click()
        page_a.locator("#draftStorageStatus", has_text="임시 저장본이 없습니다").wait_for()
        open_it_draft(page_a)
        before_failed_save = page_a.locator("#conversationItDraft").input_value()
        page_a.locator("[data-save-draft]").click()
        page_a.locator("#draftStorageStatus[data-state='error']").wait_for()
        assert page_a.locator("#conversationItDraft").input_value() == before_failed_save
        assert "저장하지 못했습니다" in page_a.locator("#draftStorageStatus").inner_text()

        # A save that finishes after "new inquiry" may update the saved record, never the new screen.
        late_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        late_page = new_page(late_context, args.base_url)
        open_it_draft(late_page)
        late_page.locator("#conversationItDraft").fill("늦은 저장에만 들어갈 옛 글")
        late_page.evaluate(
            """
            () => {
              const original = window.EmployeeAssistantDraftStore.save;
              window.EmployeeAssistantDraftStore.save = function (revision, payload) {
                return new Promise(function (resolve, reject) {
                  setTimeout(function () { original(revision, payload).then(resolve, reject); }, 350);
                });
              };
            }
            """
        )
        late_page.locator("[data-save-draft]").click()
        late_page.locator("[data-new-inquiry]").click()
        late_page.locator("[data-new-inquiry-confirm]").click()
        late_page.locator('body[data-demo-state="normal"]').wait_for()
        late_page.wait_for_timeout(500)
        open_it_draft(late_page)
        assert "늦은 저장에만 들어갈 옛 글" not in late_page.locator(
            "#conversationItDraft"
        ).input_value()
        assert "마지막 저장 뒤 변경은 사라집니다" in late_page.locator(
            "#draftStorageStatus"
        ).inner_text()
        late_context.close()

        # A valid-looking future schema is preserved. Only an explicit, guarded
        # delete may remove it; a write failure must not claim success.
        future_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        future_page = new_page(future_context, args.base_url)
        future_record = deepcopy(stored_record)
        future_record["schema_version"] = "employee-assistant.draft.v2"
        future_record["revision"] = 7
        future_record["payload"]["drafts"]["it"] = "미래 형식에 남겨 둔 직원 초안"
        write_raw_record(future_page, future_record)
        future_page.reload(wait_until="networkidle")
        wait_ready(future_page)
        assert "읽을 수 없는 저장본이 남아 있습니다" in future_page.locator(
            "#draftStorageStatus"
        ).inner_text()
        assert read_raw_record(future_page) == future_record
        assert future_page.locator("[data-save-draft]").is_disabled()
        assert future_page.locator("[data-restore-draft]").is_disabled()
        assert future_page.locator("[data-delete-saved]").is_enabled()
        open_it_draft(future_page)
        future_page.locator("#conversationItDraft").fill("현재 화면의 보존할 글")
        future_page.locator("[data-delete-saved]").click()
        assert "읽을 수 없는 저장본" in future_page.locator("#deleteSavedTitle").inner_text()
        future_page.screenshot(path=args.output / "unreadable-preserved.png", full_page=True)
        future_page.locator("[data-delete-cancel]").click()
        assert read_raw_record(future_page) == future_record
        assert future_page.locator("#conversationItDraft").input_value() == "현재 화면의 보존할 글"

        future_page.evaluate(
            """
            () => {
              window.__originalDraftStorePut = IDBObjectStore.prototype.put;
              IDBObjectStore.prototype.put = function (value) {
                if (value && value.kind === 'empty') {
                  throw new DOMException('forced transaction abort', 'AbortError');
                }
                return window.__originalDraftStorePut.apply(this, arguments);
              };
            }
            """
        )
        future_page.locator("[data-delete-saved]").click()
        future_page.locator("[data-delete-confirm]").click()
        future_page.locator("#draftStorageStatus", has_text="삭제하지 못했습니다").wait_for()
        future_page.evaluate(
            """
            () => {
              IDBObjectStore.prototype.put = window.__originalDraftStorePut;
              delete window.__originalDraftStorePut;
            }
            """
        )
        assert read_raw_record(future_page) == future_record
        assert "저장본만 삭제했습니다" not in future_page.locator("#toast").inner_text()
        assert future_page.locator("#conversationItDraft").input_value() == "현재 화면의 보존할 글"

        future_page.locator("[data-delete-saved]").click()
        future_page.locator("[data-delete-confirm]").click()
        future_page.locator("#draftStorageStatus", has_text="임시 저장본이 없습니다").wait_for()
        deleted_future = read_raw_record(future_page)
        assert deleted_future["kind"] == "empty"
        assert "payload" not in deleted_future
        assert future_page.locator("#conversationItDraft").input_value() == "현재 화면의 보존할 글"
        future_context.close()

        # The opaque guard compares the full observed record, not only its
        # integer revision, before deleting in a competing tab.
        conflict_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        conflict_page = new_page(conflict_context, args.base_url)
        guarded_record = deepcopy(future_record)
        guarded_record["revision"] = 13
        guarded_record["payload"]["drafts"]["it"] = "확인창을 열 때의 글"
        write_raw_record(conflict_page, guarded_record)
        conflict_page.reload(wait_until="networkidle")
        wait_ready(conflict_page)
        conflict_page.locator("[data-delete-saved]").click()
        replacement_page = new_page(conflict_context, args.base_url)
        replacement_record = deepcopy(guarded_record)
        replacement_record["payload"]["drafts"]["it"] = "같은 revision의 다른 탭 글"
        write_raw_record(replacement_page, replacement_record)
        conflict_page.locator("[data-delete-confirm]").click()
        conflict_page.locator("#draftStorageStatus", has_text="다른 탭").wait_for()
        assert read_raw_record(replacement_page) == replacement_record
        conflict_page.screenshot(path=args.output / "unreadable-delete-conflict.png", full_page=True)
        conflict_context.close()

        # Sparse arrays must not compare equal to an observed populated array.
        # This is the exact same-revision deletion counterexample from review.
        sparse_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        sparse_page = new_page(sparse_context, args.base_url)
        sparse_record = {
            "id": "active-draft",
            "kind": "snapshot",
            "schema_version": "future-v2",
            "revision": 2,
            "payload": {"notes": ["처음 확인한 글"]},
        }
        write_raw_record(sparse_page, sparse_record)
        sparse_page.reload(wait_until="networkidle")
        wait_ready(sparse_page)
        sparse_page.locator("[data-delete-saved]").click()
        sparse_replacement = new_page(sparse_context, args.base_url)
        sparse_replacement.evaluate(
            """
            async (dbName) => {
              const db = await new Promise((resolve, reject) => {
                const request = indexedDB.open(dbName, 1);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
              });
              await new Promise((resolve, reject) => {
                const tx = db.transaction('drafts', 'readwrite');
                tx.objectStore('drafts').put({
                  id: 'active-draft',
                  kind: 'snapshot',
                  schema_version: 'future-v2',
                  revision: 2,
                  payload: { notes: new Array(1) }
                });
                tx.oncomplete = resolve;
                tx.onerror = () => reject(tx.error);
                tx.onabort = () => reject(tx.error);
              });
              db.close();
            }
            """,
            DB_NAME,
        )
        sparse_page.locator("[data-delete-confirm]").click()
        sparse_page.locator("#draftStorageStatus", has_text="다른 탭").wait_for()
        sparse_result = sparse_replacement.evaluate(
            """
            async (dbName) => {
              const db = await new Promise((resolve, reject) => {
                const request = indexedDB.open(dbName, 1);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
              });
              const record = await new Promise((resolve, reject) => {
                const tx = db.transaction('drafts', 'readonly');
                const request = tx.objectStore('drafts').get('active-draft');
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
              });
              db.close();
              return {
                kind: record.kind,
                revision: record.revision,
                notesLength: record.payload.notes.length,
                notesHasIndexZero: Object.prototype.hasOwnProperty.call(record.payload.notes, '0')
              };
            }
            """,
            DB_NAME,
        )
        assert sparse_result == {
            "kind": "snapshot",
            "revision": 2,
            "notesLength": 1,
            "notesHasIndexZero": False,
        }
        sparse_context.close()

        # A malformed current-schema record is also preserved and isolated.
        corrupt_context = browser.new_context()
        corrupt_page = new_page(corrupt_context, args.base_url)
        corrupt_record = deepcopy(stored_record)
        corrupt_record["revision"] = 17
        corrupt_record["payload"]["drafts"]["it"] = ["문자열이 아닌 손상값"]
        write_raw_record(corrupt_page, corrupt_record)
        corrupt_page.reload(wait_until="networkidle")
        wait_ready(corrupt_page)
        assert "읽을 수 없는 저장본이 남아 있습니다" in corrupt_page.locator(
            "#draftStorageStatus"
        ).inner_text()
        assert read_raw_record(corrupt_page) == corrupt_record
        assert corrupt_page.locator("[data-save-draft]").is_disabled()
        assert corrupt_page.locator("[data-restore-draft]").is_disabled()
        assert corrupt_page.locator("[data-delete-saved]").is_enabled()
        corrupt_context.close()

        # Only a valid record in the current schema follows the 24-hour auto-delete rule.
        expired_context = browser.new_context()
        expired_page = new_page(expired_context, args.base_url)
        expired_record = {
            "id": "active-draft",
            "kind": "snapshot",
            "schema_version": "employee-assistant.draft.v1",
            "revision": 1,
            "saved_at": "2020-01-01T00:00:00.000Z",
            "expires_at": "2020-01-02T00:00:00.000Z",
            "payload": {
                "inquiry_type": "monitor_and_laptop_replacement",
                "employee_input": {"tenure": "4년", "symptom": "예시", "purchase": "not-purchased"},
                "drafts": {"monitor": "만료 모니터", "it": "만료 IT"},
                "edit_meta": {"monitor_touched": True, "it_touched": True},
                "ui": {"mode": "conversation", "active_draft": "it"},
            },
        }
        write_raw_record(expired_page, expired_record)
        expired_page.reload(wait_until="networkidle")
        wait_ready(expired_page)
        assert "24시간이 지난 저장 내용" in expired_page.locator(
            "#draftStorageStatus"
        ).inner_text()
        assert expired_page.locator("[data-restore-draft]").is_disabled()
        deleted_expired = read_raw_record(expired_page)
        assert deleted_expired["kind"] == "empty"
        assert "payload" not in deleted_expired
        open_it_draft(expired_page)
        assert expired_page.locator("#conversationItDraft").input_value() != "만료 IT"
        expired_context.close()

        unavailable_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        unavailable_context.add_init_script(
            "Object.defineProperty(window, 'indexedDB', { value: null, configurable: true });"
        )
        unavailable_page = new_page(unavailable_context, args.base_url)
        assert "임시 저장소를 사용할 수 없습니다" in unavailable_page.locator(
            "#draftStorageStatus"
        ).inner_text()
        assert unavailable_page.locator("[data-save-draft]").is_disabled()
        open_it_draft(unavailable_page)
        unavailable_page.locator("#conversationItDraft").fill("저장소 없이도 남아 있는 화면 글")
        assert unavailable_page.locator("#conversationItDraft").input_value() == "저장소 없이도 남아 있는 화면 글"
        unavailable_context.close()

        mobile_context = browser.new_context(viewport={"width": 390, "height": 844})
        mobile = new_page(mobile_context, args.base_url)
        overflow = mobile.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, overflow
        mobile.screenshot(path=args.output / "mobile-storage.png", full_page=True)
        mobile_context.close()

        assert not errors, errors
        context.close()
        browser.close()
        print("draft resume flow: PASS")


if __name__ == "__main__":
    main()
