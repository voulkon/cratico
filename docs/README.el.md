# Ευρετήριο Τεκμηρίωσης

*Read this in other languages: [English](README.en.md) | [Ελληνικά](README.el.md)*

Καλώς ήρθατε στην τεκμηρίωση της πλατφόρμας Crati.Co! Αυτός ο οδηγός θα σας βοηθήσει να πλοηγηθείτε στην τεκμηρίωση και να βρείτε αυτό που χρειάζεστε.

> **Σημείωση:** Η πλήρης και πιο ενημερωμένη τεκμηρίωση είναι στα αγγλικά. Αυτή η ελληνική μετάφραση μπορεί να μην καλύπτει το σύνολο του περιεχομένου.

## 🚀 Ξεκινώντας

Νέος στην πλατφόρμα; Ξεκινήστε από εδώ:

1. **[README](../README.el.md)** - Επισκόπηση έργου και γρήγορη εκκίνηση
2. **[Επισκόπηση Αρχιτεκτονικής](en/ARCHITECTURE.md)** - Κατανοήστε τον σχεδιασμό του συστήματος
3. **[Οδηγός Deployment](en/DEPLOYMENT.md)** - Βάλτε την πλατφόρμα σε λειτουργία

## 📖 Βασική Τεκμηρίωση

### Αρχιτεκτονική & Σχεδιασμός
- **[Επισκόπηση Αρχιτεκτονικής](en/ARCHITECTURE.md)** *(στα αγγλικά)*
  - High-level αρχιτεκτονική του συστήματος
  - Αλληλεπιδράσεις μεταξύ components
  - Data flow diagrams
  - Technology stack
  - Modularity και feature flags

### Configuration
- **[Αναφορά Μεταβλητών Περιβάλλοντος](en/ENVIRONMENT_VARIABLES.md)** *(στα αγγλικά)*
  - Πλήρης λίστα μεταβλητών
  - Απαραίτητες vs προαιρετικές μεταβλητές
  - Configurations ανά environment
  - Best practices ασφαλείας
  - Αντιμετώπιση προβλημάτων configuration

### Deployment
- **[Οδηγός Deployment](en/DEPLOYMENT.md)** *(στα αγγλικά)*
  - Setup για τοπική ανάπτυξη
  - Deployment σε single-server production
  - Deployment σε multi-server production
  - Διαχείριση configuration
  - Στρατηγικές scaling
  - Backup και recovery
  - Διαδικασίες συντήρησης

## 🔧 Τεκμηρίωση Components

Αναλυτική τεκμηρίωση για κάθε service:

- **[Επισκόπηση Components](en/components/README.md)** - Εξαρτήσεις και επισκόπηση
- **[Backend API](en/components/backend-api.md)** - Λεπτομέρειες Django REST API
- Περισσότερα docs για components έρχονται σύντομα...

## 📋 Τεκμηρίωση ανά Χρήση

### Για Developers

