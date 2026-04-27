from __future__ import annotations

import argparse
import sys

import pytest
from lxml import html
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from html_xpath import cli


def test_positive_int_accepts_positive_values() -> None:
    assert cli.positive_int("123") == 123


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_positive_int_rejects_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        cli.positive_int(value)


def test_parse_args_combines_option_and_positional_xpaths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "html-xpath",
            "https://example.test",
            "--xpath",
            "//main",
            "//footer",
            "--exclude-xpath",
            "//nav",
            "--timeout",
            "100",
        ],
    )

    args = cli.parse_args()

    assert args.include_xpaths == ["//main", "//footer"]
    assert args.exclude_xpath == ["//nav"]
    assert args.timeout == 100


def test_parse_args_requires_xpath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["html-xpath", "https://example.test"])

    with pytest.raises(SystemExit):
        cli.parse_args()


def test_xpath_elements_returns_only_elements() -> None:
    document = cli.parse_html("<main><a href='/x'>Link</a><p>Text</p></main>")

    assert [
        node.tag for node in cli.xpath_elements(document, "//a | //p | //@href")
    ] == [
        "a",
        "p",
    ]


def test_xpath_elements_wraps_invalid_xpath() -> None:
    document = cli.parse_html("<main></main>")

    with pytest.raises(ValueError, match="invalid XPath"):
        cli.xpath_elements(document, "//* [")


def test_contains_handles_self_ancestor_and_unrelated_nodes() -> None:
    document = cli.parse_html("<main><section><p>Text</p></section></main>")
    main = cli.xpath_elements(document, "//main")[0]
    section = cli.xpath_elements(document, "//section")[0]
    paragraph = cli.xpath_elements(document, "//p")[0]
    other = cli.parse_html("<aside></aside>")

    assert cli.contains(main, main)
    assert cli.contains(main, paragraph)
    assert cli.contains(section, paragraph)
    assert not cli.contains(paragraph, main)
    assert not cli.contains(main, other)


def test_path_helpers_cover_valid_invalid_and_same_node_paths() -> None:
    document = cli.parse_html(
        "<main><section><p>A</p></section><section><p>B</p></section></main>"
    )
    main = cli.xpath_elements(document, "//main")[0]
    second_paragraph = cli.xpath_elements(document, "//section[2]/p")[0]
    detached = cli.parse_html("<aside><p>Other</p></aside>")

    assert cli.path_from_root(main, main) == ()
    assert cli.path_from_root(main, second_paragraph) == (1, 0)
    assert cli.path_from_root(main, detached) is None
    assert cli.path_from_root(main, None) is None
    assert cli.node_at_path(main, (1, 0)).text == "B"
    assert cli.node_at_path(main, (9,)) is None


def test_remove_excluded_descendants_removes_siblings_without_index_shift() -> None:
    document = cli.parse_html(
        "<main><p>A</p><nav>Skip1</nav><p>B</p><aside>Skip2</aside><p>C</p></main>"
    )
    main = cli.xpath_elements(document, "//main")[0]
    excluded = cli.xpath_elements(document, "//nav | //aside")

    clone = cli.remove_excluded_descendants(main, excluded)

    assert (
        html.tostring(clone, encoding="unicode")
        == "<main><p>A</p><p>B</p><p>C</p></main>"
    )
    assert html.tostring(main, encoding="unicode") == (
        "<main><p>A</p><nav>Skip1</nav><p>B</p><aside>Skip2</aside><p>C</p></main>"
    )


def test_remove_excluded_descendants_ignores_root_and_external_nodes() -> None:
    document = cli.parse_html("<main><p>A</p></main>")
    main = cli.xpath_elements(document, "//main")[0]
    external = cli.parse_html("<aside></aside>")

    clone = cli.remove_excluded_descendants(main, [main, external])

    assert html.tostring(clone, encoding="unicode") == "<main><p>A</p></main>"


