# Environment Variables Reference

This document provides a comprehensive reference for all environment variables used in the Crati.Co platform.

## Quick Reference

### Required Variables
- `DATABASE_URL` or (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DB_HOST`, `DB_PORT`)
- `DJANGO_SECRET_KEY`
- `RABBITMQ_USER`, `RABBITMQ_PASSWORD`

### Recommended for Production
- `ALLOWED_HOSTS`
- `DEBUG=false`
- `CLERK_JWT_PUBLIC_KEY`, `CLERK_SECRET_KEY`

---

## Database Configuration

### PostgreSQL Connection

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes* | - | Full PostgreSQL connection string. Format: `postgresql://user:pass@host:port/dbname` |
| `POSTGRES_USER` | Yes* | - | PostgreSQL username |
| `POSTGRES_PASSWORD` | Yes* | - | PostgreSQL password |
| `POSTGRES_DB` | Yes* | - | PostgreSQL database name |
| `DB_HOST` | Yes* | `db` | PostgreSQL host (service name in Docker) |
| `DB_PORT` | No | `5432` | PostgreSQL port |
| `DB_LOG_LEVEL` | No | `WARNING` | Database query logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

**Note**: Either provide `DATABASE_URL` OR the individual variables (`POSTGRES_*`). `DATABASE_URL` takes precedence.

### Test Database

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TEST_DB_NAME` | No | `test_` + main DB | Test database name for running tests |
| `PG_TEST` | No | - | Flag to enable test database creation |

---

## Django Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DJANGO_SECRET_KEY` | Yes | - | Django secret key for cryptographic signing |
| `DEBUG` | No | `false` | Enable Django debug mode (`true`/`false`) |
| `ALLOWED_HOSTS` | Production | `localhost,127.0.0.1` | Comma-separated list of allowed hostnames |
| `FRONTEND_DOMAINS` | No | - | Comma-separated list of frontend domains for CORS |

### Django Admin Superuser

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DJANGO_SUPERUSER_USERNAME` | No | `admin` | Initial superuser username |
| `DJANGO_SUPERUSER_EMAIL` | No | `admin@example.com` | Initial superuser email |
| `DJANGO_SUPERUSER_PASSWORD` | No | - | Initial superuser password |
| `DJANGO_SUPERUSER_AUTO_UPDATE` | No | `false` | Auto-update superuser password on restart |

---

## Celery & Task Queue

### RabbitMQ

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RABBITMQ_USER` | Yes | `guest` | RabbitMQ username |
| `RABBITMQ_PASSWORD` | Yes | `guest` | RabbitMQ password |
| `CELERY_BROKER_URL` | No | Auto-generated | Full AMQP broker URL. Format: `amqp://user:pass@host:5672//` |

### Celery Worker Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CELERY_CONCURRENCY` | No | CPU count | Number of concurrent worker processes |
| `CELERY_WORKER_MAX_MEMORY_PER_CHILD` | No | `2000000` KB | Max memory per child process (KB) |
| `CELERY_WORKER_MAX_TASKS_PER_CHILD` | No | `200` | Max tasks per child before restart |
| `LIGHT_WORKER` | No | `false` | Use lightweight worker without PDF processing dependencies |
| `WORKER_LOG_LEVEL` | No | `INFO` | Worker logging level |
| `CELERY_DEBUG_PORT` | No | `8004` | Port for remote debugging Celery workers |

### Flower (Celery Monitoring)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FLOWER_BASIC_AUTH` | Recommended | - | Basic auth for Flower UI. Format: `username:password` |

---

## Redis Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDIS_HOST` | No | `redis` | Redis host (service name in Docker) |
| `REDIS_PORT` | No | `6379` | Redis port |
| `REDIS_DB` | No | `1` | Redis database number (0-15) |
| `REDIS_PASSWORD` | No | `` (empty) | Redis password (leave empty for no auth) |

---

## OpenSearch Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENSEARCH_URL` | No | `http://opensearch:9200` | OpenSearch endpoint URL |
| `OPENSEARCH_PASSWORD` | No | - | OpenSearch password (if security enabled) |
| `INDEX_THE_OPENSEARCH` | No | `true` | Enable/disable document indexing to OpenSearch |
| `OPENSEARCH_JAVA_OPTS` | No | `-Xms512m -Xmx512m` | JVM options for OpenSearch |

---

## Observability & Monitoring

### Jaeger (Distributed Tracing)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JAEGER_HOST` | No | `jaeger` | Jaeger host (service name) |
| `JAEGER_PORT` | No | `4317` | OTLP gRPC port |
| `TRANSMIT_TO_JAEGER` | No | `true` | Enable/disable sending traces to Jaeger |

### Grafana

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GRAFANA_ADMIN_PASSWORD` | Recommended | `admin` | Grafana admin password |

### Loki & Promtail

No specific environment variables required. Configuration is file-based in `docker/loki-config/` and `docker/promtail-config/`.

---

## Authentication & Security

### Clerk (Authentication Provider)

Clerk is controlled **server-side**. The backend exposes the active auth
methods and the publishable key at runtime via `GET /api/system/config/auth/`
— the frontend needs no Clerk build-time variable.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `USE_CLERK_AUTH` | No | `false` | Feature flag enabling Clerk authentication |
| `CLERK_JWT_PUBLIC_KEY` | When Clerk enabled | - | Public key for JWT verification (PEM format) |
| `CLERK_SECRET_KEY` | When Clerk enabled | - | Clerk secret key |
| `CLERK_PUBLISHABLE_KEY` | When Clerk enabled | - | Clerk publishable key (backend-owned, delivered to the frontend at runtime) |
| `CLERK_JWT_AUDIENCE` | Production | - | JWT audience claim (your Clerk instance URL) |

Clerk is only advertised to the frontend when `USE_CLERK_AUTH=true` **and** all
three Clerk keys are set; otherwise the app runs Django-only with a single
backend warning.

### Basic Authentication

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BASIC_AUTH_USER` | No | `admin` | Username for auxiliary services basic auth |
| `BASIC_AUTH_PASSWORD` | No | - | Password for auxiliary services basic auth |
| `BASIC_AUTH_HASH` | No | Auto-generated | Apache-style password hash for nginx |

### Stealth Mode

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `STEALTH_MODE` | No | `false` | Enable authentication requirements |
| `STEALTH_ALLOWLIST` | No | `false` | Enable allowlist-based access control |
| `REACT_APP_STEALTH_MODE` | Frontend | `false` | Frontend stealth mode flag |
| `REACT_APP_STEALTH_ALLOWLIST` | Frontend | `false` | Frontend allowlist flag |

### Staging Environment Protection

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `STAGING_MODE` | No | `false` | Enable basic auth on nginx for entire site |
| `STAGING_USERNAME` | No | - | Staging environment username |
| `STAGING_PASSWORD` | No | - | Staging environment password |

---

## External Services

### AWS S3

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AWS_ACCESS_KEY_ID` | Optional* | - | AWS access key for S3 backups |
| `AWS_SECRET_ACCESS_KEY` | Optional* | - | AWS secret key |
| `AWS_STORAGE_BUCKET_NAME` | No | `crati-backups` | S3 bucket name for backups |
| `AWS_S3_REGION_NAME` | No | `eu-north-1` | AWS region |
| `AWS_DEFAULT_REGION` | No | `eu-north-1` | AWS default region (for OpenSearch snapshot) |
| `AWS_BEARER_TOKEN_BEDROCK` | No | - | Bearer token for AWS Bedrock (ML features) |

**Note**: Only required if you want to use S3 for backups or OpenSearch snapshots.

### GEMI API (Greek Company Registry)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMI_API_KEY` | Optional* | - | API key for GEMI service |
| `HAVE_AFM_FETCH_JOB` | No | `true` | Enable/disable automatic company data fetching |

**Note**: Only required if you want to fetch company data from GEMI.

---

## Feature Flags

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `INDEX_THE_OPENSEARCH` | No | `true` | Enable document indexing to OpenSearch |
| `TRANSMIT_TO_JAEGER` | No | `true` | Enable distributed tracing |
| `EXTRACT_THE_DOCS_FROM_PDFS` | No | `true` | Enable PDF text extraction |
| `HAVE_AFM_FETCH_JOB` | No | `true` | Enable company data fetching jobs |
| `LIGHT_WORKER` | No | `false` | Use lightweight worker (no PDF dependencies) |

---

## Frontend Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REACT_APP_API_URL` | Yes | - | Backend API base URL |
| `REACT_APP_STEALTH_MODE` | No | `false` | Enable frontend authentication |
| `REACT_APP_STEALTH_ALLOWLIST` | No | `false` | Enable allowlist checks |

Note: auth methods (Clerk/Django) are **not** frontend variables — they come
from the backend at runtime via `/api/system/config/auth/`.

---

## Logging Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BACKEND_LOG_LEVEL` | No | `INFO` | Backend application log level |
| `WORKER_LOG_LEVEL` | No | `INFO` | Celery worker log level |
| `DB_LOG_LEVEL` | No | `WARNING` | Database query log level |

Valid levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

---

## Service URLs (Coolify/Production)

These are typically auto-generated by Coolify or your orchestration platform:

| Variable | Description |
|----------|-------------|
| `SERVICE_URL_NGINX` | Public URL for the application |
| `SERVICE_FQDN_NGINX` | Fully qualified domain name |
| `SERVICE_FQDN_REDIS_COMMANDER` | FQDN for Redis Commander (optional) |

---

## Environment File Examples

### Development (`.env.local.secrets`)
```bash
# Database
POSTGRES_USER=local_user
POSTGRES_PASSWORD=local_pass
POSTGRES_DB=local_diavgia
DB_HOST=db
DB_PORT=5432

# Django
DJANGO_SECRET_KEY=your_secret_key_here
DEBUG=true
ALLOWED_HOSTS=localhost,127.0.0.1

# RabbitMQ
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest

# Redis (no password for local)
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=

# Feature flags (optional services disabled)
INDEX_THE_OPENSEARCH=false
TRANSMIT_TO_JAEGER=false
EXTRACT_THE_DOCS_FROM_PDFS=false
```

### Production (`.env.production.secrets`)
```bash
# Database (remote)
DATABASE_URL=postgresql://user:pass@db-server.com:5432/dbname

# Django
DJANGO_SECRET_KEY=strong_random_secret_key
DEBUG=false
ALLOWED_HOSTS=app.example.com,www.app.example.com
FRONTEND_DOMAINS=https://app.example.com

# RabbitMQ
RABBITMQ_USER=prod_rabbitmq_user
RABBITMQ_PASSWORD=strong_rabbitmq_password

# Redis
REDIS_HOST=redis
REDIS_PASSWORD=strong_redis_password

# OpenSearch (remote)
OPENSEARCH_URL=http://opensearch-server.com:9200
INDEX_THE_OPENSEARCH=true

# Observability
TRANSMIT_TO_JAEGER=true
GRAFANA_ADMIN_PASSWORD=strong_grafana_password

# Clerk Authentication
CLERK_JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
CLERK_SECRET_KEY=sk_live_...
CLERK_JWT_AUDIENCE=https://your-app.clerk.accounts.dev

# AWS
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=your-backup-bucket

# GEMI
GEMI_API_KEY=your_gemi_api_key

# Celery
CELERY_CONCURRENCY=4
CELERY_WORKER_MAX_MEMORY_PER_CHILD=3000000
LIGHT_WORKER=false

# Security
STEALTH_MODE=true
FLOWER_BASIC_AUTH=admin:strong_password
```

---

## Variable Precedence

1. **Environment variables** from `.env` files take precedence
2. **Docker Compose** `environment:` section overrides `.env` files
3. **Defaults** in application code apply when nothing is set

---

## Security Best Practices

1. **Never commit** `.env` files to version control
2. Use **strong random values** for secrets in production
3. **Rotate credentials** regularly
4. Use **secret management** systems (AWS Secrets Manager, Vault) for production
5. Enable **authentication** (`STEALTH_MODE=true`) in production
6. Use **TLS/SSL** for all external connections in production
7. Set **restrictive ALLOWED_HOSTS** in production

---

## Validation

To check if your environment is properly configured:

```bash
# Check Django configuration
docker-compose exec backend python manage.py check

# Test database connection
docker-compose exec backend python manage.py dbshell

# Verify Celery connectivity
docker-compose exec worker celery -A diavgeia_project inspect ping

# Check OpenSearch connection
docker-compose exec backend python opensearch_test_connection.py
```

---

## Troubleshooting

### Database Connection Issues
- Verify `DATABASE_URL` or individual `POSTGRES_*` variables are correct
- Check `DB_HOST` matches your docker-compose service name
- Ensure database service is healthy: `docker-compose ps db`

### Celery Not Processing Tasks
- Check `CELERY_BROKER_URL` or `RABBITMQ_*` variables
- Verify RabbitMQ is running: `docker-compose ps rabbitmq`
- Check worker logs: `docker-compose logs worker`

### OpenSearch Connection Errors
- If you don't need search, set `INDEX_THE_OPENSEARCH=false`
- Verify `OPENSEARCH_URL` is accessible from worker/backend containers
- Check OpenSearch health: `curl http://opensearch:9200/_cluster/health`

### Tracing Overhead
- If Jaeger causes performance issues, set `TRANSMIT_TO_JAEGER=false`
- This disables tracing without affecting core functionality
