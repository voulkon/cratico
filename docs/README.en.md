# Documentation Index

*Read this in other languages: [English](README.en.md) | [Ελληνικά](README.el.md)*

Welcome to the Crati.Co platform documentation! This guide will help you navigate the documentation and find what you need.

## 🚀 Getting Started

New to the platform? Start here:

1. **[README](../README.en.md)** - Project overview and quick start
2. **[Architecture Overview](en/ARCHITECTURE.md)** - Understand the system design
3. **[Deployment Guide](en/DEPLOYMENT.md)** - Get the platform running

## 📖 Core Documentation

### Architecture & Design
- **[Architecture Overview](en/ARCHITECTURE.md)**
  - High-level system architecture
  - Component interactions
  - Data flow diagrams
  - Technology stack
  - Modularity and feature flags

### Configuration
- **[Environment Variables Reference](en/ENVIRONMENT_VARIABLES.md)**
  - Complete variable listing
  - Required vs optional variables
  - Environment-specific configurations
  - Security best practices
  - Troubleshooting configuration issues

### Deployment
- **[Deployment Guide](en/DEPLOYMENT.md)**
  - Local development setup
  - Single-server production deployment
  - Multi-server production deployment
  - Configuration management
  - Scaling strategies
  - Backup and recovery
  - Maintenance procedures

## 🔧 Component Documentation

Detailed documentation for each service:

- **[Component Overview](en/components/README.md)** - Component dependencies and overview
- **[Backend API](en/components/backend-api.md)** - Django REST API details
- More component docs coming soon...

## 📋 Documentation by Use Case

### For Developers

