import argparse
from typing import TYPE_CHECKING

from ..cli.cmd import RootCommand
from ..cli.completion import ArgumentParser

if TYPE_CHECKING:
    from ..config import GlobalConfig


class NewsCommand(
    RootCommand,
    cmd="news",
    has_subcommands=True,
    help="List and read news items from configured repository",
):
    @classmethod
    def configure_args(cls, gc: "GlobalConfig", p: ArgumentParser) -> None:
        pass


class NewsListCommand(
    NewsCommand,
    cmd="list",
    help="List news items",
):
    @classmethod
    def configure_args(cls, gc: "GlobalConfig", p: ArgumentParser) -> None:
        p.add_argument(
            "--new",
            action="store_true",
            help="List unread news items only",
        )

    @classmethod
    def main(cls, cfg: "GlobalConfig", args: argparse.Namespace) -> int:
        from .news import do_news_list

        only_unread: bool = args.new
        return do_news_list(
            cfg,
            only_unread,
        )


class NewsReadCommand(
    NewsCommand,
    cmd="read",
    help="Read news items",
    description="Outputs news item(s) to the console and mark as already read. Defaults to reading all unread items if no item is specified.",
):
    @classmethod
    def configure_args(cls, gc: "GlobalConfig", p: ArgumentParser) -> None:
        p.add_argument(
            "--quiet",
            "-q",
            action="store_true",
            help="Do not output anything and only mark as read",
        )
        p.add_argument(
            "item",
            type=str,
            nargs="*",
            help="Ordinal or ID of the news item(s) to read",
        )

    @classmethod
    def main(cls, cfg: "GlobalConfig", args: argparse.Namespace) -> int:
        from .news import do_news_read

        quiet: bool = args.quiet
        items_strs: list[str] = args.item

        return do_news_read(
            cfg,
            quiet,
            items_strs,
        )
