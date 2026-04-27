# html-xpath

Render a web page with Playwright and extract only the HTML elements matched by
XPath.

## Usage

```bash
uv run html_xpath.py "https://example.com" "//main"
```

Multiple extraction XPath values can be passed positionally or with `--xpath`.
Matched elements are printed as rendered `outerHTML`.

```bash
uv run html_xpath.py "https://example.com" \
  --xpath "//main" \
  --xpath "//footer"
```

Use `--exclude-xpath` to remove unwanted descendant elements from each extracted
fragment.

```bash
uv run html_xpath.py "https://example.com" \
  --xpath "//body" \
  --exclude-xpath "//script" \
  --exclude-xpath "//style" \
  --exclude-xpath "//nav"
```

JSON output is available when you want to process multiple matches safely:

```bash
uv run html_xpath.py "https://example.com" "//a" --json
```

If Playwright browsers are not installed yet, install Chromium once:

```bash
uv run --with playwright playwright install chromium
```