**Setting up local environment:**
1. [README - Quick Start](../README.en.md#quick-start)
2. [Deployment Guide - Development](en/DEPLOYMENT.md#quick-start-development)
3. [Environment Variables - Development](en/ENVIRONMENT_VARIABLES.md#development)

**Understanding the codebase:**
1. [Architecture Overview](en/ARCHITECTURE.md)
2. [Component Details](en/components/)
3. [Backend API Documentation](en/components/backend-api.md)

**Adding features:**
1. [Architecture - Modularity](en/ARCHITECTURE.md#modularity--feature-flags)
2. [Backend API - Development](en/components/backend-api.md#development)
3. [Environment Variables](en/ENVIRONMENT_VARIABLES.md) - Add new config

### For DevOps/SysAdmins

**Deploying to production:**
1. [Deployment Guide - Production](en/DEPLOYMENT.md#production-deployment)
2. [Environment Variables - Production](en/ENVIRONMENT_VARIABLES.md#production)
3. [Architecture - Deployment Topologies](en/ARCHITECTURE.md#deployment-topologies)

**Monitoring and maintenance:**
1. [Deployment Guide - Monitoring](en/DEPLOYMENT.md#monitoring)
2. [Component Overview - Monitoring](en/components/README.md#monitoring-checklist)
3. [Deployment Guide - Backup & Recovery](en/DEPLOYMENT.md#backup--recovery)

**Scaling the platform:**
1. [Architecture - Scalability](en/ARCHITECTURE.md#scalability)
2. [Deployment Guide - Scaling](en/DEPLOYMENT.md#scaling)
3. [Component Overview - Scaling Strategies](en/components/README.md#scaling-strategies)

**Troubleshooting:**
1. [Deployment Guide - Troubleshooting](en/DEPLOYMENT.md#troubleshooting)
2. [Environment Variables - Troubleshooting](en/ENVIRONMENT_VARIABLES.md#troubleshooting)
3. [Component Overview - Common Issues](en/components/README.md#common-issues)

### For Project Managers

**Understanding capabilities:**
1. [README - Overview](../README.en.md#overview)
2. [Architecture - High-Level](en/ARCHITECTURE.md#high-level-architecture-diagram)
3. [Architecture - Feature Flags](en/ARCHITECTURE.md#modularity--feature-flags)

**Resource planning:**
1. [Component Overview - Resource Requirements](en/components/README.md#resource-requirements)
2. [Architecture - Deployment Topologies](en/ARCHITECTURE.md#deployment-topologies)
3. [Deployment Guide - Prerequisites](en/DEPLOYMENT.md#prerequisites)

## 🎯 Feature-Specific Guides

### Core Services (Always Required)
- Backend API - Django REST API
- Celery Worker - Background processing
- PostgreSQL - Primary database
- Redis - Caching
- RabbitMQ - Message queue
- Nginx - Reverse proxy

**Docs**: [Architecture - Core Services](en/ARCHITECTURE.md#1-core-services-required)

### Optional: Search Layer
Enable with `INDEX_THE_OPENSEARCH=true`

- OpenSearch - Full-text search
- OpenSearch Dashboards - Search UI

**Docs**: [Architecture - Search Layer](en/ARCHITECTURE.md#2-search-layer-optional)

### Optional: Observability Stack
Enable with `TRANSMIT_TO_JAEGER=true`

- Jaeger - Distributed tracing
- Loki - Log aggregation
- Promtail - Log collection
- Grafana - Unified dashboards
- Flower - Celery monitoring

**Docs**: [Architecture - Observability](en/ARCHITECTURE.md#3-observability-stack-optional)

### Optional: External Integrations
- AWS S3 - Backup storage
- GEMI API - Company data
- Diavgeia API - Government documents

**Docs**: [Environment Variables - External Services](en/ENVIRONMENT_VARIABLES.md#external-services)

## 🔍 Search Tips

### Find Configuration Options
Search [Environment Variables](en/ENVIRONMENT_VARIABLES.md) for variable names

### Find Deployment Instructions
Search [Deployment Guide](en/DEPLOYMENT.md) for your deployment scenario

### Find Component Details
Browse [Component Documentation](en/components/) for service-specific info

### Find Architecture Info
See [Architecture Overview](en/ARCHITECTURE.md) for system design

## 📚 Additional Resources

### External Documentation
- [Django Docs](https://docs.djangoproject.com/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [Celery Docs](https://docs.celeryproject.org/)
- [OpenSearch Docs](https://opensearch.org/docs/)
- [Docker Docs](https://docs.docker.com/)

### Community
- GitHub Issues: Report bugs or request features
- GitHub Discussions: Ask questions and share ideas

## 🔄 Documentation Updates

This documentation is continuously updated. Key areas being expanded:

- [ ] Individual component documentation pages
- [ ] Development workflow guides
- [ ] API reference documentation
- [ ] Performance tuning guides
- [ ] Advanced configuration examples
- [ ] Migration guides
- [ ] Video tutorials

## 📝 Contributing to Documentation

Found an error or want to improve documentation?

1. Edit the relevant markdown file
2. Submit a pull request
3. Follow the documentation style guide (coming soon)

## 🗂️ File Structure

```
docs/
├── README.md                      # This file
├── ARCHITECTURE.md                # System architecture
├── DEPLOYMENT.md                  # Deployment guide
├── ENVIRONMENT_VARIABLES.md       # Configuration reference
└── components/                    # Component-specific docs
    ├── README.md                  # Component overview
    ├── backend-api.md             # Backend documentation
    └── ...                        # More components
```

## 📊 Documentation Completeness

| Document | Status | Last Updated |
|----------|--------|--------------|
| README | ✅ Complete | 2026-03-05 |
| Architecture | ✅ Complete | 2026-03-05 |
| Deployment Guide | ✅ Complete | 2026-03-05 |
| Environment Variables | ✅ Complete | 2026-03-05 |
| Backend API | ✅ Complete | 2026-03-05 |
| Component Overview | ✅ Complete | 2026-03-05 |
| Other Components | 🚧 In Progress | - |

---

**Need help?** Check the [Troubleshooting sections](en/DEPLOYMENT.md#troubleshooting) or open an issue on GitHub.
