"""
Default legal page content for Crati.
Fallback used when no custom content has been set by an admin.

Each document type has a default title and default markdown content
for both English and Greek.
"""

# Registry of default document types: slug → {en_title, el_title}
_DEFAULT_DOCS = {
    "tos": {"en": "Terms of Service", "el": "Όροι Χρήσης"},
    "privacy": {"en": "Privacy Policy", "el": "Πολιτική Απορρήτου"},
    "cookies": {"en": "Cookie Policy", "el": "Πολιτική Cookies"},
}


def get_available_types():
    """Return the list of known document type slugs."""
    return list(_DEFAULT_DOCS.keys())


def get_default_legal_content(doc_type, field, language="en"):
    """
    Return the default value for a document type and field.

    Args:
        doc_type: Slug like 'tos', 'privacy', 'cookies'
        field: 'title' or 'content'
        language: 'en' or 'el'

    Returns:
        str: The default title or content for the given document type.
    """
    if field == "title":
        return _DEFAULT_DOCS.get(doc_type, {}).get(language, doc_type.title())

    # field == "content"
    content_funcs = {
        "tos": _get_default_terms_of_service,
        "privacy": _get_default_privacy_policy,
        "cookies": _get_default_cookie_policy,
    }
    func = content_funcs.get(doc_type)
    if func:
        return func(language)
    # Unknown type: return a placeholder
    return f"# {doc_type.title()}\n\nContent coming soon."


