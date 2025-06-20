import argparse
from os import PathLike
import pathlib
from typing import Any

from ...cli.cmd import RootCommand
from ...cli.completion import SelfArgumentParser
from ...config import GlobalConfig
from ...log import humanize_list
from ...ruyipkg.atom import Atom
from ...ruyipkg.host import get_native_host
from . import ConfiguredTargetTuple
from .provision import render_template_str, VenvMaker


class VenvCommand(
    RootCommand,
    cmd="venv",
    help="Generate a virtual environment adapted to the chosen toolchain and profile",
):
    @classmethod
    def configure_args(cls, gc: GlobalConfig, p: SelfArgumentParser) -> None:
        p.add_argument("profile", type=str, help="Profile to use for the environment")
        p.add_argument("dest", type=str, help="Path to the new virtual environment")
        p.add_argument(
            "--name",
            "-n",
            type=str,
            default=None,
            help="Override the venv's name",
        )
        p.add_argument(
            "--toolchain",
            "-t",
            type=str,
            action="append",
            help="Specifier(s) (atoms) of the toolchain package(s) to use",
        )
        p.add_argument(
            "--emulator",
            "-e",
            type=str,
            help="Specifier (atom) of the emulator package to use",
        )
        p.add_argument(
            "--with-sysroot",
            action="store_true",
            dest="with_sysroot",
            default=True,
            help="Provision a fresh sysroot inside the new virtual environment (default)",
        )
        p.add_argument(
            "--without-sysroot",
            action="store_false",
            dest="with_sysroot",
            help="Do not include a sysroot inside the new virtual environment",
        )
        p.add_argument(
            "--sysroot-from",
            type=str,
            help="Specifier (atom) of the sysroot package to use, in favor of the toolchain-included one if applicable",
        )
        p.add_argument(
            "--extra-commands-from",
            type=str,
            action="append",
            help="Specifier(s) (atoms) of extra package(s) to add commands to the new virtual environment",
        )

    @classmethod
    def main(cls, cfg: GlobalConfig, args: argparse.Namespace) -> int:
        return cli_venv(cfg, args)


