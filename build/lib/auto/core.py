"""Main workflow orchestrator for the auto tool."""

from pathlib import Path
from typing import Dict, List, Optional

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


# Global core instance
core = AutoCore()


def get_core() -> AutoCore:
    """Get core instance.
    
    Returns:
        Core instance
    """
    return core