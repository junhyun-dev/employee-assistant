#!/usr/bin/env python3
"""Model-free retrieval and draft-state baseline for one supported inquiry type.

This module does not infer an inquiry type, translate arbitrary Korean, call a
model, or decide whether a policy applies to an employee. The caller supplies a
supported inquiry type. Runtime configuration below declares its manual English
search terms and required evidence roles. Returned Korean text is rule-composed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "gitlab-expenses-excerpts.json"
DEFAULT_LAPTOP_INQUIRY_GOAL = "replacement_process"
LAPTOP_INQUIRY_GOALS = frozenset(
    {"before_replacement", "replacement_process"}
)
DEFAULT_INQUIRY_SCOPE = "both"
INQUIRY_SCOPES = frozenset({"both", "monitor", "laptop"})


class UnknownEvidenceId(ValueError):
    """A result cited evidence that was not material for this request."""


SECTION_ROLES: dict[str, tuple[str, ...]] = {
    "equipment": (
        "monitor_allowance_condition",
        "laptop_excluded_from_wfh_allowance",
    ),
    "approved-wfh-computer": (
        "monitor_approved_item",
        "small_laptop_parts_list",
    ),
    "laptops-insurance-repairs": (
        "laptop_refresh_condition",
        "laptop_it_contact_before_damage_replacement",
    ),
    "repairs-company-issued": ("small_laptop_repair_process",),
}


# Runtime support configuration, not evaluation answers. The service must know
# which inquiry type the caller selected; this module does not classify free text.
SUPPORTED_INQUIRY_TYPES: dict[str, dict[str, Any]] = {
    "monitor_and_laptop_replacement": {
        "label": "재택용 모니터 구입과 회사 노트북 문의",
        "selection": "caller_supplied_not_inferred",
        "manual_correspondence": {
            "모니터": ("monitor", "wfh", "home office", "additional", "purchase"),
            "노트북 문의": (
                "laptop",
                "replacement",
                "refresh",
                "it",
                "issue",
                "purchase",
            ),
        },
        "branches": {
            "monitor": {
                "query_terms": ("monitor", "wfh", "home office", "additional", "purchase"),
                "required_roles": (
                    "monitor_allowance_condition",
                    "monitor_approved_item",
                ),
                "result_budget": 2,
            },
            "laptop": {
                "query_terms": (
                    "laptop",
                    "replacement",
                    "refresh",
                    "it",
                    "issue",
                    "purchase",
                ),
                "required_roles": (
                    "laptop_refresh_condition",
                    "laptop_it_contact_before_damage_replacement",
                ),
                "result_budget": 2,
            },
        },
    }
}


SPECIFIC_TERMS = {
    "additional",
    "battery",
    "home office",
    "laptop",
    "monitor",
    "refresh",
    "replace",
    "replacement",
    "wfh",
}
PROCESS_TERMS = {"issue", "it", "purchase"}


def load_corpus(path: Path = DATA_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _contains_term(text: str, term: str) -> bool:
    pattern = rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])"
    return re.search(pattern, text.lower()) is not None


def _term_weight(term: str) -> int:
    if term in SPECIFIC_TERMS:
        return 3
    if term in PROCESS_TERMS:
        return 1
    raise ValueError(f"unclassified runtime query term: {term}")


def _score_section(section: dict[str, Any], terms: Iterable[str]) -> dict[str, Any]:
    leaf = section["heading_path"][-1]
    ancestors = " / ".join(section["heading_path"][:-1])
    body = section["original_text"]
    score = 0
    components = []

    for term in dict.fromkeys(terms):
        weight = _term_weight(term)
        leaf_match = _contains_term(leaf, term)
        ancestor_match = _contains_term(ancestors, term)
        body_match = _contains_term(body, term)
        contribution = weight * (
            (3 if leaf_match else 0)
            + (1 if ancestor_match else 0)
            + (1 if body_match else 0)
        )
        if contribution:
            components.append(
                {
                    "term": term,
                    "leaf": leaf_match,
                    "ancestor": ancestor_match,
                    "original_text": body_match,
                    "contribution": contribution,
                }
            )
            score += contribution

    return {
        "evidence_id": section["id"],
        "score": score,
        "score_components": components,
    }


def _retrieve(
    sections: list[dict[str, Any]], terms: Iterable[str], budget: int
) -> dict[str, Any]:
    scored = [_score_section(section, terms) for section in sections]
    positive = [item for item in scored if item["score"] > 0]
    ranked = sorted(positive, key=lambda item: (-item["score"], item["evidence_id"]))
    return {
        "search_count": 1,
        "result_budget": budget,
        "positive_candidate_count": len(positive),
        "selected": ranked[:budget],
    }


def _role_state(
    role: str,
    selected_ids: list[str],
    available_ids: set[str],
) -> dict[str, Any]:
    providers = sorted(
        section_id for section_id, roles in SECTION_ROLES.items() if role in roles
    )
    found = [section_id for section_id in selected_ids if section_id in providers]
    available = [section_id for section_id in providers if section_id in available_ids]
    if found:
        status = "found"
    elif available:
        status = "not_retrieved"
    else:
        status = "not_in_prepared_source"
    return {
        "role": role,
        "status": status,
        "supporting_evidence_ids": found,
        "known_provider_ids": providers,
    }


def _entered_fact(employee_facts: dict[str, str], key: str) -> str | None:
    value = employee_facts.get(key)
    if not isinstance(value, str):
        return None
    entered = value.strip()
    return entered or None


def _purchase_sentence(value: str | None) -> str | None:
    if value == "not_purchased":
        return "새 기기를 구매하지 않았습니다."
    if value == "purchased":
        return "새 기기를 이미 구매했습니다."
    if value == "unknown":
        return "새 기기 구매 여부는 아직 확인하지 못했습니다."
    return None


def _monitor_output(employee_facts: dict[str, str]) -> tuple[str, str]:
    answer = (
        "공개 표본의 승인 WFH 장비 목록에 모니터와 모니터 스탠드가 있고, "
        "추가 모니터는 Stipend/Allowance를 통한 검토·경비 처리 대상으로 "
        "안내됩니다. 같은 표본의 기존 직원 연간 500 USD(또는 현지 통화 "
        "상당액) home office refresh에는 직전 한 해 전체 재직 조건이 있습니다. "
        "이 조건이 모든 모니터 구입 경로에 동일하게 적용되는지와 개인의 적용 "
        "경로·잔액·실제 처리는 이 자료로 확인하지 못했습니다."
    )
    employee_detail = _entered_fact(employee_facts, "monitor_employee_detail")
    lines = []
    if employee_detail:
        lines.append(f"직원 정보: {employee_detail}")
    lines.extend(
        (
            "재택근무용 모니터 구입을 검토 중입니다.",
            "공개 문서에서 모니터가 승인 WFH 장비 목록에 있고 추가 모니터가 "
            "Stipend/Allowance를 통한 검토·경비 처리 대상으로 안내되는 것을 "
            "확인했습니다.",
            "제게 적용되는 수당 경로와 이용 가능한 금액, 필요한 제출 정보를 확인 부탁드립니다.",
        )
    )
    draft = "\n".join(lines)
    return answer, draft


def _laptop_output(
    employee_facts: dict[str, str], laptop_inquiry_goal: str
) -> tuple[str, str]:
    answer = (
        "공개 표본에는 3년 재직 뒤 노트북 refresh가 가능하고, 손상 교체는 "
        "구매 전에 IT issue로 문의하라고 적혀 있습니다. 느려진 노트북에 "
        "실제로 적용될 절차는 이 자료만으로 확인하지 못했습니다."
    )
    tenure = _entered_fact(employee_facts, "tenure")
    symptom = _entered_fact(employee_facts, "symptom")
    purchase = _purchase_sentence(_entered_fact(employee_facts, "purchase_status"))
    situation = "회사 노트북이"
    if tenure:
        situation = f"{tenure}째 재직 중이며 {situation}"
    if symptom:
        situation += f" {symptom} 느려졌습니다."
    else:
        situation += " 느려져 문의드립니다."
    if laptop_inquiry_goal == "before_replacement":
        request = (
            "교체 여부를 정하기 전에, 증상을 확인하려면 어떤 정보를 더 드려야 "
            "하는지와 다음 문의 절차를 안내 부탁드립니다."
        )
    elif laptop_inquiry_goal == "replacement_process":
        request = (
            "공개 정책의 3년 refresh 조건을 참고해 제 상황에 적용될 절차와 진행 "
            "방법을 확인 부탁드립니다."
        )
    else:  # process_request rejects unsupported values before output is built.
        raise ValueError(f"unsupported laptop inquiry goal: {laptop_inquiry_goal}")
    draft = " ".join(part for part in (situation, purchase, request) if part)
    return answer, draft


def _proposal_revision(
    branch_name: str,
    proposal_text: str,
    evidence_ids: list[str],
    employee_facts: dict[str, str],
    available_sections: list[dict[str, Any]],
    laptop_inquiry_goal: str,
    inquiry_scope: str,
) -> str:
    section_by_id = {section["id"]: section for section in available_sections}
    payload = {
        "branch": branch_name,
        "proposal_text": proposal_text,
        "employee_facts": employee_facts,
        "inquiry_scope": inquiry_scope,
        "evidence": [section_by_id[evidence_id] for evidence_id in evidence_ids],
    }
    if branch_name == "laptop":
        payload["laptop_inquiry_goal"] = laptop_inquiry_goal
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_branch(
    branch_name: str,
    branch_config: dict[str, Any],
    available_sections: list[dict[str, Any]],
    employee_facts: dict[str, str],
    laptop_inquiry_goal: str,
    inquiry_scope: str,
) -> dict[str, Any]:
    retrieval = _retrieve(
        available_sections,
        branch_config["query_terms"],
        branch_config["result_budget"],
    )
    selected_ids = [item["evidence_id"] for item in retrieval["selected"]]
    available_ids = {section["id"] for section in available_sections}
    role_states = [
        _role_state(role, selected_ids, available_ids)
        for role in branch_config["required_roles"]
    ]
    missing = [item for item in role_states if item["status"] != "found"]
    supporting_ids = list(
        dict.fromkeys(
            evidence_id
            for item in role_states
            for evidence_id in item["supporting_evidence_ids"]
        )
    )

    if missing:
        missing_roles = [item["role"] for item in missing]
        return {
            "status": "withheld_missing_required_evidence",
            "manual_query_terms": list(branch_config["query_terms"]),
            "retrieval": retrieval,
            "required_role_states": role_states,
            "missing_required_roles": missing_roles,
            "answer": {
                "status": "withheld",
                "text": None,
                "evidence_ids": [],
                "reason": "필수 근거 역할이 준비 자료 또는 검색 결과에 없습니다.",
            },
            "draft_proposal": {
                "status": "withheld",
                "text": None,
                "evidence_ids": [],
                "revision": None,
                "reason": "새 정책 기반 문의 글을 제안할 근거가 부족합니다.",
            },
        }

    if branch_name == "monitor":
        answer_text, draft_text = _monitor_output(employee_facts)
    elif branch_name == "laptop":
        answer_text, draft_text = _laptop_output(
            employee_facts, laptop_inquiry_goal
        )
    else:
        raise ValueError(f"no rule-composed output for branch: {branch_name}")

    return {
        "status": "ready_rule_composed",
        "manual_query_terms": list(branch_config["query_terms"]),
        "retrieval": retrieval,
        "required_role_states": role_states,
        "missing_required_roles": [],
        "answer": {
            "status": "available_rule_composed",
            "text": answer_text,
            "evidence_ids": supporting_ids,
        },
        "draft_proposal": {
            "status": "available_rule_composed",
            "text": draft_text,
            "evidence_ids": supporting_ids,
            "revision": _proposal_revision(
                branch_name,
                draft_text,
                supporting_ids,
                employee_facts,
                available_sections,
                laptop_inquiry_goal,
                inquiry_scope,
            ),
        },
    }


def _not_selected_branch() -> dict[str, Any]:
    return {
        "status": "not_selected",
        "manual_query_terms": [],
        "retrieval": {
            "search_count": 0,
            "result_budget": 0,
            "positive_candidate_count": 0,
            "selected": [],
            "reason": "not_selected",
        },
        "required_role_states": [],
        "missing_required_roles": [],
        "answer": {
            "status": "not_selected",
            "text": None,
            "evidence_ids": [],
            "reason": "이번 문의 범위에서 선택하지 않은 갈래입니다.",
        },
        "draft_proposal": {
            "status": "not_selected",
            "text": None,
            "evidence_ids": [],
            "revision": None,
            "reason": "이번 문의 범위에서 선택하지 않아 새 글을 제안하지 않습니다.",
        },
    }


def validate_structure(response: dict[str, Any]) -> dict[str, str]:
    material_ids = set(response["material"]["evidence_ids"])
    for branch in response["branches"].values():
        for field in ("answer", "draft_proposal"):
            for evidence_id in branch[field]["evidence_ids"]:
                if evidence_id not in material_ids:
                    raise UnknownEvidenceId(evidence_id)
    return {
        "evidence_id_membership": "valid_for_this_request",
        "semantic_alignment": "not_checked",
    }


def process_request(
    corpus: dict[str, Any],
    request: dict[str, Any],
    *,
    excluded_evidence_ids: Iterable[str] = (),
) -> dict[str, Any]:
    inquiry_type = request.get("inquiry_type")
    if inquiry_type not in SUPPORTED_INQUIRY_TYPES:
        return {
            "status": "unsupported_inquiry_type",
            "inquiry_type": inquiry_type,
            "supported_inquiry_types": sorted(SUPPORTED_INQUIRY_TYPES),
            "note": "임의 질문의 유형과 필수 근거는 이 기준선이 추론하지 않습니다.",
        }

    laptop_inquiry_goal = request.get(
        "laptop_inquiry_goal", DEFAULT_LAPTOP_INQUIRY_GOAL
    )
    if (
        not isinstance(laptop_inquiry_goal, str)
        or laptop_inquiry_goal not in LAPTOP_INQUIRY_GOALS
    ):
        return {
            "status": "unsupported_laptop_inquiry_goal",
            "laptop_inquiry_goal": laptop_inquiry_goal,
            "supported_laptop_inquiry_goals": sorted(LAPTOP_INQUIRY_GOALS),
            "note": "노트북 문의 목적은 직원이 지원 값에서 명시적으로 선택해야 합니다.",
        }

    inquiry_scope = request.get("inquiry_scope", DEFAULT_INQUIRY_SCOPE)
    if not isinstance(inquiry_scope, str) or inquiry_scope not in INQUIRY_SCOPES:
        return {
            "status": "unsupported_inquiry_scope",
            "inquiry_scope": inquiry_scope,
            "supported_inquiry_scopes": sorted(INQUIRY_SCOPES),
            "note": "문의 범위는 지원 값에서 직원이 명시적으로 선택해야 합니다.",
        }

    support = SUPPORTED_INQUIRY_TYPES[inquiry_type]
    excluded = set(excluded_evidence_ids)
    available_sections = [
        section for section in corpus["sections"] if section["id"] not in excluded
    ]
    employee_facts = request.get("employee_facts", {})
    selected_branches = (
        {"monitor", "laptop"} if inquiry_scope == "both" else {inquiry_scope}
    )
    branches = {}
    for branch_name, branch_config in support["branches"].items():
        if branch_name not in selected_branches:
            branches[branch_name] = _not_selected_branch()
            continue
        branches[branch_name] = _build_branch(
            branch_name,
            branch_config,
            available_sections,
            employee_facts,
            laptop_inquiry_goal,
            inquiry_scope,
        )

    selected_ids = list(
        dict.fromkeys(
            item["evidence_id"]
            for branch in branches.values()
            for item in branch["retrieval"]["selected"]
        )
    )
    section_by_id = {section["id"]: section for section in available_sections}
    material = {
        "source": corpus["source"],
        "evidence_ids": selected_ids,
        "evidence": [section_by_id[evidence_id] for evidence_id in selected_ids],
    }
    normalized_request = copy.deepcopy(request)
    normalized_request["laptop_inquiry_goal"] = laptop_inquiry_goal
    normalized_request["inquiry_scope"] = inquiry_scope
    response = {
        "status": "processed_supported_inquiry_type",
        "inquiry_type": inquiry_type,
        "support_label": support["label"],
        "type_selection": support["selection"],
        "manual_correspondence": {
            label: list(terms)
            for label, terms in support["manual_correspondence"].items()
        },
        "request": normalized_request,
        "excluded_evidence_ids": sorted(excluded),
        "material": material,
        "branches": branches,
        "limitations": [
            "문의 유형과 필요한 근거 역할은 사람이 미리 정의했습니다.",
            "노트북 문의 목적은 지원 값에서 직원이 명시적으로 고르며 자유문장에서 추론하지 않습니다.",
            "문의 범위는 지원 값에서 직원이 명시적으로 고르며 선택 밖 갈래는 검색하거나 생성하지 않습니다.",
            "한국어 질문을 일반적으로 해석하거나 번역하지 않습니다.",
            "답과 문의 글은 고정 규칙으로 구성하며 모델 생성이 아닙니다.",
            "구조 검사는 근거 ID의 요청별 포함 여부만 확인하고 문장 의미 정합성은 확인하지 않습니다.",
        ],
    }
    response["validation"] = validate_structure(response)
    return response


def create_workspace(
    corpus: dict[str, Any],
    request: dict[str, Any],
    *,
    excluded_evidence_ids: Iterable[str] = (),
) -> dict[str, Any]:
    response = process_request(
        corpus, request, excluded_evidence_ids=excluded_evidence_ids
    )
    if response["status"] != "processed_supported_inquiry_type":
        return {"revision": 1, "response": response, "drafts": {}}

    drafts = {}
    for branch_name, branch in response["branches"].items():
        proposal = branch["draft_proposal"]
        if proposal["status"] == "available_rule_composed":
            drafts[branch_name] = {
                "employee_text": proposal["text"],
                "employee_edited": False,
                "source_evidence_ids": list(proposal["evidence_ids"]),
                "source_proposal_revision": proposal["revision"],
                "support_status": "matches_current_rule_proposal",
                "applied_from_response_revision": 1,
            }
        else:
            drafts[branch_name] = {
                "employee_text": "",
                "employee_edited": False,
                "source_evidence_ids": [],
                "source_proposal_revision": None,
                "support_status": (
                    "not_selected_preserved_for_reselection"
                    if branch["status"] == "not_selected"
                    else "no_policy_based_proposal"
                ),
                "applied_from_response_revision": None,
            }
    return {"revision": 1, "response": response, "drafts": drafts}


def edit_draft(
    workspace: dict[str, Any], branch_name: str, employee_text: str
) -> dict[str, Any]:
    updated = copy.deepcopy(workspace)
    draft = updated["drafts"][branch_name]
    draft["employee_text"] = employee_text
    draft["employee_edited"] = True
    branch = updated["response"]["branches"][branch_name]
    if branch["status"] == "not_selected":
        draft["support_status"] = "not_selected_preserved_for_reselection"
    elif branch["status"] == "ready_rule_composed":
        draft["support_status"] = "current_evidence_available_semantics_not_checked"
    else:
        draft["support_status"] = "previous_text_not_supported_by_current_evidence"
    return updated


def refresh_workspace(
    workspace: dict[str, Any],
    corpus: dict[str, Any],
    *,
    request: dict[str, Any] | None = None,
    excluded_evidence_ids: Iterable[str] = (),
) -> dict[str, Any]:
    updated = copy.deepcopy(workspace)
    updated["revision"] += 1
    updated["response"] = process_request(
        corpus,
        request if request is not None else updated["response"]["request"],
        excluded_evidence_ids=excluded_evidence_ids,
    )

    for branch_name, draft in updated["drafts"].items():
        branch = updated["response"]["branches"][branch_name]
        proposal = branch["draft_proposal"]
        if branch["status"] == "not_selected":
            draft["support_status"] = "not_selected_preserved_for_reselection"
            continue
        if proposal["status"] != "available_rule_composed":
            draft["support_status"] = "previous_text_not_supported_by_current_evidence"
            continue
        if (
            not draft["employee_edited"]
            and not draft["employee_text"]
            and draft["source_proposal_revision"] is None
        ):
            draft.update(
                {
                    "employee_text": proposal["text"],
                    "employee_edited": False,
                    "source_evidence_ids": list(proposal["evidence_ids"]),
                    "source_proposal_revision": proposal["revision"],
                    "support_status": "matches_current_rule_proposal",
                    "applied_from_response_revision": updated["revision"],
                }
            )
            continue
        current_ids = set(proposal["evidence_ids"])
        source_ids = set(draft["source_evidence_ids"])
        if (
            current_ids != source_ids
            or proposal["revision"] != draft["source_proposal_revision"]
            or (not draft["employee_edited"] and draft["employee_text"] != proposal["text"])
        ):
            draft["support_status"] = "evidence_changed_review_required"
        elif draft["employee_edited"]:
            draft["support_status"] = "current_evidence_available_semantics_not_checked"
        else:
            draft["support_status"] = "matches_current_rule_proposal"
    return updated


def apply_current_proposal(
    workspace: dict[str, Any], branch_name: str
) -> dict[str, Any]:
    updated = copy.deepcopy(workspace)
    proposal = updated["response"]["branches"][branch_name]["draft_proposal"]
    if proposal["status"] != "available_rule_composed":
        raise ValueError(f"no current proposal to apply for branch: {branch_name}")
    updated["drafts"][branch_name] = {
        "employee_text": proposal["text"],
        "employee_edited": False,
        "source_evidence_ids": list(proposal["evidence_ids"]),
        "source_proposal_revision": proposal["revision"],
        "support_status": "matches_current_rule_proposal",
        "applied_from_response_revision": updated["revision"],
    }
    return updated
