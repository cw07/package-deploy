"""
Configuration constants and settings for the package deployment system.
"""
from pathlib import Path
from typing import Dict, Any

# Build configuration
BUILD_ATTEMPTS = 3
BUILD_RETRY_DELAY_RANGE = (1, 10)  # seconds

# Platform configuration
SUPPORTED_PLATFORMS = {
    'win_amd64': ('windows', 'AMD64'),
    'win_arm64': ('windows', 'ARM64'),
    'linux_x86_64': ('linux', 'x86_64'),
    'linux_i686': ('linux', 'i686'),
    'linux_aarch64': ('linux', 'aarch64'),
    'macosx_x86_64': ('macos', 'x86_64'),
    'macosx_arm64': ('macos', 'arm64'),
}



# File patterns
CONFIG_FILE_PATTERNS = [
    'pyproject.toml',
    'setup.cfg',
    '.bumpversion.cfg'
]

POETRY_LOCK_FILE = 'poetry.lock'

# Build directories
BUILD_DIRS = ['dist', 'build']
EGG_INFO_PATTERNS = ['*.egg-info']

# Git configuration
DEFAULT_BRANCHES = ['main', 'master']
DEFAULT_DEV_BRANCH = 'dev'

# Version bumping
VERSION_BUMP_TYPES = ['major', 'minor', 'patch', 'build']

# Environment variables
CYTHON_ENV_VAR = 'USE_CYTHON'
CYTHON_ENABLED = '1'
CYTHON_DISABLED = '0'

# Commands
BUMP2VERSION_COMMANDS = {
    'windows': 'bump2version.exe',
    'unix': 'bump2version'
}

# Subprocess configuration
SUBPROCESS_STDERR = 'STDOUT'
SUBPROCESS_DISABLE_PROGRESS = '--disable-progress-bar'


