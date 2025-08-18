"""Shell command execution utilities."""

import asyncio
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Union

from auto.utils.logger import get_logger

logger = get_logger(__name__)


class ShellError(Exception):
    """Shell command execution error."""
    
    def __init__(self, message: str, returncode: int, stdout: str = "", stderr: str = ""):
        """Initialize shell error.
        
        Args:
            message: Error message
            returncode: Process return code
            stdout: Standard output
            stderr: Standard error
        """
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ShellResult:
    """Shell command result."""
    
    def __init__(
        self,
        returncode: int,
        stdout: str,
        stderr: str,
        command: str,
        cwd: Optional[Path] = None,
    ):
        """Initialize shell result.
        
        Args:
            returncode: Process return code
            stdout: Standard output
            stderr: Standard error
            command: Executed command
            cwd: Working directory
        """
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.command = command
        self.cwd = cwd
    
    @property
    def success(self) -> bool:
        """Check if command succeeded."""
        return self.returncode == 0
    
    def check(self) -> "ShellResult":
        """Check result and raise error if failed.
        
        Returns:
            Self for chaining
            
        Raises:
            ShellError: If command failed
        """
        if not self.success:
            raise ShellError(
                f"Command failed: {self.command}",
                self.returncode,
                self.stdout,
                self.stderr,
            )
        return self


def run_command(
    command: Union[str, List[str]],
    cwd: Optional[Union[str, Path]] = None,
    env: Optional[Dict[str, str]] = None,
    check: bool = False,
    capture_output: bool = True,
    timeout: Optional[float] = None,
) -> ShellResult:
    """Run shell command synchronously.
    
    Args:
        command: Command to execute
        cwd: Working directory
        env: Environment variables
        check: Raise exception on failure
        capture_output: Capture stdout/stderr
        timeout: Command timeout in seconds
        
    Returns:
        Command result
        
    Raises:
        ShellError: If command fails and check=True
    """
    if isinstance(command, str):
        command_str = command
        command_list = command.split()
    else:
        command_str = " ".join(command)
        command_list = command
    
    cwd_path = Path(cwd) if cwd else None
    
    logger.debug(f"Running command: {command_str} (cwd: {cwd_path})")
    
    try:
        result = subprocess.run(
            command_list,
            cwd=cwd_path,
            env=env,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
        )
        
        shell_result = ShellResult(
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            command=command_str,
            cwd=cwd_path,
        )
        
        if result.returncode == 0:
            logger.debug(f"Command succeeded: {command_str}")
        else:
            logger.warning(f"Command failed with code {result.returncode}: {command_str}")
            if result.stderr:
                logger.debug(f"stderr: {result.stderr}")
        
        if check:
            shell_result.check()
        
        return shell_result
        
    except subprocess.TimeoutExpired as e:
        logger.error(f"Command timed out after {timeout}s: {command_str}")
        raise ShellError(f"Command timed out: {command_str}", -1, "", str(e))
    except FileNotFoundError as e:
        logger.error(f"Command not found: {command_str}")
        raise ShellError(f"Command not found: {command_str}", -1, "", str(e))


async def run_command_async(
    command: Union[str, List[str]],
    cwd: Optional[Union[str, Path]] = None,
    env: Optional[Dict[str, str]] = None,
    check: bool = False,
    timeout: Optional[float] = None,
) -> ShellResult:
    """Run shell command asynchronously.
    
    Args:
        command: Command to execute
        cwd: Working directory
        env: Environment variables
        check: Raise exception on failure
        timeout: Command timeout in seconds
        
    Returns:
        Command result
        
    Raises:
        ShellError: If command fails and check=True
    """
    if isinstance(command, str):
        command_str = command
        command_list = command.split()
    else:
        command_str = " ".join(command)
        command_list = command
    
    cwd_path = Path(cwd) if cwd else None
    
    logger.debug(f"Running async command: {command_str} (cwd: {cwd_path})")
    
    try:
        process = await asyncio.create_subprocess_exec(
            *command_list,
            cwd=cwd_path,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
        
        stdout = stdout_bytes.decode() if stdout_bytes else ""
        stderr = stderr_bytes.decode() if stderr_bytes else ""
        
        shell_result = ShellResult(
            returncode=process.returncode or 0,
            stdout=stdout,
            stderr=stderr,
            command=command_str,
            cwd=cwd_path,
        )
        
        if process.returncode == 0:
            logger.debug(f"Async command succeeded: {command_str}")
        else:
            logger.warning(f"Async command failed with code {process.returncode}: {command_str}")
            if stderr:
                logger.debug(f"stderr: {stderr}")
        
        if check:
            shell_result.check()
        
        return shell_result
        
    except asyncio.TimeoutError:
        logger.error(f"Async command timed out after {timeout}s: {command_str}")
        if process:
            process.kill()
            await process.wait()
        raise ShellError(f"Command timed out: {command_str}", -1, "", "Timeout")
    except FileNotFoundError as e:
        logger.error(f"Async command not found: {command_str}")
        raise ShellError(f"Command not found: {command_str}", -1, "", str(e))


def check_command_exists(command: str) -> bool:
    """Check if a command exists in PATH.
    
    Args:
        command: Command name to check
        
    Returns:
        True if command exists, False otherwise
    """
    try:
        result = run_command(f"which {command}", capture_output=True)
        return result.success
    except ShellError:
        return False


def get_git_root() -> Optional[Path]:
    """Get git repository root directory.
    
    Returns:
        Git root path or None if not in a git repo
    """
    try:
        result = run_command("git rev-parse --show-toplevel", check=True)
        return Path(result.stdout.strip())
    except ShellError:
        return None


def get_current_branch() -> Optional[str]:
    """Get current git branch name.
    
    Returns:
        Current branch name or None if not in a git repo
    """
    try:
        result = run_command("git branch --show-current", check=True)
        return result.stdout.strip()
    except ShellError:
        return None