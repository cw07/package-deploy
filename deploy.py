import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from package_deploy import Deploy


class PKGDeploy(Deploy):
    project_name = 'package-deploy'

if __name__ == '__main__':
    deploy_obj = PKGDeploy()
    deploy_obj()