import os
from typing import List
from setuptools import Extension
from setuptools.dist import Distribution
from setuptools.command.build_py import build_py as _build_py

# This is needed for the conditional logic in build_py
USE_CYTHON = os.environ.get('USE_CYTHON') == '1'


class build_py(_build_py):
    """
    Custom build_py command to exclude modules that are compiled by Cython.
    """
    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        if USE_CYTHON and self.distribution.ext_modules:
            # Get the list of compiled module names
            compiled_modules = {ext.name for ext in self.distribution.ext_modules}
            # Filter out the modules that are compiled
            modules = [
                (pkg, mod, file) for (pkg, mod, file) in modules
                if f"{pkg}.{mod}" not in compiled_modules
            ]
        return modules


class BinaryDistribution(Distribution):
    """
    Distribution which always forces a binary package with platform name.
    """

    def has_ext_modules(self) -> bool:
        return True


def find_extensions(package_dir: str, src_dir: str = "src") -> List[Extension]:
    """
    Finds all .py files in a package and creates Extension objects for Cython.
    It skips __init__.py files, as they should remain as .py files.
    """
    extensions = []
    package_path = os.path.join(src_dir, package_dir)

    for root, _, files in os.walk(package_path):
        for file in files:
            # We don't want to compile __init__.py files
            if file.endswith('.py') and not file.startswith('__init__'):
                py_path = os.path.join(root, file)

                # Create a module path like 'package_deploy.sub_module.file'
                module_path = os.path.splitext(py_path)[0].replace(os.path.sep, '.')

                # In a src layout, the 'src' prefix is not part of the module path
                if module_path.startswith(f"{src_dir}."):
                    module_path = module_path[len(f"{src_dir}."):]

                extensions.append(Extension(module_path, sources=[py_path]))

    if not extensions:
        raise ValueError(f"No Python files found to compile in {package_path}")

    print(f"Found {len(extensions)} files to compile.")
    return extensions


def get_kwargs(package_name: str, src_dir: str = "src") -> dict:
    """Returns kwargs for setup() function for cython builds."""
    from Cython.Build import cythonize
    use_cython = os.environ.get('USE_CYTHON') == '1'

    if use_cython:
        return dict(
            ext_modules=cythonize(
                find_extensions(package_name, src_dir=src_dir),
                compiler_directives={'language_level': "3"},
                exclude=["*/__init__.py"]
            ),
            distclass=BinaryDistribution,
            setup_requires=['cython>=0.29'],
            cmdclass={'build_py': build_py},
            zip_safe=False
        )
    else:
        return dict(
            cmdclass={'build_py': build_py},
            zip_safe=False
        )