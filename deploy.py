from package_deploy import Deploy

class PKGDeploy(Deploy):
    project_name = 'package-deploy'


if __name__ == '__main__':
    deploy_obj = PKGDeploy()
    deploy_obj()