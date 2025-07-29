import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from typing import Dict, Any
from setuptools import setup, find_packages
from package_deploy.python_build import get_kwargs


PACKAGE_NAME = "package_deploy"
SRC_DIR = "src"


with open("requirements.txt") as f:
    install_requires = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup_kwargs: Dict[str, Any] = dict(
    name="package-deploy",
    version="0.14.2",
    author="Chen Wang",
    author_email="",
    description="Package deploy",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    python_requires=">=3.11",
    install_requires=install_requires,
    entry_points={
        'console_scripts': []
    },
    packages=find_packages(where=SRC_DIR),
    package_dir={'': SRC_DIR},
    include_package_data=True,
)

setup_kwargs.update(get_kwargs(PACKAGE_NAME, src_dir=SRC_DIR))
setup(**setup_kwargs)
