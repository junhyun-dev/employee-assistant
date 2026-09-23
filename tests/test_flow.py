from __future__ import annotations

import unittest

from employee_assistant.flow import (
    apply_current_proposal,
    create_workspace,
    edit_draft,
    load_corpus,
    refresh_workspace,
)


def request(tenure: str = "4년") -> dict:
    return {
        "inquiry_type": "monitor_and_laptop_replacement",
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


if __name__ == "__main__":
    unittest.main()
