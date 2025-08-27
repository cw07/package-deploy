import re
import os
import sys
import time
import glob
import random
import shutil
import logging
import argparse
import subprocess
from enum import Enum
from pathlib import Path
from functools import partial
from argparse import ArgumentParser
from configparser import ConfigParser
from abc import ABC, abstractmethod, ABCMeta
from typing import List, Type, Optional, Callable, Dict, Tuple

from .config import (
    BUILD_ATTEMPTS, BUILD_RETRY_DELAY_RANGE, SUPPORTED_PLATFORMS,
    CONFIG_FILE_PATTERNS, POETRY_LOCK_FILE, BUILD_DIRS, EGG_INFO_PATTERNS,
    DEFAULT_BRANCHES, DEFAULT_DEV_BRANCH, VERSION_BUMP_TYPES,
    CYTHON_ENV_VAR, CYTHON_ENABLED, CYTHON_DISABLED,
    BUMP2VERSION_COMMANDS, SUBPROCESS_STDERR, SUBPROCESS_DISABLE_PROGRESS
)
from .utils import (
    run_command, get_git_info, check_git_status, find_wheel_files,
    is_supported_platform, get_platform_info, is_windows_amd64,
    set_cython_environment, get_bump2version_command
)


_log = logging.getLogger(__name__)
_log.setLevel(logging.INFO)


def str_to_bool(value):
    if isinstance(value, bool):
        return value
    if value.lower() in {'false', 'f', '0', 'no', 'n'}:
        return False
    elif value.lower() in {'true', 't', '1', 'yes', 'y'}:
        return True
    raise ValueError(f'{value} is not a valid boolean value')


class NexusRepo(str, Enum):
    trading = 'trading'
    pypi = 'pypi'

    @property
    def repo_url(self) -> str:
        return {
            NexusRepo.trading: 'http://8.222.211.138:8081/repository/trading/',
            NexusRepo.pypi: 'https://upload.pypi.org/legacy/'
        }[self]

    @property
    def repo_config_name(self) -> str:
        return {
            NexusRepo.trading: 'trading',
            NexusRepo.pypi: 'pypi'
        }[self]


class DeployArgumentProperty:
    """
    DeployArgumentProperty works in a very similar way to the in built property decorator.
    Any function decorated by DeployArgumentProperty will have the following behavior:
        1. Can be overridden by a child class variable.
        2. Can be overridden by a child class property.
        3. Will be added to the argument parser with name and short name.
    """

    def __init__(
            self,
            value=None,
            option_string_short: str = None,
            option_string_long: str = None,
            choices: List = None,
            action: str = None,
            type=None
    ):
        self._value = value
        self._option_string_short = option_string_short
        self._option_string_long = option_string_long
        self.choices = choices
        self.type = type
        self.action = action

    def __call__(self, value):
        return DeployArgumentProperty(
            value,
            self._option_string_short,
            self._option_string_long,
            self.choices,
            self.action,
            self.type,
        )

    def __get__(self, instance, owner):
        return self._value(instance) if callable(self._value) else self._value

    def __set_name__(self, owner, name):
        self._name = name

    def __set__(self, instance, value):
        self._value = value

    @property
    def option_string_long(self):
        return self._option_string_long or f'--{self._name}'

    @property
    def option_string_short(self):
        return self._option_string_short or f'-{self._name[0]}'

    def add_argument(self, arg_parser: ArgumentParser, instance='Deploy'):
        kwargs = {
            'default': getattr(instance, self._name),
            'type': self.type
        }
        if self.choices:
            kwargs['choices'] = self.choices
        if self.action:
            kwargs['action'] = self.action

        try:
            arg_parser.add_argument(
                self.option_string_short,
                self.option_string_long,
                **kwargs
            )
        except argparse.ArgumentError:
            arg_parser.add_argument(
                self.option_string_long,
                **kwargs
            )