def _get_default_terms_of_service(language):
    """Default Terms of Service content."""

    if language == "el":
        return """# Όροι Χρήσης του Crati

Η χρήση της παρούσας διαδικτυακής πλατφόρμας Crati (εφεξής «Crati» ή «πλατφόρμα») προϋποθέτει την ανεπιφύλακτη αποδοχή των όρων χρήσης που περιγράφονται κατωτέρω. Εάν δεν συμφωνείτε με οποιονδήποτε από τους ακόλουθους όρους, παρακαλούμε να μην χρησιμοποιείτε την πλατφόρμα και τις υπηρεσίες της.

## Περιγραφή Υπηρεσίας και Σκοπός

Το Crati είναι μια **ανοιχτού κώδικα** διαδικτυακή πλατφόρμα που παρέχει προηγμένες δυνατότητες αναζήτησης και παρακολούθησης στις δημοσιευμένες πράξεις και αποφάσεις του επίσημου προγράμματος «Διαύγεια» της Ελληνικής Δημοκρατίας.

### Κύριες Λειτουργίες

- **Αναζήτηση Αποφάσεων**: Πλήρης αναζήτηση τόσο στο κείμενο όσο και στα μεταδεδομένα των αποφάσεων
- **Παρακολούθηση Ειδοποιήσεων**: Ειδοποιήσεις για νέες αποφάσεις βάσει κριτηρίων
- **Αποθήκευση Αγαπημένων**: Δυνατότητα αποθήκευσης και οργάνωσης αποφάσεων

### Φύση της Υπηρεσίας

Μέσω του Crati, οι χρήστες έχουν τη δυνατότητα να πραγματοποιούν πλήρη αναζήτηση στις αποφάσεις που αναρτώνται στη Διαύγεια, λαμβάνοντας αποτελέσματα με υψηλή συνάφεια και φίλτρα για στοχευμένη πλοήγηση.

Κάθε αποτέλεσμα περιλαμβάνει σύνδεσμο που οδηγεί στο επίσημο έγγραφο της πράξης, όπως αυτό δημοσιεύεται στη Διαύγεια. Το Crati δεν δημιουργεί, συντάσσει ή τροποποιεί το περιεχόμενο των πράξεων – αντλεί αυτόματα τα δεδομένα από την επίσημη πηγή.

### Ανοιχτός Κώδικας

Το Crati είναι έργο ανοιχτού κώδικα. Ο πηγαίος κώδικας είναι διαθέσιμος και μπορεί να εξεταστεί από οποιονδήποτε. Αυτό εξασφαλίζει διαφάνεια ως προς τον τρόπο λειτουργίας της πλατφόρμας και επεξεργασίας των δεδομένων.

## Μη Φιλοξενία Εγγράφων

Το Crati δεν φιλοξενεί στους δικούς του διακομιστές τα επίσημα έγγραφα PDF των πράξεων, ούτε αλλοιώνει ή επεμβαίνει στο περιεχόμενό τους. Παρέχεται πάντα σύνδεσμος προς την επίσημη σελίδα του εγγράφου στη Διαύγεια.

## Ακρίβεια Περιεχομένου

Το Crati καταβάλλει κάθε δυνατή προσπάθεια να διατηρεί το ευρετήριο των πράξεων ενημερωμένο. Ωστόσο:

- Το επίσημο μητρώο της Διαύγειας αποτελεί τη μοναδική έγκυρη πηγή
- Δεν εγγυόμαστε ότι όλες οι πράξεις περιλαμβάνονται στο σύστημα
- Ορισμένα έγγραφα ενδέχεται να μην είναι πλήρως ευρετηριασμένα
- Οι χρήστες οφείλουν να διασταυρώνουν τις πληροφορίες με τα επίσημα έγγραφα

## Πρόσβαση στην Υπηρεσία

### Ελεύθερη Πρόσβαση

Το Crati παρέχεται **δωρεάν** για προσωπική και ερευνητική χρήση. Η βασική λειτουργικότητα είναι διαθέσιμη σε όλους τους χρήστες.

### Όρια Χρήσης

Για τη διασφάλιση της εύρυθμης λειτουργίας και την αποτροπή κατάχρησης, ενδέχεται να εφαρμόζονται όρια:

- Αριθμός αναζητήσεων ανά χρονική περίοδο
- Αριθμός αποφάσεων που μπορούν να προβληθούν
- Συχνότητα αιτημάτων API

### Υπηρεσίες Ειδοποιήσεων

Η υπηρεσία ειδοποιήσεων παρέχεται "όπως είναι" και ενδέχεται να μην είναι διαθέσιμη ανά πάσα στιγμή. Δεν εγγυόμαστε την έγκαιρη ή ακριβή παράδοση ειδοποιήσεων.

## Δεδομένα Χρηστών

### Ελάχιστη Συλλογή Δεδομένων

Το Crati συλλέγει μόνο τα απολύτως απαραίτητα δεδομένα για τη λειτουργία της υπηρεσίας:

- Στοιχεία εγγραφής (email, όνομα χρήστη)
- Προτιμήσεις χρήστη (γλώσσα, θέμα)
- Αποθηκευμένες αποφάσεις (bookmarks)
- Κριτήρια ειδοποιήσεων

### Χρήση Δεδομένων

Τα δεδομένα χρησιμοποιούνται αποκλειστικά για:

- Παροχή της υπηρεσίας
- Βελτίωση της λειτουργίας
- Επικοινωνία σχετική με τον λογαριασμό

### Μη Διαμοιρασμός

Δεν μοιραζόμαστε τα προσωπικά σας δεδομένα με τρίτους, εκτός αν απαιτείται από τον νόμο.

## Δικαιώματα Πνευματικής Ιδιοκτησίας

### Περιεχόμενο Διαύγειας

Οι αποφάσεις και τα έγγραφα που προέρχονται από τη Διαύγεια είναι δημόσια έγγραφα και δεν υπόκεινται σε πνευματικά δικαιώματα.

### Λογισμικό Crati

Το λογισμικό του Crati διατίθεται υπό άδεια ανοιχτού κώδικα. Βλέπε το αρχείο LICENSE στο αποθετήριο του έργου.

## Περιορισμός Ευθύνης

Το Crati παρέχεται "όπως είναι", χωρίς καμία εγγύηση, ρητή ή σιωπηρή.

- Δεν ευθυνόμαστε για τυχόν απώλειες ή ζημίες από τη χρήση της υπηρεσίας
- Δεν εγγυόμαστε τη διαθεσιμότητα ή την ακρίβεια της υπηρεσίας
- Οι χρήστες χρησιμοποιούν την πλατφόρμα με δική τους ευθύνη

## Αλλαγές Όρων

Διατηρούμε το δικαίωμα να τροποποιούμε τους παρόντες όρους ανά πάσα στιγμή. Οι αλλαγές θα ανακοινώνονται μέσω της πλατφόρμας.

## Επικοινωνία

Για ερωτήσεις σχετικά με τους όρους χρήσης, μπορείτε να επικοινωνήσετε μέσω του αποθετηρίου GitHub του έργου.

---

**Σημείωση**: Αυτό είναι προεπιλεγμένο κείμενο. Οι διαχειριστές μπορούν να το τροποποιήσουν από τη σελίδα διαχείρισης.
"""

    else:  # English
        return """# Terms of Service for Crati

By using the Crati online platform (hereinafter "Crati" or "platform"), you unconditionally accept the terms of use described below. If you do not agree with any of the following terms, please do not use the platform and its services.

## Service Description and Purpose

Crati is an **open source** online platform that provides advanced search and tracking capabilities for published acts and decisions of the official "Diavgeia" program of the Hellenic Republic.

### Main Features

- **Decision Search**: Full-text search in both the content and metadata of decisions
- **Notification Tracking**: Alerts for new decisions based on custom criteria
- **Bookmarking**: Ability to save and organize decisions

### Nature of Service

Through Crati, users can perform comprehensive searches on decisions published in Diavgeia, receiving highly relevant results with filters for targeted navigation.

Each result includes a link to the official document of the act, as published in Diavgeia. Crati does not create, compose, or modify the content of acts – it automatically extracts data from the official source.

### Open Source

Crati is an open source project. The source code is publicly available and can be examined by anyone. This ensures transparency regarding how the platform operates and processes data.

## Non-Hosting of Documents

Crati does not host the official PDF documents of acts on its own servers, nor does it alter or interfere with their content. A link to the official document page in Diavgeia is always provided.

## Content Accuracy

Crati makes every effort to keep the decision index updated. However:

- The official Diavgeia registry is the sole valid source
- We do not guarantee that all decisions are included in the system
- Some documents may not be fully indexed
- Users must cross-reference information with official documents

## Access to Service

### Free Access

Crati is provided **free of charge** for personal and research use. Basic functionality is available to all users.

### Usage Limits

To ensure smooth operation and prevent abuse, limits may be applied:

- Number of searches per time period
- Number of decisions that can be viewed
- API request frequency

### Notification Services

The notification service is provided "as is" and may not be available at all times. We do not guarantee timely or accurate delivery of notifications.

## User Data

### Minimal Data Collection

Crati collects only the absolutely necessary data for the service to function:

- Registration details (email, username)
- User preferences (language, theme)
- Saved decisions (bookmarks)
- Notification criteria

### Data Usage

Data is used exclusively for:

- Providing the service
- Improving functionality
- Account-related communication

### No Sharing

We do not share your personal data with third parties, unless required by law.

## Intellectual Property Rights

### Diavgeia Content

Decisions and documents from Diavgeia are public documents and are not subject to copyright.

### Crati Software

Crati software is released under an open source license. See the LICENSE file in the project repository.

## Limitation of Liability

Crati is provided "as is," without any warranty, express or implied.

- We are not liable for any losses or damages from using the service
- We do not guarantee service availability or accuracy
- Users use the platform at their own risk

## Changes to Terms

We reserve the right to modify these terms at any time. Changes will be announced through the platform.

## Contact

For questions regarding the terms of use, you can contact us through the project's GitHub repository.

---

**Note**: This is default text. Administrators can modify it from the admin page.
"""


