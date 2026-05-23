# Backend API Component

## Overview

The Backend API is a Django-based REST API that serves as the core application server. It handles:
- User authentication and authorization (via Clerk)
- Business logic for document processing
- Database operations
- Task scheduling to Celery workers
- Full-text search queries (to OpenSearch)
- Real-time monitoring and tracing

## Technology Stack

- **Django 4.2+** - Web framework
- **Django REST Framework** - REST API toolkit
- **Psycopg2** - PostgreSQL adapter
- **Celery** - Task queue client
- **OpenTelemetry** - Distributed tracing instrumentation
- **Poetry** - Dependency management

## Architecture

```
┌─────────────────────────────────────────┐
│         Frontend (React)                │
└──────────────┬──────────────────────────┘
               │ HTTP/JSON
               ▼
┌─────────────────────────────────────────┐
│            Nginx Proxy                  │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│         Backend API (Django)            │
│  ┌─────────────────────────────────┐   │
│  │  Authentication Middleware      │   │
│  │  (Clerk JWT verification)       │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │  API Views (DRF)                │   │
│  │  - Documents API                │   │
│  │  - Search API                   │   │
│  │  - Analytics API                │   │
│  │  - Admin API                    │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │  Business Logic Layer           │   │
│  │  - Document processing          │   │
│  │  - Search orchestration         │   │
│  │  - User management              │   │
│  └─────────────────────────────────┘   │
│  ┌─────────────────────────────────┐   │
│  │  Data Layer (Django ORM)        │   │
│  └─────────────────────────────────┘   │
└──────┬──────┬──────┬──────┬────────────┘
       │      │      │      │
       ▼      ▼      ▼      ▼
      DB   Redis  RabbitMQ OpenSearch
```

## Key Features

### 1. Authentication & Authorization
- **Clerk Integration**: JWT-based authentication
- **Stealth Mode**: Optional authentication bypass for development
- **Allowlist**: Optional IP/user-based access control
- **Security Tracing**: All auth events logged to Jaeger

### 2. Document Management
- CRUD operations for government documents
- Metadata extraction and storage
- PDF file management (via S3)
- Document status tracking

### 3. Search Capabilities
- Full-text search via OpenSearch (optional)
- Semantic search using pgvector embeddings
- Hybrid search combining both approaches
- Search result ranking and filtering

### 4. Task Management
- Async task submission to Celery
- Task status monitoring
- Periodic task scheduling (via Celery Beat)
- Task retry logic

### 5. Analytics & Reporting
- Document statistics
- User activity tracking
- Top counterparts analysis
- Custom report generation

## API Endpoints

### Health Check
```
GET /healthz/
```
Returns service health status

### Authentication
```
POST /api/auth/login/
POST /api/auth/logout/
GET /api/auth/me/
```

### Documents
```
GET    /api/documents/              # List documents
GET    /api/documents/{id}/         # Get document details
POST   /api/documents/              # Create document
PATCH  /api/documents/{id}/         # Update document
DELETE /api/documents/{id}/         # Delete document
GET    /api/documents/search/       # Search documents
```

### Analytics
```
GET /api/analytics/stats/           # Overall statistics
GET /api/analytics/top-counterparts/ # Top organizations
GET /api/analytics/trends/          # Time-based trends
```

### Admin
```
GET  /admin/                        # Django admin interface
POST /api/admin/reindex/            # Trigger OpenSearch reindex
POST /api/admin/cleanup/            # Run cleanup tasks
```

## Configuration

### Environment Variables

See [Environment Variables Reference](../ENVIRONMENT_VARIABLES.md) for complete list. Key variables:

```bash
# Core
DATABASE_URL=postgresql://user:pass@host:port/dbname
DJANGO_SECRET_KEY=your_secret_key
DEBUG=false
ALLOWED_HOSTS=app.example.com

# Authentication
CLERK_JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----..."
CLERK_JWT_AUDIENCE=https://your-app.clerk.accounts.dev

# Services
REDIS_HOST=redis
RABBITMQ_USER=user
RABBITMQ_PASSWORD=pass
OPENSEARCH_URL=http://opensearch:9200

# Features
INDEX_THE_OPENSEARCH=true
TRANSMIT_TO_JAEGER=true
STEALTH_MODE=true
```

### Django Settings Structure

Settings are split across multiple files in `backend/diavgeia_project/settings/`:

- `base.py` - Common settings for all environments
- `database.py` - Database configuration
- `celery.py` - Celery configuration
- `opensearch.py` - OpenSearch configuration
- `logging.py` - Logging configuration
- `auth.py` - Authentication settings

## Tracing & Observability

### OpenTelemetry Integration

The backend is instrumented with OpenTelemetry for distributed tracing:

```python
from diavgeia_project.otel_setup import setup_tracing

tracer = setup_tracing(service_name="backend-api")

with tracer.start_as_current_span("process_document") as span:
    span.set_attribute("document.id", doc_id)
    # ... processing logic ...
```

Traces are automatically exported to Jaeger when `TRANSMIT_TO_JAEGER=true`.

### Security Event Tracing

Security events are logged using the `SecurityTracer`:

```python
from diavgeia_project.otel_setup import security_tracer

security_tracer.log_security_event(
    event_type="authentication.failed",
    details={"reason": "Invalid token"},
    user=user,
    ip=request.META.get('REMOTE_ADDR'),
    severity="WARNING"
)
```

### Logging

