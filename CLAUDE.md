# Claude Code Instructions

This project contains `wp-poster` - a tool for posting markdown files to WordPress via REST API.

## For Claude Code Sessions

The `wp-post` command is installed globally and can be used from any directory.

### Basic Usage
```bash
# Post a markdown file
wp-post filename.md

# Post as draft
wp-post filename.md --draft
```

### When Helping Users
1. **Check README.md** for complete usage and frontmatter syntax
2. **Reference comprehensive-test.md** for examples of all supported markdown features
3. **Use wp-post via Bash tool** - it's already installed globally
4. **Help create frontmatter** with proper WordPress fields (title, slug, status, etc.)

### Supported Features
- Full Gutenberg block generation
- Custom post types and taxonomies
- Featured images (local and remote)
- Inline images (uploads to WordPress media library)
- All standard markdown: lists, blockquotes, tables, code blocks
- Advanced: nested lists, multi-line blockquotes, strikethrough

### Configuration
- First-time: `wp-post --init` (creates `.wp-poster.json` in current directory)
- Each project directory can have its own WordPress config
- See README.md for all configuration options

### Testing
- Use `wp-post comprehensive-test.md` to verify all features work
- Check WordPress admin to confirm Gutenberg blocks render properly

The tool converts markdown directly to WordPress Gutenberg blocks, so posts edit cleanly in WordPress admin without block validation errors.