def test_remove_excluded_descendants_ignores_paths_that_no_longer_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = cli.parse_html("<main><p>A</p></main>")
    main = cli.xpath_elements(document, "//main")[0]
    paragraph = cli.xpath_elements(document, "//p")[0]
    detached = cli.parse_html("<span>Detached</span>")

    monkeypatch.setattr(cli, "node_at_path", lambda root, path: detached)

    clone = cli.remove_excluded_descendants(main, [paragraph])

    assert html.tostring(clone, encoding="unicode") == "<main><p>A</p></main>"


def test_fragments_from_html_extracts_multiple_fragments_and_excludes_children() -> (
    None
):
    fragments = cli.fragments_from_html(
        "<html><body><main><article><p>A</p><nav>Skip</nav></article></main>"
        "<footer>Foot</footer></body></html>",
        ["//article", "//footer"],
        ["//nav"],
    )

    assert fragments == ["<article><p>A</p></article>", "<footer>Foot</footer>"]


def test_fragments_from_html_skips_roots_inside_excluded_nodes() -> None:
    fragments = cli.fragments_from_html(
        "<main><section><p>Hidden</p></section><p>Visible</p></main>",
        ["//section", "//section/p", "//main/p"],
        ["//section"],
    )

    assert fragments == ["<p>Visible</p>"]


def test_wait_for_xpath_in_html_returns_when_xpath_appears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Page:
        def __init__(self) -> None:
            self.contents = iter(["<main></main>", "<main><p>Ready</p></main>"])

        def content(self) -> str:
            return next(self.contents)

    sleeps: list[float] = []
    monkeypatch.setattr(cli.time, "sleep", sleeps.append)

    assert (
        cli.wait_for_xpath_in_html(Page(), "//p", 1000) == "<main><p>Ready</p></main>"
    )
    assert sleeps == [0.1]


def test_wait_for_xpath_in_html_raises_invalid_xpath() -> None:
    class Page:
        def content(self) -> str:
            return "<main></main>"

    with pytest.raises(ValueError, match="invalid XPath"):
        cli.wait_for_xpath_in_html(Page(), "//* [", 1000)


def test_wait_for_xpath_in_html_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    class Page:
        def content(self) -> str:
            return "<main></main>"

    times = iter([0.0, 0.2])
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    with pytest.raises(TimeoutError, match="timed out waiting for XPath"):
        cli.wait_for_xpath_in_html(Page(), "//p", 100)


def test_wait_for_xpath_in_html_reports_parse_errors_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Page:
        def content(self) -> str:
            return "<main></main>"

    def raise_parse_error(content: str) -> object:
        raise RuntimeError("broken parser")

    times = iter([0.0, 0.2])
    monkeypatch.setattr(cli, "parse_html", raise_parse_error)
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    with pytest.raises(TimeoutError, match="broken parser"):
        cli.wait_for_xpath_in_html(Page(), "//p", 100)


def test_fetch_rendered_html_uses_playwright_and_closes_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, object]] = []

    class Browser:
        def new_page(self) -> object:
            events.append(("new_page", None))
            return Page()

        def close(self) -> None:
            events.append(("close", None))

    class Page:
        def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
            events.append(("goto", (url, wait_until, timeout)))

    class BrowserType:
        def launch(self, *, headless: bool) -> Browser:
            events.append(("launch", headless))
            return Browser()

    class Playwright:
        chromium = BrowserType()

    class Context:
        def __enter__(self) -> Playwright:
            return Playwright()

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            events.append(("exit", None))

    def fake_wait(page: object, xpath: str, timeout: int) -> str:
        events.append(("wait", (xpath, timeout)))
        return "<main></main>"

    def fake_sync_playwright() -> Context:
        return Context()

    args = argparse.Namespace(
        browser="chromium",
        headed=True,
        include_xpaths=["//main"],
        timeout=123,
        url="https://example.test",
        wait_for_xpath=None,
        wait_until="load",
    )
    monkeypatch.setattr(cli, "sync_playwright", fake_sync_playwright)
    monkeypatch.setattr(cli, "wait_for_xpath_in_html", fake_wait)

    assert cli.fetch_rendered_html(args) == "<main></main>"
    assert events == [
        ("launch", False),
        ("new_page", None),
        ("goto", ("https://example.test", "load", 123)),
        ("wait", ("//main", 123)),
        ("close", None),
        ("exit", None),
    ]


