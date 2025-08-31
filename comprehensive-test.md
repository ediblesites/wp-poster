---
post_type: faxfaq
title: Comprehensive Markdown Test
slug: comprehensive-markdown-test
status: draft
excerpt: Testing all markdown features including new enhancements
taxonomies:
  faqtype: Test
featured_image: blablabla.jpg
---

This document tests all supported markdown features including the newly added ones.

## Text Formatting

Regular text with **bold text**, *italic text*, and ~~strikethrough text~~.

You can also combine them: **bold and ~~strikethrough~~** or *italic and ~~strikethrough~~*.

## Links

Here's a [link to Google](https://google.com) and a [link with title](https://example.com "Example Site").

## Ordered Lists

1. First item
2. Second item
3. Third item with **bold text**
4. Fourth item with *italic text*
5. Fifth item with ~~strikethrough~~

## Unordered Lists

- First bullet point
- Second bullet point
- Third bullet with **bold text**
- Fourth bullet with [a link](https://example.com)
- Fifth bullet with ~~strikethrough~~

## Nested Lists

1. First level ordered
   - Nested unordered item
   - Another nested item
     1. Deep nested ordered
     2. Another deep item
   - Back to second level
2. Second first level item
   1. Nested ordered item
   2. Another nested ordered
     - Deep nested unordered
     - Another deep unordered item
3. Third first level item

## Mixed Nested Lists

- Unordered first level
  1. Nested ordered item
  2. Another nested ordered
    - Deep nested unordered
    - Another deep item
  3. Back to nested ordered
- Second unordered item
  - Nested unordered
    1. Deep nested ordered
    2. Another deep ordered

## Blockquotes

### Single Line Blockquote
> This is a simple blockquote.

### Multi-line Blockquote
> This is a multi-line blockquote
> that spans several lines and
> demonstrates the new functionality.

### Blockquote with Paragraphs
> This is the first paragraph of the blockquote.
>
> This is the second paragraph with **bold text** and *italic text*.
>
> This is the third paragraph with a [link](https://example.com).

### Blockquote with Formatting
> This blockquote contains **bold text**, *italic text*, and ~~strikethrough text~~.
> It also has a [link to Google](https://google.com).

## Code Blocks

```bash
# This is a bash code block
echo "Hello World"
ls -la
```

```python
# This is a Python code block
def hello_world():
    print("Hello, World!")
    return True
```

## Tables

| Feature | Status | Notes |
|---------|--------|-------|
| Ordered Lists | ✓ | Working |
| Nested Lists | ✓ | Working |
| Multi-line Quotes | ✓ | Working |
| Strikethrough | ✓ | Working |

## Images

### Local Image
![Local test image](blablabla.jpg "This is a local image with caption")

### Remote Image
![Remote test image](https://picsum.photos/400/300 "This is a remote image")

## Complex Combinations

### List with Blockquote
1. First item
2. Second item with a quote:
   > This is a blockquote inside a list item
   > with multiple lines.
3. Third item

### Blockquote with List
> This blockquote contains a list:
> 
> 1. First quoted list item
> 2. Second quoted list item with **bold**
> 3. Third quoted list item

## WordPress Shortcodes

The current year is [current-year] and this post was created on [post-date].

[gallery id="123"]

## Final Test

This document tests:
- ✓ **Bold**, *italic*, and ~~strikethrough~~ formatting
- ✓ [Links](https://example.com) with and without titles
- ✓ Ordered lists (1., 2., 3.)
- ✓ Unordered lists (-, *, +)
- ✓ Nested lists (mixed types)
- ✓ Multi-line blockquotes with paragraphs
- ✓ Code blocks with syntax
- ✓ Tables
- ✓ Images (local and remote)
- ✓ WordPress shortcodes
- ✓ Complex combinations

All features should render correctly in Gutenberg!