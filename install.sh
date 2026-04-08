#!/bin/bash

# WordPress Poster Installation Script
# Installs runtime files to /opt/wp-poster and symlinks the launcher into
# /usr/local/bin so every user on the system can run `wp-post`.

set -e

INSTALL_DIR="/opt/wp-poster"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Installing WordPress Poster..."

# Install Python dependencies
echo "Installing Python dependencies..."
sudo apt update && sudo apt install -y python3-requests python3-yaml python3-mistune

# Copy runtime files to a shared, world-readable location
echo "Installing runtime files to $INSTALL_DIR..."
sudo install -d -m 755 "$INSTALL_DIR"
sudo install -m 755 "$SRC_DIR/wp-post"      "$INSTALL_DIR/wp-post"
sudo install -m 644 "$SRC_DIR/wp-post.py"   "$INSTALL_DIR/wp-post.py"
sudo install -m 644 "$SRC_DIR/gutenberg.py" "$INSTALL_DIR/gutenberg.py"

# Create symlink for system-wide access
echo "Creating system-wide command..."
sudo ln -sf "$INSTALL_DIR/wp-post" /usr/local/bin/wp-post

# Create per-user config directory for the invoking user
mkdir -p ~/.config/wp-poster

echo ""
echo "✓ Installation complete!"
echo ""
echo "To configure WordPress credentials, you can:"
echo "1. Create a config file: ~/.wp-poster.json"
echo "2. Set environment variables: WP_SITE_URL, WP_USERNAME, WP_APP_PASSWORD"
echo "3. Pass credentials via command line arguments"
echo ""
echo "Example config file (~/.wp-poster.json):"
cat << 'EOF'
{
  "site_url": "https://your-site.com",
  "username": "your-username",
  "app_password": "xxxx xxxx xxxx xxxx"
}
EOF
echo ""
echo "To get a WordPress Application Password:"
echo "1. Go to WordPress Admin → Users → Your Profile"
echo "2. Scroll to 'Application Passwords'"
echo "3. Enter a name and click 'Add New Application Password'"
echo ""
echo "Usage: wp-post <markdown-file>"
echo "Example: wp-post example-post.md"