def test_fetch_rendered_html_closes_browser_when_wait_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class Browser:
        def new_page(self) -> object:
            return Page()

        def close(self) -> None:
            events.append("close")

    class Page:
        def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
            events.append("goto")

    class BrowserType:
        def launch(self, *, headless: bool) -> Browser:
            return Browser()

    class Playwright:
        firefox = BrowserType()

    class Context:
        def __enter__(self) -> Playwright:
            return Playwright()

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            events.append("exit")

    def fake_sync_playwright() -> Context:
        return Context()

    def fail_wait(page: object, xpath: str, timeout: int) -> str:
        raise TimeoutError("nope")

    args = argparse.Namespace(
        browser="firefox",
        headed=False,
        include_xpaths=["//main"],
        timeout=123,
        url="https://example.test",
        wait_for_xpath="//ready",
        wait_until="load",
    )
    monkeypatch.setattr(cli, "sync_playwright", fake_sync_playwright)
    monkeypatch.setattr(cli, "wait_for_xpath_in_html", fail_wait)

    with pytest.raises(TimeoutError):
        cli.fetch_rendered_html(args)

    assert events == ["goto", "close", "exit"]


def test_extract_fragments_fetches_html_then_parses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = argparse.Namespace(include_xpaths=["//p"], exclude_xpath=["//span"])
    monkeypatch.setattr(
        cli, "fetch_rendered_html", lambda args: "<p>A<span>B</span></p>"
    )

    assert cli.extract_fragments(args) == ["<p>A</p>"]


def test_main_prints_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(json=True, separator="\n")
    monkeypatch.setattr(cli, "parse_args", lambda: args)
    monkeypatch.setattr(cli, "extract_fragments", lambda args: ["<p>あ</p>"])

    assert cli.main() == 0
    assert capsys.readouterr().out == '[\n  "<p>あ</p>"\n]\n'


def test_main_prints_separator_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(json=False, separator="\n---\n")
    monkeypatch.setattr(cli, "parse_args", lambda: args)
    monkeypatch.setattr(cli, "extract_fragments", lambda args: ["<p>A</p>", "<p>B</p>"])

    assert cli.main() == 0
    assert capsys.readouterr().out == "<p>A</p>\n---\n<p>B</p>\n"


def test_main_prints_nothing_for_empty_non_json_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = argparse.Namespace(json=False, separator="\n")
    monkeypatch.setattr(cli, "parse_args", lambda: args)
    monkeypatch.setattr(cli, "extract_fragments", lambda args: [])

    assert cli.main() == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (PlaywrightTimeoutError("slow"), "html-xpath: timed out: slow"),
        (TimeoutError("missing"), "html-xpath: timed out: missing"),
        (ValueError("invalid XPath"), "html-xpath: invalid XPath"),
    ],
)
def test_main_handles_expected_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    exc: Exception,
    expected: str,
) -> None:
    monkeypatch.setattr(cli, "parse_args", lambda: argparse.Namespace())

    def fail(args: argparse.Namespace) -> list[str]:
        raise exc

    monkeypatch.setattr(cli, "extract_fragments", fail)

    assert cli.main() == 2
    assert expected in capsys.readouterr().err


def test_main_handles_playwright_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "parse_args", lambda: argparse.Namespace())

    def fail(args: argparse.Namespace) -> list[str]:
        raise PlaywrightError("browser missing")

    monkeypatch.setattr(cli, "extract_fragments", fail)

    assert cli.main() == 2
    err = capsys.readouterr().err
    assert "html-xpath: playwright error: browser missing" in err
    assert "uv run --with playwright playwright install chromium" in err


def test_main_handles_unexpected_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "parse_args", lambda: argparse.Namespace())

    def fail(args: argparse.Namespace) -> list[str]:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "extract_fragments", fail)

    assert cli.main() == 1
    assert "html-xpath: error: boom" in capsys.readouterr().err
