"""Workflow modules for different automation stages."""

from auto.workflows.fetch import (
    fetch_issue_workflow,
    fetch_issue_workflow_sync,
    validate_issue_access,
    get_issue_from_state,
    FetchWorkflowError,
)

from auto.workflows.process import (
    process_issue_workflow,
    cleanup_process_workflow,
    get_process_status,
    validate_process_prerequisites,
    ProcessWorkflowError,
)

from auto.workflows.implement import (
    implement_issue_workflow,
    apply_ai_changes,
    validate_implementation_prerequisites,
    ImplementationError,
)

from auto.workflows.pr_create import (
    create_pull_request_workflow,
    generate_pr_metadata,
    generate_pr_description,
    PRCreationError,
)

from auto.workflows.review import (
    execute_review_cycle,
    trigger_ai_review,
    wait_for_human_review,
    process_review_comments,
    check_cycle_completion,
    trigger_ai_update,
    initiate_review_cycle,
    ReviewCycleStatus,
    ReviewCycleState,
    ReviewWorkflowError,
)

from auto.workflows.review_update import (
    execute_review_update,
    ReviewUpdateWorkflow,
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