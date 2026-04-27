"""Command line interface for html-xpath."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


EXTRACT_SCRIPT = """
({ includeXPaths, excludeXPaths }) => {
  const resultType = XPathResult.ORDERED_NODE_SNAPSHOT_TYPE;

  function xpathNodes(xpath, contextNode = document) {
    const snapshot = document.evaluate(xpath, contextNode, null, resultType, null);
    const nodes = [];
    for (let i = 0; i < snapshot.snapshotLength; i += 1) {
      const node = snapshot.snapshotItem(i);
      if (node && node.nodeType === Node.ELEMENT_NODE) {
        nodes.push(node);
      }
    }
    return nodes;
  }

  function nodePath(root, target) {
    const path = [];
    let current = target;

    while (current && current !== root) {
      const parent = current.parentNode;
      if (!parent) {
        return null;
      }
      path.push(Array.prototype.indexOf.call(parent.childNodes, current));
      current = parent;
    }

    return current === root ? path.reverse() : null;
  }

  function nodeAtPath(root, path) {
    let current = root;
    for (const index of path) {
      if (!current || !current.childNodes || index >= current.childNodes.length) {
        return null;
      }
      current = current.childNodes[index];
    }
    return current;
  }

  function removalOrder(a, b) {
    const minLength = Math.min(a.length, b.length);
    for (let i = 0; i < minLength; i += 1) {
      if (a[i] !== b[i]) {
        return b[i] - a[i];
      }
    }
    return b.length - a.length;
  }

  const includeNodes = includeXPaths.flatMap((xpath) => xpathNodes(xpath));
  const excludedNodes = excludeXPaths.flatMap((xpath) => xpathNodes(xpath));
  const excludedSet = new Set(excludedNodes);
  const fragments = [];

  for (const root of includeNodes) {
    if (excludedSet.has(root) || excludedNodes.some((node) => node.contains(root))) {
      continue;
    }

    const clone = root.cloneNode(true);
    const paths = excludedNodes
      .filter((node) => root.contains(node))
      .map((node) => nodePath(root, node))
      .filter((path) => path !== null)
      .sort(removalOrder);

    for (const path of paths) {
      const node = nodeAtPath(clone, path);
      if (node && node.parentNode) {
        node.parentNode.removeChild(node);
      }
    }

    fragments.push(clone.outerHTML);
  }

  return fragments;
}
"""


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


def extract_fragments(args: argparse.Namespace) -> list[str]:
    wait_xpath = args.wait_for_xpath or args.include_xpaths[0]

    with sync_playwright() as playwright:
        browser_type = getattr(playwright, args.browser)
        browser = browser_type.launch(headless=not args.headed)
        try:
            page = browser.new_page()
            page.goto(args.url, wait_until=args.wait_until, timeout=args.timeout)
            page.locator(f"xpath={wait_xpath}").first.wait_for(timeout=args.timeout)
            fragments: Any = page.evaluate(
                EXTRACT_SCRIPT,
                {
                    "includeXPaths": args.include_xpaths,
                    "excludeXPaths": args.exclude_xpath,
                },
            )
        finally:
            browser.close()

    if not isinstance(fragments, list) or not all(
        isinstance(fragment, str) for fragment in fragments
    ):
        raise RuntimeError("unexpected extraction result from browser")

    return fragments


def main() -> int:
    args = parse_args()

    try:
        fragments = extract_fragments(args)
    except PlaywrightTimeoutError as exc:
        print(f"html-xpath: timed out: {exc}", file=sys.stderr)
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
