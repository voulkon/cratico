#!/bin/bash

echo "🔧 Custom OpenSearch entrypoint starting..."

# Create keystore first if it doesn't exist
echo "📦 Creating OpenSearch keystore..."
echo "y" | /usr/share/opensearch/bin/opensearch-keystore create

# Add AWS credentials to keystore
echo "🔑 Adding AWS Access Key to keystore..."
echo "$AWS_ACCESS_KEY_ID" | /usr/share/opensearch/bin/opensearch-keystore add --stdin s3.client.default.access_key

echo "🔐 Adding AWS Secret Key to keystore..."
echo "$AWS_SECRET_ACCESS_KEY" | /usr/share/opensearch/bin/opensearch-keystore add --stdin s3.client.default.secret_key

echo "✅ AWS credentials added to keystore successfully"

# List keystore contents for verification
echo "📋 Keystore contents:"
/usr/share/opensearch/bin/opensearch-keystore list

echo "🚀 Starting OpenSearch with original entrypoint..."
exec /usr/share/opensearch/opensearch-docker-entrypoint.sh "$@"
