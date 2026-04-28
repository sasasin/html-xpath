# html-xpath

Render a web page with Playwright, parse the rendered HTML with lxml, and
extract only the HTML elements matched by XPath.

## Usage

Install the CLI directly from GitHub:

```bash
uv tool install git+https://github.com/sasasin/html-xpath.git
html-xpath --help
```

For local development, run the command through uv:

```bash
uv run html-xpath "https://example.com" "//main"
```

Multiple extraction XPath values can be passed positionally or with `--xpath`.
Matched elements are printed as rendered `outerHTML`.

```bash
uv run html-xpath "https://example.com" \
  --xpath "//main" \
  --xpath "//footer"
```

Use `--exclude-xpath` to remove unwanted descendant elements from each extracted
fragment.

```bash
uv run html-xpath "https://example.com" \
  --xpath "//body" \
  --exclude-xpath "//script" \
  --exclude-xpath "//style" \
  --exclude-xpath "//nav"
```

JSON output is available when you want to process multiple matches safely:

```bash
uv run html-xpath "https://example.com" "//a" --json
```

If Playwright browsers are not installed yet, install Chromium once:

```bash
uv run --with playwright playwright install chromium
```

## Tests

```bash
uv run --group dev pytest --cov-report=xml --cov-report=html
```
