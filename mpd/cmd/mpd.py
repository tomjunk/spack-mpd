import os
import sys
from pathlib import Path

import llnl.util.filesystem as fs
import llnl.util.tty as tty

from .. import clone
from ..build import build
from ..init import init
from ..list_projects import list_projects, project_details, project_path
from ..mpd_config import mpd_local_dir, project_config, refresh_mpd_config, update_mpd_config
from ..new_project import declare_active, new_project, update_project
from ..rm_project import rm_project
from ..util import bold

description = "develop multiple packages using Spack for external software"
section = "scripting"
level = "long"

_VERSION = "0.1.0"


def setup_parser(subparser):
    subparser.add_argument(
        "-V", "--version", action="store_true", help=f"print MPD version ({_VERSION}) and exit"
    )
    subparsers = subparser.add_subparsers(dest="mpd_subcommand", required=False)
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

    subparsers.add_parser(
        "init", description="initialize MPD on this system", help="initialize MPD on this system"
    )

    subparsers.add_parser(
        "install",
        description="install (and build if necessary) repositories",
        aliases=["i"],
        help="install built repositories",
    )

    lst_description = """list MPD projects

When no arguments are specified, prints a list of known MPD projects
and their corresponding top-level directories."""
    lst = subparsers.add_parser(
        "list", description=lst_description, aliases=["ls"], help="list MPD projects"
    )
    lst.add_argument(
        "project", metavar="<project name>", nargs="*", help="print details of the MPD project"
    )
    lst.add_argument(
        "-t", "--top", metavar="<project name>", help="print top-level directory for project"
    )

    default_top = Path.cwd()
    new_project = subparsers.add_parser(
        "new-project",
        description="create MPD development area",
        aliases=["n", "newDev"],
        help="create MPD development area",
    )
    new_project.add_argument("--name", required=True, help="(required)")
    new_project.add_argument(
        "-T",
        "--top",
        default=default_top,
        help="top-level directory for MPD area\n(default: %(default)s)",
    )
    new_project.add_argument(
        "-S",
        "--srcs",
        help="directory containing repositories to develop\n"
        "(default: <top-level directory>/srcs)",
    )
    new_project.add_argument(
        "-f", "--force", action="store_true", help="overwrite existing project with same name"
    )
    new_project.add_argument(
        "-E",
        "--env",
        help="environments from which to create project\n(multiple allowed)",
        action="append",
    )
    new_project.add_argument("variants", nargs="*")

    subparsers.add_parser(
        "refresh", description="refresh project area", help="refresh project area"
    )

    rm_proj_description = """remove MPD project

Removing a project will:

  * Remove the project entry from the list printed by 'spack mpd list'
  * Delete the 'build' and 'local' directories
  * If '--full' specified, delete the entire 'top' level directory tree of the
    project (including the specified sources directory if it resides
    within the top-level directory).
  * Uninstall the project's package/environment"""
    rm_proj = subparsers.add_parser(
        "rm-project", description=rm_proj_description, aliases=["rm"], help="remove MPD project"
    )
    rm_proj.add_argument("project", metavar="<project name>", help="MPD project to remove")
    rm_proj.add_argument(
        "--full",
        action="store_true",
        help="remove entire directory tree starting at the top level of the project",
    )

    subparsers.add_parser(
        "test", description="build and run tests", aliases=["t"], help="build and run tests"
    )
    zap_parser = subparsers.add_parser(
        "zap",
        description="delete everything in your build and/or install areas.\n\n"
        "If no optional argument is provided, the '--build' option is assumed.",
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


def _active_project():
    session_id = os.getsid(os.getpid())
    active_project = Path(mpd_local_dir() / "active" / f"{session_id}")
    if not active_project.exists():
        print()
        tty.die(f"Active MPD project required to invoke 'spack {' '.join(sys.argv[1:])}'\n")

    with open(active_project) as f:
        name = f.read().strip()
    return name


def _active_project_config():
    return project_config(_active_project())


def mpd(parser, args):
    if not args.version and not args.mpd_subcommand:
        parser.parse_args(["mpd", "-h"])
        return

    if args.mpd_subcommand in ("build", "b"):
        config = _active_project_config()
        srcs, build_area, install_area = (config["source"], config["build"], config["install"])
        if args.clean:
            fs.remove_directory_contents(build_area)

        build(
            srcs, build_area, install_area, args.generator, args.parallel, args.generator_options
        )
        return

    if args.mpd_subcommand in ("git-clone", "g", "gitCheckout"):
        if args.repos:
            config = _active_project_config()
            clone.clone_repos(args.repos, config["source"], config["local"])
        else:
            if args.suite:
                config = _active_project_config()
                clone.clone_suite(args.suite, config["source"], config["local"])
            elif args.help_suites:
                clone.help_suites()
            elif args.help_repos:
                clone.help_repos()
            else:
                print()
                tty.die(
                    f"At least one option required when invoking 'spack {' '.join(sys.argv[1:])}'"
                    "\n"
                )
        return

    if args.mpd_subcommand == "init":
        init()
        return

    if args.mpd_subcommand in ("list", "ls"):
        if args.project:
            project_details(args.project)
        elif args.top:
            project_path(args.top, "top")
        else:
            list_projects()
        return

    if args.mpd_subcommand in ("new-project", "n", "newDev"):
        new_project(args)
        return

    if args.mpd_subcommand == "refresh":
        name = _active_project()
        current_config = project_config(name)
        new_config = refresh_mpd_config(name)
        if current_config == new_config:
            tty.msg(f"Project {name} is up-to-date")
            return
        update_project(name, new_config)
        return

    if args.mpd_subcommand in ("rm-project", "rm"):
        config = project_config(args.project)
        if args.project == os.environ.get("MPD_PROJECT"):
            print()
            tty.die(
                f"Cannot remove active MPD project {bold(args.project)}.  Deactivate by invoking:"
                "\n\n"
                "           spack env deactivate\n"
            )
        rm_project(args.project, config, args.full)
        return

    if args.mpd_subcommand in ("zap", "z"):
        config = _active_project_config()
        if args.zap_install:
            fs.remove_directory_contents(config["install"])
        if args.zap_all:
            fs.remove_directory_contents(config["install"])
            fs.remove_directory_contents(config["build"])
        if args.zap_build:
            fs.remove_directory_contents(config["build"])
        return


# The following is invoked post-installation
def make_active(name):
    declare_active(name)


def add_project(project_config):
    update_mpd_config(project_config, installed=True)
