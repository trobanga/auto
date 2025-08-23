"""Workflow modules for different automation stages."""

from auto.workflows.fetch import (
    FetchWorkflowError,
    fetch_issue_workflow,
    fetch_issue_workflow_sync,
    get_issue_from_state,
    validate_issue_access,
)
from auto.workflows.implement import (
    ImplementationError,
    apply_ai_changes,
    implement_issue_workflow,
    validate_implementation_prerequisites,
)
from auto.workflows.pr_create import (
    PRCreationError,
    create_pull_request_workflow,
    generate_pr_description,
    generate_pr_metadata,
)
from auto.workflows.process import (
    ProcessWorkflowError,
    cleanup_process_workflow,
    get_process_status,
    process_issue_workflow,
    validate_process_prerequisites,
)
from auto.workflows.review import (
    ReviewCycleState,
    ReviewCycleStatus,
    ReviewWorkflowError,
    check_cycle_completion,
    execute_review_cycle,
    initiate_review_cycle,
    process_review_comments,
    trigger_ai_review,
    trigger_ai_update,
    wait_for_human_review,
)
from auto.workflows.review_update import (
    ReviewUpdateWorkflow,
    execute_review_update,
)

__all__ = [
    # Fetch workflow
    "fetch_issue_workflow",
    "fetch_issue_workflow_sync",
    "validate_issue_access",
    "get_issue_from_state",
    "FetchWorkflowError",
    # Process workflow
    "process_issue_workflow",
    "cleanup_process_workflow",
    "get_process_status",
    "validate_process_prerequisites",
    "ProcessWorkflowError",
    # Implementation workflow
    "implement_issue_workflow",
    "apply_ai_changes",
    "validate_implementation_prerequisites",
    "ImplementationError",
    # PR creation workflow
    "create_pull_request_workflow",
    "generate_pr_metadata",
    "generate_pr_description",
    "PRCreationError",
    # Review workflow
    "execute_review_cycle",
    "trigger_ai_review",
    "wait_for_human_review",
    "process_review_comments",
    "check_cycle_completion",
    "trigger_ai_update",
    "initiate_review_cycle",
    "ReviewCycleStatus",
    "ReviewCycleState",
    "ReviewWorkflowError",
    # Review update workflow
    "execute_review_update",
    "ReviewUpdateWorkflow",
]
