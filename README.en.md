# Crati.Co Platform

*Read this in other languages: [English](README.en.md) | [Ελληνικά](README.el.md)*

> **A modern, scalable platform for processing and analyzing Greek government transparency documents**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Django 4.2+](https://img.shields.io/badge/django-4.2+-green.svg)](https://www.djangoproject.com/)
[![React 18](https://img.shields.io/badge/react-18-blue.svg)](https://reactjs.org/)

## Overview

The Crati.Co platform is a comprehensive distributed system for working with documents and relationships from the Greek government transparency portal (Diavgeia). It:

- **ingests** decisions published on Diavgeia via its public api,
- **processes** them (text extraction, entity/relationship mapping, analytics), and
- **analyzes** them through search, exploration, and monitoring tools.

### What it does

**Search & Explore**
- **Full-text search** across all decisions, powered by OpenSearch
- **Semantic search** using vector embeddings (foundation laid, not yet implemented)
- **Relationship exploration** — decisions are not just documents; the platform maps who is connected to what: companies receiving money, people tied to companies, signers of decisions and units beloging to organizations, organization graph with all its subcomponents, etc.
- **Value-based browsing** — sort and filter decisions by highest value, and refine the context you care about (direct assignments, payments, etc.).

**Monitoring & Tracking**
- **Bookmarks & folders** — save decisions you care about, organize them into folders, and share them with collaborators (e.g. journalists working on different cases). A folder can be published as a **public shareable page**, so you can gather all decisions relevant to a story and send a single link to anyone.
- **Custom alerts** — define your own criteria ("decisions from this organization, between this value range, of this type…") and get notified when matching decisions appear. Each subscription can be marked as "AI summary": instead of raw links, you get an AI-written summary of every matching decision, plus a digest that summarizes the summaries — useful for high-volume subscriptions you don't want to open one by one.

**AI assistance (bring your own key)**
- The platform integrates with AI providers via [OpenRouter](https://openrouter.ai/) — you supply your own API key, so you control which model you use and what you pay. (A shared "SYSTEM" key fallback is planned for users who don't want to manage their own key — not yet enabled.)
- **On-the-spot summaries** — ask for an AI summary of any decision while browsing it.
- **Subscription digests** — as above, alert subscriptions can summarize each matching decision automatically and produce a digest across them.
- **Usage & cost transparency** — every AI interaction (what was asked, which model, how much it cost) is logged and visible on a dedicated usage page.

**Built to expand**

The architecture leaves plenty of room for growth:
- **Decision substance extraction** — pull the one sentence that matters out of each
decision ("To pay company X for building a kiosk in the main square"), skipping the
boilerplate: the "Taking into consideration" ("Λαμβάνοντας υπ'όψιν") list of cited laws, the formal
"We decide:" wording, and the signature block. Titles like "Payment decision 102941"
carry no meaning, so this is what makes decisions searchable by what they actually
do. Contributions here: pattern rules for the boilerplate sections, a small
evaluation set of hand-marked operative sentences, and wiring the extractor into
the ingestion pipeline.
- **Better AI quality & custom pipelines** — the current AI features work, but the prompts are basic and summaries tend toward verbose restatements rather than the crisp one-liner we want. Longer term the vision is a **user-built processing pipeline**: the user composes steps like "extract the text between 'Αποφασίζουμε' and the signature block → feed that to the AI with this prompt → store the result for the next pipeline to use". This would make AI processing transparent, tunable, and reusable instead of a fixed black box.
- Integration with **more external sources**, such as **Pothen Esches** (Πόθεν Έσχες — "where did you get them from"), the platform where all politicians declare their assets. A scraper prototype already exists as a wireframe in [`backend/pothen`](backend/pothen/) — see its [README](backend/pothen/README.md) — covering declaration scraping, PDF downloading, and structured parsing.
- **Real-time updates** — re-ingest Diavgeia continuously throughout the day so new decisions appear shortly after they are published.
- **User interactions** — let users share and discuss interesting decisions with each other (e.g. a journalist sending a tip to a colleague or assistant).

**See [`docs/en/ROADMAP.md`](docs/en/ROADMAP.md) for the full roadmap**, including where contributions are most welcome.

It also provides document analytics and integrations with external services like GEMI (Greek company registry).

### Key Features

-  **Full-text & Semantic Search** - OpenSearch and pgvector-powered search
-  **PDF Processing** - Automated text extraction and analysis
-  **Analytics Dashboard** - Document statistics and insights
-  **Asynchronous Processing** - Celery-based task queue
-  **Observability** - Distributed tracing with Jaeger, logs with Loki/Grafana stack
-  **Authentication** - Django native and Clerk-based JWT authentication
-  **Modular Design** - Enable/disable features via feature flags and environment variables
-  **Containerized** - Full Docker Compose setup for easy deployment
-  **Scalable** - Horizontal and vertical scaling options

## Architecture

The platform uses a microservices architecture with the following components:

```
┌─────────────┐
│   Frontend  │ (React)
└──────┬──────┘
       │
┌──────▼──────┐
│    Nginx    │ (Reverse Proxy)
└──────┬──────┘
       │
       ├─────► Backend API (Django + DRF)
       │           ├─── PostgreSQL (pgvector)
       │           ├─── Redis (Cache)
       │           ├─── RabbitMQ (Queue)
       │           └─── OpenSearch (optional)
       │
       ├─────► Celery Workers (Task Processing)
       │
       └─────► Observability Stack (optional)
                   ├─── Jaeger (Tracing)
                   ├─── Loki (Logs)
                   ├─── Grafana (Dashboards)
                   └─── Flower (Celery Monitor)
```

**See [Architecture Documentation](docs/en/ARCHITECTURE.md) for detailed diagrams and explanations.**

## Quick Start

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- 8 GB RAM minimum
- 20 GB free disk space

### Development Setup

1. **Clone the repository**

```bash
git clone https://github.com/voulkon/crati.git
cd crati
```

2. **Create environment file**

```bash
cp .env_files/.env.local.secrets.example .env_files/.env.local.secrets
```

Edit `.env_files/.env.local.secrets`:

```bash
# Minimal configuration for quick start
POSTGRES_USER=local_user
POSTGRES_PASSWORD=local_pass
POSTGRES_DB=local_diavgia
DJANGO_SECRET_KEY=$(openssl rand -hex 32)
DEBUG=true

# Disable optional services for faster startup (optional)
INDEX_THE_OPENSEARCH=false
TRANSMIT_TO_JAEGER=false
```

3. **Start the stack**

Minimal stack (no observability — logs go to rolling files, tracing degrades to no-op):

```bash
docker-compose -f docker/docker-compose.yml --env-file=.env_files/.env.local.secrets up -d
```

Full stack with observability (Jaeger, Loki, Promtail, Grafana):

```bash
docker-compose -f docker/docker-compose.yml --env-file=.env_files/.env.local.secrets --profile observability up -d
```

4. **Access the application**

Migrations, superuser creation, feature-flag initialization and static file
collection all run automatically on backend startup (see
[`backend/entrypoint.sh`](backend/entrypoint.sh)) — no manual steps needed.

- **Frontend**: http://localhost
- **API**: http://localhost/api/
- **Admin**: http://localhost/admin/
- **Flower (Celery)**: http://localhost:5555 (direct host port — media/assets are not served correctly through the nginx proxy)

Only when started with `--profile observability`:

- **Grafana**: http://localhost:3001
- **Jaeger**: http://localhost:16686

## Documentation

### Core Documentation

- **[Architecture Overview](docs/en/ARCHITECTURE.md)** - System design, components, and data flow
- **[Deployment Guide](docs/en/DEPLOYMENT.md)** - Local, single-server, and multi-server deployment
- **[Environment Variables](docs/en/ENVIRONMENT_VARIABLES.md)** - Complete configuration reference
- **[Component Details](docs/en/components/)** - Deep dive into each service

### Component Guides

- [Backend API](docs/en/components/backend-api.md) - Django REST API documentation
- [Celery Workers](docs/en/components/) - Task processing and background jobs
- [Frontend](docs/en/components/) - React application
- [PostgreSQL](docs/en/components/) - Database setup and optimization
- [OpenSearch](docs/en/components/) - Search configuration
- [Observability Stack](docs/en/components/) - Jaeger, Loki, Grafana setup

## Configuration

### Feature Flags

The platform is highly modular and configured via feature flags: each flag can be
set as an environment variable or overridden at runtime from the admin interface
(Database is the highest priority, then environment variables, then the code default).

> **Single source of truth:** the full, up-to-date list of flags (≈40, with descriptions,
> defaults and categories) lives in [`KNOWN_FLAGS`](backend/core/services/feature_flag_service.py)
> (`FeatureFlagService.KNOWN_FLAGS` in `backend/core/services/feature_flag_service.py`).
> The table below only shows the flags most relevant when first running the stack.

| Flag | Default | Description |
|------|---------|-------------|
| `EXTRACT_THE_DOCS_FROM_PDFS` | `true` | Enable PDF text extraction (use wisely - it requires plenty of storage) |
| `INDEX_THE_OPENSEARCH` | `true` | Enable OpenSearch full-text indexing (it has no effect if `EXTRACT_THE_DOCS_FROM_PDFS`) |
| `TRANSMIT_TO_JAEGER` | `false` | Enable distributed tracing (requires service restart) |
| `HAVE_AFM_FETCH_JOB` | `true` | Enable company data fetching |
| `STEALTH_MODE` | `false` | Require authentication for all API endpoints |
| `DEBUG` | `false` | Django debug mode |

**For lightweight development**: Disable OpenSearch and Jaeger to reduce resource usage:

```bash
INDEX_THE_OPENSEARCH=false
TRANSMIT_TO_JAEGER=false
```

See [Environment Variables Reference](docs/en/ENVIRONMENT_VARIABLES.md) for complete list.

## [W] Production Deployment

### Single-Server Deployment

```bash
# Use production docker-compose
docker-compose -f docker-compose.prod.yml --env-file=.env_files/.env.production.secrets up -d
```

### Multi-Server Deployment (Advanced)

For larger deployments, split services across multiple servers:

- **App Server**: Backend, workers, Redis, RabbitMQ, observability
- **Database**: External PostgreSQL instance (managed service or self-hosted)
- **Search**: External OpenSearch instance (AWS OpenSearch or self-hosted)

Use `docker-compose.prod-no-db.yml` on the application server and configure external database/search connections.

**See [Deployment Guide](docs/en/DEPLOYMENT.md) for detailed instructions.**

## + Development

### Project Structure

```
crati/
├── backend/                 # Django application
│   ├── api/                 # REST API endpoints
│   ├── core/                # Core business logic
│   ├── diavgeia_project/    # Django settings
│   ├── docs/                # API documentation
│   ├── users/               # User management
│   └── manage.py
├── frontend/                # React application
├── docker/                  # Docker configurations
│   ├── Dockerfile.backend
│   ├── Dockerfile.worker
│   ├── Dockerfile.frontend
│   └── docker-compose.yml
├── docs/                    # Platform documentation
├── nginx/                   # Nginx configurations
├── .env_files/              # Environment configurations
└── docker-compose.*.yml     # Deployment configurations
```

### Running Tests

```bash
# Backend tests
docker-compose exec backend pytest

# With coverage
docker-compose exec backend pytest --cov=api --cov=core

# Frontend tests
docker-compose exec frontend npm test
```

### Adding Dependencies

**Backend (Poetry)**:
```bash
# Add package
cd backend && poetry add package-name

# Add dev dependency
cd backend && poetry add --group dev package-name

# Or use the task (rebuilds containers)
# Tasks: Run Task > Add Package
```

**Frontend (npm)**:
```bash
cd frontend && npm install package-name
```

## [#] Monitoring & Observability

### Built-in Monitoring Tools

- **Jaeger**: Distributed tracing - http://localhost:16686 (requires `--profile observability`)
- **Grafana**: Metrics and logs - http://localhost:3001 (requires `--profile observability`)
- **Flower**: Celery task monitoring - http://localhost:5555
- **OpenSearch Dashboards**: Search analytics - http://localhost:5601 (requires `--profile search`)
- **RabbitMQ Management**: Queue overview - http://localhost:15672

### Key Metrics

- API response times and error rates
- Celery task success/failure rates
- Database connection pool usage
- Cache hit rates
- Resource utilization (CPU, memory, disk)

### Logs

All logs are collected by Promtail and aggregated in Loki, viewable through Grafana.

**To query logs**:
```
# Grafana Explore -> Loki data source
{container_name="diavgeia_backend"} |= "ERROR"
```

## (_) Security

- **Authentication**: Clerk-based JWT authentication
- **Authorization**: Role-based access control
- **HTTPS**: Nginx SSL/TLS termination
- **Secrets Management**: Environment-based configuration
- **Network Isolation**: Docker network segregation
- **Rate Limiting**: Nginx-based API rate limits
- **Security Tracing**: All auth events logged to Jaeger

**Production Security Checklist**:
- [ ] Set `DEBUG=false`
- [ ] Use strong `DJANGO_SECRET_KEY`
- [ ] Configure restrictive `ALLOWED_HOSTS`
- [ ] Enable `STEALTH_MODE=true`
- [ ] Use HTTPS with valid certificates
- [ ] Protect admin interfaces with basic auth
- [ ] Regular security updates

## U Testing

```bash
# Run all backend tests
docker-compose exec backend pytest

# Run specific test file
docker-compose exec backend pytest tests/test_documents.py

# Run with coverage report
docker-compose exec backend pytest --cov=api --cov=core --cov-report=html

# Frontend tests
docker-compose exec frontend npm test
```

## /\ Scaling

### Horizontal Scaling

```bash
# Scale workers
docker-compose up -d --scale worker=3

# Scale backend (requires load balancer)
docker-compose up -d --scale backend=3
```

### Vertical Scaling

Adjust worker concurrency:
```bash
CELERY_CONCURRENCY=8
CELERY_WORKER_MAX_MEMORY_PER_CHILD=3000000
```

**See [Deployment Guide - Scaling](docs/en/DEPLOYMENT.md#scaling) for more options.**

## Troubleshooting

### Common Issues

#### Services won't start
```bash
# Check logs
docker-compose logs backend
docker-compose logs worker

# Verify environment variables
docker-compose config
```

#### Database connection errors
```bash
# Verify database is healthy
docker-compose ps db

# Check connection string
echo $DATABASE_URL
```

#### OpenSearch errors (when disabled)
```bash
# Disable OpenSearch integration
INDEX_THE_OPENSEARCH=false
```

#### Task not processing
```bash
# Check RabbitMQ is running
docker-compose ps rabbitmq

# View worker logs
docker-compose logs worker -f

# Check Flower dashboard
http://localhost:5555/
```

**See [Deployment Guide - Troubleshooting](docs/en/DEPLOYMENT.md#troubleshooting) for more solutions.**

## <> Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines

- Follow PEP 8 for Python code
- Use ESLint/Prettier for JavaScript code
- Write tests for new features
- Update documentation as needed
- Keep commits atomic and well-described

## [=] License

This project is licensed under the GNU AGPL v3 License - see the [LICENSE](LICENSE) file for details.

## \o/ Acknowledgments

- [Django](https://www.djangoproject.com/) - Web framework
- [React](https://reactjs.org/) - Frontend framework
- [OpenSearch](https://opensearch.org/) - Search engine
- [Celery](https://docs.celeryproject.org/) - Task queue
- [Jaeger](https://www.jaegertracing.io/) - Distributed tracing
- [Grafana](https://grafana.com/) - Observability platform

## [_] Support

- **Documentation**: [docs/](docs/)
- **Issues**: [GitHub Issues](https://github.com/voulkon/crati/issues)
- **Discussions**: [GitHub Discussions](https://github.com/voulkon/crati/discussions)

## %% Roadmap

- [ ] Add multi-language support
- [ ] Implement advanced analytics features
- [ ] Add machine learning-based document classification
- [ ] Create mobile application
- [ ] Add GraphQL API support
- [ ] Improve semantic search with better embeddings models
- [ ] Add real-time notifications via WebSockets

---

**Made with <3 for transparency and open government data**
