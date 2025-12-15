"""
Markdown to Gutenberg block converter
"""

import re


class GutenbergConverter:
    """Converts markdown to WordPress Gutenberg blocks"""

    def __init__(self, image_handler=None):
        """
        Initialize converter.

        Args:
            image_handler: Optional callable(image_url) -> (final_url, media_id)
                          If None, images are left as-is with no media ID.
        """
        self.image_handler = image_handler or (lambda url: (url, None))

    def convert(self, markdown_content):
        """Convert markdown to Gutenberg block format"""
        blocks = []

        lines = markdown_content.split('\n')
        current_block = []
        in_code_block = False

        i = 0
        while i < len(lines):
            line = lines[i]

            # Handle code blocks
            if line.startswith('```'):
                if in_code_block:
                    code_content = '\n'.join(current_block)
                    blocks.append(f'<!-- wp:code -->\n<pre class="wp-block-code"><code>{code_content}</code></pre>\n<!-- /wp:code -->')
                    current_block = []
                    in_code_block = False
                else:
                    in_code_block = True
                    current_block = []
                i += 1
                continue

            if in_code_block:
                current_block.append(line)
                i += 1
                continue

            # Handle headings
            if line.startswith('#'):
                if current_block:
                    paragraph_text = '\n'.join(current_block)
                    if paragraph_text:
                        processed_blocks = self._process_paragraph_with_images(paragraph_text)
                        blocks.extend(processed_blocks)
                    current_block = []

                level = len(line) - len(line.lstrip('#'))
                heading_text = line[level:].strip()
                blocks.append(f'<!-- wp:heading {{"level":{level}}} -->\n<h{level} class="wp-block-heading">{heading_text}</h{level}>\n<!-- /wp:heading -->')
                i += 1
                continue

            # Handle lists (including nested)
            if self._is_list_item(line):
                if current_block:
                    paragraph_text = '\n'.join(current_block)
                    if paragraph_text:
                        processed_blocks = self._process_paragraph_with_images(paragraph_text)
                        blocks.extend(processed_blocks)
                    current_block = []

                list_lines = []
                j = i

                while j < len(lines) and (self._is_list_item(lines[j]) or lines[j].strip() == ''):
                    if lines[j].strip():
                        list_lines.append(lines[j])
                    j += 1

                list_html, is_ordered = self._process_nested_list(list_lines)

                if is_ordered:
                    blocks.append(f'<!-- wp:list {{"ordered":true}} -->\n{list_html}\n<!-- /wp:list -->')
                else:
                    blocks.append(f'<!-- wp:list -->\n{list_html}\n<!-- /wp:list -->')

                i = j
                continue

            # Handle tables
            if '|' in line and i + 1 < len(lines) and '---' in lines[i + 1]:
                table_lines = [line]
                j = i + 1
                while j < len(lines) and '|' in lines[j]:
                    table_lines.append(lines[j])
                    j += 1

                table_html = self._markdown_table_to_html(table_lines)
                blocks.append(f'<!-- wp:table -->\n<figure class="wp-block-table"><table>{table_html}</table></figure>\n<!-- /wp:table -->')

                i = j
                continue

            # Handle blockquotes (including multi-line)
            if line.startswith('>'):
                quote_lines = []

                while i < len(lines) and lines[i].startswith('>'):
                    quote_content = lines[i][1:].strip()
                    if quote_content:
                        quote_lines.append(quote_content)
                    elif quote_lines:
                        quote_lines.append('')
                    i += 1

                if quote_lines:
                    while quote_lines and not quote_lines[-1]:
                        quote_lines.pop()

                    quote_html = self._process_blockquote_content(quote_lines)
                    blocks.append(f'<!-- wp:quote -->\n<blockquote class="wp-block-quote">{quote_html}</blockquote>\n<!-- /wp:quote -->')
                continue

            # Handle empty lines (paragraph breaks)
            if not line.strip():
                if current_block:
                    paragraph_text = '\n'.join(current_block)
                    if paragraph_text:
                        processed_blocks = self._process_paragraph_with_images(paragraph_text)
                        blocks.extend(processed_blocks)
                    current_block = []
                i += 1
                continue

            # Regular paragraph line
            current_block.append(line)
            i += 1

        # Handle any remaining paragraph
        if current_block and not in_code_block:
            paragraph_text = '\n'.join(current_block)
            if paragraph_text:
                processed_blocks = self._process_paragraph_with_images(paragraph_text)
                blocks.extend(processed_blocks)

        return '\n\n'.join(blocks)

    def _is_list_item(self, line):
        """Check if line is a list item (ordered or unordered)"""
        return re.match(r'^(\s*)([*\-+]|\d+[.)]) ', line) is not None

    def _get_list_type(self, line):
        """Determine if list item is ordered or unordered"""
        if re.match(r'^(\s*)\d+[.)] ', line):
            return 'ordered'
        return 'unordered'

    def _extract_list_item_content(self, line):
        """Extract the content of a list item, removing the marker"""
        match = re.match(r'^(\s*)([*\-+]|\d+[.)]) (.*)$', line)
        if match:
            return match.group(3)
        return line.strip()

    def _get_indentation_level(self, line):
        """Get the indentation level of a line (number of leading spaces)"""
        return len(line) - len(line.lstrip())

    def _process_nested_list(self, list_lines):
        """Process a list with potential nesting into HTML"""
        if not list_lines:
            return "", False

        result_html = []
        root_is_ordered = self._get_list_type(list_lines[0]) == 'ordered'

        # For simple flat lists (most common case), use simple logic
        if all(self._get_indentation_level(line) == 0 for line in list_lines):
            tag = 'ol' if root_is_ordered else 'ul'
            result_html.append(f'<{tag}>')

            for line in list_lines:
                content = self._extract_list_item_content(line)
                processed_content = self._process_inline_markdown(content)
                result_html.append(f'<li>{processed_content}</li>')

            result_html.append(f'</{tag}>')
            return '\n'.join(result_html), root_is_ordered

        # Handle nested lists with stack-based approach
        stack = []

        for line in list_lines:
            indent_level = self._get_indentation_level(line)
            content = self._extract_list_item_content(line)
            is_ordered = self._get_list_type(line) == 'ordered'

            target_depth = indent_level // 2
            current_depth = len(stack)

            while current_depth > target_depth:
                tag, _ = stack.pop()
                result_html.append(f'</{tag}>')
                current_depth -= 1

            while current_depth < target_depth:
                if current_depth == 0:
                    tag = 'ol' if root_is_ordered else 'ul'
                else:
                    tag = 'ol' if is_ordered else 'ul'
                result_html.append(f'<{tag}>')
                stack.append((tag, current_depth))
                current_depth += 1

            if not stack:
                tag = 'ol' if root_is_ordered else 'ul'
                result_html.append(f'<{tag}>')
                stack.append((tag, 0))

            processed_content = self._process_inline_markdown(content)
            result_html.append(f'<li>{processed_content}</li>')

        while stack:
            tag, _ = stack.pop()
            result_html.append(f'</{tag}>')

        return '\n'.join(result_html), root_is_ordered

    def _process_blockquote_content(self, quote_lines):
        """Process blockquote content, handling multiple paragraphs"""
        if not quote_lines:
            return ""

        paragraphs = []
        current_paragraph = []

        for line in quote_lines:
            if line == '':
                if current_paragraph:
                    paragraphs.append(' '.join(current_paragraph))
                    current_paragraph = []
            else:
                current_paragraph.append(line)

        if current_paragraph:
            paragraphs.append(' '.join(current_paragraph))

        processed_paragraphs = []
        for paragraph in paragraphs:
            processed = self._process_inline_markdown(paragraph)
            processed_paragraphs.append(f'<p>{processed}</p>')

        return ''.join(processed_paragraphs)

    def _process_html_images(self, text):
        """Process HTML figure/img tags and convert to Gutenberg blocks"""
        # Pattern for HTML figure with img and figcaption
        figure_pattern = r'<figure[^>]*>\s*<img\s+([^>]+)\s*/?\>\s*(?:<figcaption[^>]*>(.*?)</figcaption>)?\s*</figure>'

        def replace_figure(match):
            img_attrs = match.group(1)
            caption = match.group(2) if match.group(2) else ""

            src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', img_attrs)
            alt_match = re.search(r'alt\s*=\s*["\']([^"\']*)["\']', img_attrs)

            if not src_match:
                return match.group(0)

            image_url = src_match.group(1)
            alt_text = alt_match.group(1) if alt_match else ""

            final_url, media_id = self.image_handler(image_url)

            if final_url:
                if caption and caption.strip():
                    caption_clean = re.sub(r'<[^>]+>', '', caption).strip()
                    if media_id:
                        return f'<!-- wp:image {{"id":{media_id},"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}" class="wp-image-{media_id}"/><figcaption class="wp-element-caption">{caption_clean}</figcaption></figure>\n<!-- /wp:image -->'
                    else:
                        return f'<!-- wp:image {{"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}"/><figcaption class="wp-element-caption">{caption_clean}</figcaption></figure>\n<!-- /wp:image -->'
                else:
                    if media_id:
                        return f'<!-- wp:image {{"id":{media_id},"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}" class="wp-image-{media_id}"/></figure>\n<!-- /wp:image -->'
                    else:
                        return f'<!-- wp:image {{"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}"/></figure>\n<!-- /wp:image -->'
            else:
                return match.group(0)

        text = re.sub(figure_pattern, replace_figure, text, flags=re.DOTALL | re.IGNORECASE)

        # Handle standalone img tags
        standalone_img_pattern = r'<img\s+([^>]+)\s*/?\>'

        def replace_standalone_img(match):
            if '<!-- wp:image' in match.group(0):
                return match.group(0)

            img_attrs = match.group(1)

            src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', img_attrs)
            alt_match = re.search(r'alt\s*=\s*["\']([^"\']*)["\']', img_attrs)

            if not src_match:
                return match.group(0)

            image_url = src_match.group(1)
            alt_text = alt_match.group(1) if alt_match else ""

            final_url, media_id = self.image_handler(image_url)

            if final_url:
                if media_id:
                    return f'<!-- wp:image {{"id":{media_id},"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}" class="wp-image-{media_id}"/></figure>\n<!-- /wp:image -->'
                else:
                    return f'<!-- wp:image {{"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}"/></figure>\n<!-- /wp:image -->'
            else:
                return match.group(0)

        if '<!-- wp:image' not in text:
            text = re.sub(standalone_img_pattern, replace_standalone_img, text, flags=re.IGNORECASE)

        return text

    def _process_paragraph_with_images(self, text):
        """Process a paragraph that may contain images, splitting into separate blocks"""
        blocks = []

        # First, handle HTML figure/img tags
        processed_text = self._process_html_images(text)

        # Pattern for markdown images: ![alt text](url "optional title")
        image_pattern = r'!\[([^\]]*)\]\(([^)]+?)(?:\s+"([^"]*)")?\)'

        parts = re.split(image_pattern, processed_text)

        i = 0
        while i < len(parts):
            if i % 4 == 0:
                text_part = parts[i].strip()
                if text_part:
                    if text_part.startswith('<!-- wp:image'):
                        blocks.append(text_part)
                    else:
                        text_part = self._process_inline_markdown(text_part)
                        blocks.append(f'<!-- wp:paragraph -->\n<p>{text_part}</p>\n<!-- /wp:paragraph -->')

            elif i % 4 == 1 and i + 2 < len(parts):
                alt_text = parts[i]
                image_url = parts[i + 1]
                title = parts[i + 2] if parts[i + 2] else alt_text

                final_url, media_id = self.image_handler(image_url)

                if final_url:
                    if title and title.strip():
                        if media_id:
                            blocks.append(f'<!-- wp:image {{"id":{media_id},"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}" class="wp-image-{media_id}"/><figcaption class="wp-element-caption">{title}</figcaption></figure>\n<!-- /wp:image -->')
                        else:
                            blocks.append(f'<!-- wp:image {{"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}"/><figcaption class="wp-element-caption">{title}</figcaption></figure>\n<!-- /wp:image -->')
                    else:
                        if media_id:
                            blocks.append(f'<!-- wp:image {{"id":{media_id},"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}" class="wp-image-{media_id}"/></figure>\n<!-- /wp:image -->')
                        else:
                            blocks.append(f'<!-- wp:image {{"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}"/></figure>\n<!-- /wp:image -->')

                i += 2

            i += 1

        return blocks

    def _process_inline_markdown(self, text):
        """Process inline markdown like bold, italic, strikethrough, and links"""
        # Convert line breaks to <br> tags
        text = re.sub(r'(?<!\n)\n(?!\n)', '<br>', text)

        # Strikethrough
        text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', text)

        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)

        # Italic
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)

        # Links (but not images which start with !)
        text = re.sub(r'(?<!\!)\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)

        return text

    def _markdown_table_to_html(self, table_lines):
        """Convert markdown table to HTML"""
        if len(table_lines) < 2:
            return ""

        headers = [cell.strip() for cell in table_lines[0].split('|')[1:-1]]

        rows = []
        for line in table_lines[2:]:
            if '|' in line:
                row = [cell.strip() for cell in line.split('|')[1:-1]]
                rows.append(row)

        html = '<thead><tr>'
        for header in headers:
            html += f'<th>{header}</th>'
        html += '</tr></thead><tbody>'

        for row in rows:
            html += '<tr>'
            for cell in row:
                html += f'<td>{cell}</td>'
            html += '</tr>'
        html += '</tbody>'

        return html
