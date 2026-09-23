from __future__ import annotations

import copy
import unittest

from employee_assistant.flow import load_corpus, process_request
from employee_assistant.model_contract import (
    INPUT_SCHEMA_VERSION,
    PROPOSAL_SCHEMA_VERSION,
    ModelContractError,
    assemble_model_input,
    validate_model_proposal,
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


def synthetic_candidate(model_input: dict, response: dict) -> dict:
    branches = {}
    for name, branch in response["branches"].items():
        if branch["status"] == "ready_rule_composed":
            branches[name] = {
                "status": "ready",
                "reason": None,
                "answer": {
                    "text": branch["answer"]["text"],
                    "evidence_ids": list(branch["answer"]["evidence_ids"]),
                },
                "draft_proposal": {
                    "text": branch["draft_proposal"]["text"],
                    "evidence_ids": list(branch["draft_proposal"]["evidence_ids"]),
                },
            }
        else:
            branches[name] = {
                "status": "withheld",
                "reason": branch["draft_proposal"]["reason"],
                "answer": {"text": None, "evidence_ids": []},
                "draft_proposal": {"text": None, "evidence_ids": []},
            }
    return {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "input_revision": model_input["input_revision"],
        "branches": branches,
    }


class ModelContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.corpus = load_corpus()
        self.response = process_request(self.corpus, request())
        self.model_input = assemble_model_input(self.response)
        self.candidate = synthetic_candidate(self.model_input, self.response)

    def assert_contract_error(self, code: str, function) -> ModelContractError:
        with self.assertRaises(ModelContractError) as caught:
            function()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_assembles_distinct_untrusted_content_and_validates_synthetic_return(self) -> None:
        self.assertEqual(self.model_input["schema_version"], INPUT_SCHEMA_VERSION)
        self.assertEqual(
            self.model_input["employee_input"]["trust"],
            "untrusted_employee_content",
        )
        self.assertTrue(
            all(
                item["trust"] == "untrusted_reference_content"
                for item in self.model_input["retrieved_material"]["evidence"]
            )
        )
        self.assertIn(
            "같은 신청",
            self.model_input["cross_branch_unverified_items"][0],
        )

        original_candidate = copy.deepcopy(self.candidate)
        validated = validate_model_proposal(self.model_input, self.candidate)

        self.assertEqual(self.candidate, original_candidate)
        self.assertFalse(validated["application_boundary"]["workspace_mutated"])
        self.assertTrue(validated["application_boundary"]["requires_explicit_apply"])
        self.assertEqual(validated["validation"]["semantic_alignment"], "not_checked")
        self.assertEqual(len(validated["proposal_revision"]), 64)

    def test_rejects_known_catalog_id_absent_from_this_request(self) -> None:
        known_but_absent = "repairs-company-issued"
        self.assertIn(known_but_absent, {section["id"] for section in self.corpus["sections"]})
        self.assertNotIn(
            known_but_absent,
            self.model_input["retrieved_material"]["evidence_ids"],
        )
        self.candidate["branches"]["monitor"]["answer"]["evidence_ids"] = [
            known_but_absent
        ]

        self.assert_contract_error(
            "evidence_not_in_request",
            lambda: validate_model_proposal(self.model_input, self.candidate),
        )

    def test_rejects_missing_required_branch(self) -> None:
        del self.candidate["branches"]["laptop"]
        self.assert_contract_error(
            "branch_set_mismatch",
            lambda: validate_model_proposal(self.model_input, self.candidate),
        )

    def test_rejects_ready_branch_that_does_not_cite_each_required_role(self) -> None:
        self.candidate["branches"]["monitor"]["answer"]["evidence_ids"] = [
            "equipment"
        ]
        self.candidate["branches"]["monitor"]["draft_proposal"][
            "evidence_ids"
        ] = ["equipment"]
        self.assert_contract_error(
            "required_role_not_cited",
            lambda: validate_model_proposal(self.model_input, self.candidate),
        )

    def test_rejects_completed_output_for_branch_with_missing_evidence(self) -> None:
        response = process_request(
            self.corpus,
            request(),
            excluded_evidence_ids=["laptops-insurance-repairs"],
        )
        model_input = assemble_model_input(response)
        candidate = synthetic_candidate(model_input, response)
        candidate["branches"]["laptop"] = {
            "status": "ready",
            "reason": None,
            "answer": {"text": "완성 답", "evidence_ids": ["equipment"]},
            "draft_proposal": {
                "text": "완성 문의 글",
                "evidence_ids": ["equipment"],
            },
        }

        self.assert_contract_error(
            "branch_must_withhold",
            lambda: validate_model_proposal(model_input, candidate),
        )

    def test_rejects_wrong_types_and_state_actions(self) -> None:
        wrong_type = copy.deepcopy(self.candidate)
        wrong_type["branches"]["monitor"]["answer"]["evidence_ids"] = "equipment"
        self.assert_contract_error(
            "invalid_type",
            lambda: validate_model_proposal(self.model_input, wrong_type),
        )

        action = copy.deepcopy(self.candidate)
        action["actions"] = [{"send": True}]
        self.assert_contract_error(
            "unexpected_field",
            lambda: validate_model_proposal(self.model_input, action),
        )

    def test_rejects_stale_proposal_revision_after_employee_fact_change(self) -> None:
        changed_response = process_request(self.corpus, request("2년 10개월"))
        changed_input = assemble_model_input(changed_response)
        self.assertNotEqual(
            self.model_input["input_revision"], changed_input["input_revision"]
        )
        self.assert_contract_error(
            "input_revision_mismatch",
            lambda: validate_model_proposal(changed_input, self.candidate),
        )

    def test_rejects_employee_fact_changed_inside_assembled_snapshot(self) -> None:
        self.model_input["employee_input"]["facts"]["tenure"] = "2년 10개월"

        self.assert_contract_error(
            "model_input_revision_mismatch",
            lambda: validate_model_proposal(self.model_input, self.candidate),
        )

    def test_rejects_original_text_changed_inside_assembled_snapshot(self) -> None:
        self.model_input["retrieved_material"]["evidence"][0][
            "original_text"
        ] = "변경된 원문"

        self.assert_contract_error(
            "model_input_revision_mismatch",
            lambda: validate_model_proposal(self.model_input, self.candidate),
        )

    def test_rejects_wrong_model_input_schema(self) -> None:
        self.model_input["schema_version"] = "employee-assistant.model-input.v0"

        self.assert_contract_error(
            "schema_version_mismatch",
            lambda: validate_model_proposal(self.model_input, self.candidate),
        )

    def test_rejects_unsupported_processing_result(self) -> None:
        unsupported = process_request(
            self.corpus,
            {"inquiry_type": "free_text", "user_text": "anything", "employee_facts": {}},
        )
        self.assert_contract_error(
            "unsupported_result", lambda: assemble_model_input(unsupported)
        )


if __name__ == "__main__":
    unittest.main()
