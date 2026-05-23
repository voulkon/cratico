# Crati.Co

<div align="center">

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Django 4.2+](https://img.shields.io/badge/django-4.2+-green.svg)](https://www.djangoproject.com/)
[![React 18](https://img.shields.io/badge/react-18-blue.svg)](https://reactjs.org/)

### 🌍 Choose Your Language / Επιλέξτε Γλώσσα

**[English](README.en.md)** | **[Ελληνικά](README.el.md)**

</div>

---

## About / Σχετικά

A modern, scalable platform for processing and analyzing Greek government transparency documents from Diavgeia.

Μια σύγχρονη, επεκτάσιμη πλατφόρμα για την επεξεργασία και ανάλυση εγγράφων διαφάνειας της ελληνικής κυβέρνησης από τη Διαύγεια.

## Quick Links / Γρήγοροι Σύνδεσμοι

### English
- [Full Documentation](README.en.md)
- [Architecture](docs/en/ARCHITECTURE.md)
- [Deployment Guide](docs/en/DEPLOYMENT.md)
- [Environment Variables](docs/en/ENVIRONMENT_VARIABLES.md)

### Ελληνικά
- [Πλήρης Τεκμηρίωση](README.el.md)
- [Αρχιτεκτονική](docs/el/) (Σύντομα)
- [Οδηγός Εγκατάστασης](docs/el/) (Σύντομα)

---

## Quick Start / Γρήγορη Εκκίνηση

```bash
# Clone the repository / Κλωνοποιήστε το αποθετήριο
git clone https://github.com/voulkon/crati.git
cd crati

# Copy environment file / Αντιγράψτε το αρχείο περιβάλλοντος
cp .env_files/.env.local.secrets.example .env_files/.env.local.secrets

# Start services / Εκκινήστε τις υπηρεσίες
docker-compose -f docker/docker-compose.yml --env-file=.env_files/.env.local.secrets up -d
```

For detailed instructions, see the documentation in your preferred language.

Για λεπτομερείς οδηγίες, δείτε την τεκμηρίωση στη γλώσσα της προτίμησής σας.

---

<div align="center">

**Made with ❤️ for transparency and open government data**

**Φτιαγμένο με ❤️ για τη διαφάνεια και τα ανοιχτά κυβερνητικά δεδομένα**

</div>
