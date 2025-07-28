import sys
import argparse
from package_deploy import Deploy


def parse_args(args):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--deploy_type",
        default="patch"
    )
    args = parser.parse_args(args)
    return args

run_args = parse_args(sys.argv[1:])


class PKGDeploy(Deploy):
    project_name = 'package-deploy'
    deploy_type = run_args.deploy_type
    cython = True


if __name__ == '__main__':
    deploy_obj = PKGDeploy()
    deploy_obj()