class DeployMetaClass(ABCMeta):
    def __new__(mcs, name, bases, props):
        if mcs.__module__ != props.get('__module__', ''):
            # We are in a concrete class
            deploy_args = [
                k
                for k, v in vars(Deploy).items()
                if isinstance(v, DeployArgumentProperty)
            ]
            new_props = {}
            for k, v in props.items():
                if k in deploy_args and not callable(v):
                    new_props[k] = DeployArgumentProperty(v)
                else:
                    new_props[k] = v
            props = new_props
        return ABCMeta.__new__(mcs, *[name, bases, props])

    def __init__(cls: Type['Deploy'], *args, **kwargs):
        # Create a partial function that adds the param to the arg parser.
        # Store this partial in a list in Deploy so that it can be called at class Deploy init.
        # The limitation of storing these Lists on the Deploy class is that any instance of child classes
        # will share the list. However, for our use case this is not a problem as we only instantiate 1 Deploy per
        # instance of python
        ABCMeta.__init__(cls, *args, **kwargs)
        for name, v in vars(cls).items():
            if name != 'arg_parser':
                if (
                        isinstance(v, DeployArgumentProperty)
                        and name not in cls.deploy_arg_property_names
                ):
                    cls.deploy_arg_property_names.append(name)
                    cls.deploy_arg_properties.append(partial(v.add_argument))


