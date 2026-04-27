"""Command line interface for html-xpath."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from collections.abc import Iterable

from lxml import etree, html
from lxml.html import HtmlElement
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid integer: {value}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch rendered HTML elements from a URL using XPath selectors.",
    )
    parser.add_argument("url", help="URL to open")
    parser.add_argument(
        "xpath",
        nargs="*",
        help="XPath to extract. Can be passed positionally or with --xpath.",
    )
    parser.add_argument(
        "-x",
        "--xpath",
        dest="xpath_options",
        action="append",
        default=[],
        help="XPath to extract. Repeatable.",
    )
    parser.add_argument(
        "-e",
        "--exclude-xpath",
        action="append",
        default=[],
        help="XPath to remove from extracted elements. Repeatable.",
    )
    parser.add_argument(
        "--wait-until",
        choices=("commit", "domcontentloaded", "load", "networkidle"),
        default="networkidle",
        help="Navigation readiness state. Default: networkidle.",
    )
    parser.add_argument(
        "--wait-for-xpath",
        help="XPath to wait for before extraction. Defaults to the first extraction XPath.",
    )
    parser.add_argument(
        "--timeout",
        type=positive_int,
        default=30_000,
        help="Timeout in milliseconds. Default: 30000.",
    )
    parser.add_argument(
        "--browser",
        choices=("chromium", "firefox", "webkit"),
        default="chromium",
        help="Browser engine. Default: chromium.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Run with a visible browser window.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a JSON array instead of newline-separated HTML fragments.",
    )
    parser.add_argument(
        "--separator",
        default="\n",
        help="Separator for non-JSON output. Default: newline.",
    )
    args = parser.parse_args()
    args.include_xpaths = [*args.xpath_options, *args.xpath]

    if not args.include_xpaths:
        parser.error("at least one XPath is required")

    return args


def element_nodes(nodes: Iterable[object]) -> list[HtmlElement]:
    return [node for node in nodes if isinstance(node, HtmlElement)]


def parse_html(content: str) -> HtmlElement:
    return html.fromstring(content)


def xpath_elements(document: HtmlElement, xpath: str) -> list[HtmlElement]:
    try:
        return element_nodes(document.xpath(xpath))
    except etree.XPathError as exc:
        raise ValueError(f"invalid XPath {xpath!r}: {exc}") from exc


def contains(root: HtmlElement, node: HtmlElement) -> bool:
    current: HtmlElement | None = node
    while current is not None:
        if current is root:
            return True
        current = current.getparent()
    return False


def path_from_root(root: HtmlElement, node: HtmlElement) -> tuple[int, ...] | None:
    path: list[int] = []
    current: HtmlElement | None = node

    while current is not None and current is not root:
        parent = current.getparent()
        if parent is None:
            return None
        path.append(parent.index(current))
        current = parent

    if current is not root:
        return None

    return tuple(reversed(path))


def node_at_path(root: HtmlElement, path: tuple[int, ...]) -> HtmlElement | None:
    current = root
    for index in path:
        if index >= len(current):
            return None
        current = current[index]
    return current


def removal_order(path: tuple[int, ...]) -> tuple[tuple[int, ...], int]:
    return tuple(-index for index in path), -len(path)


def remove_excluded_descendants(
    root: HtmlElement,
    excluded_nodes: list[HtmlElement],
) -> HtmlElement:
    clone = copy.deepcopy(root)
    paths = [
        path
        for node in excluded_nodes
        if node is not root and contains(root, node)
        for path in [path_from_root(root, node)]
        if path is not None
    ]

    for path in sorted(paths, key=removal_order):
        node = node_at_path(clone, path)
        if node is not None and node.getparent() is not None:
            node.getparent().remove(node)

    return clone


def fragments_from_html(
    content: str,
    include_xpaths: list[str],
    exclude_xpaths: list[str],
) -> list[str]:
    document = parse_html(content)
    include_nodes = [
        node
        for xpath in include_xpaths
        for node in xpath_elements(document, xpath)
    ]
    excluded_nodes = [
        node
        for xpath in exclude_xpaths
        for node in xpath_elements(document, xpath)
    ]

    fragments = []
    for root in include_nodes:
        if any(node is root or contains(node, root) for node in excluded_nodes):
            continue

        clone = remove_excluded_descendants(root, excluded_nodes)
        fragments.append(
            html.tostring(clone, encoding="unicode", method="html", with_tail=False)
        )

    return fragments


def wait_for_xpath_in_html(page: Page, xpath: str, timeout: int) -> str:
    deadline = time.monotonic() + timeout / 1000
    last_error: Exception | None = None

    while True:
        content = page.content()
        try:
            if xpath_elements(parse_html(content), xpath):
                return content
        except ValueError as exc:
            raise exc
        except Exception as exc:
            last_error = exc

        if time.monotonic() >= deadline:
            detail = f": {last_error}" if last_error else ""
            raise TimeoutError(f"timed out waiting for XPath {xpath!r}{detail}")

        time.sleep(0.1)


def fetch_rendered_html(args: argparse.Namespace) -> str:
    wait_xpath = args.wait_for_xpath or args.include_xpaths[0]

    with sync_playwright() as playwright:
        browser_type = getattr(playwright, args.browser)
        browser = browser_type.launch(headless=not args.headed)
        try:
            page = browser.new_page()
            page.goto(args.url, wait_until=args.wait_until, timeout=args.timeout)
            content = wait_for_xpath_in_html(page, wait_xpath, args.timeout)
        finally:
            browser.close()

    return content


def extract_fragments(args: argparse.Namespace) -> list[str]:
    content = fetch_rendered_html(args)
    return fragments_from_html(content, args.include_xpaths, args.exclude_xpath)


def main() -> int:
    args = parse_args()

    try:
        fragments = extract_fragments(args)
    except PlaywrightTimeoutError as exc:
        print(f"html-xpath: timed out: {exc}", file=sys.stderr)
        return 2
    except TimeoutError as exc:
        print(f"html-xpath: timed out: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"html-xpath: {exc}", file=sys.stderr)
        return 2
    except PlaywrightError as exc:
        print(f"html-xpath: playwright error: {exc}", file=sys.stderr)
        print(
            "html-xpath: if browsers are not installed, run: "
            "uv run --with playwright playwright install chromium",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(f"html-xpath: error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(fragments, ensure_ascii=False, indent=2))
    elif fragments:
        print(args.separator.join(fragments))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
