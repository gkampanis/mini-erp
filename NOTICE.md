# Προέλευση

`app/infrastructure/importers/legacy_primitives.py` περιέχει επιλεγμένα καθαρά functions και aliases από το EBS Batch Agent v2.9 που παρασχέθηκε από τον χρήστη ειδικά για επιλεκτική επαναχρησιμοποίηση. Ο monetary parser προσαρμόστηκε στο domain και η orchestration/GUI/database είναι νέα. Το πρωτότυπο δεν μεταβάλλεται ούτε εισάγεται ως runtime dependency. Δεν έχει επιβεβαιωθεί άδεια δημόσιας αναδιανομής του baseline: απαιτείται έλεγχος πριν εξωτερική δημοσίευση. Δεν αντιγράφηκε κώδικας ERPNext/Dolibarr.

Η έρευνα ERPNext/OCA/Dolibarr/Paperless-ngx/CustomTkinter χρησιμοποιήθηκε για λειτουργικές και σχεδιαστικές ιδέες μόνο. Δεν εισήχθη δικός τους κώδικας, UI assets ή runtime dependencies. Pinned πηγές και άδειες καταγράφονται στα docs/RESEARCH_WORKFLOW.md και docs/RESEARCH_UI.md.
