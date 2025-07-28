import os
from setuptools import setup, Extension, find_packages
from setuptools.dist import Distribution
from typing import Dict, Any


PACKAGE_NAME = "package_deploy"
SRC_DIR = "src"

USE_CYTHON = os.environ.get('USE_CYTHON') == '1'

class BinaryDistribution(Distribution):
    """
    Distribution which always forces a binary package with platform name.
    """

    def has_ext_modules(self):
        return True


def find_extensions(package_dir: str) -> list[Extension]:
    """
    Finds all .py files in a package and creates Extension objects for Cython.
    It skips __init__.py files, as they should remain as .py files.
    """
    extensions = []
    package_path = os.path.join(SRC_DIR, package_dir)

    for root, _, files in os.walk(package_path):
        for file in files:
            # We don't want to compile __init__.py files
            if file.endswith('.py') and not file.startswith('__init__'):
                py_path = os.path.join(root, file)

                # Create a module path like 'package_deploy.sub_module.file'
                module_path = os.path.splitext(py_path)[0].replace(os.path.sep, '.')

                # In a src layout, the 'src' prefix is not part of the module path
                if module_path.startswith(f"{SRC_DIR}."):
                    module_path = module_path[len(f"{SRC_DIR}."):]

                extensions.append(Extension(module_path, sources=[py_path]))

    if not extensions:
        raise ValueError(f"No Python files found to compile in {package_path}")

    print(f"Found {len(extensions)} files to compile.")
    return extensions


# --- Main setup ---

with open("requirements.txt") as f:
    install_requires = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup_kwargs: Dict[str, Any] = dict(
    name="package-deploy",
    version="0.0.4",
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

if USE_CYTHON:
    from Cython.Build import cythonize
    setup_kwargs.update(
        ext_modules=cythonize(
            find_extensions(PACKAGE_NAME),
            compiler_directives={'language_level': "3"},
            exclude=["*/__init__.py"]
        ),
        distclass=BinaryDistribution,
        setup_requires=['cython>=0.29'],
    )

setup_kwargs['zip_safe'] = False

setup(**setup_kwargs)
