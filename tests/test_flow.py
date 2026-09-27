from __future__ import annotations

import unittest

from employee_assistant.flow import (
    apply_current_proposal,
    create_workspace,
    edit_draft,
    load_corpus,
    process_request,
    refresh_workspace,
)


def request(
    tenure: str = "4년",
    laptop_inquiry_goal: str = "replacement_process",
    inquiry_scope: str = "both",
) -> dict:
    return {
        "inquiry_type": "monitor_and_laptop_replacement",
        "laptop_inquiry_goal": laptop_inquiry_goal,
        "inquiry_scope": inquiry_scope,
        "user_text": "모니터와 느려진 노트북 문의",
        "employee_facts": {
            "tenure": tenure,
            "symptom": "지난주부터 화상회의 중",
            "purchase_status": "not_purchased",
        },
    }


class FlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus = load_corpus()

    def test_fact_correction_preserves_text_until_explicit_apply(self) -> None:
        workspace = create_workspace(self.corpus, request())
        old_text = workspace["drafts"]["laptop"]["employee_text"]
        workspace["response"]["request"]["employee_facts"]["tenure"] = "2년 10개월"

        refreshed = refresh_workspace(workspace, self.corpus)

        self.assertEqual(refreshed["drafts"]["laptop"]["employee_text"], old_text)
        self.assertEqual(refreshed["drafts"]["laptop"]["support_status"], "evidence_changed_review_required")
        self.assertNotEqual(
            refreshed["drafts"]["laptop"]["source_proposal_revision"],
            refreshed["response"]["branches"]["laptop"]["draft_proposal"]["revision"],
        )

        applied = apply_current_proposal(refreshed, "laptop")
        self.assertIn("2년 10개월", applied["drafts"]["laptop"]["employee_text"])
        self.assertNotIn("4년째", applied["drafts"]["laptop"]["employee_text"])
        self.assertEqual(applied["drafts"]["laptop"]["support_status"], "matches_current_rule_proposal")

    def test_explicit_laptop_goal_changes_only_laptop_request_wording(self) -> None:
        replacement = process_request(
            self.corpus, request("2년 10개월", "replacement_process")
        )
        before_replacement = process_request(
            self.corpus, request("2년 10개월", "before_replacement")
        )

        self.assertEqual(
            replacement["branches"]["laptop"]["answer"],
            before_replacement["branches"]["laptop"]["answer"],
        )
        self.assertEqual(
            replacement["branches"]["monitor"]["draft_proposal"],
            before_replacement["branches"]["monitor"]["draft_proposal"],
        )
        replacement_draft = replacement["branches"]["laptop"]["draft_proposal"]
        before_draft = before_replacement["branches"]["laptop"]["draft_proposal"]
        self.assertIn("3년 refresh 조건", replacement_draft["text"])
        self.assertIn("교체 여부를 정하기 전에", before_draft["text"])
        self.assertIn("어떤 정보를 더 드려야 하는지", before_draft["text"])
        self.assertNotEqual(replacement_draft["revision"], before_draft["revision"])

    def test_missing_goal_defaults_to_prior_replacement_process(self) -> None:
        explicit = process_request(self.corpus, request())
        legacy_request = request()
        del legacy_request["laptop_inquiry_goal"]
        legacy = process_request(self.corpus, legacy_request)

        self.assertEqual(
            legacy["request"]["laptop_inquiry_goal"], "replacement_process"
        )
        self.assertEqual(
            legacy["branches"]["laptop"]["draft_proposal"],
            explicit["branches"]["laptop"]["draft_proposal"],
        )

    def test_before_replacement_preserves_purchase_status_wording(self) -> None:
        value = request("2년 10개월", "before_replacement")
        value["employee_facts"]["purchase_status"] = "purchased"
        response = process_request(self.corpus, value)

        draft = response["branches"]["laptop"]["draft_proposal"]["text"]
        self.assertIn("새 기기를 이미 구매했습니다", draft)
        self.assertNotIn("새 기기를 구매하지 않았습니다", draft)

    def test_symptom_only_and_explicit_unknown_make_distinct_minimal_drafts(self) -> None:
        symptom_only_request = request("", "before_replacement")
        symptom_only_request["employee_facts"] = {
            "symptom": "오늘 화상회의 중"
        }
        unknown_request = request("", "before_replacement")
        unknown_request["employee_facts"] = {
            "symptom": "오늘 화상회의 중",
            "purchase_status": "unknown",
        }

        symptom_only = process_request(self.corpus, symptom_only_request)
        unknown = process_request(self.corpus, unknown_request)
        symptom_draft = symptom_only["branches"]["laptop"]["draft_proposal"]["text"]
        unknown_draft = unknown["branches"]["laptop"]["draft_proposal"]["text"]

        self.assertEqual(
            symptom_draft,
            "회사 노트북이 오늘 화상회의 중 느려졌습니다. 교체 여부를 정하기 전에, "
            "증상을 확인하려면 어떤 정보를 더 드려야 하는지와 다음 문의 절차를 안내 "
            "부탁드립니다.",
        )
        self.assertNotIn("구매", symptom_draft)
        self.assertNotIn("[", symptom_draft)
        self.assertIn("새 기기 구매 여부는 아직 확인하지 못했습니다.", unknown_draft)
        self.assertNotIn("[기간]", unknown_draft)
        self.assertEqual(
            symptom_only["branches"]["laptop"]["answer"],
            unknown["branches"]["laptop"]["answer"],
        )
        self.assertEqual(
            symptom_only["branches"]["laptop"]["retrieval"],
            unknown["branches"]["laptop"]["retrieval"],
        )

    def test_blank_facts_stay_in_request_but_not_in_either_goal_draft(self) -> None:
        raw_facts = {
            "tenure": "  \t ",
            "symptom": " \n ",
            "purchase_status": " \t",
        }
        for goal in ("before_replacement", "replacement_process"):
            with self.subTest(goal=goal):
                value = request("", goal)
                value["employee_facts"] = dict(raw_facts)
                response = process_request(self.corpus, value)
                draft = response["branches"]["laptop"]["draft_proposal"]["text"]

                self.assertEqual(response["request"]["employee_facts"], raw_facts)
                self.assertTrue(draft.startswith("회사 노트북이 느려져 문의드립니다."))
                self.assertNotIn("[", draft)
                self.assertNotIn("구매 상태", draft)
                if goal == "before_replacement":
                    self.assertIn("교체 여부를 정하기 전에", draft)
                else:
                    self.assertIn("3년 refresh 조건", draft)

    def test_known_unknown_and_missing_purchase_make_new_proposals(self) -> None:
        proposals = {}
        for label, purchase_status in (
            ("known", "not_purchased"),
            ("unknown", "unknown"),
            ("missing", None),
        ):
            value = request("", "before_replacement")
            value["employee_facts"] = {"symptom": "오늘 화상회의 중"}
            if purchase_status is not None:
                value["employee_facts"]["purchase_status"] = purchase_status
            proposals[label] = process_request(self.corpus, value)["branches"]["laptop"]["draft_proposal"]

        self.assertIn("구매하지 않았습니다", proposals["known"]["text"])
        self.assertIn("아직 확인하지 못했습니다", proposals["unknown"]["text"])
        self.assertNotIn("구매", proposals["missing"]["text"])
        self.assertEqual(len({proposal["revision"] for proposal in proposals.values()}), 3)

    def test_monitor_general_policy_and_optional_employee_detail_stay_distinct(self) -> None:
        expected_answer_parts = (
            "승인 WFH 장비 목록에 모니터와 모니터 스탠드",
            "추가 모니터는 Stipend/Allowance",
            "연간 500 USD(또는 현지 통화 상당액)",
            "직전 한 해 전체 재직 조건",
            "모든 모니터 구입 경로에 동일하게 적용되는지",
            "개인의 적용 경로·잔액·실제 처리",
        )
        generic_drafts = []
        for label, raw_detail in (
            ("absent", None),
            ("empty", ""),
            ("whitespace", "  \t "),
        ):
            with self.subTest(label=label):
                value = request("2년 10개월")
                value["employee_facts"]["purchase_status"] = "purchased"
                if raw_detail is not None:
                    value["employee_facts"]["monitor_employee_detail"] = raw_detail
                response = process_request(self.corpus, value)
                branch = response["branches"]["monitor"]
                draft = branch["draft_proposal"]["text"]

                self.assertEqual(response["request"]["employee_facts"], value["employee_facts"])
                self.assertTrue(all(part in branch["answer"]["text"] for part in expected_answer_parts))
                self.assertTrue(draft.startswith("재택근무용 모니터 구입을 검토 중입니다."))
                self.assertNotIn("[신규/기존 직원", draft)
                self.assertNotIn("저는 이고", draft)
                self.assertNotIn("2년 10개월", draft)
                self.assertNotIn("이미 구매", draft)
                generic_drafts.append(draft)

        self.assertEqual(len(set(generic_drafts)), 1)

        value = request("2년 10개월")
        value["employee_facts"].update(
            {
                "purchase_status": "purchased",
                "monitor_employee_detail": "  기존 직원, 입사일 2025-06-01  ",
            }
        )
        explicit = process_request(self.corpus, value)
        explicit_draft = explicit["branches"]["monitor"]["draft_proposal"]["text"]

        self.assertEqual(
            explicit["request"]["employee_facts"]["monitor_employee_detail"],
            "  기존 직원, 입사일 2025-06-01  ",
        )
        self.assertTrue(explicit_draft.startswith("직원 정보: 기존 직원, 입사일 2025-06-01\n"))
        self.assertNotIn("직전 한 해 전체 재직 조건을 충족", explicit_draft)
        self.assertNotIn("2년 10개월", explicit_draft)
        self.assertNotIn("이미 구매", explicit_draft)

    def test_missing_monitor_evidence_withholds_only_monitor_branch(self) -> None:
        response = process_request(
            self.corpus,
            request(),
            excluded_evidence_ids=["approved-wfh-computer"],
        )

        self.assertEqual(
            response["branches"]["monitor"]["status"],
            "withheld_missing_required_evidence",
        )
        self.assertIsNone(response["branches"]["monitor"]["answer"]["text"])
        self.assertIsNone(response["branches"]["monitor"]["draft_proposal"]["text"])
        self.assertEqual(response["branches"]["laptop"]["status"], "ready_rule_composed")

    def test_missing_laptop_evidence_keeps_other_branch_and_edit(self) -> None:
        workspace = create_workspace(self.corpus, request())
        workspace = edit_draft(workspace, "laptop", "직원이 직접 고친 IT 문의")

        missing = refresh_workspace(
            workspace,
            self.corpus,
            excluded_evidence_ids=["laptops-insurance-repairs"],
        )

        self.assertEqual(missing["response"]["branches"]["monitor"]["status"], "ready_rule_composed")
        self.assertEqual(
            missing["response"]["branches"]["laptop"]["status"],
            "withheld_missing_required_evidence",
        )
        self.assertEqual(missing["drafts"]["laptop"]["employee_text"], "직원이 직접 고친 IT 문의")
        self.assertEqual(
            missing["drafts"]["laptop"]["support_status"],
            "previous_text_not_supported_by_current_evidence",
        )

        restored = refresh_workspace(missing, self.corpus)
        self.assertEqual(restored["drafts"]["laptop"]["employee_text"], "직원이 직접 고친 IT 문의")
        self.assertEqual(
            restored["drafts"]["laptop"]["support_status"],
            "current_evidence_available_semantics_not_checked",
        )

    def test_request_evidence_ids_are_members_of_current_material(self) -> None:
        workspace = create_workspace(self.corpus, request())
        result = workspace["response"]
        material_ids = set(result["material"]["evidence_ids"])
        for branch in result["branches"].values():
            for field in ("answer", "draft_proposal"):
                self.assertLessEqual(set(branch[field]["evidence_ids"]), material_ids)
        self.assertEqual(result["validation"]["semantic_alignment"], "not_checked")

    def test_scope_omission_defaults_to_both_and_each_scope_limits_work(self) -> None:
        explicit_both = process_request(self.corpus, request())
        legacy_request = request()
        del legacy_request["inquiry_scope"]
        omitted = process_request(self.corpus, legacy_request)

        self.assertEqual(omitted["request"]["inquiry_scope"], "both")
        self.assertEqual(omitted["material"], explicit_both["material"])
        self.assertEqual(omitted["branches"], explicit_both["branches"])

        expected = {
            "both": {
                "material": [
                    "equipment",
                    "approved-wfh-computer",
                    "laptops-insurance-repairs",
                ],
                "selected": {"monitor", "laptop"},
            },
            "monitor": {
                "material": ["equipment", "approved-wfh-computer"],
                "selected": {"monitor"},
            },
            "laptop": {
                "material": ["equipment", "laptops-insurance-repairs"],
                "selected": {"laptop"},
            },
        }
        for scope, expectation in expected.items():
            with self.subTest(scope=scope):
                response = process_request(self.corpus, request(inquiry_scope=scope))
                self.assertEqual(response["material"]["evidence_ids"], expectation["material"])
                for branch_name, branch in response["branches"].items():
                    if branch_name in expectation["selected"]:
                        self.assertEqual(branch["status"], "ready_rule_composed")
                        self.assertEqual(branch["retrieval"]["search_count"], 1)
                    else:
                        self.assertEqual(branch["status"], "not_selected")
                        self.assertEqual(branch["retrieval"]["search_count"], 0)
                        self.assertEqual(branch["retrieval"]["reason"], "not_selected")
                        self.assertEqual(branch["missing_required_roles"], [])
                        self.assertIsNone(branch["answer"]["text"])
                        self.assertIsNone(branch["draft_proposal"]["text"])

    def test_scope_changes_revision_and_preserves_both_employee_drafts(self) -> None:
        workspace = create_workspace(self.corpus, request())
        workspace = edit_draft(workspace, "monitor", "직원이 고친 모니터 글")
        workspace = edit_draft(workspace, "laptop", "직원이 고친 노트북 글")
        both_laptop_revision = workspace["response"]["branches"]["laptop"][
            "draft_proposal"
        ]["revision"]

        laptop_request = request(inquiry_scope="laptop")
        laptop_only = refresh_workspace(workspace, self.corpus, request=laptop_request)
        self.assertEqual(
            laptop_only["drafts"]["monitor"]["support_status"],
            "not_selected_preserved_for_reselection",
        )
        self.assertEqual(laptop_only["drafts"]["monitor"]["employee_text"], "직원이 고친 모니터 글")
        self.assertEqual(laptop_only["drafts"]["laptop"]["employee_text"], "직원이 고친 노트북 글")
        self.assertNotEqual(
            both_laptop_revision,
            laptop_only["response"]["branches"]["laptop"]["draft_proposal"]["revision"],
        )
        with self.assertRaises(ValueError):
            apply_current_proposal(laptop_only, "monitor")

        both_again = refresh_workspace(laptop_only, self.corpus, request=request())
        self.assertEqual(both_again["drafts"]["monitor"]["employee_text"], "직원이 고친 모니터 글")
        self.assertEqual(both_again["drafts"]["laptop"]["employee_text"], "직원이 고친 노트북 글")

    def test_newly_selected_untouched_branch_gets_its_first_proposal(self) -> None:
        workspace = create_workspace(self.corpus, request(inquiry_scope="laptop"))
        self.assertEqual(workspace["drafts"]["monitor"]["employee_text"], "")
        self.assertIsNone(workspace["drafts"]["monitor"]["source_proposal_revision"])
        self.assertEqual(
            workspace["drafts"]["monitor"]["support_status"],
            "not_selected_preserved_for_reselection",
        )

        selected = refresh_workspace(workspace, self.corpus, request=request())
        self.assertTrue(selected["drafts"]["monitor"]["employee_text"])
        self.assertEqual(
            selected["drafts"]["monitor"]["support_status"],
            "matches_current_rule_proposal",
        )

    def test_unselected_laptop_is_not_missing_but_selected_laptop_can_be(self) -> None:
        monitor_only = process_request(
            self.corpus,
            request(inquiry_scope="monitor"),
            excluded_evidence_ids=["laptops-insurance-repairs"],
        )
        self.assertEqual(monitor_only["branches"]["monitor"]["status"], "ready_rule_composed")
        self.assertEqual(monitor_only["branches"]["laptop"]["status"], "not_selected")

        laptop_only = process_request(
            self.corpus,
            request(inquiry_scope="laptop"),
            excluded_evidence_ids=["laptops-insurance-repairs"],
        )
        self.assertEqual(laptop_only["branches"]["monitor"]["status"], "not_selected")
        self.assertEqual(
            laptop_only["branches"]["laptop"]["status"],
            "withheld_missing_required_evidence",
        )

    def test_invalid_scope_is_not_interpreted(self) -> None:
        for invalid in (None, [], {}, True, 1, "automatic"):
            with self.subTest(invalid=invalid):
                value = request()
                value["inquiry_scope"] = invalid
                response = process_request(self.corpus, value)
                self.assertEqual(response["status"], "unsupported_inquiry_scope")


if __name__ == "__main__":
    unittest.main()
