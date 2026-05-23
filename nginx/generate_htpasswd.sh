#!/bin/sh

# Generate .htpasswd file from environment variables
if [ -n "$STAGING_USERNAME" ] && [ -n "$STAGING_PASSWORD" ]; then
    echo "Generating .htpasswd file..."
    htpasswd -cbB /etc/nginx/.htpasswd "$STAGING_USERNAME" "$STAGING_PASSWORD"
    echo ".htpasswd file generated successfully"
else
    echo "No staging credentials provided, skipping .htpasswd generation"
    # Create empty file so nginx doesn't fail
    touch /etc/nginx/.htpasswd
fi