def _get_default_privacy_policy(language):
    """Default Privacy Policy content."""

    if language == "el":
        return """# Πολιτική Απορρήτου

## Εισαγωγή

Το Crati σέβεται την ιδιωτικότητά σας και δεσμεύεται να προστατεύει τα προσωπικά σας δεδομένα. Αυτή η πολιτική περιγράφει πώς συλλέγουμε, χρησιμοποιούμε και προστατεύουμε τις πληροφορίες σας.

## Δεδομένα που Συλλέγουμε

### Στοιχεία Εγγραφής
- Διεύθυνση email
- Όνομα χρήστη

### Δεδομένα Χρήσης
- Προτιμήσεις (γλώσσα, θέμα)
- Αποθηκευμένες αποφάσεις
- Κριτήρια ειδοποιήσεων

## Χρήση Δεδομένων

Χρησιμοποιούμε τα δεδομένα σας αποκλειστικά για:
- Παροχή και βελτίωση της υπηρεσίας
- Αποστολή ειδοποιήσεων που έχετε ζητήσει
- Τεχνική υποστήριξη

## Διαμοιρασμός Δεδομένων

Δεν πωλούμε, ενοικιάζουμε ή μοιραζόμαστε τα προσωπικά σας δεδομένα με τρίτους.

## Ασφάλεια

Εφαρμόζουμε κατάλληλα τεχνικά και οργανωτικά μέτρα για την προστασία των δεδομένων σας.

## Δικαιώματά σας

Έχετε δικαίωμα να:
- Προσπελάσετε τα δεδομένα σας
- Διορθώσετε ανακρίβειες
- Ζητήσετε διαγραφή του λογαριασμού σας

## Επικοινωνία

Για θέματα απορρήτου, επικοινωνήστε μέσω του GitHub repository του έργου.
"""

    else:  # English
        return """# Privacy Policy

## Introduction

Crati respects your privacy and is committed to protecting your personal data. This policy describes how we collect, use, and protect your information.

## Data We Collect

### Registration Information
- Email address
- Username

### Usage Data
- Preferences (language, theme)
- Saved decisions
- Notification criteria

## Data Usage

We use your data exclusively for:
- Providing and improving the service
- Sending notifications you've requested
- Technical support

## Data Sharing

We do not sell, rent, or share your personal data with third parties.

## Security

We implement appropriate technical and organizational measures to protect your data.

## Your Rights

You have the right to:
- Access your data
- Correct inaccuracies
- Request deletion of your account

## Contact

For privacy matters, contact us through the project's GitHub repository.
"""


