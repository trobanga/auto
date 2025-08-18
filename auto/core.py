"""Main workflow orchestrator for the auto tool."""

from datetime import datetime
from pathlib import Path
from typing import List, Optional

from auto.config import get_config
from auto.models import IssueIdentifier, WorkflowState, WorkflowStatus
from auto.utils.logger import get_logger
from auto.utils.shell import get_git_root

logger = get_logger(__name__)


class AutoCore:
    """Main workflow orchestrator."""
    
    def __init__(self):
        """Initialize auto core."""
        self.config = get_config()
        self.state_dir = self._get_state_dir()
    
    def _get_state_dir(self) -> Path:
        """Get state directory path.
        
        Returns:
            State directory path
        """
        git_root = get_git_root()
        if git_root:
            state_dir = git_root / ".auto" / "state"
        else:
            state_dir = Path.cwd() / ".auto" / "state"
        
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir
    
    def parse_issue_id(self, issue_id: str) -> IssueIdentifier:
        """Parse issue identifier.
        
        Args:
            issue_id: Issue identifier string
            
        Returns:
            Parsed issue identifier
        """
        return IssueIdentifier.parse(issue_id)
    
    def get_workflow_states(self) -> List[WorkflowState]:
        """Get all workflow states.
        
        Returns:
            List of workflow states
        """
        states = []
        
        for state_file in self.state_dir.glob("*.yaml"):
            try:
                import yaml
                
                with open(state_file) as f:
                    state_data = yaml.safe_load(f)
                
                state = WorkflowState(**state_data)
                states.append(state)
                
            except Exception as e:
                logger.warning(f"Failed to load state file {state_file}: {e}")
        
        return states
    
    def get_workflow_state(self, issue_id: str) -> Optional[WorkflowState]:
        """Get workflow state for issue.
        
        Args:
            issue_id: Issue identifier
            
        Returns:
            Workflow state or None if not found
        """
        state_file = self.state_dir / f"{issue_id}.yaml"
        
        if not state_file.exists():
            return None
        
        try:
            import yaml
            
            with open(state_file) as f:
                state_data = yaml.safe_load(f)
            
            return WorkflowState(**state_data)
            
        except Exception as e:
            logger.error(f"Failed to load workflow state for {issue_id}: {e}")
            return None
    
    def save_workflow_state(self, state: WorkflowState) -> None:
        """Save workflow state.
        
        Args:
            state: Workflow state to save
        """
        state_file = self.state_dir / f"{state.issue_id}.yaml"
        
        try:
            import yaml
            
            state_data = state.model_dump(mode="json")  # Use JSON mode to serialize enums as strings
            
            with open(state_file, "w") as f:
                yaml.safe_dump(state_data, f, default_flow_style=False)
            
            logger.debug(f"Saved workflow state for {state.issue_id}")
            
        except Exception as e:
            logger.error(f"Failed to save workflow state for {state.issue_id}: {e}")
    
    def create_workflow_state(self, issue_id: str) -> WorkflowState:
        """Create new workflow state.
        
        Args:
            issue_id: Issue identifier
            
        Returns:
            New workflow state
        """
        state = WorkflowState(
            issue_id=issue_id,
            status=WorkflowStatus.INITIALIZED,
        )
        
        self.save_workflow_state(state)
        return state
    
    def cleanup_completed_states(self) -> int:
        """Clean up completed workflow states.
        
        Returns:
            Number of states cleaned up
        """
        cleaned = 0
        
        for state in self.get_workflow_states():
            if state.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
                state_file = self.state_dir / f"{state.issue_id}.yaml"
                
                try:
                    state_file.unlink()
                    cleaned += 1
                    logger.debug(f"Cleaned up state for {state.issue_id}")
                except Exception as e:
                    logger.warning(f"Failed to clean up state for {state.issue_id}: {e}")
        
        return cleaned
    
    def get_github_repository(self) -> Optional["GitHubRepository"]:
        """Get GitHub repository context.
        
        Returns:
            GitHub repository or None if not available
        """
        try:
            from auto.integrations.github import detect_repository
            return detect_repository()
        except Exception as e:
            logger.debug(f"Failed to get GitHub repository: {e}")
            return None
    
    def validate_github_access(self) -> bool:
        """Validate GitHub access.
        
        Returns:
            True if GitHub is accessible, False otherwise
        """
        try:
            from auto.integrations.github import validate_github_auth
            return validate_github_auth()
        except Exception as e:
            logger.debug(f"Failed to validate GitHub access: {e}")
            return False
    
    def get_active_worktrees(self) -> List["WorktreeInfo"]:
        """Get list of active worktrees for this project.
        
        Returns:
            List of active worktree information
        """
        try:
            from auto.integrations.git import GitWorktreeManager
            config = self.config
            manager = GitWorktreeManager(config)
            return manager.list_worktrees()
        except Exception as e:
            logger.debug(f"Failed to get active worktrees: {e}")
            return []
    
    def cleanup_orphaned_worktrees(self) -> int:
        """Clean up worktrees that don't have corresponding workflow states.
        
        Returns:
            Number of orphaned worktrees cleaned up
        """
        try:
            from auto.integrations.git import GitWorktreeManager
            
            cleaned = 0
            config = self.config
            manager = GitWorktreeManager(config)
            
            # Get all auto worktrees
            worktrees = manager.list_worktrees()
            
            # Get all workflow states
            states = self.get_workflow_states()
            state_issue_ids = {state.issue_id for state in states}
            
            # Find orphaned worktrees
            for worktree in worktrees:
                if worktree.issue_id not in state_issue_ids:
                    logger.info(f"Cleaning up orphaned worktree for {worktree.issue_id}")
                    try:
                        manager.cleanup_worktree(worktree)
                        cleaned += 1
                    except Exception as e:
                        logger.warning(f"Failed to clean up orphaned worktree {worktree.path}: {e}")
            
            return cleaned
            
        except Exception as e:
            logger.warning(f"Failed to cleanup orphaned worktrees: {e}")
            return 0

    def get_review_cycle_state(self, pr_number: int) -> Optional[dict]:
        """Get review cycle state for a PR.
        
        Args:
            pr_number: Pull request number
            
        Returns:
            Review cycle state dict or None if not found
        """
        try:
            # Look for workflow states that match this PR
            states = self.get_workflow_states()
            for state in states:
                if state.pr_number == pr_number:
                    # Extract review cycle information from the state
                    review_state = getattr(state, 'review_cycle_state', None)
                    if review_state:
                        return review_state
            
            # Check for dedicated review cycle state file
            review_state_file = self.state_dir / f"review_cycle_{pr_number}.yaml"
            if review_state_file.exists():
                import yaml
                with open(review_state_file, 'r') as f:
                    return yaml.safe_load(f)
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting review cycle state for PR #{pr_number}: {e}")
            return None
    
    def save_review_cycle_state(self, pr_number: int, review_state: dict) -> None:
        """Save review cycle state for a PR.
        
        Args:
            pr_number: Pull request number
            review_state: Review cycle state to save
        """
        try:
            import yaml
            
            # Update workflow state if it exists
            states = self.get_workflow_states()
            for state in states:
                if state.pr_number == pr_number:
                    # Update the review cycle state in the workflow state
                    state_dict = state.model_dump() if hasattr(state, 'model_dump') else state.dict()
                    state_dict['review_cycle_state'] = review_state
                    
                    # Save the updated state
                    state_file = self.state_dir / f"{state.issue_id}.yaml"
                    with open(state_file, 'w') as f:
                        yaml.dump(state_dict, f, default_flow_style=False)
                    
                    logger.debug(f"Updated review cycle state for PR #{pr_number} in workflow state")
                    return
            
            # Save as dedicated review cycle state file
            review_state_file = self.state_dir / f"review_cycle_{pr_number}.yaml"
            self.state_dir.mkdir(parents=True, exist_ok=True)
            
            with open(review_state_file, 'w') as f:
                yaml.dump(review_state, f, default_flow_style=False)
            
            logger.debug(f"Saved review cycle state for PR #{pr_number}")
            
        except Exception as e:
            logger.error(f"Error saving review cycle state for PR #{pr_number}: {e}")
    
    def update_review_iteration(self, pr_number: int, iteration_count: int) -> None:
        """Update review iteration count for a PR.
        
        Args:
            pr_number: Pull request number
            iteration_count: New iteration count
        """
        try:
            review_state = self.get_review_cycle_state(pr_number) or {}
            review_state['iteration_count'] = iteration_count
            review_state['last_updated'] = datetime.utcnow().isoformat()
            
            self.save_review_cycle_state(pr_number, review_state)
            logger.debug(f"Updated review iteration for PR #{pr_number} to {iteration_count}")
            
        except Exception as e:
            logger.error(f"Error updating review iteration for PR #{pr_number}: {e}")
    
    def get_review_status(self, pr_number: int) -> Optional[str]:
        """Get current review status for a PR.
        
        Args:
            pr_number: Pull request number
            
        Returns:
            Review status string or None
        """
        try:
            review_state = self.get_review_cycle_state(pr_number)
            if review_state:
                return review_state.get('status')
            return None
            
        except Exception as e:
            logger.error(f"Error getting review status for PR #{pr_number}: {e}")
            return None
    
    def set_review_status(self, pr_number: int, status: str) -> None:
        """Set review status for a PR.
        
        Args:
            pr_number: Pull request number
            status: New review status
        """
        try:
            review_state = self.get_review_cycle_state(pr_number) or {}
            review_state['status'] = status
            review_state['last_updated'] = datetime.utcnow().isoformat()
            
            self.save_review_cycle_state(pr_number, review_state)
            logger.debug(f"Set review status for PR #{pr_number} to {status}")
            
        except Exception as e:
            logger.error(f"Error setting review status for PR #{pr_number}: {e}")
    
    def cleanup_review_cycle_state(self, pr_number: int) -> None:
        """Clean up review cycle state for a completed/closed PR.
        
        Args:
            pr_number: Pull request number
        """
        try:
            # Remove dedicated review cycle state file
            review_state_file = self.state_dir / f"review_cycle_{pr_number}.yaml"
            if review_state_file.exists():
                review_state_file.unlink()
                logger.debug(f"Cleaned up review cycle state file for PR #{pr_number}")
            
            # Clean up review cycle state from workflow states
            states = self.get_workflow_states()
            for state in states:
                if state.pr_number == pr_number:
                    state_dict = state.model_dump() if hasattr(state, 'model_dump') else state.dict()
                    if 'review_cycle_state' in state_dict:
                        del state_dict['review_cycle_state']
                        
                        # Save the updated state
                        state_file = self.state_dir / f"{state.issue_id}.yaml"
                        import yaml
                        with open(state_file, 'w') as f:
                            yaml.dump(state_dict, f, default_flow_style=False)
                        
                        logger.debug(f"Cleaned up review cycle state from workflow state for PR #{pr_number}")
            
        except Exception as e:
            logger.error(f"Error cleaning up review cycle state for PR #{pr_number}: {e}")
    
    def get_prs_in_review(self) -> List[int]:
        """Get list of PR numbers currently in review cycle.
        
        Returns:
            List of PR numbers in review
        """
        try:
            prs_in_review = []
            
            # Check workflow states
            states = self.get_workflow_states()
            for state in states:
                if (state.pr_number and 
                    state.status in [WorkflowStatus.IN_REVIEW, WorkflowStatus.UPDATING]):
                    prs_in_review.append(state.pr_number)
            
            # Check dedicated review cycle state files
            if self.state_dir.exists():
                for state_file in self.state_dir.glob("review_cycle_*.yaml"):
                    try:
                        pr_number = int(state_file.stem.split('_')[-1])
                        if pr_number not in prs_in_review:
                            prs_in_review.append(pr_number)
                    except (ValueError, IndexError):
                        continue
            
            return sorted(prs_in_review)
            
        except Exception as e:
            logger.error(f"Error getting PRs in review: {e}")
            return []


# Global core instance
core = AutoCore()


def get_core() -> AutoCore:
    """Get core instance.
    
    Returns:
        Core instance
    """
    return core