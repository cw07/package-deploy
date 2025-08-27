"""
Utility functions for the package deployment system.
"""
import os
import subprocess
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from .config import SUPPORTED_PLATFORMS

_log = logging.getLogger(__name__)


def run_command(cmd: List[str], capture_output: bool = True, env: Optional[dict] = None) -> str:
    """
    Run a command and return the output.
    
    Args:
        cmd: Command to run
        capture_output: Whether to capture output
        env: Environment variables to set
        
    Returns:
        Command output as string
        
    Raises:
        subprocess.CalledProcessError: If command fails
    """
    try:
        result = subprocess.run(cmd, capture_output=capture_output, env=env, check=True, text=True)
        return result.stdout if capture_output else ""
    except subprocess.CalledProcessError as e:
        if capture_output:
            _log.error(f"Command failed: {' '.join(cmd)}")
            _log.error(f"Error output: {e.stderr}")
        raise


def get_git_info() -> Tuple[str, str]:
    """
    Get current git branch and commit hash.
    
    Returns:
        Tuple of (branch_name, commit_hash)
    """
    try:
        branch = run_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).strip()
        commit = run_command(['git', 'rev-parse', '--short', 'HEAD']).strip()
        return branch, commit
    except subprocess.CalledProcessError as e:
        _log.warning(f"Failed to get git info: {e}")
        return 'main', 'unknown'


def check_git_status() -> bool:
    """
    Check if git repository is clean.
    
    Returns:
        True if clean, False otherwise
    """
    try:
        status = run_command(['git', 'status', '--porcelain'])
        return not bool(status.strip())
    except subprocess.CalledProcessError as e:
        _log.warning(f"Failed to check git status: {e}")
        return False


def find_wheel_files(project_name: str, version: str, dist_dir: str = './dist') -> List[str]:
    """
    Find wheel files matching project name and version.
    
    Args:
        project_name: Name of the project
        version: Version string
        dist_dir: Directory to search in
        
    Returns:
        List of wheel file names
    """
    wheel_files = []
    dist_path = Path(dist_dir)
    
    if not dist_path.exists():
        return wheel_files
    
    for binary in dist_path.iterdir():
        if (binary.suffix == '.whl' and
            (project_name in binary.name or project_name.replace('-', '_') in binary.name) and
            version.replace('-dev', '.dev') in binary.name):
            wheel_files.append(binary.name)
    
    return wheel_files


def is_supported_platform(platform: str) -> bool:
    """
    Check if a platform is supported.
    
    Args:
        platform: Platform string to check
        
    Returns:
        True if supported, False otherwise
    """
    return platform in SUPPORTED_PLATFORMS


def get_platform_info(platform: str) -> Optional[Tuple[str, str]]:
    """
    Get cibuildwheel platform and architecture for a given platform string.
    
    Args:
        platform: Platform string
        
    Returns:
        Tuple of (platform, architecture) or None if not supported
    """
    return SUPPORTED_PLATFORMS.get(platform)


def is_windows_amd64(platform: str) -> bool:
    """
    Check if platform is Windows AMD64 for native building.
    
    Args:
        platform: Platform string to check
        
    Returns:
        True if Windows AMD64, False otherwise
    """
    return platform == 'win_amd64'


def get_supported_platforms() -> List[str]:
    """
    Get list of all supported platforms.
    
    Returns:
        List of supported platform strings
    """
    return list(SUPPORTED_PLATFORMS.keys())


def set_cython_environment(use_cython: bool) -> None:
    """
    Set Cython environment variable.
    
    Args:
        use_cython: Whether to enable Cython
    """
    from .config import CYTHON_ENV_VAR, CYTHON_ENABLED, CYTHON_DISABLED
    
    if use_cython:
        os.environ[CYTHON_ENV_VAR] = CYTHON_ENABLED
    else:
        os.environ[CYTHON_ENV_VAR] = CYTHON_DISABLED


def get_bump2version_command() -> str:
    """
    Get the appropriate bump2version command for the current OS.
    
    Returns:
        Command string for bump2version
    """
    from .config import BUMP2VERSION_COMMANDS
    
    return BUMP2VERSION_COMMANDS['windows'] if os.name == 'nt' else BUMP2VERSION_COMMANDS['unix']