def _get_default_cookie_policy(language):
    """Default Cookie Policy content."""

    if language == "el":
        return """# Πολιτική Cookies

## Τι είναι τα Cookies;

Τα cookies είναι μικρά αρχεία κειμένου που αποθηκεύονται στη συσκευή σας όταν επισκέπτεστε τον ιστότοπό μας.

## Πώς Χρησιμοποιούμε Cookies

Χρησιμοποιούμε cookies για:
- Αποθήκευση προτιμήσεων (γλώσσα, θέμα)
- Διατήρηση συνεδρίας χρήστη
- Βελτίωση της εμπειρίας περιήγησης

## Διαχείριση Cookies

Μπορείτε να διαχειριστείτε τα cookies μέσω των ρυθμίσεων του περιηγητή σας.

## Τύποι Cookies

- **Απαραίτητα**: Για τη βασική λειτουργία του ιστότοπου
- **Προτιμήσεις**: Για την απομνημόνευση των επιλογών σας
"""

    else:  # English
        return """# Cookie Policy

## What are Cookies?

Cookies are small text files stored on your device when you visit our website.

## How We Use Cookies

We use cookies for:
- Storing preferences (language, theme)
- Maintaining user session
- Improving browsing experience

## Managing Cookies

You can manage cookies through your browser settings.

## Types of Cookies

- **Essential**: For basic website functionality
- **Preferences**: To remember your choices
"""
