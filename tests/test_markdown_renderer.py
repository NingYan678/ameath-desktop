from digital_pet.markdown_renderer import is_safe_link, markdown_to_plain, render_markdown


def test_renderer_supports_common_markdown_without_raw_html():
    rendered = render_markdown("# 标题\n\n- **粗体** 与 `代码`\n\n> 引用\n\n[官网](https://example.com)")

    assert "<h1>标题</h1>" in rendered
    assert "<ul><li><b>粗体</b> 与 <code>代码</code></li></ul>" in rendered
    assert '<a href="https://example.com">官网</a>' in rendered


def test_renderer_escapes_html_and_rejects_unsafe_links():
    rendered = render_markdown("<img src=x> [bad](file:///secret)")

    assert "&lt;img" in rendered
    assert "file:///secret" not in rendered
    assert not is_safe_link("file:///secret")


def test_unclosed_code_fence_renders_as_code_and_compact_preview_is_clean():
    rendered = render_markdown("```python\nprint('ok')")

    assert "<pre><code>print(&#x27;ok&#x27;)</code></pre>" in rendered
    assert markdown_to_plain("## 标题\n[链接](https://example.com) **加粗**") == "标题 链接 加粗"
