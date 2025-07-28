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
import bumpversion.cli
from enum import Enum
from pathlib import Path
from functools import partial
from argparse import ArgumentParser
from configparser import ConfigParser
from abc import ABC, abstractmethod, ABCMeta
from typing import List, Type, Optional, Callable
import platform


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

    @property
    def repo_url(self) -> str:
        raise NotImplementedError(""
                                  ""
                                  ""
                                  )

    @property
    def repo_config_name(self) -> str:
        return {
            NexusRepo.trading: 'trading',
        }[self]


class DeployArgumentProperty:
    """
    DeployArgumentProperty works in a very similar way to the in built property decorator.
    Any function decorated by DeployArgumentProperty will have the following behaviour:
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
        kwargs = {}
        if self.choices:
            kwargs['choices'] = self.choices
            kwargs['action'] = self.action

        try:
            arg_parser.add_argument(
                self.option_string_short,
                  self.option_string_long,
                  default=getattr(instance, self._name),
                  type=self.type
            )
        except argparse.ArgumentError:
            arg_parser.add_argument(
                self.option_string_long,
                  default=getattr(instance, self._name),
                  type=self.type
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
        return 'dev'

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
        gs = subprocess.check_output(['git', 'branch'])
        branches = [
            x_str.replace('* ', '').strip()
            for x_str in gs.decode().split('\n')
        ]
        return 'main' if 'main' in branches else 'master'

    @DeployArgumentProperty(type=str_to_bool)
    def bumpver(self) -> bool:
        """Whether to bump the version."""
        return True

    @DeployArgumentProperty
    def git_branch(self) -> str:
        git_branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        return git_branch.decode().replace('\n', '')

    @DeployArgumentProperty
    def git_push(self) -> bool:
        """Whether to push to bump commits to git"""
        return True

    @DeployArgumentProperty(choices=['major', 'minor', 'patch', 'build'])
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

    @DeployArgumentProperty
    def cleanup_build(self) -> bool:
        """Whether to delete dist and build after script has run."""
        return True

    @DeployArgumentProperty(type=str)
    def python_interpreter(self) -> str:
        return sys.executable

    @property
    def config_file(self) -> Path:
        paths = [
            Path('.bumpversion.cfg'),
            Path('setup.cfg'),
        ]
        for pth in paths:
            if pth.exists():
                return pth
        raise FileNotFoundError(f'Cannot find any paths, expected at least one of: {paths}.')

    @property
    def is_poetry(self) -> bool:
        pth = Path('poetry.lock')
        return pth.exists()

    def _build_windows_platform_wheel(self, args, deploy_version: str) -> List[str]:
        """Build wheel for Windows platform using native build tools."""
        build_command = [x if x != 'python' else args.python_interpreter for x in args.build_command]
        attempts_remaining: int = 3
        need_to_build_wheel: bool = True
        
        while need_to_build_wheel:
            attempts_remaining -= 1
            try:
                subprocess.check_output(build_command, stderr=subprocess.STDOUT)
                need_to_build_wheel = False
            except subprocess.CalledProcessError as e:
                _log.error(f"Failed to build wheel: {e.output}")
                if attempts_remaining > 0:
                    sleep_amount = random.randint(1, 10)
                    print(f"Attempt {10 - attempts_remaining} failed; retry in {sleep_amount}s...")
                    time.sleep(sleep_amount)
                else:
                    raise
        
        # Find the built wheel
        wheel_files = []
        for binary in Path('./dist').iterdir():
            if (
                    self.project_name in binary.name or self.project_name.replace('-', '_') in binary.name
                    and deploy_version.replace('-dev', '.dev') in binary.name
                    and binary.suffix == '.whl'
            ):
                wheel_files.append(binary.name)
        
        if len(wheel_files) != 1:
            raise ValueError(f"Unable to determine wheel name: candidates were {wheel_files}")
        
        return wheel_files

    def _build_cross_platform_wheels(self, args, deploy_version: str) -> List[str]:
        """Build wheels for multiple platforms using cibuildwheel."""
        try:
            # Check if cibuildwheel is available
            subprocess.run(['cibuildwheel', '--help'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            _log.error("cibuildwheel not found. Installing...")
            subprocess.check_output([args.python_interpreter, '-m', 'pip', 'install', 'cibuildwheel'])
        
        wheel_files = []
        
        # Build for each target platform
        for platform in args.target_platforms:
            _log.info(f"Building wheel for platform: {platform}")
            
            # Convert platform names to cibuildwheel format
            if platform.startswith('win'):
                cibuildwheel_platform = 'windows'
                if platform == 'win_amd64':
                    archs = 'AMD64'
                elif platform == 'win_arm64':
                    archs = 'ARM64'
                else:
                    _log.warning(f"Unknown Windows platform: {platform}, skipping")
                    continue
            elif platform.startswith('linux'):
                cibuildwheel_platform = 'linux'
                if platform == 'linux_x86_64':
                    archs = 'x86_64'
                elif platform == 'linux_i686':
                    archs = 'i686'
                elif platform == 'linux_aarch64':
                    archs = 'aarch64'
                else:
                    _log.warning(f"Unknown Linux platform: {platform}, skipping")
                    continue
            elif platform.startswith('macos'):
                cibuildwheel_platform = 'macos'
                if platform == 'macosx_x86_64':
                    archs = 'x86_64'
                elif platform == 'macosx_arm64':
                    archs = 'arm64'
                else:
                    _log.warning(f"Unknown macOS platform: {platform}, skipping")
                    continue
            else:
                _log.warning(f"Unknown platform: {platform}, skipping")
                continue
            
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
                if args.cython:
                    env['USE_CYTHON'] = '1'
                else:
                    env['USE_CYTHON'] = '0'
                
                subprocess.check_output(cmd, stderr=subprocess.STDOUT, env=env)
            except subprocess.CalledProcessError as e:
                if "docker" in str(e.output).lower() and "not working" in str(e.output).lower():
                    _log.error(f"Docker is not running or not available for {platform}. Please start Docker Desktop and try again.")
                    _log.error("For Windows-only builds, you can use the native build method instead.")
                else:
                    _log.error(f"Failed to build wheel for {platform}: {e.output}")
                continue
                
                # Find wheels for this platform
                for binary in Path('./dist').iterdir():
                    if (binary.suffix == '.whl' and 
                        (self.project_name in binary.name or self.project_name.replace('-', '_') in binary.name) and
                        deploy_version.replace('-dev', '.dev') in binary.name and
                        platform in binary.name):
                        wheel_files.append(binary.name)
                        
            except subprocess.CalledProcessError as e:
                _log.warning(f"Failed to build wheel for {platform}: {e.output}")
                continue
        
        return wheel_files

    def __call__(self, args=None, namespace=None):
        args = self.arg_parser.parse_args(args, namespace)
        # 1. check for git status (if not clean, abort)
        _log.info("Checking git status - we maintain to make sure repo is clean")
        gs = subprocess.check_output(['git', 'status', '--porcelain'])
        gs = gs.decode('UTF-8')
        if gs:
            raise IOError(f'Repository is NOT clean: \n{gs}')

        git_commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'])
        git_commit = git_commit.decode().replace('\n', '')

        # 2. Bump versions
        if args.bumpver:
            new_version_command = []
            if (
                    args.git_branch not in [args.dev_branch_name, args.prod_branch_name]
                    or args.deploy_type == 'commit'
            ):
                cfg = ConfigParser()
                cfg.read(self.config_file)
                current_version = cfg['bumpversion']['current_version']
                parse = cfg['bumpversion']['parse']
                old_commit = re.search(parse, current_version).group('commit')

                if old_commit:
                    # if old commit exists we replace it
                    new_version = current_version.replace(old_commit, f'+{git_commit}')
                else:
                    new_version = current_version + f'+{git_commit}'
                new_version_command = ['--new-version', new_version]

            _log.info(f"Bumping {args.deploy_type} version")
            b2v = bumpversion.cli.main([args.deploy_type, "--verbose"] + new_version_command)
            _log.info(b2v)

        # we just use "minor" below, because we don't actually care what we're trying to bump: all we are after
        # is the current version
        bump2version_command = 'bump2version.exe' if os.name == 'nt' else 'bump2version'
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
        except:
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

        # 3. build the wheel
        if args.cython:
            os.environ['USE_CYTHON'] = '1'
        else:
            os.environ['USE_CYTHON'] = '0'

        # Check if we need cross-platform OR cross-architecture builds
        needs_cross_build = any(
            platform.startswith(('linux', 'macos')) or
            (platform.startswith('win') and platform != 'win_amd64')  # Different Windows arch
            for platform in args.target_platforms
        )
        
        if needs_cross_build:
            _log.info(f"Building multi-platform wheels for: {args.target_platforms}")
            wheel_files = self._build_cross_platform_wheels(args, deploy_version)
        else:
            _log.info(f"Building single-platform wheel for: {args.target_platforms[0]}")
            wheel_files = self._build_windows_platform_wheel(args, deploy_version)
        
        if not wheel_files:
            raise ValueError("No wheels were built successfully")
        
        _log.info(f"Built {len(wheel_files)} wheel(s): {wheel_files}")

        # 4. copy the wheel to its destination directories
        if args.nas:
            for wheel_file in wheel_files:
                src = Path(__file__).parent / 'dist' / wheel_file
                dests = []
                for dest_dir in args.wheel_dests:
                    dest = dest_dir / wheel_file
                    dests.append(dest)
                    if not os.path.exists(dest):
                        _log.info(f"{src} -> {dest}")
                        shutil.copyfile(src, dest)
                    else:
                        _log.info(f"Ignoring {src} as {dest} already exists")

        # 5 maybe upload to nexus
        if args.nexus:
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
                        ],
                        stderr=subprocess.STDOUT,
                    )
                except subprocess.CalledProcessError as e:
                    _log.error(f"Failed to upload {wheel_file} to nexus: {e.output}")
                    raise e
        if args.cleanup_build:
            _log.info('Deleting build, dist and egg-info')
            shutil.rmtree('dist', ignore_errors=True)
            shutil.rmtree('build', ignore_errors=True)
            shutil.rmtree(f'src/{args.project_name}.egg-info', ignore_errors=True)
            egg_info_name = args.project_name.replace('-', '_')
            shutil.rmtree(f'src/{egg_info_name}.egg-info', ignore_errors=True)
            directory = 'src/package_deploy'
            c_files = glob.glob(os.path.join(directory, '*.c'))
            for file_path in c_files:
                try:
                    os.remove(file_path)
                except Exception as e:
                    pass

        # 6 push to GitHub
        if args.git_push:
            _log.info('Pushing to github.')
            try:
                subprocess.check_output(['git', 'pull'], stderr=subprocess.STDOUT)
                subprocess.check_output(['git', 'push', '--tags'], stderr=subprocess.STDOUT)
                subprocess.check_output(['git', 'push'], stderr=subprocess.STDOUT)
            except Exception as ex:
                if isinstance(ex, subprocess.CalledProcessError):
                    _log.error(ex.output)
                _log.warning(f'Failed to push bump version commit. Please merge and push manually.')
        _log.info('Deploy Complete')
