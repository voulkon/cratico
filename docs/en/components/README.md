# Component Details

This directory contains detailed documentation for each component of the Crati.Co platform.

## Core Services (Required)

These services are essential for the platform to function:

- **[Backend API](./backend-api.md)** - Django REST API, business logic, and data models
- **Celery Worker** - Asynchronous task processing and background jobs
- **Celery Beat** - Scheduled task dispatcher (publishes via the broker, reads schedule from PostgreSQL)
- **Flower** - Celery task monitoring
- **Nginx** - Reverse proxy and load balancer
- **Frontend** - React application

## Data Network (Required in dev, externalizable in prod)

Stateful services that can be split out and run externally in production:

- **PostgreSQL** - Primary relational database with pgvector
- **Redis** - Caching and Celery result backend
- **RabbitMQ** - Message broker for task queue
- **PgBouncer** - PostgreSQL connection pooler (production only)

## Optional Services

These services can be disabled via environment variables:

### Search Layer
- **OpenSearch** - Full-text search engine (disable with `INDEX_THE_OPENSEARCH=false`)
- **OpenSearch Dashboards** - Search UI and exploration tool

### Observability Stack
- **Jaeger** - Distributed tracing (disable with `TRANSMIT_TO_JAEGER=false`)
- **Loki** - Log aggregation
- **Promtail** - Log collection agent
- **Grafana** - Unified observability dashboard

> **Note**: Detailed per-component pages are being added incrementally. Currently
> available: [Backend API](./backend-api.md). For the full architecture and
> component relationships, see the [Architecture Overview](../ARCHITECTURE.md).

## Component Relationships

For the authoritative component dependency map and service communication matrix,
see the [Architecture Overview diagram](../ARCHITECTURE.md#high-level-architecture-diagram).
Keeping a single source of truth avoids drift between docs.

## Health Check Endpoints

| From | To | Protocol | Port | Purpose |
|------|-----|----------|------|---------|
| Frontend | Nginx | HTTP | 80/443 | User interface |
| Nginx | Backend | HTTP | 8000 | API requests |
| Backend | PostgreSQL | PostgreSQL | 5432 | Data persistence |
| Backend | Redis | Redis | 6379 | Caching |
| Backend | RabbitMQ | AMQP | 5672 | Task queuing |
| Backend | OpenSearch | HTTP | 9200 | Document indexing |
| Backend | Jaeger | gRPC | 4317 | Trace submission |
| Worker | RabbitMQ | AMQP | 5672 | Task consumption |
| Worker | PostgreSQL | PostgreSQL | 5432 | Data access |
| Worker | OpenSearch | HTTP | 9200 | Document indexing |
| Promtail | Loki | HTTP | 3100 | Log shipping |
| Grafana | Loki | HTTP | 3100 | Log queries |

## Health Check Endpoints

| Service | Endpoint | Method | Expected Response |
|---------|----------|--------|-------------------|
| Backend | `/healthz/` | GET | 200 OK |
| RabbitMQ | n/a | CLI | `rabbitmq-diagnostics -q ping` |
| PostgreSQL | n/a | CLI | `pg_isready` |
| Redis | n/a | CLI | `redis-cli ping` |
| OpenSearch | `/_cluster/health` | GET | 200 OK |
| Loki | `/ready` | GET | 200 OK |

## Resource Requirements

### Minimum (Development)
- **CPU**: 4 cores
- **RAM**: 8 GB
- **Disk**: 20 GB

### Recommended (Production)
- **CPU**: 8 cores
- **RAM**: 16 GB
- **Disk**: 100 GB (SSD)

### Per-Service Memory Usage (Typical)

| Service | Development | Production |
|---------|-------------|------------|
| Backend | 512 MB | 1-2 GB |
| Worker | 1-2 GB | 2-4 GB |
| PostgreSQL | 512 MB | 2-4 GB |
| Redis | 256 MB | 512 MB - 2 GB |
| RabbitMQ | 256 MB | 512 MB - 1 GB |
| OpenSearch | 1 GB | 2-4 GB |
| Frontend | 256 MB | 512 MB |
| Nginx | 128 MB | 256 MB |
| Grafana | 256 MB | 512 MB |
| Loki | 256 MB | 512 MB - 1 GB |
| Jaeger | 256 MB | 512 MB - 1 GB |

## Scaling Strategies

### Horizontal Scaling
- **Worker**: Add more worker containers (`docker-compose up --scale worker=3`)
- **Backend**: Add multiple backend instances behind Nginx load balancer
- **PostgreSQL**: Add read replicas, use PgBouncer for connection pooling
- **OpenSearch**: Multi-node cluster deployment

### Vertical Scaling
- Adjust `CELERY_CONCURRENCY` for worker parallelism
- Increase `OPENSEARCH_JAVA_OPTS` heap size
- Tune PgBouncer pool sizes
- Optimize PostgreSQL shared_buffers and work_mem

## Monitoring Checklist

- [ ] Backend API response times (via Jaeger)
- [ ] Celery task success/failure rates (via Flower)
- [ ] Database connection pool usage (via PgBouncer stats)
- [ ] Redis memory usage
- [ ] RabbitMQ queue depths
- [ ] OpenSearch cluster health
- [ ] Disk usage on all volumes
- [ ] Container CPU/memory usage
- [ ] Application logs in Grafana/Loki

## Common Issues

### Backend/Worker can't connect to services
- **Symptom**: Connection refused errors
- **Cause**: Service names in environment variables don't match docker-compose service names
- **Fix**: Use docker-compose service names (e.g., `redis`, `db`, `rabbitmq`) not `localhost`

### Out of Memory (OOM) Errors
- **Symptom**: Container restarts, OOM killed in logs
- **Cause**: Insufficient memory allocation
- **Fix**: Reduce `CELERY_CONCURRENCY`, increase container memory limits, or set `CELERY_WORKER_MAX_MEMORY_PER_CHILD`

### Slow performance
- **Symptom**: High latency, timeouts
- **Cause**: Database queries, insufficient resources, or unoptimized code
- **Fix**: Enable tracing (`TRANSMIT_TO_JAEGER=true`), check slow query logs, add database indexes, optimize queries

### OpenSearch errors but don't need search
- **Symptom**: OpenSearch connection errors in logs
- **Cause**: OpenSearch not running or misconfigured
- **Fix**: Set `INDEX_THE_OPENSEARCH=false` to disable

## Security Hardening

1. **Network isolation**: Use Docker networks, don't expose internal ports
2. **Least privilege**: Run containers as non-root users where possible
3. **Secrets management**: Use Docker secrets or external secret managers
4. **TLS/SSL**: Enable HTTPS on Nginx, use TLS for database connections
5. **Authentication**: Enable Clerk authentication, protect admin interfaces
6. **Regular updates**: Keep Docker images and dependencies up to date
7. **Audit logging**: Enable comprehensive logging to Loki
8. **Rate limiting**: Configure Nginx rate limits
