# Crati.Co Platform

*Read this in other languages: [English](README.en.md) | [Ελληνικά](README.el.md)*

> **A modern, scalable platform for processing and analyzing Greek government transparency documents**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Django 4.2+](https://img.shields.io/badge/django-4.2+-green.svg)](https://www.djangoproject.com/)
[![React 18](https://img.shields.io/badge/react-18-blue.svg)](https://reactjs.org/)

## 📋 Overview

The Crati.Co platform is a comprehensive system for ingesting, processing, and analyzing documents from the Greek government transparency portal (Diavgeia). It provides full-text search, semantic search using vector embeddings, document analytics, and integrations with external services like GEMI (Greek company registry).

### Key Features

- 🔍 **Full-text & Semantic Search** - OpenSearch and pgvector-powered search
- 📄 **PDF Processing** - Automated text extraction and analysis
- 📊 **Analytics Dashboard** - Document statistics and insights
- 🔄 **Asynchronous Processing** - Celery-based task queue
- 📈 **Observability** - Distributed tracing with Jaeger, logs with Loki/Grafana
- 🔐 **Authentication** - Clerk-based JWT authentication
- 🎯 **Modular Design** - Enable/disable features via environment variables
- 🐳 **Containerized** - Full Docker Compose setup for easy deployment
- 🚀 **Scalable** - Horizontal and vertical scaling options

## 🏗️ Architecture

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

## 🚀 Quick Start

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

```bash
docker-compose -f docker/docker-compose.yml --env-file=.env_files/.env.local.secrets up -d
```

4. **Run migrations and create superuser**

```bash
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py createsuperuser
```

5. **Access the application**

- **Frontend**: http://localhost
- **API**: http://localhost/api/
- **Admin**: http://localhost/admin/
- **Flower**: http://localhost/flower/
- **Grafana**: http://localhost:3001
- **Jaeger**: http://localhost:16686

## 📚 Documentation

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

## 🎛️ Configuration

### Feature Flags

The platform is highly modular. Key feature flags:

| Flag | Default | Description |
|------|---------|-------------|
| `INDEX_THE_OPENSEARCH` | `true` | Enable OpenSearch full-text indexing |
| `TRANSMIT_TO_JAEGER` | `true` | Enable distributed tracing |
| `EXTRACT_THE_DOCS_FROM_PDFS` | `true` | Enable PDF text extraction |
| `HAVE_AFM_FETCH_JOB` | `true` | Enable company data fetching |
| `STEALTH_MODE` | `false` | Require authentication |
| `DEBUG` | `false` | Django debug mode |

**For lightweight development**: Disable OpenSearch and Jaeger to reduce resource usage:

```bash
INDEX_THE_OPENSEARCH=false
TRANSMIT_TO_JAEGER=false
```

See [Environment Variables Reference](docs/en/ENVIRONMENT_VARIABLES.md) for complete list.

## 🏭 Production Deployment

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

## 🔧 Development

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

## 📊 Monitoring & Observability

### Built-in Monitoring Tools

- **Jaeger**: Distributed tracing - http://localhost:16686
- **Grafana**: Metrics and logs - http://localhost:3001
- **Flower**: Celery task monitoring - http://localhost/flower/
- **OpenSearch Dashboards**: Search analytics - http://localhost:5601

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

## 🔐 Security

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

## 🧪 Testing

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

## 📈 Scaling

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

## 🛠️ Troubleshooting

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
http://localhost/flower/
```

**See [Deployment Guide - Troubleshooting](docs/en/DEPLOYMENT.md#troubleshooting) for more solutions.**

## 🤝 Contributing

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

## 📄 License

This project is licensed under the GNU AGPL v3 License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Django](https://www.djangoproject.com/) - Web framework
- [React](https://reactjs.org/) - Frontend framework
- [OpenSearch](https://opensearch.org/) - Search engine
- [Celery](https://docs.celeryproject.org/) - Task queue
- [Jaeger](https://www.jaegertracing.io/) - Distributed tracing
- [Grafana](https://grafana.com/) - Observability platform

## 📧 Support

- **Documentation**: [docs/](docs/)
- **Issues**: [GitHub Issues](https://github.com/voulkon/crati/issues)
- **Discussions**: [GitHub Discussions](https://github.com/voulkon/crati/discussions)

## 🗺️ Roadmap

- [ ] Add multi-language support
- [ ] Implement advanced analytics features
- [ ] Add machine learning-based document classification
- [ ] Create mobile application
- [ ] Add GraphQL API support
- [ ] Improve semantic search with better embeddings models
- [ ] Add real-time notifications via WebSockets

---

**Made with ❤️ for transparency and open government data**