class Deploy(ABC, metaclass=DeployMetaClass):
    """
    A deployment object that has configurable parameters decorated by DeployArgumentProperty.
    Any function decorated with DeployArgumentProperty is a config option that can be overridden from the command
    line or from the concrete class.
    """

    deploy_arg_properties: List[partial[[ArgumentParser, 'Deploy'], None]] = []
    deploy_arg_property_names: List[str] = []

    def __init__(self):
        self.arg_parser = ArgumentParser()
        for add_arg_call, name in zip(
                self.deploy_arg_properties, self.deploy_arg_property_names
        ):
            add_arg_call(self.arg_parser, self)

    @DeployArgumentProperty
    @abstractmethod
    def project_name(self) -> str:
        ...

    @DeployArgumentProperty
    def nexus_repo(self) -> NexusRepo:
        """The Nexus repo to upload the wheel to."""
        return NexusRepo.trading

    @DeployArgumentProperty
    def dev_branch_name(self) -> str:
        """Name of the dev branch."""
        return DEFAULT_DEV_BRANCH

    @DeployArgumentProperty(type=str_to_bool)
    def cython(self) -> bool:
        """Whether to compile with cython."""
        return False

    @DeployArgumentProperty
    def target_platforms(self) -> List[str]:
        """List of target platforms to build for. Defaults to Windows platform."""
        return ['win_amd64']

    @DeployArgumentProperty(type=str_to_bool)
    def nexus(self) -> bool:
        """Whether to publish to Nexus."""
        return True

    @DeployArgumentProperty(type=str)
    def component_name(self) -> str:
        """The name of the deployed component, which is used when specifying versions in a requirements.txt or
        python dependencies list. Defaults to the project name"""
        return self.project_name

    @DeployArgumentProperty
    def prod_branch_name(self) -> str:
        """Name of the prod branch."""
        try:
            gs = subprocess.check_output(['git', 'branch'])
            branches = [
                x_str.replace('* ', '').strip()
                for x_str in gs.decode().split('\n')
            ]
            return DEFAULT_BRANCHES[0] if DEFAULT_BRANCHES[0] in branches else DEFAULT_BRANCHES[1]
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            _log.warning(f"Failed to get git branches: {e}. Defaulting to '{DEFAULT_BRANCHES[0]}'.")
            return DEFAULT_BRANCHES[0]

    @DeployArgumentProperty(type=str_to_bool)
    def bumpver(self) -> bool:
        """Whether to bump the version."""
        return True

    @DeployArgumentProperty
    def git_branch(self) -> str:
        try:
            git_branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
            return git_branch.decode().replace('\n', '')
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            _log.warning(f"Failed to get current git branch: {e}. Defaulting to '{DEFAULT_BRANCHES[0]}'.")
            return DEFAULT_BRANCHES[0]

    @DeployArgumentProperty
    def git_push(self) -> bool:
        """Whether to push to bump commits to git"""
        return True

    @DeployArgumentProperty(choices=VERSION_BUMP_TYPES)
    def deploy_type(self) -> str:
        """What version to bump. As defined in config file."""
        return 'build' if not self.git_branch == self.prod_branch_name else 'patch'

    @DeployArgumentProperty
    def build_command(self) -> List[str]:
        """What commands to use to build the wheel."""
        if self.is_poetry:
            return ['poetry', 'build']
        elif Path('setup.py').exists():
            return ['python', 'setup.py', 'bdist_wheel']
        else:
            return ['python', '-m', 'build', '--wheel']

    @DeployArgumentProperty(type=str_to_bool)
    def nas(self) -> bool:
        """Whether to publish to nas."""
        return False

    @DeployArgumentProperty(type=str_to_bool)
    def cleanup_build(self) -> bool:
        """Whether to delete dist and build after script has run."""
        return True

    @DeployArgumentProperty(type=str)
    def python_interpreter(self) -> str:
        return sys.executable

    @DeployArgumentProperty
    def wheel_dests(self) -> List[Path]:
        """List of destination directories for wheel files when using NAS deployment."""
        return []

    @property
    def config_file(self) -> Path:
        paths = [Path(pattern) for pattern in CONFIG_FILE_PATTERNS]
        for pth in paths:
            if pth.exists():
                return pth
        raise FileNotFoundError(f'Cannot find any paths, expected at least one of: {paths}.')

    @property
    def is_poetry(self) -> bool:
        pth = Path(POETRY_LOCK_FILE)
        return pth.exists()

    def _check_git_status(self) -> None:
        """Check if git repository is clean."""
        _log.info("Checking git status - we maintain to make sure repo is clean")
        if not check_git_status():
            raise IOError("Repository is NOT clean: Repository has uncommitted changes")

    def _get_git_commit(self) -> str:
        """Get current git commit hash."""
        _, commit = get_git_info()
        return commit

    def _bump_version(self, args, git_commit: str) -> None:
        """Bump version using bumpversion."""
        if not args.bumpver:
            return
            
        new_version_command = []
        if (
                args.git_branch not in [args.dev_branch_name, args.prod_branch_name]
                or args.deploy_type == 'commit'
        ):
            cfg = ConfigParser()
            cfg.read(self.config_file)
            current_version = cfg['bumpversion']['current_version']
            parse = cfg['bumpversion']['parse']
            match = re.search(parse, current_version)
            old_commit = match.group('commit') if match else None

            if old_commit:
                # if old commit exists we replace it
                new_version = current_version.replace(old_commit, f'+{git_commit}')
            else:
                new_version = current_version + f'+{git_commit}'
            new_version_command = ['--new-version', new_version]

        _log.info(f"Bumping {args.deploy_type} version")
        import bumpversion.cli
        b2v = bumpversion.cli.main([args.deploy_type, "--verbose"] + new_version_command)
        _log.info(b2v)

    def _get_deploy_version(self, args) -> str:
        """Get the current deployment version."""
        # we just use "minor" below, because we don't care what we're trying to bump: all we are after
        # is the current version
        bump2version_command = get_bump2version_command()
        try:
            b2v = subprocess.check_output(
                [bump2version_command, '--dry-run', '--list', args.deploy_type]
            )
            b2v = b2v.decode('UTF-8')
            parts = b2v.splitlines(keepends=False)
            current_versions = []
            for part in parts:
                cv_m = re.match(r'pattern:.*current_version=(.*)$', part)
                if cv_m:
                    current_versions.append(cv_m.group(1))
            if len(current_versions) != 1:
                raise ValueError(f"Ambiguous versions found: {current_versions}")
            deploy_version = current_versions[0]
        except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
            _log.warning(f"Failed to get version from bump2version: {e}. Reading from config file.")
            cfg = ConfigParser()
            cfg.read(self.config_file)
            deploy_version = cfg['bumpversion']['current_version']

        if (
                '-dev' in deploy_version
                and args.git_branch == args.prod_branch_name
                and args.bumpver
        ):
            _log.info(f"Bumping release version")
            b2v = subprocess.check_output([bump2version_command, 'release'])
            b2v = b2v.decode('UTF-8')
            _log.info(b2v)

            b2v = subprocess.check_output(
                [bump2version_command, '--dry-run', '--list', args.deploy_type]
            )
            b2v = b2v.decode('UTF-8')
            parts = b2v.splitlines(keepends=False)
            current_versions = []
            for part in parts:
                cv_m = re.match(r'pattern:.*current_version=(.*)$', part)
                if cv_m:
                    current_versions.append(cv_m.group(1))
            if len(current_versions) != 1:
                raise ValueError(f"Ambiguous versions found: {current_versions}")
            deploy_version = current_versions[0]

        if not deploy_version:
            raise ValueError("Unable to determine version info")
            
        return deploy_version

    def _build_windows_platform_wheel(self, args, deploy_version: str) -> List[str]:
        """Build wheel for Windows platform using native build tools."""
        build_command = [x if x != 'python' else args.python_interpreter for x in args.build_command]
        attempts_remaining: int = BUILD_ATTEMPTS
        need_to_build_wheel: bool = True
        
        while need_to_build_wheel:
            attempts_remaining -= 1
            try:
                subprocess.check_output(build_command, stderr=subprocess.STDOUT)
                need_to_build_wheel = False
            except subprocess.CalledProcessError as e:
                _log.error(f"Failed to build wheel: {e.output}")
                if attempts_remaining > 0:
                    sleep_amount = random.randint(*BUILD_RETRY_DELAY_RANGE)
                    print(f"Attempt {BUILD_ATTEMPTS - attempts_remaining} failed; retry in {sleep_amount}s...")
                    time.sleep(sleep_amount)
                else:
                    raise
        
        # Find the built wheel
        wheel_files = find_wheel_files(self.project_name, deploy_version)
        
        if len(wheel_files) != 1:
            raise ValueError(f"Unable to determine wheel name: candidates were {wheel_files}")
        
        return wheel_files

    def _build_cross_platform_wheels_for_platforms(self, args, deploy_version: str, platforms: List[str]) -> List[str]:
        """Build wheels for specific platforms using cibuildwheel."""
        try:
            # Check if cibuildwheel is available
            subprocess.run(['cibuildwheel', '--help'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            _log.error("cibuildwheel not found. Installing...")
            subprocess.check_output([args.python_interpreter, '-m', 'pip', 'install', 'cibuildwheel'])
        
        wheel_files = []
        
        # Build for each specified platform
        for platform in platforms:
            _log.info(f"Building wheel for platform: {platform}")
            
            # Get platform info using the utility function
            platform_info = get_platform_info(platform)
            if not platform_info:
                _log.warning(f"Unknown platform: {platform}, skipping")
                continue
                
            cibuildwheel_platform, archs = platform_info
            
            # Create cibuildwheel command
            cmd = [
                'cibuildwheel',
                '--platform', cibuildwheel_platform,
                '--archs', archs,
                '--output-dir', './dist',
                '--config-file', 'cibuildwheel.toml'
            ]
            
            try:
                # Set environment variables for the subprocess
                env = os.environ.copy()
                set_cython_environment(args.cython)
                # Update the environment dict with the new value
                env[CYTHON_ENV_VAR] = os.environ[CYTHON_ENV_VAR]
                
                subprocess.check_output(cmd, stderr=subprocess.STDOUT, env=env)
                
                # Find wheels for this platform
                platform_wheels = find_wheel_files(self.project_name, deploy_version)
                # Filter by platform
                for wheel in platform_wheels:
                    if platform in wheel:
                        wheel_files.append(wheel)
                        
            except subprocess.CalledProcessError as e:
                if "docker" in str(e.output).lower() and "not working" in str(e.output).lower():
                    _log.error(f"Docker is not running or not available for {platform}. Please start Docker Desktop and try again.")
                    _log.error("For Windows-only builds, you can use the native build method instead.")
                else:
                    _log.error(f"Failed to build wheel for {platform}: {e.output}")
                continue
        
        return wheel_files

    def _build_wheels(self, args, deploy_version: str) -> List[str]:
        """Build wheels for all target platforms."""
        # Set Cython environment variable
        set_cython_environment(args.cython)

        # Separate Windows AMD64 from other platforms
        windows_amd64_platforms = [p for p in args.target_platforms if is_windows_amd64(p)]
        other_platforms = [p for p in args.target_platforms if not is_windows_amd64(p)]
        
        wheel_files = []
        
        # Build Windows AMD64 wheels using native build (faster)
        if windows_amd64_platforms:
            _log.info(f"Building Windows AMD64 wheels natively for: {windows_amd64_platforms}")
            windows_wheels = self._build_windows_platform_wheel(args, deploy_version)
            wheel_files.extend(windows_wheels)
        
        # Build other platforms using cibuildwheel
        if other_platforms:
            _log.info(f"Building cross-platform wheels for: {other_platforms}")
            other_wheels = self._build_cross_platform_wheels_for_platforms(args, deploy_version, other_platforms)
            wheel_files.extend(other_wheels)
        
        if not wheel_files:
            raise ValueError("No wheels were built successfully")
        
        _log.info(f"Built {len(wheel_files)} wheel(s): {wheel_files}")
        return wheel_files

    def _deploy_to_nas(self, args, wheel_files: List[str]) -> None:
        """Deploy wheel files to NAS destinations."""
        if not args.nas:
            return
            
        for wheel_file in wheel_files:
            src = Path('./dist') / wheel_file
            for dest_dir in args.wheel_dests:
                dest = dest_dir / wheel_file
                if not os.path.exists(dest):
                    _log.info(f"{src} -> {dest}")
                    shutil.copyfile(src, dest)
                else:
                    _log.info(f"Ignoring {src} as {dest} already exists")

    def _deploy_to_nexus(self, args, wheel_files: List[str]) -> None:
        """Deploy wheel files to Nexus repository."""
        if not args.nexus:
            return
            
        _log.info('Deploying to nexus')
        for wheel_file in wheel_files:
            try:
                _log.info(f'Uploading {wheel_file} to nexus')
                subprocess.check_output(
                    [
                        'twine',
                        'upload',
                        '--repository',
                        args.nexus_repo.repo_config_name,
                        f'dist/{wheel_file}',
                        SUBPROCESS_DISABLE_PROGRESS,
                    ],
                    stderr=subprocess.STDOUT,
                )
            except subprocess.CalledProcessError as e:
                _log.error(f"Failed to upload {wheel_file} to nexus: {e.output}")
                raise e

    def _cleanup_build(self, args) -> None:
        """Clean up build artifacts."""
        if not args.cleanup_build:
            return
            
        _log.info('Deleting build, dist and egg-info')
        for build_dir in BUILD_DIRS:
            shutil.rmtree(build_dir, ignore_errors=True)
        
        # Remove egg-info directories
        for pattern in EGG_INFO_PATTERNS:
            egg_info_paths = glob.glob(f'src/{args.project_name}{pattern}')
            egg_info_name = args.project_name.replace('-', '_')
            egg_info_paths.extend(glob.glob(f'src/{egg_info_name}{pattern}'))
            
            for egg_info_path in egg_info_paths:
                shutil.rmtree(egg_info_path, ignore_errors=True)
        
        # Remove C files
        directory = 'src/package_deploy'
        c_files = glob.glob(os.path.join(directory, '*.c'))
        for file_path in c_files:
            try:
                os.remove(file_path)
            except (OSError, FileNotFoundError) as e:
                _log.warning(f"Failed to remove C file {file_path}: {e}")

    def _push_to_github(self, args) -> None:
        """Push changes to GitHub."""
        if not args.git_push:
            return
            
        _log.info('Pushing to github.')
        try:
            subprocess.check_output(['git', 'pull'], stderr=subprocess.STDOUT)
            subprocess.check_output(['git', 'push', '--tags'], stderr=subprocess.STDOUT)
            subprocess.check_output(['git', 'push'], stderr=subprocess.STDOUT)
        except Exception as ex:
            if isinstance(ex, subprocess.CalledProcessError):
                _log.error(ex.output)
            _log.warning(f'Failed to push bump version commit. Please merge and push manually.')

    def __call__(self, args=None, namespace=None):
        """Main deployment workflow."""
        args = self.arg_parser.parse_args(args, namespace)
        
        # 1. Check git status
        self._check_git_status()
        git_commit = self._get_git_commit()

        # 2. Bump versions
        self._bump_version(args, git_commit)
        deploy_version = self._get_deploy_version(args)

        # 3. Build wheels
        wheel_files = self._build_wheels(args, deploy_version)

        # 4. Deploy to NAS
        self._deploy_to_nas(args, wheel_files)

        # 5. Deploy to Nexus
        self._deploy_to_nexus(args, wheel_files)

        # 6. Cleanup build artifacts
        self._cleanup_build(args)

        # 7. Push to GitHub
        self._push_to_github(args)
        
        _log.info('Deploy Complete')
