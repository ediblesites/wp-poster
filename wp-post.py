#!/usr/bin/env python3
"""
WordPress Markdown Poster
Posts markdown files with frontmatter to WordPress via REST API
"""

import warnings
warnings.filterwarnings("ignore", message="urllib3")
warnings.filterwarnings("ignore", category=DeprecationWarning)

import argparse
import json
import os
import sys
import base64
from pathlib import Path
import requests
import yaml
import markdown2
from datetime import datetime
import getpass


class WordPressPost:
    def __init__(self, site_url, username, app_password):
        self.site_url = site_url.rstrip('/')
        self.auth = (username, app_password)
        self.api_url = f"{self.site_url}/wp-json/wp/v2"
        self.uploaded_media = {}  # Track uploaded media: {url: media_id}
        
    def parse_markdown_file(self, filepath):
        """Parse markdown file with frontmatter"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Split frontmatter and content
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                markdown_content = parts[2].strip()
            else:
                frontmatter = {}
                markdown_content = content
        else:
            frontmatter = {}
            markdown_content = content
            
        # Convert markdown to Gutenberg blocks
        blocks_content = self.markdown_to_gutenberg_blocks(markdown_content)

        return frontmatter, blocks_content

    def parse_raw_file(self, filepath):
        """Parse file with frontmatter but keep content as-is (no markdown conversion)"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Split frontmatter and content
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                raw_content = parts[2].strip()
            else:
                frontmatter = {}
                raw_content = content
        else:
            frontmatter = {}
            raw_content = content

        return frontmatter, raw_content

    def markdown_to_gutenberg_blocks(self, markdown_content):
        """Convert markdown to Gutenberg block format"""
        blocks = []
        
        # Split content into lines for processing
        lines = markdown_content.split('\n')
        current_block = []
        current_type = None
        in_code_block = False
        in_list = False
        list_items = []
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Handle code blocks
            if line.startswith('```'):
                if in_code_block:
                    # End code block
                    code_content = '\n'.join(current_block)
                    blocks.append(f'<!-- wp:code -->\n<pre class="wp-block-code"><code>{code_content}</code></pre>\n<!-- /wp:code -->')
                    current_block = []
                    in_code_block = False
                else:
                    # Start code block
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
                # Process any accumulated paragraph content first
                if current_block:
                    paragraph_text = '\n'.join(current_block)
                    if paragraph_text:
                        processed_blocks = self.process_paragraph_with_images(paragraph_text)
                        blocks.extend(processed_blocks)
                    current_block = []

                # Count the number of # symbols for heading level
                level = len(line) - len(line.lstrip('#'))
                heading_text = line[level:].strip()
                blocks.append(f'<!-- wp:heading {{"level":{level}}} -->\n<h{level} class="wp-block-heading">{heading_text}</h{level}>\n<!-- /wp:heading -->')
                i += 1
                continue
            
            # Handle lists (including nested)
            if self.is_list_item(line):
                # Process any accumulated paragraph content first
                if current_block:
                    paragraph_text = '\n'.join(current_block)
                    if paragraph_text:
                        processed_blocks = self.process_paragraph_with_images(paragraph_text)
                        blocks.extend(processed_blocks)
                    current_block = []
                
                # Collect all consecutive list items starting from current line
                list_lines = []
                j = i
                
                # Collect all consecutive list items
                while j < len(lines) and (self.is_list_item(lines[j]) or lines[j].strip() == ''):
                    if lines[j].strip():  # Skip empty lines but don't break the list
                        list_lines.append(lines[j])
                    j += 1
                
                # Process the collected list
                list_html, is_ordered = self.process_nested_list(list_lines)
                
                if is_ordered:
                    blocks.append(f'<!-- wp:list {{"ordered":true}} -->\n{list_html}\n<!-- /wp:list -->')
                else:
                    blocks.append(f'<!-- wp:list -->\n{list_html}\n<!-- /wp:list -->')
                
                i = j  # Skip the processed lines
                continue
            
            # Handle tables (basic support)
            if '|' in line and i + 1 < len(lines) and '---' in lines[i + 1]:
                # Start of a table
                table_lines = [line]
                j = i + 1
                while j < len(lines) and '|' in lines[j]:
                    table_lines.append(lines[j])
                    j += 1
                
                # Convert table to HTML
                table_html = self.markdown_table_to_html(table_lines)
                blocks.append(f'<!-- wp:table -->\n<figure class="wp-block-table"><table>{table_html}</table></figure>\n<!-- /wp:table -->')
                
                # Skip processed lines
                i = j
                continue
            
            # Handle blockquotes (including multi-line)
            if line.startswith('>'):
                quote_lines = []
                
                # Collect all consecutive blockquote lines
                while i < len(lines) and lines[i].startswith('>'):
                    quote_content = lines[i][1:].strip()  # Remove '>' and strip
                    if quote_content:  # Only add non-empty lines
                        quote_lines.append(quote_content)
                    elif quote_lines:  # Add empty line if we have content (for paragraph breaks)
                        quote_lines.append('')
                    i += 1
                
                # Process the collected blockquote
                if quote_lines:
                    # Remove trailing empty lines
                    while quote_lines and not quote_lines[-1]:
                        quote_lines.pop()
                    
                    # Convert to paragraphs (split by empty lines)
                    quote_html = self.process_blockquote_content(quote_lines)
                    blocks.append(f'<!-- wp:quote -->\n<blockquote class="wp-block-quote">{quote_html}</blockquote>\n<!-- /wp:quote -->')
                continue
            
            # Handle empty lines (paragraph breaks)
            if not line.strip():
                if current_block:
                    paragraph_text = '\n'.join(current_block)
                    if paragraph_text:
                        # Check for standalone images in the paragraph
                        processed_blocks = self.process_paragraph_with_images(paragraph_text)
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
                processed_blocks = self.process_paragraph_with_images(paragraph_text)
                blocks.extend(processed_blocks)
        
        return '\n\n'.join(blocks)
    
    def is_list_item(self, line):
        """Check if line is a list item (ordered or unordered)"""
        import re
        # Unordered: -, *, +
        # Ordered: 1., 2., 10., 1)
        return re.match(r'^(\s*)([*\-+]|\d+[.)]) ', line) is not None
    
    def get_list_type(self, line):
        """Determine if list item is ordered or unordered"""
        import re
        if re.match(r'^(\s*)\d+[.)] ', line):
            return 'ordered'
        return 'unordered'
    
    def extract_list_item_content(self, line):
        """Extract the content of a list item, removing the marker"""
        import re
        # Match the list marker and extract content
        match = re.match(r'^(\s*)([*\-+]|\d+[.)]) (.*)$', line)
        if match:
            return match.group(3)  # The content after the marker
        return line.strip()
    
    def get_indentation_level(self, line):
        """Get the indentation level of a line (number of leading spaces)"""
        return len(line) - len(line.lstrip())
    
    def process_nested_list(self, list_lines):
        """Process a list with potential nesting into HTML"""
        if not list_lines:
            return "", False
            
        result_html = []
        root_is_ordered = self.get_list_type(list_lines[0]) == 'ordered'
        
        # For simple flat lists (most common case), use simple logic
        if all(self.get_indentation_level(line) == 0 for line in list_lines):
            # All items at same level - create single list
            tag = 'ol' if root_is_ordered else 'ul'
            result_html.append(f'<{tag}>')
            
            for line in list_lines:
                content = self.extract_list_item_content(line)
                processed_content = self.process_inline_markdown_no_images(content)
                result_html.append(f'<li>{processed_content}</li>')
            
            result_html.append(f'</{tag}>')
            return '\n'.join(result_html), root_is_ordered
        
        # Handle nested lists with stack-based approach
        stack = []  # Stack of (tag, level) tuples
        
        for line in list_lines:
            indent_level = self.get_indentation_level(line)
            content = self.extract_list_item_content(line)
            is_ordered = self.get_list_type(line) == 'ordered'
            
            # Determine target depth (every 2 spaces = 1 level)
            target_depth = indent_level // 2
            current_depth = len(stack)
            
            # Close deeper levels
            while current_depth > target_depth:
                tag, _ = stack.pop()
                result_html.append(f'</{tag}>')
                current_depth -= 1
            
            # Open new levels if needed
            while current_depth < target_depth:
                if current_depth == 0:
                    # Use the type of the first item for root level
                    tag = 'ol' if root_is_ordered else 'ul'
                else:
                    # For nested levels, use the type of this item
                    tag = 'ol' if is_ordered else 'ul'
                result_html.append(f'<{tag}>')
                stack.append((tag, current_depth))
                current_depth += 1
            
            # Ensure we have a list container at current level
            if not stack:
                tag = 'ol' if root_is_ordered else 'ul'
                result_html.append(f'<{tag}>')
                stack.append((tag, 0))
            
            # Process inline markdown in the content
            processed_content = self.process_inline_markdown_no_images(content)
            result_html.append(f'<li>{processed_content}</li>')
        
        # Close all remaining levels
        while stack:
            tag, _ = stack.pop()
            result_html.append(f'</{tag}>')
        
        return '\n'.join(result_html), root_is_ordered
    
    def process_blockquote_content(self, quote_lines):
        """Process blockquote content, handling multiple paragraphs"""
        if not quote_lines:
            return ""
        
        # Split into paragraphs by empty lines
        paragraphs = []
        current_paragraph = []
        
        for line in quote_lines:
            if line == '':
                if current_paragraph:
                    paragraphs.append(' '.join(current_paragraph))
                    current_paragraph = []
            else:
                current_paragraph.append(line)
        
        # Add the last paragraph if any
        if current_paragraph:
            paragraphs.append(' '.join(current_paragraph))
        
        # Process each paragraph for inline markdown
        processed_paragraphs = []
        for paragraph in paragraphs:
            processed = self.process_inline_markdown_no_images(paragraph)
            processed_paragraphs.append(f'<p>{processed}</p>')
        
        return ''.join(processed_paragraphs)
    
    def process_html_images(self, text):
        """Process HTML figure/img tags and convert to Gutenberg blocks"""
        import re
        
        # Pattern for HTML figure with img and figcaption
        figure_pattern = r'<figure[^>]*>\s*<img\s+([^>]+)\s*/?\>\s*(?:<figcaption[^>]*>(.*?)</figcaption>)?\s*</figure>'
        
        def replace_figure(match):
            img_attrs = match.group(1)
            caption = match.group(2) if match.group(2) else ""
            
            # Extract src and alt from img attributes
            src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', img_attrs)
            alt_match = re.search(r'alt\s*=\s*["\']([^"\']*)["\']', img_attrs)
            
            if not src_match:
                return match.group(0)  # Return original if no src
            
            image_url = src_match.group(1)
            alt_text = alt_match.group(1) if alt_match else ""
            
            # Process the image URL (download and upload to WordPress)
            final_url = self.process_image_url(image_url)
            
            if final_url:
                media_id = self.get_media_id_from_url(final_url)
                
                if caption and caption.strip():
                    # Clean HTML tags from caption
                    caption_clean = re.sub(r'<[^>]+>', '', caption).strip()
                    if media_id:
                        return f'<!-- wp:image {{"id":{media_id},"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}" class="wp-image-{media_id}"/><figcaption class="wp-element-caption">{caption_clean}</figcaption></figure>\n<!-- /wp:image -->'
                    else:
                        return f'<!-- wp:image {{"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}"/><figcaption class="wp-element-caption">{caption_clean}</figcaption></figure>\n<!-- /wp:image -->'
                else:
                    # Image without caption
                    if media_id:
                        return f'<!-- wp:image {{"id":{media_id},"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}" class="wp-image-{media_id}"/></figure>\n<!-- /wp:image -->'
                    else:
                        return f'<!-- wp:image {{"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}"/></figure>\n<!-- /wp:image -->'
            else:
                return match.group(0)  # Return original if processing failed
        
        # Replace figure tags first
        text = re.sub(figure_pattern, replace_figure, text, flags=re.DOTALL | re.IGNORECASE)
        
        # Also handle standalone img tags (not wrapped in figure)
        # Use a simpler approach - find all img tags and filter out those in figure tags
        standalone_img_pattern = r'<img\s+([^>]+)\s*/?\>'
        
        def replace_standalone_img(match):
            # Skip if this img tag is already processed (would be inside a wp:image block)
            if '<!-- wp:image' in match.group(0):
                return match.group(0)
            
            img_attrs = match.group(1)
            
            # Extract src and alt from img attributes
            src_match = re.search(r'src\s*=\s*["\']([^"\']+)["\']', img_attrs)
            alt_match = re.search(r'alt\s*=\s*["\']([^"\']*)["\']', img_attrs)
            
            if not src_match:
                return match.group(0)  # Return original if no src
            
            image_url = src_match.group(1)
            alt_text = alt_match.group(1) if alt_match else ""
            
            # Process the image URL
            final_url = self.process_image_url(image_url)
            
            if final_url:
                media_id = self.get_media_id_from_url(final_url)
                
                if media_id:
                    return f'<!-- wp:image {{"id":{media_id},"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}" class="wp-image-{media_id}"/></figure>\n<!-- /wp:image -->'
                else:
                    return f'<!-- wp:image {{"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}"/></figure>\n<!-- /wp:image -->'
            else:
                return match.group(0)  # Return original if processing failed
        
        # Only process standalone img tags (those not already converted)
        if '<!-- wp:image' not in text:
            text = re.sub(standalone_img_pattern, replace_standalone_img, text, flags=re.IGNORECASE)
        
        return text
    
    def process_paragraph_with_images(self, text):
        """Process a paragraph that may contain images, splitting into separate blocks"""
        import re
        
        blocks = []
        
        # First, handle HTML figure/img tags
        processed_text = self.process_html_images(text)
        
        # Pattern for markdown images: ![alt text](url "optional title")
        image_pattern = r'!\[([^\]]*)\]\(([^)]+?)(?:\s+"([^"]*)")?\)'
        
        # Split text by images
        parts = re.split(image_pattern, processed_text)
        
        i = 0
        while i < len(parts):
            # Text part (could be before, between, or after images)
            if i % 4 == 0:  # Text parts are at positions 0, 4, 8, etc.
                text_part = parts[i].strip()
                if text_part:
                    # Check if this is already a processed image block
                    if text_part.startswith('<!-- wp:image'):
                        blocks.append(text_part)
                    else:
                        # Process other inline markdown
                        text_part = self.process_inline_markdown_no_images(text_part)
                        blocks.append(f'<!-- wp:paragraph -->\n<p>{text_part}</p>\n<!-- /wp:paragraph -->')
            
            # Image parts (alt, url, title) - positions 1,2,3 then 5,6,7, etc.
            elif i % 4 == 1 and i + 2 < len(parts):
                alt_text = parts[i]
                image_url = parts[i + 1] 
                title = parts[i + 2] if parts[i + 2] else alt_text
                
                # Process the image URL
                final_url = self.process_image_url(image_url)
                
                if final_url:
                    # Create Gutenberg image block with proper format
                    media_id = self.get_media_id_from_url(final_url)
                    
                    if title and title.strip():
                        # Image with caption
                        if media_id:
                            blocks.append(f'<!-- wp:image {{"id":{media_id},"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}" class="wp-image-{media_id}"/><figcaption class="wp-element-caption">{title}</figcaption></figure>\n<!-- /wp:image -->')
                        else:
                            blocks.append(f'<!-- wp:image {{"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}"/><figcaption class="wp-element-caption">{title}</figcaption></figure>\n<!-- /wp:image -->')
                    else:
                        # Image without caption
                        if media_id:
                            blocks.append(f'<!-- wp:image {{"id":{media_id},"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}" class="wp-image-{media_id}"/></figure>\n<!-- /wp:image -->')
                        else:
                            blocks.append(f'<!-- wp:image {{"sizeSlug":"full","linkDestination":"none","align":"center"}} -->\n<figure class="wp-block-image aligncenter size-full"><img src="{final_url}" alt="{alt_text}"/></figure>\n<!-- /wp:image -->')
                
                i += 2  # Skip the url and title parts
            
            i += 1
        
        return blocks
    
    def get_media_id_from_url(self, url):
        """Extract media ID from WordPress media URL if possible"""
        return self.uploaded_media.get(url, None)
    
    def process_inline_markdown_no_images(self, text):
        """Process inline markdown like bold, italic, strikethrough, and links (but not images)"""
        import re
        
        # Convert line breaks to <br> tags (but not double line breaks which separate paragraphs)
        # This handles the case where single line breaks should be preserved within a paragraph
        text = re.sub(r'(?<!\n)\n(?!\n)', '<br>', text)
        
        # Strikethrough (must come before other formatting to avoid conflicts)
        text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', text)
        
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        
        # Italic
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        
        # Links (but not images which start with !)
        text = re.sub(r'(?<!\!)\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
        
        return text
    
    def process_inline_markdown(self, text):
        """Process inline markdown like bold, italic, strikethrough, links, and images"""
        import re
        
        # Process images first (before links)
        text = self.process_inline_images(text)
        
        # Strikethrough (must come before other formatting to avoid conflicts)
        text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', text)
        
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        
        # Italic
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        
        # Links (but not images which start with !)
        text = re.sub(r'(?<!\!)\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
        
        return text
    
    def process_inline_images(self, text):
        """Process inline images with figure/figcaption wrapping"""
        import re
        
        # Pattern for markdown images: ![alt text](url "optional title")
        image_pattern = r'!\[([^\]]*)\]\(([^)]+?)(?:\s+"([^"]*)")?\)'
        
        def replace_image(match):
            alt_text = match.group(1)
            image_url = match.group(2)
            title = match.group(3) or alt_text
            
            # Handle local files and remote URLs
            final_url = self.process_image_url(image_url)
            
            if final_url:
                # Create figure with figcaption if we have alt text or title
                if alt_text or title:
                    caption = title if title else alt_text
                    return f'<figure><img src="{final_url}" alt="{alt_text}" /><figcaption>{caption}</figcaption></figure>'
                else:
                    return f'<figure><img src="{final_url}" alt="" /></figure>'
            else:
                # If image processing failed, return original markdown
                return match.group(0)
        
        return re.sub(image_pattern, replace_image, text)
    
    def process_image_url(self, image_path_or_url):
        """Process image URL - upload local files and remote URLs to WordPress media library"""
        
        # If it's already a remote URL, upload it to WordPress
        if image_path_or_url.startswith(('http://', 'https://')):
            media_id = self.upload_media(image_path_or_url)
            if media_id:
                # Get the WordPress media URL
                try:
                    media_response = requests.get(f"{self.api_url}/media/{media_id}", auth=self.auth, timeout=30)
                    if media_response.status_code == 200:
                        media_url = media_response.json()['source_url']
                        self.uploaded_media[media_url] = media_id  # Track the media ID
                        print(f"✓ Downloaded and uploaded remote image: {image_path_or_url} → {media_url}")
                        return media_url
                except (requests.RequestException, KeyError, ValueError) as e:
                    print(f"⚠ Error getting media URL: {e}")
            
            # If upload failed, fall back to original URL
            print(f"⚠ Failed to upload remote image, using original URL: {image_path_or_url}")
            return image_path_or_url
        
        # Local file - upload to WordPress
        else:
            # Check if file exists
            if os.path.exists(image_path_or_url):
                media_id = self.upload_media(image_path_or_url)
                if media_id:
                    # Get the WordPress media URL
                    try:
                        media_response = requests.get(f"{self.api_url}/media/{media_id}", auth=self.auth, timeout=30)
                        if media_response.status_code == 200:
                            media_url = media_response.json()['source_url']
                            self.uploaded_media[media_url] = media_id  # Track the media ID
                            print(f"✓ Uploaded inline image: {image_path_or_url} → {media_url}")
                            return media_url
                    except (requests.RequestException, KeyError, ValueError) as e:
                        print(f"⚠ Error getting media URL: {e}")
                
                print(f"✗ Failed to upload inline image: {image_path_or_url}")
                return None
            else:
                print(f"✗ Inline image file not found: {image_path_or_url}")
                return None
    
    def markdown_table_to_html(self, table_lines):
        """Convert markdown table to HTML"""
        if len(table_lines) < 2:
            return ""
        
        # Parse header
        headers = [cell.strip() for cell in table_lines[0].split('|')[1:-1]]
        
        # Skip separator line
        rows = []
        for line in table_lines[2:]:
            if '|' in line:
                row = [cell.strip() for cell in line.split('|')[1:-1]]
                rows.append(row)
        
        # Build HTML
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
    
    def get_categories(self):
        """Get all categories from WordPress"""
        response = requests.get(f"{self.api_url}/categories", auth=self.auth, timeout=30)
        if response.status_code == 200:
            return {cat['name']: cat['id'] for cat in response.json()}
        return {}
    
    def get_tags(self):
        """Get all tags from WordPress"""
        response = requests.get(f"{self.api_url}/tags", auth=self.auth, timeout=30)
        if response.status_code == 200:
            return {tag['name']: tag['id'] for tag in response.json()}
        return {}
    
    def create_category(self, name):
        """Create a new category"""
        data = {'name': name}
        response = requests.post(f"{self.api_url}/categories", auth=self.auth, json=data, timeout=30)
        if response.status_code == 201:
            return response.json()['id']
        return None
    
    def create_tag(self, name):
        """Create a new tag"""
        data = {'name': name}
        response = requests.post(f"{self.api_url}/tags", auth=self.auth, json=data, timeout=30)
        if response.status_code == 201:
            return response.json()['id']
        return None
    
    def get_taxonomy_rest_base(self, taxonomy):
        """Get the REST API base for a taxonomy (may differ from slug)"""
        if not hasattr(self, '_taxonomy_cache'):
            self._taxonomy_cache = {}
        if taxonomy in self._taxonomy_cache:
            return self._taxonomy_cache[taxonomy]

        # Query WordPress for taxonomy info
        response = requests.get(f"{self.api_url}/taxonomies/{taxonomy}", auth=self.auth, timeout=30)
        if response.status_code == 200:
            rest_base = response.json().get('rest_base', taxonomy)
            self._taxonomy_cache[taxonomy] = rest_base
            return rest_base

        # Fallback to slug if taxonomy not found
        self._taxonomy_cache[taxonomy] = taxonomy
        return taxonomy

    def get_taxonomy_terms(self, taxonomy):
        """Get all terms for a taxonomy"""
        rest_base = self.get_taxonomy_rest_base(taxonomy)
        response = requests.get(f"{self.api_url}/{rest_base}", auth=self.auth, timeout=30)
        if response.status_code == 200:
            return {term['name']: term['id'] for term in response.json()}
        return {}

    def create_taxonomy_term(self, taxonomy, name):
        """Create a new term in a taxonomy"""
        rest_base = self.get_taxonomy_rest_base(taxonomy)
        data = {'name': name}
        response = requests.post(f"{self.api_url}/{rest_base}", auth=self.auth, json=data, timeout=30)
        if response.status_code == 201:
            return response.json()['id']
        return None

    def get_user_id(self, username_or_id):
        """Get user ID from username or return ID if already numeric"""
        # If it's already a number, return it
        if isinstance(username_or_id, int):
            return username_or_id
        if isinstance(username_or_id, str) and username_or_id.isdigit():
            return int(username_or_id)

        # Look up by username
        response = requests.get(
            f"{self.api_url}/users",
            auth=self.auth,
            params={'search': username_or_id},
            timeout=30
        )
        if response.status_code == 200:
            users = response.json()
            for user in users:
                if user.get('slug') == username_or_id or user.get('name') == username_or_id:
                    return user['id']
        return None

    def post_to_wordpress(self, filepath, draft=False, raw=False, author_context=None):
        """Post file to WordPress"""
        if raw:
            frontmatter, content = self.parse_raw_file(filepath)
        else:
            frontmatter, content = self.parse_markdown_file(filepath)
        
        # Determine post type and API endpoint
        post_type = frontmatter.get('post_type', 'posts')
        
        # Map common post type names to API endpoints
        if post_type in ['post', 'posts']:
            api_endpoint = 'posts'
        elif post_type in ['page', 'pages']:
            api_endpoint = 'pages'
        else:
            # Custom post type - use as-is
            api_endpoint = post_type
        
        # Prepare post data
        post_data = {
            'title': frontmatter.get('title', Path(filepath).stem),
            'content': content,
            'status': 'draft' if draft else frontmatter.get('status', 'publish'),
            'slug': frontmatter.get('slug', ''),
            'excerpt': frontmatter.get('excerpt', ''),
        }
        
        # Handle date
        if 'date' in frontmatter:
            if isinstance(frontmatter['date'], datetime):
                post_data['date'] = frontmatter['date'].isoformat()
            else:
                post_data['date'] = frontmatter['date']

        # Handle author (frontmatter overrides config)
        author = frontmatter.get('author', author_context)
        if author:
            author_id = self.get_user_id(author)
            if author_id:
                post_data['author'] = author_id
            else:
                print(f"⚠ Author '{author}' not found, using authenticated user")

        # Handle categories (only for posts)
        if 'categories' in frontmatter and api_endpoint == 'posts':
            existing_cats = self.get_categories()
            cat_ids = []
            for cat_name in frontmatter['categories']:
                if cat_name in existing_cats:
                    cat_ids.append(existing_cats[cat_name])
                else:
                    # Create new category
                    new_id = self.create_category(cat_name)
                    if new_id:
                        cat_ids.append(new_id)
            if cat_ids:
                post_data['categories'] = cat_ids
        
        # Handle tags (only for posts)
        if 'tags' in frontmatter and api_endpoint == 'posts':
            existing_tags = self.get_tags()
            tag_ids = []
            for tag_name in frontmatter['tags']:
                if tag_name in existing_tags:
                    tag_ids.append(existing_tags[tag_name])
                else:
                    # Create new tag
                    new_id = self.create_tag(tag_name)
                    if new_id:
                        tag_ids.append(new_id)
            if tag_ids:
                post_data['tags'] = tag_ids
        
        # Handle custom fields/meta
        if 'meta' in frontmatter:
            post_data['meta'] = frontmatter['meta']
        
        # Handle ACF fields if present
        if 'acf' in frontmatter:
            post_data['acf'] = frontmatter['acf']
        
        # Handle custom taxonomies
        if 'taxonomies' in frontmatter:
            for taxonomy, terms in frontmatter['taxonomies'].items():
                # Ensure terms is a list
                if isinstance(terms, str):
                    terms = [terms]
                
                # Get existing terms for this taxonomy
                existing_terms = self.get_taxonomy_terms(taxonomy)
                term_ids = []
                
                for term_name in terms:
                    if term_name in existing_terms:
                        term_ids.append(existing_terms[term_name])
                    else:
                        # Create new term
                        new_id = self.create_taxonomy_term(taxonomy, term_name)
                        if new_id:
                            term_ids.append(new_id)
                
                if term_ids:
                    post_data[taxonomy] = term_ids
        
        # Handle featured image
        if 'featured_image' in frontmatter:
            media_id = self.upload_media(frontmatter['featured_image'])
            if media_id:
                post_data['featured_media'] = media_id
        
        # Create or update post
        if 'id' in frontmatter:
            # Update existing post
            response = requests.post(
                f"{self.api_url}/{api_endpoint}/{frontmatter['id']}",
                auth=self.auth,
                json=post_data,
                timeout=30
            )
        else:
            # Create new post
            response = requests.post(
                f"{self.api_url}/{api_endpoint}",
                auth=self.auth,
                json=post_data,
                timeout=30
            )
        
        if response.status_code in [200, 201]:
            post = response.json()
            return {
                'success': True,
                'id': post['id'],
                'url': post['link'],
                'title': post['title']['rendered']
            }
        else:
            error_msg = response.text
            # Check for author permission error
            try:
                error_data = response.json()
                if error_data.get('code') == 'rest_cannot_edit_others':
                    error_msg = f"Permission denied: cannot set author to another user. {error_data.get('message', '')}"
            except (ValueError, KeyError):
                pass
            return {
                'success': False,
                'error': error_msg,
                'status_code': response.status_code
            }
    
    def upload_media(self, filepath_or_url):
        """Upload media file to WordPress from local file or remote URL"""
        # Check if it's a URL
        if filepath_or_url.startswith(('http://', 'https://')):
            return self.upload_media_from_url(filepath_or_url)
        else:
            return self.upload_media_from_file(filepath_or_url)
    
    def upload_media_from_url(self, url):
        """Upload media from remote URL to WordPress"""
        try:
            print(f"Downloading featured image from URL: {url}")
            
            # Download the image
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                print(f"✗ Failed to download image from URL: {response.status_code}")
                return None
            
            media_data = response.content
            
            # Get filename from URL or generate one
            filename = os.path.basename(url.split('?')[0])  # Remove query params
            if not filename or '.' not in filename:
                # Generate filename based on content type
                content_type = response.headers.get('content-type', '').lower()
                if 'jpeg' in content_type or 'jpg' in content_type:
                    filename = 'image.jpg'
                elif 'png' in content_type:
                    filename = 'image.png'
                elif 'gif' in content_type:
                    filename = 'image.gif'
                elif 'webp' in content_type:
                    filename = 'image.webp'
                else:
                    filename = 'image.jpg'  # Default
            
            # Get content type
            content_type = response.headers.get('content-type', 'application/octet-stream')
            
        except requests.exceptions.RequestException as e:
            print(f"✗ Error downloading image from URL: {e}")
            return None
        
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': content_type
        }
        
        print(f"Uploading featured image: {filename}")

        upload_response = requests.post(
            f"{self.api_url}/media",
            auth=self.auth,
            headers=headers,
            data=media_data,
            timeout=60
        )
        
        if upload_response.status_code == 201:
            media_info = upload_response.json()
            print(f"✓ Featured image uploaded successfully: {media_info['source_url']}")
            return media_info['id']
        else:
            print(f"✗ Failed to upload featured image: {upload_response.status_code} - {upload_response.text}")
            return None
    
    def upload_media_from_file(self, filepath):
        """Upload media from local file to WordPress"""
        if not os.path.exists(filepath):
            print(f"Warning: Featured image file '{filepath}' not found")
            return None
            
        with open(filepath, 'rb') as f:
            media_data = f.read()
        
        filename = os.path.basename(filepath)
        
        # Determine content type based on file extension
        ext = os.path.splitext(filename)[1].lower()
        content_type_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        }
        
        content_type = content_type_map.get(ext, 'application/octet-stream')
        
        headers = {
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Type': content_type
        }
        
        print(f"Uploading featured image: {filename}")

        response = requests.post(
            f"{self.api_url}/media",
            auth=self.auth,
            headers=headers,
            data=media_data,
            timeout=60
        )
        
        if response.status_code == 201:
            media_info = response.json()
            print(f"✓ Featured image uploaded successfully: {media_info['source_url']}")
            return media_info['id']
        else:
            print(f"✗ Failed to upload featured image: {response.status_code} - {response.text}")
            return None


