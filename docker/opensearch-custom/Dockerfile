FROM opensearchproject/opensearch:3

# Copy custom configuration if needed
COPY opensearch.yml /usr/share/opensearch/config/

# Install plugins with error handling
# Install ICU Analysis plugin (for Unicode text analysis)
RUN bin/opensearch-plugin install --batch analysis-icu || \
    (echo "Failed to install analysis-icu, continuing..." && exit 0)

# Install S3 plugin for repository backups
RUN bin/opensearch-plugin install --batch repository-s3 || \
    (echo "Failed to install repository-s3, continuing..." && exit 0)

# Set env vars (these will be overridden by docker-compose at runtime)
ENV AWS_ACCESS_KEY_ID=changeme
ENV AWS_SECRET_ACCESS_KEY=changeme

# Add credentials to keystore at container start (not build time)
COPY --chmod=755 opensearch-entrypoint.sh /usr/share/opensearch/bin/opensearch-entrypoint.sh
ENTRYPOINT ["/usr/share/opensearch/bin/opensearch-entrypoint.sh"]
