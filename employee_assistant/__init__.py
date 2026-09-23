"""Local-first employee assistant baseline."""

from .flow import (
    SUPPORTED_INQUIRY_TYPES,
    UnknownEvidenceId,
    apply_current_proposal,
    create_workspace,
    edit_draft,
    load_corpus,
    process_request,
    refresh_workspace,
)
from .model_contract import (
    INPUT_SCHEMA_VERSION,
    PROPOSAL_SCHEMA_VERSION,
    ModelContractError,
    assemble_model_input,
    validate_model_proposal,
)

__all__ = [
    "SUPPORTED_INQUIRY_TYPES",
    "UnknownEvidenceId",
    "apply_current_proposal",
    "create_workspace",
    "edit_draft",
    "load_corpus",
    "process_request",
    "refresh_workspace",
    "INPUT_SCHEMA_VERSION",
    "PROPOSAL_SCHEMA_VERSION",
    "ModelContractError",
    "assemble_model_input",
    "validate_model_proposal",
]
