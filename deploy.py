import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from package_deploy import Deploy


class PKGDeploy(Deploy):
    project_name = 'package-deploy'
    cython = True
    target_platforms = ['linux_x86_64']  # Build for Windows and Linux


if __name__ == '__main__':
    deploy_obj = PKGDeploy()
    deploy_obj()