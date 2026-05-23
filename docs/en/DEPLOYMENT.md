# Deployment Guide

This guide covers deploying the Crati.Co platform in various configurations, from local development to multi-server production deployments.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start (Development)](#quick-start-development)
- [Production Deployment](#production-deployment)
  - [Single Server](#single-server-production)
  - [Multi-Server (Recommended)](#multi-server-production-recommended)
- [Configuration](#configuration)
- [Scaling](#scaling)
- [Monitoring](#monitoring)
- [Backup & Recovery](#backup--recovery)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Software Requirements
- Docker 20.10+
- Docker Compose 2.0+
- Git
- (Production) Domain name with DNS configured
- (Production) SSL/TLS certificates

### Hardware Requirements

#### Development
- **CPU**: 4 cores
- **RAM**: 8 GB
- **Disk**: 20 GB free space

#### Production (Single Server)
- **CPU**: 8 cores
- **RAM**: 16 GB
- **Disk**: 100 GB SSD

#### Production (Multi-Server)
- **App Server**: 4-8 cores, 8-16 GB RAM, 50 GB SSD
- **Database Server**: 4-8 cores, 8-16 GB RAM, 100 GB SSD
- **Search Server**: 4 cores, 8 GB RAM, 100 GB SSD

---

## Quick Start (Development)

### 1. Clone Repository

```bash
git clone https://github.com/voulkon/crati.git
cd crati
```

### 2. Create Environment File

```bash
cp .env_files/.env.local.secrets.example .env_files/.env.local.secrets
```

Edit `.env_files/.env.local.secrets` with your configuration:

```bash
# Minimal development configuration
POSTGRES_USER=local_user
POSTGRES_PASSWORD=local_pass
POSTGRES_DB=local_diavgia

DJANGO_SECRET_KEY=$(openssl rand -hex 32)
DEBUG=true
ALLOWED_HOSTS=localhost,127.0.0.1

RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest

# Optional: Disable non-essential services for faster startup
INDEX_THE_OPENSEARCH=false
TRANSMIT_TO_JAEGER=false
EXTRACT_THE_DOCS_FROM_PDFS=false
```

### 3. Start Services

```bash
# Start all services
docker-compose -f docker/docker-compose.yml --env-file=.env_files/.env.local.secrets up -d

# Or use the provided task
# (VS Code: Tasks: Run Task > Docker Compose (with DB) Up)
```

### 4. Run Migrations

```bash
docker-compose exec backend python manage.py migrate
```

### 5. Create Superuser

```bash
docker-compose exec backend python manage.py createsuperuser
```

### 6. Access Application

- **Frontend**: http://localhost (via Nginx)
- **Backend API**: http://localhost/api/
- **Django Admin**: http://localhost/admin/
- **Flower (Celery)**: http://localhost/flower/
- **Grafana**: http://localhost:3001
- **Jaeger**: http://localhost:16686

### 7. Stop Services

```bash
docker-compose -f docker/docker-compose.yml down
```

---

## Production Deployment

### Single Server Production

Deploy all services on a single server. Suitable for small to medium deployments.

#### 1. Prepare Server

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Create Docker network
docker network create coolify
```

#### 2. Clone and Configure

```bash
git clone https://github.com/voulkon/crati.git
cd crati
```

Create production environment file:

```bash
nano .env_files/.env.production.secrets
```

```bash
# Database
POSTGRES_USER=prod_user
POSTGRES_PASSWORD=$(openssl rand -base64 32)
POSTGRES_DB=crati_production
DB_HOST=db
DB_PORT=5432

# Django
DJANGO_SECRET_KEY=$(openssl rand -hex 50)
DEBUG=false
ALLOWED_HOSTS=app.example.com,www.app.example.com
FRONTEND_DOMAINS=https://app.example.com

# RabbitMQ
RABBITMQ_USER=crati_rabbitmq
RABBITMQ_PASSWORD=$(openssl rand -base64 32)

# Redis
REDIS_PASSWORD=$(openssl rand -base64 32)

# OpenSearch
OPENSEARCH_URL=http://opensearch:9200
INDEX_THE_OPENSEARCH=true

# Observability
TRANSMIT_TO_JAEGER=true
GRAFANA_ADMIN_PASSWORD=$(openssl rand -base64 32)

# Authentication (get from Clerk dashboard)
CLERK_JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
CLERK_SECRET_KEY=sk_live_...
CLERK_JWT_AUDIENCE=https://your-app.clerk.accounts.dev

# AWS (optional, for backups)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=crati-prod-backups

# GEMI API (optional)
GEMI_API_KEY=your_gemi_api_key

# Celery
CELERY_CONCURRENCY=4
CELERY_WORKER_MAX_MEMORY_PER_CHILD=3000000
LIGHT_WORKER=false

# Security
STEALTH_MODE=true
FLOWER_BASIC_AUTH=admin:$(openssl rand -base64 16)
```

#### 3. Deploy

```bash
docker-compose -f docker-compose.prod.yml --env-file=.env_files/.env.production.secrets up -d
```

#### 4. Run Migrations

```bash
docker-compose -f docker-compose.prod.yml exec backend python manage.py migrate
```

#### 5. Create Superuser

```bash
docker-compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

#### 6. Configure Reverse Proxy (Caddy/Nginx)

If using an external reverse proxy like Caddy:

```caddyfile
app.example.com {
    reverse_proxy localhost:80
}
```

---

### Multi-Server Production (Advanced)

For better performance and isolation, you can split services across multiple servers. This configuration uses the `docker-compose.prod-no-db.yml` file on the application server and connects to external PostgreSQL and OpenSearch instances.

#### Architecture

```
┌──────────────────┐
│   App Server     │  ← Stateless services
│  - Frontend      │
│  - Backend       │
│  - Workers       │
│  - Redis         │
│  - RabbitMQ      │
│  - Observability │
└────────┬─────────┘
         │
         ├─────────► ┌──────────────────┐
         │           │  Database Server │
         │           │  - PostgreSQL    │  (External/Managed)
         │           └──────────────────┘
         │
         └─────────► ┌──────────────────┐
                     │  Search Server   │
                     │  - OpenSearch    │  (External/Managed)
                     └──────────────────┘
```

#### Prerequisites

You'll need to set up PostgreSQL and OpenSearch separately:
- **PostgreSQL**: Use a managed service (AWS RDS, DigitalOcean, etc.) or deploy manually with pgvector extension
- **OpenSearch**: Use AWS OpenSearch Service, or deploy manually using Docker/Kubernetes

#### Application Server Setup

```bash
# On application server (e.g., 49.13.136.52)
cd crati
docker-compose -f docker-compose.prod-no-db.yml --env-file=.env_files/.env.app.secrets up -d
```

**Environment variables** (`.env_files/.env.app.secrets`):
```bash
# Database (external)
POSTGRES_USER=prod_user
POSTGRES_PASSWORD=<strong-password>
POSTGRES_DB=crati_production
DB_HOST=<database-host-or-ip>  # Your PostgreSQL server
DB_PORT=5432

# OpenSearch (external)
OPENSEARCH_URL=http://<opensearch-host-or-ip>:9200
INDEX_THE_OPENSEARCH=true

# Redis, RabbitMQ, etc. (running locally in app server)
# ... rest of configuration ...
```

#### Database Setup

Ensure your PostgreSQL database has:
- pgvector extension installed
- User with appropriate permissions
- Network access from application server

#### Networking & Security

1. **Firewall Rules**:
```bash
# Database server: Allow PostgreSQL only from app server
sudo ufw allow from <app-server-ip> to any port 5432

# Search server: Allow OpenSearch only from app server
sudo ufw allow from <app-server-ip> to any port 9200

# App server: Allow HTTP/HTTPS from anywhere
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

2. **SSL/TLS**: Use Caddy or Let's Encrypt for automatic HTTPS

3. **Private Network**: Use a VPN or cloud provider's private network for inter-server communication

4. **Managed Services**: Consider using managed PostgreSQL (AWS RDS, DigitalOcean) and OpenSearch services for easier setup and maintenance

---

## Configuration

### Environment-Specific Configuration

Create separate `.env` files for each environment:

```
.env_files/
├── .env.local.secrets          # Development
├── .env.preview-test.secrets   # Staging
└── .env.production.secrets     # Production
```

### Feature Flags for Different Environments

#### Development
```bash
DEBUG=true
INDEX_THE_OPENSEARCH=false  # Faster startup
TRANSMIT_TO_JAEGER=false    # Less overhead
EXTRACT_THE_DOCS_FROM_PDFS=false  # Optional
```

#### Staging/Preview
```bash
DEBUG=false
INDEX_THE_OPENSEARCH=true
TRANSMIT_TO_JAEGER=true
EXTRACT_THE_DOCS_FROM_PDFS=true
STAGING_MODE=true  # Basic auth protection
STAGING_USERNAME=preview
STAGING_PASSWORD=<secure-password>
```

#### Production
```bash
DEBUG=false
INDEX_THE_OPENSEARCH=true
TRANSMIT_TO_JAEGER=true
EXTRACT_THE_DOCS_FROM_PDFS=true
STEALTH_MODE=true
STEALTH_ALLOWLIST=true
```

### Database Migrations

```bash
# Check migration status
docker-compose exec backend python manage.py showmigrations

# Apply migrations
docker-compose exec backend python manage.py migrate

# Create new migration
docker-compose exec backend python manage.py makemigrations

# Rollback migration
docker-compose exec backend python manage.py migrate app_name migration_name
```

---

## Scaling

### Horizontal Scaling

#### Scale Workers
```bash
# Scale to 3 worker instances
docker-compose -f docker-compose.prod-no-db.yml up -d --scale worker=3
```

#### Scale Backend API
```yaml
# In docker-compose.prod-no-db.yml
backend:
  deploy:
    replicas: 3

# Update Nginx upstream
upstream backend {
    server backend:8000;
    # If using multiple instances, use swarm mode or external load balancer
}
```

### Vertical Scaling

#### Increase Worker Concurrency
```bash
CELERY_CONCURRENCY=8  # More concurrent tasks per worker
```

#### Increase Database Resources
```bash
# Adjust PostgreSQL settings
shared_buffers = 4GB
effective_cache_size = 12GB
work_mem = 64MB
```

#### Increase OpenSearch Heap
```bash
OPENSEARCH_JAVA_OPTS=-Xms4g -Xmx4g
```

### Auto-Scaling (Docker Swarm/Kubernetes)

For automatic scaling, consider:
- **Docker Swarm**: Built-in orchestration
- **Kubernetes**: Enterprise-grade orchestration
- **AWS ECS/Fargate**: Managed container service
- **Google Cloud Run**: Serverless container platform

---

## Monitoring

### Health Checks

```bash
# Backend health
curl http://localhost/healthz/

# Database
docker-compose exec db pg_isready -U $POSTGRES_USER

# OpenSearch
curl http://localhost:9200/_cluster/health

# RabbitMQ
docker-compose exec rabbitmq rabbitmq-diagnostics ping

# Redis
docker-compose exec redis redis-cli ping
```

### Accessing Monitoring Tools

- **Grafana**: `https://app.example.com/grafana/` (if proxied via Nginx)
- **Jaeger**: `https://app.example.com/jaeger/`
- **Flower**: `https://app.example.com/flower/`
- **OpenSearch Dashboards**: `http://search-server:5601`

### Setting Up Alerts

Configure alerts in Grafana for:
- High error rates
- Slow response times
- High memory usage
- Database connection pool exhaustion
- Celery queue depth

---

## Backup & Recovery

### Database Backups

#### Automated Backups (Cron)

```bash
# On database server or app server with database access
# Add to crontab: crontab -e

# Daily backup at 2 AM
0 2 * * * docker exec diavgeia_db pg_dump -U $POSTGRES_USER $POSTGRES_DB | gzip > /backups/db_$(date +\%Y\%m\%d).sql.gz
```

#### Manual Backup

```bash
# Backup database
docker-compose exec db pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup_$(date +%Y%m%d).sql

# Or with docker exec
docker exec diavgeia_db pg_dump -U postgres crati_production > backup.sql
```

#### Restore from Backup

```bash
# Stop application
docker-compose down

# Restore database
docker-compose up -d db
cat backup.sql | docker-compose exec -T db psql -U $POSTGRES_USER $POSTGRES_DB

# Start application
docker-compose up -d
```

### OpenSearch Snapshots

Configure S3 snapshot repository in OpenSearch:

```bash
# Register snapshot repository
curl -X PUT "opensearch:9200/_snapshot/s3_repository" -H 'Content-Type: application/json' -d'
{
  "type": "s3",
  "settings": {
    "bucket": "crati-opensearch-snapshots",
    "region": "eu-north-1"
  }
}'

# Create snapshot
curl -X PUT "opensearch:9200/_snapshot/s3_repository/snapshot_1"
```

### Volume Backups

```bash
# Backup all volumes
docker run --rm --volumes-from diavgeia_db -v $(pwd):/backup ubuntu tar czf /backup/volumes_backup.tar.gz /var/lib/postgresql/data
```

---

## Troubleshooting

### Services Won't Start

**Check logs:**
```bash
docker-compose logs --tail=100 backend
docker-compose logs --tail=100 worker
```

**Common issues:**
- Port conflicts: Check if ports are already in use (`netstat -tulpn | grep <port>`)
- Missing environment variables: Verify `.env` file
- Database not ready: Wait for database healthcheck

### Connection Refused Errors

**Cause**: Service names don't match docker-compose service definitions

**Fix**: Use service names (e.g., `redis`, `db`, `rabbitmq`) not `localhost` in environment variables

### Out of Memory

**Check memory usage:**
```bash
docker stats
```

**Solutions:**
- Reduce `CELERY_CONCURRENCY`
- Set `CELERY_WORKER_MAX_MEMORY_PER_CHILD`
- Increase server RAM
- Enable swap (not recommended for production)

### Database Connection Pool Exhausted

**Symptoms**: "Too many connections" error

**Solutions:**
- Use PgBouncer (already configured in production compose files)
- Reduce Django `CONN_MAX_AGE`
- Increase PostgreSQL `max_connections`

### Slow Performance

**Enable tracing:**
```bash
TRANSMIT_TO_JAEGER=true
```

**View traces in Jaeger to identify bottlenecks**

**Check database queries:**
```bash
DB_LOG_LEVEL=DEBUG
```

### OpenSearch Issues

**If you don't need search:**
```bash
INDEX_THE_OPENSEARCH=false
```

**Check cluster health:**
```bash
curl http://opensearch:9200/_cluster/health?pretty
```

---

## Security Checklist

- [ ] Change all default passwords
- [ ] Use strong, random `DJANGO_SECRET_KEY`
- [ ] Set `DEBUG=false` in production
- [ ] Configure restrictive `ALLOWED_HOSTS`
- [ ] Enable `STEALTH_MODE=true`
- [ ] Protect admin interfaces with basic auth
- [ ] Use HTTPS/TLS for all external connections
- [ ] Restrict database and OpenSearch access to app server only
- [ ] Keep Docker images and dependencies up to date
- [ ] Enable audit logging
- [ ] Regular security scanning of containers
- [ ] Backup regularly and test restore procedures

---

## Maintenance

### Updating the Application

```bash
# Pull latest code
git pull origin main

# Rebuild containers
docker-compose -f docker-compose.prod-no-db.yml build

# Restart with zero-downtime (if using swarm/k8s)
docker-compose -f docker-compose.prod-no-db.yml up -d

# Run migrations
docker-compose exec backend python manage.py migrate
```

### Cleaning Up

```bash
# Remove unused images
docker image prune -a

# Remove unused volumes
docker volume prune

# Remove stopped containers
docker container prune
```

---

## Support

For additional help:
- [Architecture Overview](./ARCHITECTURE.md)
- [Environment Variables Reference](./ENVIRONMENT_VARIABLES.md)
- [Component Documentation](./components/)
- GitHub Issues: https://github.com/voulkon/crati/issues