def find_local_config():
    """Walk up directory tree from cwd to find nearest .wp-poster.json"""
    current = Path.cwd()
    while current != current.parent:
        config_path = current / '.wp-poster.json'
        if config_path.exists():
            return config_path
        current = current.parent
    # Check root directory
    config_path = current / '.wp-poster.json'
    if config_path.exists():
        return config_path
    return None


def get_config_paths():
    """Get all config paths in precedence order with their status."""
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
    local_config = find_local_config()

    paths = []
    seen = set()

    if local_config:
        paths.append(('Local project', local_config, True))
        seen.add(local_config.resolve())

    candidates = [
        ('User global', Path.home() / '.wp-poster.json'),
        ('XDG config', Path.home() / '.config/wp-poster/config.json'),
        ('App default', script_dir / '.wp-poster.json'),
    ]

    for name, path in candidates:
        resolved = path.resolve() if path.exists() else path
        if resolved not in seen:
            paths.append((name, path, path.exists()))
            if path.exists():
                seen.add(resolved)

    return paths


def load_config():
    """Load configuration from various sources.

    Precedence (first match wins):
    1. Local/project config (nearest .wp-poster.json walking up from cwd)
    2. User global (~/.wp-poster.json)
    3. XDG config (~/.config/wp-poster/config.json)
    4. App default (script directory .wp-poster.json)
    """
    config = {}

    # Get the directory where this script is located
    script_dir = Path(os.path.dirname(os.path.abspath(__file__)))

    # Find local config by walking up directory tree
    local_config = find_local_config()

    # Check for config file in various locations (highest priority first)
    config_paths = []
    if local_config:
        config_paths.append(local_config)
    config_paths.extend([
        Path.home() / '.wp-poster.json',
        Path.home() / '.config/wp-poster/config.json',
        script_dir / '.wp-poster.json',  # App default (lowest priority)
    ])

    for config_path in config_paths:
        if config_path.exists():
            with open(config_path, 'r') as f:
                config = json.load(f)
                break
    
    # Override with environment variables
    if 'WP_SITE_URL' in os.environ:
        config['site_url'] = os.environ['WP_SITE_URL']
    if 'WP_USERNAME' in os.environ:
        config['username'] = os.environ['WP_USERNAME']
    if 'WP_APP_PASSWORD' in os.environ:
        config['app_password'] = os.environ['WP_APP_PASSWORD']
    
    return config