**Setup τοπικού περιβάλλοντος:**
1. [README - Quick Start](../README.el.md#γρήγορη-εκκίνηση)
2. [Οδηγός Deployment - Development](en/DEPLOYMENT.md#quick-start-development)
3. [Μεταβλητές Περιβάλλοντος - Development](en/ENVIRONMENT_VARIABLES.md#development)

**Κατανόηση του codebase:**
1. [Επισκόπηση Αρχιτεκτονικής](en/ARCHITECTURE.md)
2. [Λεπτομέρειες Components](en/components/)
3. [Τεκμηρίωση Backend API](en/components/backend-api.md)

**Προσθήκη features:**
1. [Αρχιτεκτονική - Modularity](en/ARCHITECTURE.md#modularity--feature-flags)
2. [Backend API - Development](en/components/backend-api.md#development)
3. [Μεταβλητές Περιβάλλοντος](en/ENVIRONMENT_VARIABLES.md) - Προσθήκη νέου configuration

### Για DevOps/SysAdmins

**Deployment σε production:**
1. [Οδηγός Deployment - Production](en/DEPLOYMENT.md#production-deployment)
2. [Μεταβλητές Περιβάλλοντος - Production](en/ENVIRONMENT_VARIABLES.md#production)
3. [Αρχιτεκτονική - Deployment Topologies](en/ARCHITECTURE.md#deployment-topologies)

**Monitoring και συντήρηση:**
1. [Οδηγός Deployment - Monitoring](en/DEPLOYMENT.md#monitoring)
2. [Επισκόπηση Components - Monitoring](en/components/README.md#monitoring-checklist)
3. [Οδηγός Deployment - Backup & Recovery](en/DEPLOYMENT.md#backup--recovery)

**Scaling της πλατφόρμας:**
1. [Αρχιτεκτονική - Scalability](en/ARCHITECTURE.md#scalability)
2. [Οδηγός Deployment - Scaling](en/DEPLOYMENT.md#scaling)
3. [Επισκόπηση Components - Στρατηγικές Scaling](en/components/README.md#scaling-strategies)

**Αντιμετώπιση προβλημάτων:**
1. [Οδηγός Deployment - Troubleshooting](en/DEPLOYMENT.md#troubleshooting)
2. [Μεταβλητές Περιβάλλοντος - Troubleshooting](en/ENVIRONMENT_VARIABLES.md#troubleshooting)
3. [Επισκόπηση Components - Συχνά Προβλήματα](en/components/README.md#common-issues)

## 🎯 Οδηγοί ανά Feature

### Βασικά Services (Πάντα Απαραίτητα)
- Backend API - Django REST API
- Celery Worker - Επεξεργασία στο background
- PostgreSQL - Κύρια βάση δεδομένων
- Redis - Caching
- RabbitMQ - Message queue
- Nginx - Reverse proxy

**Docs**: [Αρχιτεκτονική - Βασικά Services](en/ARCHITECTURE.md#1-core-services-required)

### Προαιρετικά: Search Layer
Ενεργοποίηση με `INDEX_THE_OPENSEARCH=true`

- OpenSearch - Full-text search
- OpenSearch Dashboards - Search UI

**Docs**: [Αρχιτεκτονική - Search Layer](en/ARCHITECTURE.md#2-search-layer-optional)

### Προαιρετικά: Observability Stack
Ενεργοποίηση με `TRANSMIT_TO_JAEGER=true`

- Jaeger - Distributed tracing
- Loki - Συγκέντρωση logs
- Promtail - Συλλογή logs
- Grafana - Ενοποιημένα dashboards
- Flower - Monitoring για το Celery

**Docs**: [Αρχιτεκτονική - Observability](en/ARCHITECTURE.md#3-observability-stack-optional)

### Προαιρετικά: Εξωτερικές Ενσωματώσεις
- AWS S3 - Backup storage
- GEMI API - Δεδομένα εταιρειών
- Diavgeia API - Δημόσια έγγραφα

**Docs**: [Μεταβλητές Περιβάλλοντος - Εξωτερικά Services](en/ENVIRONMENT_VARIABLES.md#external-services)

## 📚 Επιπλέον Πόροι

### Εξωτερική Τεκμηρίωση
- [Django Docs](https://docs.djangoproject.com/)
- [Django REST Framework](https://www.django-rest-framework.org/)
- [Celery Docs](https://docs.celeryproject.org/)
- [OpenSearch Docs](https://opensearch.org/docs/)
- [Docker Docs](https://docs.docker.com/)

### Community
- GitHub Issues: Αναφέρετε bugs ή ζητήστε features
- GitHub Discussions: Κάντε ερωτήσεις και μοιραστείτε ιδέες

## 📝 Συμβολή στην Τεκμηρίωση

Βρήκατε κάποιο σφάλμα ή θέλετε να βελτιώσετε την τεκμηρίωση;

1. Επεξεργαστείτε το αντίστοιχο markdown αρχείο
2. Υποβάλετε ένα pull request
3. Για μεταφράσεις στα ελληνικά, δείτε το [CONTRIBUTING.md](../CONTRIBUTING.md)

---

**Χρειάζεστε βοήθεια;** Δείτε τις [ενότητες Troubleshooting](en/DEPLOYMENT.md#troubleshooting) ή ανοίξτε ένα issue στο GitHub.
