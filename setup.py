import os
from Cython.Build import cythonize
from setuptools import setup, Extension, find_packages
from setuptools.dist import Distribution


PACKAGE_NAME = "package_deploy"
SRC_DIR = "src"


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

ext_modules = find_extensions(PACKAGE_NAME)

setup(
    name="package-deploy",
    version="0.0.1",
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

    # --- Build Configuration ---

    # Find packages (like your package_deploy/__init__.py)
    packages=find_packages(where=SRC_DIR),
    package_dir={'': SRC_DIR},

    # This is the magic part: it tells setuptools to use Cython
    ext_modules=cythonize(
        ext_modules,
        compiler_directives={'language_level': "3"},  # Use Python 3 syntax
        exclude=["*/__init__.py"]  # Be explicit about excluding __init__ files
    ),

    # This ensures the wheel is correctly tagged as a binary distribution
    distclass=BinaryDistribution,

    # Add Cython as a build-time dependency
    setup_requires=['cython>=0.29'],

    # This ensures non-python files defined in MANIFEST.in are included
    include_package_data=True,

    # C-extensions should not be zipped
    zip_safe=False,
)
