import os
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile

import ruamel
from ruamel.yaml.scalarstring import SingleQuotedScalarString as YamlQuote

import llnl.util.tty as tty

import spack.environment as ev
import spack.util.spack_yaml as syaml
from spack.parser import SPLIT_KVP, SpecParser, TokenType
from spack.repo import PATH, UnknownPackageError
from spack.spec import Spec

from . import init
from .util import cyan, gray, magenta, spack_cmd_line, yellow


def _variant_pair(value, variant):
    return dict(value=value, variant=variant)


UNINSTALLED = "---"

_DEFAULT_CXXSTD = _variant_pair(value="17", variant="cxxstd=17")
_DEFAULT_GENERATOR = _variant_pair(value="make", variant="generator=make")
_DEVELOP_VARIANT = _variant_pair(value="develop", variant="@develop")


# Pilfered from https://stackoverflow.com/a/568285/3585575
def _process_exists(pid):
    """Check For the existence of a unix pid."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def mpd_config_dir():
    return init.mpd_config_dir()


def mpd_config_file():
    return init.mpd_config_file(mpd_config_dir())


def selected_projects_dir():
    return init.mpd_selected_projects_dir(mpd_config_dir())


def selected_projects():
    projects = {}
    for sp in selected_projects_dir().iterdir():
        project_name = sp.read_text()
        projects.setdefault(project_name, []).append(sp.name)
    return projects


def session_id():
    return f"{os.getsid(os.getpid())}"


def selected_project_token():
    projects_dir = selected_projects_dir()
    return projects_dir / session_id() if projects_dir else None


def mpd_config():
    config_file = mpd_config_file()
    if not config_file.exists():
        return None

    with open(config_file, "r") as f:
        return syaml.load(f)
    return None


def prepare_project_directories(top_path, srcs_path):
    def _create_dir(path):
        path.mkdir(exist_ok=True)
        return str(path.absolute())

    return {"top": _create_dir(top_path),
            "source": _create_dir(srcs_path),
            "build": _create_dir(top_path / "build"),
            "local": _create_dir(top_path / "local")}


def ordered_requirement_list(requirements):
    # Assemble things in the right order
    requirement_list = []
    for variant_name in ("version", "compiler"):
        if variant := requirements.pop(variant_name, None):
            requirement_list.append(YamlQuote(variant))

    # We don't care about the order of the remaining variants
    requirement_list += [YamlQuote(r) for r in requirements.values()]
    return requirement_list


def handle_variant(token):
    # Last specification wins (this behavior may need to be massaged)
    if token.kind in (TokenType.COMPILER, TokenType.COMPILER_AND_VERSION):
        return "compiler", _variant_pair(token.value[1:], token.value)
    if token.kind in (TokenType.KEY_VALUE_PAIR, TokenType.PROPAGATED_KEY_VALUE_PAIR):
        match = SPLIT_KVP.match(token.value)
        name, _, value = match.groups()
        return name, _variant_pair(value, token.value)
    if token.kind == TokenType.BOOL_VARIANT:
        name = token.value[1:].strip()
        return name, _variant_pair(token.value[0] == "+", token.value)
    if token.kind == TokenType.PROPAGATED_BOOL_VARIANT:
        name = token.value[2:].strip()
        return name, _variant_pair(token.value[:2] == "++", token.value)
    elif token.kind == TokenType.VERSION:
        return "version", _variant_pair(token.value[1:], token.value)

    tty.die(f"The token '{token.value}' is not supported")


def spack_packages(srcs_dir):
    srcs_path = Path(srcs_dir)
    assert srcs_path.exists()
    srcs_repos = sorted(
        f.name for f in srcs_path.iterdir() if not f.name.startswith(".") and f.is_dir()
    )

    # Check for unknown packages
    unknown_packages = []
    packages_to_develop = {}
    for p in srcs_repos:
        spec = Spec(p)
        try:
            pkg_cls = PATH.get_pkg_class(spec.name)
        except UnknownPackageError:
            unknown_packages.append(p)
        packages_to_develop[p] = pkg_cls(spec)

    if unknown_packages:
        print()
        msg = "The following directories do not correspond to any known Spack package:\n"
        for p in unknown_packages:
            msg += f"\n - {srcs_path / p}"
        tty.die(msg + "\n")

    return packages_to_develop


def handle_variants(project_cfg, variants):
    variant_str = " ".join(variants)
    tokens_from_str = SpecParser(variant_str).tokens()
    general_variant_map = {}
    package_variant_map = {}
    dependency_variant_map = {}
    virtual_package = None
    virtual_dependency = False
    virtual_dependencies = {}
    concrete_package_expected = False
    dependency = False
    variant_map = general_variant_map
    for token in tokens_from_str:
        if token.kind == TokenType.DEPENDENCY:
            dependency = True
            continue
        if token.kind == TokenType.START_EDGE_PROPERTIES:
            virtual_dependency = True
            continue
        if token.kind == TokenType.END_EDGE_PROPERTIES:
            virtual_dependency = False
            concrete_package_expected = True
            continue
        if token.kind == TokenType.UNQUALIFIED_PACKAGE_NAME:
            if concrete_package_expected:
                virtual_dependencies.setdefault(virtual_package, []).append(token.value)
                virtual_package = None
                concrete_package_expected = False
            else:
                parent_map = dependency_variant_map if dependency else package_variant_map
                variant_map = parent_map.setdefault(token.value, dict())
            continue

        name, variant_pair = handle_variant(token)
        if virtual_dependency:
            virtual_package = variant_pair["value"]
        else:
            variant_map[name] = variant_pair

    # Compiler
    if "compiler" in general_variant_map:
        project_cfg["compiler"] = general_variant_map.pop("compiler")
    elif "compiler" not in project_cfg:
        tty.warn("No compiler spec specified in the variants list " +
                 gray("(using environment default)"))
        project_cfg["compiler"] = None

    # CXX standard
    if "cxxstd" in general_variant_map:
        cxxstd_variant = general_variant_map.pop("cxxstd")
        project_cfg["cxxstd"] = cxxstd_variant
    elif "cxxstd" not in project_cfg:
        project_cfg["cxxstd"] = _DEFAULT_CXXSTD

    # Generator
    if "generator" in general_variant_map:
        generator_variant = general_variant_map.pop("generator")
        project_cfg["generator"] = generator_variant
    elif "generator" not in project_cfg:
        project_cfg["generator"] = _DEFAULT_GENERATOR

    if variants:
        project_cfg["variants"] = " ".join(variants)

    packages_to_develop = spack_packages(project_cfg["source"])
    cxxstd = project_cfg["cxxstd"]
    generator = project_cfg["generator"]
    packages = project_cfg.get("packages", {})

    # We need to make sure that the packages cached in the configuration file still exist
    packages = {key: value for key, value in packages.items() if key in packages_to_develop}

    for p, pkg in packages_to_develop.items():
        # Start with existing requirements
        existing_pkg_requirements = packages.get(p, {}).get("require", [])
        existing_pkg_requirements_str = " ".join(existing_pkg_requirements)
        pkg_requirements = {}
        for token in SpecParser(existing_pkg_requirements_str).tokens():
            name, variant = handle_variant(token)
            pkg_requirements[name] = variant["variant"]

        # Check to see if packages support a 'cxxstd' variant
        pkg_requirements["version"] = _DEVELOP_VARIANT["variant"]
        if compiler := project_cfg["compiler"]:
            pkg_requirements["compiler"] = compiler["variant"]
        maybe_has_variant = getattr(pkg, "has_variant", lambda _: False)
        if maybe_has_variant("cxxstd") or "cxxstd" in pkg.variants:
            pkg_requirements["cxxstd"] = cxxstd["variant"]
        if maybe_has_variant("generator") or "generator" in pkg.variants:
            pkg_requirements["generator"] = generator["variant"]

        # Go through remaining general variants
        for name, value in general_variant_map.items():
            if not maybe_has_variant(name) and name not in pkg.variants:
                continue

            pkg_requirements[name] = value["variant"]

        only_variants = {k: v["variant"] for k, v in package_variant_map.get(p, {}).items()}
        pkg_requirements.update(only_variants)

        packages[p] = dict(require=ordered_requirement_list(pkg_requirements))

    dependency_requirements = project_cfg.get("dependencies", {})
    for name, requirements in dependency_variant_map.items():
        only_variants = [r["variant"] for r in requirements]
        dependency_requirements[name] = dict(require=ordered_requirement_list(only_variants))

    # Handle virtual dependencies
    if virtual_dependencies:
        dependency_requirements["all"] = dict(providers=virtual_dependencies)

    project_cfg["packages"] = packages
    project_cfg["dependencies"] = dependency_requirements
    return project_cfg


def project_config_from_args(args):
    project = ruamel.yaml.comments.CommentedMap()
    project["name"] = args.name
    project["envs"] = args.env

    top_path = Path(args.top)
    srcs_path = Path(args.srcs) if args.srcs else top_path / "srcs"

    directories = prepare_project_directories(top_path, srcs_path)
    project.update(directories)
    return handle_variants(project, args.variants)


def mpd_project_exists(project_name):
    config_file = mpd_config_file()
    config = None
    if config_file.exists():
        with open(config_file, "r") as f:
            config = syaml.load(f)

    if config is None:
        return False

    projects = config.get("projects")
    if projects is None:
        return False

    return project_name in projects


def update(project_config, status=None, installed_at=None):
    config_file = mpd_config_file()
    config = None
    if config_file.exists():
        with open(config_file, "r") as f:
            config = syaml.load(f)

    if config is None:
        config = ruamel.yaml.comments.CommentedMap()
        config["projects"] = ruamel.yaml.comments.CommentedMap()

    yaml_project_config = ruamel.yaml.comments.CommentedMap()
    yaml_project_config.update(project_config)
    if status:
        yaml_project_config.update(status=status)
    if installed_at:
        yaml_project_config.update(installed=installed_at)
    config["projects"][project_config["name"]] = yaml_project_config

    # Update config file
    with NamedTemporaryFile() as f:
        syaml.dump(config, stream=f)
        shutil.copy(f.name, config_file)


def refresh(project_name, new_variants):
    config_file = mpd_config_file()
    if config_file.exists():
        with open(config_file, "r") as f:
            config = syaml.load(f)

    # Update packages field
    assert config is not None
    assert project_name is not None
    project_cfg = project_config(project_name, config)

    top_path = Path(project_cfg["top"])
    srcs_path = Path(project_cfg["source"])

    prepare_project_directories(top_path, srcs_path)
    config["projects"][project_name] = handle_variants(project_cfg, new_variants)
    with NamedTemporaryFile() as f:
        syaml.dump(config, stream=f)
        shutil.copy(f.name, config_file)

    # Return configuration for this project
    return config["projects"][project_name]


def rm_config(project_name):
    config_file = mpd_config_file()
    if config_file.exists():
        with open(config_file, "r") as f:
            config = syaml.load(f)

    assert config is not None
    assert project_name is not None

    # Remove project entry
    del config["projects"][project_name]
    with NamedTemporaryFile() as f:
        syaml.dump(config, stream=f)
        shutil.copy(f.name, config_file)


def project_config(name, config=None, missing_ok=False):
    if config is None:
        config_file = mpd_config_file()
        if config_file.exists():
            with open(config_file, "r") as f:
                config = syaml.load(f)

    if config is None:
        if missing_ok:
            return None
        print()
        tty.die("Missing MPD configuration.  Please contact scisoft-team@fnal.gov\n")

    projects = config.get("projects")
    if name not in projects:
        if missing_ok:
            return None
        print()
        tty.die(
            f"Project '{name}' not supported by MPD configuration."
            " Please contact scisoft-team@fnal.gov\n"
        )

    return projects[name]


def update_cache():
    # Update environment status in user configuration
    config = mpd_config()
    if not config:
        return

    projects = config.get("projects")
    if not projects:
        return

    adjusted = False
    for name, proj_config in projects.items():
        if "status" in proj_config and not ev.is_env_dir(proj_config["local"]):
            del proj_config["status"]
            adjusted = True
        if "installed" in proj_config and not ev.exists(name):
            del proj_config["installed"]
            adjusted = True

    if adjusted:
        with NamedTemporaryFile() as f:
            syaml.dump(config, stream=f)
            shutil.copy(f.name, mpd_config_file())

    # Remove stale selected project tokens
    for sp in selected_projects_dir().iterdir():
        if not _process_exists(int(sp.name)):
            sp.unlink()
            continue
        selected_prj = sp.read_text()
        if selected_prj not in projects:
            sp.unlink()

    # Implicitly select project if environment is active
    active_env = ev.active_environment()
    if not active_env:
        return

    for name, config in projects.items():
        if active_env.path in config["local"]:
            selected_project_token().write_text(name)


def selected_project(missing_ok=True):
    token = selected_project_token()
    if token and token.exists():
        return token.read_text()

    if missing_ok:
        return None

    print()
    tty.die(f"Active MPD project required to invoke '{spack_cmd_line()}'\n")


def selected_project_config():
    return project_config(selected_project())


def print_config_info(config):
    print(f"\nUsing {cyan('build')} area: {config['build']}")
    print(f"Using {cyan('local')} area: {config['local']}")
    print(f"Using {cyan('sources')} area: {config['source']}\n")
    packages = config["packages"]
    if not packages:
        return

    print("  Will develop:")
    for pkg, variants in packages.items():
        requirements = " ".join(variants["require"])
        print(f"    - {magenta(pkg)}{gray(requirements)}")

    dependencies = config["dependencies"]
    if not dependencies:
        return

    print("\n  Subject to the constraints:")
    for pkg, variants in dependencies.items():
        # Handle virtual dependencies
        if pkg == "all":
            for virtual, concretes in variants["providers"].items():
                for c in concretes:
                    line = f"^[virtuals={virtual}] {c}"
                    print(f"    - {yellow(line)}")
            continue
        requirements = " ".join(variants["require"])
        print(f"    - {yellow(pkg)}{gray(requirements)}")


def select(name):
    session_id = os.getsid(os.getpid())
    selected = selected_projects_dir()
    selected.mkdir(exist_ok=True)
    (selected / f"{session_id}").write_text(name)
