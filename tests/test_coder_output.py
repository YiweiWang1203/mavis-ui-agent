from src.agents.coder import strip_markdown_code_fence


def test_strip_markdown_code_fence_html():
    raw = """```html
<!DOCTYPE html>
<html>
<body>ok</body>
</html>
```"""

    cleaned = strip_markdown_code_fence(raw)

    assert cleaned.startswith("<!DOCTYPE html>")
    assert cleaned.endswith("</html>")
    assert "```" not in cleaned


def test_strip_markdown_code_fence_noop_for_raw_html():
    raw = "<!DOCTYPE html>\n<html></html>"
    assert strip_markdown_code_fence(raw) == raw
