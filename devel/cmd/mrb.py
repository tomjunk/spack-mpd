import os
from pathlib import Path

description = "create multi-repository build area"
section = "scripting"
level = "long"

from .. import clone
from ..build import build
from ..clean import clean
from ..list_projects import list_projects, project_details, project_path
from ..mrb_config import update_mrb_config
from ..new_dev import new_dev


def setup_parser(subparser):
    subparsers = subparser.add_subparsers(dest="mrb_subcommand")
    build = subparsers.add_parser(
        "build",
        description="build repositories under development",
        aliases=["b"],
        help="build repositories",
    )
    build.add_argument(
        "--generator",
        "-G",
        metavar="<generator name>",
        help="generator used to build CMake project",
    )
    build.add_argument("--clean", action="store_true", help="clean build area before building")
    build.add_argument(
        "-j",
        dest="parallel",
        metavar="<number>",
        help="specify number of threads for parallel build",
    )
    build.add_argument(
        "generator_options",
        metavar="-- <generator options>",
        nargs="*",
        help="options passed directly to generator",
    )

    git_parser = subparsers.add_parser(
        "git-clone",
        description="clone git repositories for development",
        aliases=["g", "gitCheckout"],
        help="clone git repositories",
    )
    git_parser.add_argument(
        "repos",
        metavar="<repo spec>",
        nargs="*",
        help="a specification of a repository to clone. The repo spec may either be:\n"
        + "(a) any repository name listed by the --help-repos option, or\n"
        + "(b) any URL to a Git repository.",
    )
    git = git_parser.add_mutually_exclusive_group()
    git.add_argument("--help-repos", action="store_true", help="list supported repositories")
    git.add_argument("--help-suites", action="store_true", help="list supported suites")
    git.add_argument(
        "--suite",
        metavar="<suite name>",
        help="clone repositories corresponding to the given suite name",
    )

    install = subparsers.add_parser(
        "install",
        description="install (and build if necessary) repositories",
        aliases=["i"],
        help="install built repositories",
    )

    lst_description = (
        "list MRB projects\n\n"
        + "When no arguments are specified, prints a list of known MRB projects\n"
        + "and their corresponding top-level directories."
    )
    lst = subparsers.add_parser(
        "list", description=lst_description, aliases=["ls"], help="list MRB projects"
    )
    lst.add_argument(
        "project", metavar="<project name>", nargs="*", help="print details of the MRB project"
    )
    lst.add_argument(
        "-t", "--top", metavar="<project name>", help="print top-level directory for project"
    )

    default_top = Path.cwd()
    new_dev_description = f"create new development area\n\nIf the '--top' option is not specified, the current working directory will be used:\n  {default_top}"
    newDev = subparsers.add_parser(
        "new-dev",
        description=new_dev_description,
        aliases=["n", "newDev"],
        help="create new development area",
    )
    newDev.add_argument("--name", required=True)
    newDev.add_argument(
        "--top", metavar="<dir>", default=default_top, help="top-level directory for MRSB area"
    )
    newDev.add_argument("-D", "--dir", help="directory containing repositories to develop")
    newDev.add_argument(
        "-f", "--force", action="store_true", help="overwrite existing project with same name"
    )
    newDev.add_argument("variants", nargs="*")

    test = subparsers.add_parser(
        "test", description="build and run tests", aliases=["t"], help="build and run tests"
    )
    zap_parser = subparsers.add_parser(
        "zap",
        description="delete everything in your build and/or install areas.\n\nIf no optional argument is provided, the '--build' option is assumed.",
        aliases=["z"],
        help="delete everything in your build and/or install areas",
    )
    zap = zap_parser.add_mutually_exclusive_group()
    zap.add_argument(
        "--all",
        dest="zap_all",
        action="store_true",
        help="delete everything in your build and install directories",
    )
    zap.add_argument(
        "--build",
        dest="zap_build",
        action="store_true",
        default=True,
        help="delete everything in your build directory",
    )
    zap.add_argument(
        "--install",
        dest="zap_install",
        action="store_true",
        help="delete everything in your install directory",
    )


def mrb(parser, args):
    if args.mrb_subcommand in ("new-dev", "n", "newDev"):
        project_config = update_mrb_config(
            args.name,
            Path(args.top).absolute(),
            Path(args.dir).absolute(),
            args.variants,
            args.force,
        )
        new_dev(args.name, project_config)
        return
    if args.mrb_subcommand in ("git-clone", "g", "gitCheckout"):
        if args.repos:
            clone.clone_repos(args.repos, os.environ["MRB_SOURCE"], os.environ["MRB_LOCAL"])
        if args.suite:
            clone.clone_suite(args.suite, os.environ["MRB_SOURCE"], os.environ["MRB_LOCAL"])
        if args.help_suites:
            clone.help_suites()
        if args.help_repos:
            clone.help_repos()
        return
    if args.mrb_subcommand in ("build", "b"):
        srcs, build_area, install_area = (
            os.environ["MRB_SOURCE"],
            os.environ["MRB_BUILDDIR"],
            os.environ["MRB_INSTALL"],
        )
        if args.clean:
            clean(build_area)

        build(
            srcs, build_area, install_area, args.generator, args.parallel, args.generator_options
        )
        return
    if args.mrb_subcommand in ("list", "ls"):
        if args.project:
            project_details(args.project)
        elif args.top:
            project_path(args.top, "top")
        else:
            list_projects()
        return
    if args.mrb_subcommand in ("zap", "z"):
        if args.zap_install:
            clean(os.environ["MRB_INSTALL"])
        if args.zap_all:
            clean(os.environ["MRB_INSTALL"])
            clean(os.environ["MRB_BUILDDIR"])
        if args.zap_build:
            clean(os.environ["MRB_BUILDDIR"])
        return
