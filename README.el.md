# Πλατφόρμα Διαύγεια/Crati

> **Μια σύγχρονη, επεκτάσιμη πλατφόρμα για την επεξεργασία και ανάλυση εγγράφων διαφάνειας της ελληνικής κυβέρνησης**

[![Άδεια: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Django 4.2+](https://img.shields.io/badge/django-4.2+-green.svg)](https://www.djangoproject.com/)
[![React 18](https://img.shields.io/badge/react-18-blue.svg)](https://reactjs.org/)

---

## 🚧 Η ελληνική τεκμηρίωση βρίσκεται υπό κατασκευή

Αυτή τη στιγμή, η πλήρης τεκμηρίωση είναι διαθέσιμη στα **[Αγγλικά](README.en.md)**.

Εργαζόμαστε για τη μετάφραση της τεκμηρίωσης στα ελληνικά. Εάν θέλετε να βοηθήσετε, παρακαλούμε δείτε τις [οδηγίες συνεισφοράς](CONTRIBUTING.md).

---

## 📋 Επισκόπηση

Η πλατφόρμα Διαύγεια/Crati είναι ένα ολοκληρωμένο σύστημα για τη λήψη, επεξεργασία και ανάλυση εγγράφων από την πύλη διαφάνειας της ελληνικής κυβέρνησης (Διαύγεια). Παρέχει αναζήτηση πλήρους κειμένου, σημασιολογική αναζήτηση με χρήση διανυσματικών ενσωματώσεων, αναλυτικά στοιχεία εγγράφων και ενσωματώσεις με εξωτερικές υπηρεσίες όπως το ΓΕΜΗ.

### Βασικά Χαρακτηριστικά

- 🔍 **Αναζήτηση Πλήρους Κειμένου & Σημασιολογική** - OpenSearch και pgvector
- 📄 **Επεξεργασία PDF** - Αυτόματη εξαγωγή και ανάλυση κειμένου
- 📊 **Πίνακας Αναλυτικών Στοιχείων** - Στατιστικά και πληροφορίες εγγράφων
- 🔄 **Ασύγχρονη Επεξεργασία** - Ουρά εργασιών βασισμένη σε Celery
- 📈 **Παρατηρησιμότητα** - Κατανεμημένη ανίχνευση με Jaeger, αρχεία καταγραφής με Loki/Grafana
- 🔐 **Πιστοποίηση** - Πιστοποίηση JWT βασισμένη σε Clerk
- 🎯 **Αρθρωτός Σχεδιασμός** - Ενεργοποίηση/απενεργοποίηση χαρακτηριστικών μέσω μεταβλητών περιβάλλοντος
- 🐳 **Εμπορευματοποιημένο** - Πλήρης ρύθμιση Docker Compose για εύκολη ανάπτυξη
- 🚀 **Επεκτάσιμο** - Επιλογές οριζόντιας και κάθετης κλιμάκωσης

## 🚀 Γρήγορη Εκκίνηση

### Προαπαιτούμενα

- Docker 20.10+
- Docker Compose 2.0+
- 8 GB RAM ελάχιστο
- 20 GB ελεύθερος χώρος δίσκου

### Ρύθμιση Ανάπτυξης

1. **Κλωνοποίηση του αποθετηρίου**

```bash
git clone https://github.com/voulkon/crati.git
cd crati
```

2. **Δημιουργία αρχείου περιβάλλοντος**

```bash
cp .env_files/.env.local.secrets.example .env_files/.env.local.secrets
```

Επεξεργαστείτε το `.env_files/.env.local.secrets`:

```bash
# Ελάχιστη διαμόρφωση για γρήγορη εκκίνηση
POSTGRES_USER=local_user
POSTGRES_PASSWORD=local_pass
POSTGRES_DB=local_diavgia
DJANGO_SECRET_KEY=$(openssl rand -hex 32)
DEBUG=true

# Απενεργοποίηση προαιρετικών υπηρεσιών για ταχύτερη εκκίνηση (προαιρετικό)
INDEX_THE_OPENSEARCH=false
TRANSMIT_TO_JAEGER=false
```

3. **Εκκίνηση της στοίβας**

```bash
docker-compose -f docker/docker-compose.yml --env-file=.env_files/.env.local.secrets up -d
```

4. **Εκτέλεση migrations και δημιουργία superuser**

```bash
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py createsuperuser
```

5. **Πρόσβαση στην εφαρμογή**

- **Frontend**: http://localhost
- **API**: http://localhost/api/
- **Admin**: http://localhost/admin/
- **Flower**: http://localhost/flower/
- **Grafana**: http://localhost:3001
- **Jaeger**: http://localhost:16686

## 📚 Τεκμηρίωση

Για πλήρη τεκμηρίωση, παρακαλούμε ανατρέξτε στην **[αγγλική έκδοση](README.en.md)**.

### Διαθέσιμα στα Αγγλικά

- **[Επισκόπηση Αρχιτεκτονικής](docs/en/ARCHITECTURE.md)** - Σχεδιασμός συστήματος, συστατικά και ροή δεδομένων
- **[Οδηγός Ανάπτυξης](docs/en/DEPLOYMENT.md)** - Τοπική, μονο-διακομιστή και πολυ-διακομιστή ανάπτυξη
- **[Μεταβλητές Περιβάλλοντος](docs/en/ENVIRONMENT_VARIABLES.md)** - Πλήρης αναφορά διαμόρφωσης
- **[Λεπτομέρειες Συστατικών](docs/en/components/)** - Βαθιά κατάδυση σε κάθε υπηρεσία

## 🤝 Συνεισφορά

Οι συνεισφορές είναι ευπρόσδεκτες! Για να βοηθήσετε με τις μεταφράσεις ή τον κώδικα:

1. Κάντε Fork το αποθετήριο
2. Δημιουργήστε ένα κλάδο χαρακτηριστικού (`git checkout -b feature/amazing-feature`)
3. Υποβάλετε τις αλλαγές σας (`git commit -m 'Add amazing feature'`)
4. Ωθήστε στον κλάδο (`git push origin feature/amazing-feature`)
5. Ανοίξτε ένα Pull Request

## 📄 Άδεια

Αυτό το έργο διατίθεται με άδεια MIT - δείτε το αρχείο [LICENSE](LICENSE) για λεπτομέρειες.

## 📧 Υποστήριξη

- **Τεκμηρίωση**: [docs/](docs/)
- **Ζητήματα**: [GitHub Issues](https://github.com/voulkon/crati/issues)
- **Συζητήσεις**: [GitHub Discussions](https://github.com/voulkon/crati/discussions)

---

**Φτιαγμένο με ❤️ για τη διαφάνεια και τα ανοιχτά κυβερνητικά δεδομένα**