Logs are structured and sent to stdout, collected by Promtail, and aggregated in Loki:

```python
import logging

logger = logging.getLogger(__name__)
logger.info("Document processed", extra={
    "document_id": doc.id,
    "processing_time": elapsed,
})
```

## Database Models

Key models in the application:

### Document Models
- `Document` - Main document record
- `DocumentVersion` - Version history
- `DocumentMetadata` - Extracted metadata
- `DocumentFile` - File storage references

### User Models
- `CustomUser` - Extended user model
- `UserProfile` - User preferences
- `AccessLog` - Audit trail

### Search Models
- `SearchQuery` - Search history
- `SearchResult` - Cached results

## Task Submission

Submit tasks to Celery workers:

```python
from core.tasks import process_document

# Fire and forget
process_document.delay(document_id)

# Get task ID for tracking
task = process_document.apply_async(
    args=[document_id],
    countdown=60  # Delay 60 seconds
)
task_id = task.id
```

## Performance Optimization

### Caching Strategy

```python
from django.core.cache import cache

# Cache document details
cache_key = f"document:{document_id}"
cached_data = cache.get(cache_key)

if not cached_data:
    cached_data = Document.objects.get(id=document_id).to_dict()
    cache.set(cache_key, cached_data, timeout=3600)
```

### Database Query Optimization

- Use `select_related()` for foreign keys
- Use `prefetch_related()` for many-to-many
- Add database indexes on frequently queried fields
- Use `only()` and `defer()` to limit fetched fields

### Connection Pooling

In production, use PgBouncer for connection pooling:

```bash
DATABASE_URL=postgresql://user:pass@pgbouncer:5432/dbname
```

## Development

### Running Locally

```bash
# Install dependencies
cd backend
poetry install

# Run migrations
poetry run python manage.py migrate

# Create superuser
poetry run python manage.py createsuperuser

# Start development server
poetry run python manage.py runserver 8000
```

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run specific test file
poetry run pytest tests/test_documents.py

# Run with coverage
poetry run pytest --cov=api --cov=core
```

### Debug Configuration

Enable debug logging:

```bash
DEBUG=true
BACKEND_LOG_LEVEL=DEBUG
DB_LOG_LEVEL=DEBUG
```

Attach debugger (VS Code):
```json
{
    "type": "python",
    "request": "attach",
    "name": "Attach to Backend",
    "connect": {
        "host": "localhost",
        "port": 8001
    },
    "pathMappings": [{
        "localRoot": "${workspaceFolder}/backend",
        "remoteRoot": "/code"
    }]
}
```

## Deployment

### Docker Build

```dockerfile
FROM python:3.11-slim

# Install dependencies
WORKDIR /code
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry install --no-dev

# Copy application
COPY . .

# Run migrations and start server
CMD ["sh", "-c", "poetry run python manage.py migrate && poetry run gunicorn diavgeia_project.wsgi:application --bind 0.0.0.0:8000"]
```

### Health Checks

Docker health check:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/healthz/"]
  interval: 30s
  timeout: 10s
  retries: 3
```

### Scaling

Horizontal scaling behind Nginx:

```yaml
backend:
  deploy:
    replicas: 3
```

## Monitoring

### Key Metrics to Monitor

1. **Request rate**: Requests per second
2. **Response time**: p50, p95, p99 latency
3. **Error rate**: 4xx and 5xx responses
4. **Database connections**: Active/idle connections
5. **Cache hit rate**: Redis cache effectiveness
6. **Task queue depth**: Pending Celery tasks

### Grafana Dashboards

Pre-configured dashboards available in `docker/grafana-provisioning/`:
- API Performance Dashboard
- Database Performance Dashboard
- Cache Performance Dashboard

### Alerting Rules

Set up alerts for:
- Response time > 2s for p95
- Error rate > 1%
- Database connection pool > 80% utilized
- Task queue depth > 1000

## Troubleshooting

### Backend won't start

**Check logs:**
```bash
docker-compose logs backend
```

**Common issues:**
- Database not accessible: Check `DATABASE_URL` and database health
- Missing migrations: Run `docker-compose exec backend python manage.py migrate`
- Invalid secret key: Set `DJANGO_SECRET_KEY` in environment

### 500 Internal Server Error

**Enable debug mode temporarily:**
```bash
DEBUG=true docker-compose up backend
```

**Check application logs in Grafana/Loki**

### Slow API responses

**Enable tracing:**
```bash
TRANSMIT_TO_JAEGER=true
```

**View traces in Jaeger UI**: `http://localhost:16686`

**Check database slow query log:**
```bash
DB_LOG_LEVEL=DEBUG
```

### Memory leaks

**Monitor memory usage:**
```bash
docker stats backend
```

**Check for unclosed database connections:**
```sql
SELECT count(*) FROM pg_stat_activity WHERE datname = 'your_db';
```

## Security Considerations

1. **JWT Validation**: All requests validated against Clerk public key
2. **CORS**: Restrictive CORS policy based on `FRONTEND_DOMAINS`
3. **Rate Limiting**: Nginx rate limiting on API endpoints
4. **SQL Injection**: Protected by Django ORM parameterization
5. **XSS**: Django template escaping enabled
6. **CSRF**: CSRF tokens for state-changing operations
7. **Secrets**: Never log sensitive data, use environment variables

## Further Reading

- [Django Documentation](https://docs.djangoproject.com/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)
- [Celery Documentation](https://docs.celeryproject.org/)
