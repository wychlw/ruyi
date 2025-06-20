import argparse

import ruyi
from ..config import GlobalConfig
from ..version import COPYRIGHT_NOTICE, MPL_REDIST_NOTICE, RUYI_SEMVER
from .cmd import RootCommand
from .completion import SelfArgumentParser


class VersionCommand(
    RootCommand,
    cmd="version",
    help="Print version information",
):
    @classmethod
    def configure_args(cls, gc: GlobalConfig, p: SelfArgumentParser) -> None:
        pass

    @classmethod
    def main(cls, cfg: GlobalConfig, args: argparse.Namespace) -> int:
        return cli_version(cfg, args)


def cli_version(cfg: GlobalConfig, args: argparse.Namespace) -> int:
    from ..ruyipkg.host import get_native_host

    print(f"Ruyi {RUYI_SEMVER}\n\nRunning on {get_native_host()}.")

    if cfg.is_installation_externally_managed:
        print("This Ruyi installation is externally managed.")

    print()

    cfg.logger.stdout(COPYRIGHT_NOTICE)

    # Output the MPL notice only when we actually bundle and depend on the
    # MPL component(s), which right now is only certifi. Keep the condition
    # synced with __main__.py.
    if hasattr(ruyi, "__compiled__") and ruyi.__compiled__.standalone:
        cfg.logger.stdout(MPL_REDIST_NOTICE)

    return 0
