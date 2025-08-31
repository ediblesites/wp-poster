#!/bin/bash

# WordPress Poster Installation Script

echo "Installing WordPress Poster..."

# Install Python dependencies
echo "Installing Python dependencies..."
sudo apt update && sudo apt install -y python3-requests python3-yaml python3-markdown2

# Create symlink for system-wide access
echo "Creating system-wide command..."
sudo ln -sf "$(pwd)/wp-post" /usr/local/bin/wp-post

# Create config directory
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