def init_config():
    """Interactive configuration setup"""
    print("WordPress Poster Configuration Setup")
    print("=" * 40)
    print("\nThis will create a .wp-poster.json file in the current directory.\n")
    
    # Check if config already exists
    config_path = Path.cwd() / '.wp-poster.json'
    if config_path.exists():
        response = input("Config file already exists. Overwrite? (y/N): ").strip().lower()
        if response != 'y':
            print("Configuration cancelled.")
            return False
    
    config = {}
    
    # Get site URL
    while True:
        site_url = input("WordPress site URL (e.g., https://example.com): ").strip()
        if site_url:
            if not site_url.startswith(('http://', 'https://')):
                site_url = 'https://' + site_url
            config['site_url'] = site_url.rstrip('/')
            break
        print("Site URL is required.")
    
    # Get username
    while True:
        username = input("WordPress username: ").strip()
        if username:
            config['username'] = username
            break
        print("Username is required.")
    
    # Get application password
    while True:
        app_password = getpass.getpass("Application Password: ").strip()
        if app_password:
            # Remove spaces from the password if they were included
            app_password = app_password.replace(' ', '')
            config['app_password'] = app_password
            break
        print("Application Password is required.")
    
    # Test the connection
    print("\nTesting connection...")
    try:
        response = requests.get(
            f"{config['site_url']}/wp-json/wp/v2/users/me",
            auth=(config['username'], config['app_password']),
            timeout=10
        )
        if response.status_code == 200:
            user_data = response.json()
            print(f"✓ Successfully connected as: {user_data.get('name', config['username'])}")

            # Ask for default author context
            print("\nDefault author for posts (optional):")
            print("  Leave blank to use authenticated user, or enter username/ID")
            author_context = input("Default author: ").strip()
            if author_context:
                config['author_context'] = author_context
        elif response.status_code == 401:
            print("✗ Authentication failed. Please check your credentials.")
            retry = input("Would you like to try again? (y/N): ").strip().lower()
            if retry == 'y':
                return init_config()
            return False
        else:
            print(f"✗ Connection failed with status: {response.status_code}")
            print("Please check your site URL and try again.")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Connection error: {e}")
        print("Please check your site URL and internet connection.")
        return False
    
    # Save configuration
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"\n✓ Configuration saved to: {config_path}")
    print("\nYou can now use: wp-post <file>")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Post files with frontmatter to WordPress'
    )
    parser.add_argument('file', nargs='?', help='File to post')
    parser.add_argument('--site-url', help='WordPress site URL')
    parser.add_argument('--username', help='WordPress username')
    parser.add_argument('--app-password', help='WordPress application password')
    parser.add_argument('--draft', action='store_true', help='Post as draft')
    parser.add_argument('--init', action='store_true', help='Initialize configuration interactively')
    parser.add_argument('--test', action='store_true', help='Test mode: preview content without posting')
    parser.add_argument('--markdown', action='store_true', help='Convert markdown to Gutenberg blocks (default: post as-is)')
    
    args = parser.parse_args()
    
    # Handle --init flag
    if args.init:
        sys.exit(0 if init_config() else 1)
    
    # Handle --test flag (test mode doesn't need WordPress credentials)
    if args.test:
        if not args.file:
            parser.print_help()
            sys.exit(1)

        if not os.path.exists(args.file):
            print(f"Error: File '{args.file}' not found")
            sys.exit(1)

        # Create a dummy poster instance just for parsing
        poster = WordPressPost('https://example.com', 'user', 'pass')

        if args.markdown:
            print(f"Converting {args.file} to Gutenberg blocks...")
            frontmatter, content = poster.parse_markdown_file(args.file)

            print("Frontmatter:")
            print("=" * 40)
            print(yaml.dump(frontmatter, default_flow_style=False))

            print("Generated Gutenberg blocks:")
            print("=" * 40)
            print(content)
        else:
            print(f"Parsing {args.file} (no conversion)...")
            frontmatter, content = poster.parse_raw_file(args.file)

            print("Frontmatter:")
            print("=" * 40)
            print(yaml.dump(frontmatter, default_flow_style=False))

            print("Content:")
            print("=" * 40)
            print(content)
        sys.exit(0)
    
    # If no file provided and not init/test, show help and config info
    if not args.file:
        parser.print_help()
        print("\nConfig files (in precedence order):")
        config_paths = get_config_paths()
        active_found = False
        active_config = None
        for name, path, exists in config_paths:
            if exists and not active_found:
                print(f"  ✓ {name}: {path} (active)")
                active_found = True
                with open(path, 'r') as f:
                    active_config = json.load(f)
            elif exists:
                print(f"    {name}: {path}")
            else:
                print(f"    {name}: {path} (not found)")
        if not active_found:
            print("  No config file found. Run 'wp-post --init' to create one.")
        elif active_config and active_config.get('author_context'):
            print(f"\nDefault author: {active_config['author_context']}")
        sys.exit(1)
    
    # Load configuration
    config = load_config()
    
    # Override with command line arguments
    if args.site_url:
        config['site_url'] = args.site_url
    if args.username:
        config['username'] = args.username
    if args.app_password:
        config['app_password'] = args.app_password
    
    # Validate required configuration
    required = ['site_url', 'username', 'app_password']
    missing = [key for key in required if key not in config]
    
    if missing:
        print(f"Error: Missing configuration: {', '.join(missing)}")
        print("\nNo configuration found. Run 'wp-post --init' to set up your credentials interactively.")
        print("\nAlternatively, you can provide configuration through:")
        print("1. Command line arguments (--site-url, --username, --app-password)")
        print("2. Environment variables (WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD)")
        print("3. Config file (~/.wp-poster.json or .wp-poster.json in current directory)")
        print("\nExample config file:")
        print(json.dumps({
            "site_url": "https://your-site.com",
            "username": "your-username",
            "app_password": "your-app-password"
        }, indent=2))
        sys.exit(1)
    
    # Check if file exists
    if not os.path.exists(args.file):
        print(f"Error: File '{args.file}' not found")
        sys.exit(1)
    
    # Create poster instance and post
    poster = WordPressPost(
        config['site_url'],
        config['username'],
        config['app_password']
    )
    
    print(f"Posting {args.file} to {config['site_url']}...")
    result = poster.post_to_wordpress(
        args.file,
        draft=args.draft,
        raw=not args.markdown,
        author_context=config.get('author_context')
    )
    
    if result['success']:
        print(f"✓ Successfully posted: {result['title']}")
        print(f"  Post ID: {result['id']}")
        print(f"  URL: {result['url']}")
    else:
        print(f"✗ Failed to post: {result['error']}")
        sys.exit(1)


if __name__ == '__main__':
    main()