def cli_venv(config: GlobalConfig, args: argparse.Namespace) -> int:
    logger = config.logger
    profile_name: str = args.profile
    dest = pathlib.Path(args.dest)
    with_sysroot: bool = args.with_sysroot
    override_name: str | None = args.name
    tc_atoms_str: list[str] | None = args.toolchain
    emu_atom_str: str | None = args.emulator
    sysroot_atom_str: str | None = args.sysroot_from
    extra_cmd_atoms_str: list[str] | None = args.extra_commands_from
    host = str(get_native_host())

    # TODO: support omitting this if user only has one toolchain installed
    # this should come after implementation of local state cache
    if tc_atoms_str is None:
        logger.F(
            "You have to specify at least one toolchain atom for now, e.g. [yellow]`-t gnu-plct`[/]"
        )
        return 1

    mr = config.repo

    profile = mr.get_profile(profile_name)
    if profile is None:
        logger.F(f"profile '{profile_name}' not found")
        return 1

    target_arch = ""
    seen_target_tuples: set[str] = set()
    targets: list[ConfiguredTargetTuple] = []
    warn_differing_target_arch = False

    for tc_atom_str in tc_atoms_str:
        tc_atom = Atom.parse(tc_atom_str)
        tc_pm = tc_atom.match_in_repo(mr, config.include_prereleases)
        if tc_pm is None:
            logger.F(f"cannot match a toolchain package with [yellow]{tc_atom_str}[/]")
            return 1

        if tc_pm.toolchain_metadata is None:
            logger.F(f"the package [yellow]{tc_atom_str}[/] is not a toolchain")
            return 1

        if not tc_pm.toolchain_metadata.satisfies_quirk_set(profile.need_quirks):
            logger.F(
                f"the package [yellow]{tc_atom_str}[/] does not support all necessary features for the profile [yellow]{profile_name}[/]"
            )
            logger.I(
                f"quirks needed by profile:   {humanize_list(profile.need_quirks, item_color='cyan')}"
            )
            logger.I(
                f"quirks provided by package: {humanize_list(tc_pm.toolchain_metadata.quirks, item_color='yellow')}"
            )
            return 1

        target_tuple = tc_pm.toolchain_metadata.target
        if target_tuple in seen_target_tuples:
            logger.F(
                f"the target tuple [yellow]{target_tuple}[/] is already covered by one of the requested toolchains"
            )
            logger.I(
                "for now, only toolchains with differing target tuples can co-exist in one virtual environment"
            )
            return 1

        toolchain_root = config.lookup_binary_install_dir(
            host,
            tc_pm.name_for_installation,
        )
        if toolchain_root is None:
            logger.F("cannot find the installed directory for the toolchain")
            return 1

        tc_sysroot_dir: PathLike[Any] | None = None
        gcc_install_dir: PathLike[Any] | None = None
        if with_sysroot:
            if tc_sysroot_relpath := tc_pm.toolchain_metadata.included_sysroot:
                tc_sysroot_dir = pathlib.Path(toolchain_root) / tc_sysroot_relpath
            else:
                if sysroot_atom_str is None:
                    logger.F(
                        "sysroot is requested but the toolchain package does not include one, and [yellow]--sysroot-from[/] is not given"
                    )
                    return 1

                # try extracting from the sysroot package
                # for now only GCC toolchain packages can provide sysroots, so this is
                # okay
                gcc_pkg_atom = Atom.parse(sysroot_atom_str)
                gcc_pkg_pm = gcc_pkg_atom.match_in_repo(mr, config.include_prereleases)
                if gcc_pkg_pm is None:
                    logger.F(
                        f"cannot match a toolchain package with [yellow]{sysroot_atom_str}[/]"
                    )
                    return 1

                if gcc_pkg_pm.toolchain_metadata is None:
                    logger.F(
                        f"the package [yellow]{sysroot_atom_str}[/] is not a toolchain"
                    )
                    return 1

                gcc_pkg_root = config.lookup_binary_install_dir(
                    host,
                    gcc_pkg_pm.name_for_installation,
                )
                if gcc_pkg_root is None:
                    logger.F(
                        "cannot find the installed directory for the sysroot package"
                    )
                    return 1

                tc_sysroot_relpath = gcc_pkg_pm.toolchain_metadata.included_sysroot
                if tc_sysroot_relpath is None:
                    logger.F(
                        f"sysroot is requested but the package [yellow]{sysroot_atom_str}[/] does not contain one"
                    )
                    return 1

                tc_sysroot_dir = pathlib.Path(gcc_pkg_root) / tc_sysroot_relpath

                # also figure the GCC include/libs path out for Clang to be able to
                # locate them
                gcc_install_dir = find_gcc_install_dir(
                    gcc_pkg_root,
                    # we should use the GCC-providing package's target tuple as that's
                    # not guaranteed to be the same as llvm's
                    gcc_pkg_pm.toolchain_metadata.target,
                )

                # for now, require this directory to be present (or clang would barely work)
                if gcc_install_dir is None:
                    logger.F(
                        "cannot find a GCC include & lib directory in the sysroot package"
                    )
                    return 1

        # derive flags for (the quirks of) this toolchain
        tc_flags = profile.get_common_flags(tc_pm.toolchain_metadata.quirks)

        # record the target tuple info to configure in the venv
        configured_target: ConfiguredTargetTuple = {
            "target": target_tuple,
            "toolchain_root": toolchain_root,
            "toolchain_sysroot": tc_sysroot_dir,
            "toolchain_flags": tc_flags,
            # assume clang is preferred if package contains clang
            # this is mostly true given most packages don't contain both
            "cc_flavor": "clang" if tc_pm.toolchain_metadata.has_clang else "gcc",
            # same for binutils provider flavor
            "binutils_flavor": (
                "llvm" if tc_pm.toolchain_metadata.has_llvm else "binutils"
            ),
            "gcc_install_dir": gcc_install_dir,
        }
        logger.D(f"configuration for {target_tuple}: {configured_target}")
        targets.append(configured_target)
        seen_target_tuples.add(target_tuple)

        # record the target architecture for use in emulator package matching
        if not target_arch:
            target_arch = tc_pm.toolchain_metadata.target_arch
        elif target_arch != tc_pm.toolchain_metadata.target_arch:
            # first one wins
            warn_differing_target_arch = True

    if warn_differing_target_arch:
        logger.W("multiple toolchains specified with differing target architecture")
        logger.I(
            f"using the target architecture of the first toolchain: [yellow]{target_arch}[/]"
        )

    # Now handle the emulator.
    emu_progs = None
    emu_root: PathLike[Any] | None = None
    if emu_atom_str:
        emu_atom = Atom.parse(emu_atom_str)
        emu_pm = emu_atom.match_in_repo(mr, config.include_prereleases)
        if emu_pm is None:
            logger.F(f"cannot match an emulator package with [yellow]{emu_atom_str}[/]")
            return 1

        if emu_pm.emulator_metadata is None:
            logger.F(f"the package [yellow]{emu_atom_str}[/] is not an emulator")
            return 1

        emu_progs = list(emu_pm.emulator_metadata.list_for_arch(target_arch))
        if not emu_progs:
            logger.F(
                f"the emulator package [yellow]{emu_atom_str}[/] does not support the target architecture [yellow]{target_arch}[/]"
            )
            return 1

        for prog in emu_progs:
            if not profile.check_emulator_flavor(
                prog.flavor,
                emu_pm.emulator_metadata.quirks,
            ):
                logger.F(
                    f"the package [yellow]{emu_atom_str}[/] does not support all necessary features for the profile [yellow]{profile_name}[/]"
                )
                logger.I(
                    f"quirks needed by profile:   {humanize_list(profile.get_needed_emulator_pkg_flavors(prog.flavor), item_color='cyan')}"
                )
                logger.I(
                    f"quirks provided by package: {humanize_list(emu_pm.emulator_metadata.quirks or [], item_color='yellow')}"
                )
                return 1

        emu_root = config.lookup_binary_install_dir(
            host,
            emu_pm.name_for_installation,
        )
        if emu_root is None:
            logger.F("cannot find the installed directory for the emulator")
            return 1

    # Now resolve extra commands to provide in the venv.
    extra_cmds: dict[str, str] = {}
    if extra_cmd_atoms_str:
        for extra_cmd_atom_str in extra_cmd_atoms_str:
            extra_cmd_atom = Atom.parse(extra_cmd_atom_str)
            extra_cmd_pm = extra_cmd_atom.match_in_repo(
                mr,
                config.include_prereleases,
            )
            if extra_cmd_pm is None:
                logger.F(
                    f"cannot match an extra command package with [yellow]{extra_cmd_atom_str}[/]"
                )
                return 1

            extra_cmd_bm = extra_cmd_pm.binary_metadata
            if not extra_cmd_bm:
                logger.F(
                    f"the package [yellow]{extra_cmd_atom_str}[/] is not a binary-providing package"
                )
                return 1

            extra_cmds_decl = extra_cmd_bm.get_commands_for_host(host)
            if not extra_cmds_decl:
                logger.W(
                    f"the package [yellow]{extra_cmd_atom_str}[/] does not provide any command for host [yellow]{host}[/], ignoring"
                )
                continue

            cmd_root = config.lookup_binary_install_dir(
                host,
                extra_cmd_pm.name_for_installation,
            )
            if cmd_root is None:
                logger.F(
                    f"cannot find the installed directory for the package [yellow]{extra_cmd_pm.name_for_installation}[/]"
                )
                return 1
            cmd_root = pathlib.Path(cmd_root)

            for cmd, cmd_rel_path in extra_cmds_decl.items():
                # resolve the command path
                cmd_path = (cmd_root / cmd_rel_path).resolve()
                if not cmd_path.is_relative_to(cmd_root):
                    # we don't allow commands to resolve outside of the
                    # providing package's install root
                    logger.F(
                        "internal error: resolved command path is outside of the providing package"
                    )
                    return 1

                # add the command to the list
                extra_cmds[cmd] = str(cmd_path)

    if override_name is not None:
        logger.I(
            f"Creating a Ruyi virtual environment [cyan]'{override_name}'[/] at [green]{dest}[/]..."
        )
    else:
        logger.I(f"Creating a Ruyi virtual environment at [green]{dest}[/]...")

    maker = VenvMaker(
        config,
        profile,
        targets,
        dest.resolve(),
        emu_progs,
        emu_root,
        extra_cmds,
        override_name,
    )
    maker.provision()

    logger.I(
        render_template_str(
            "prompt.venv-created.txt",
            {
                "sysroot": maker.sysroot_destdir(None),
            },
        )
    )

    return 0


def find_gcc_install_dir(
    install_root: PathLike[Any],
    target_tuple: str,
) -> PathLike[Any] | None:
    # check $PREFIX/lib/gcc/$TARGET/*
    search_root = pathlib.Path(install_root) / "lib" / "gcc" / target_tuple
    try:
        for p in search_root.iterdir():
            # only want the first one (should be the only one)
            return p
    except FileNotFoundError:
        pass

    # nothing?
    return None
