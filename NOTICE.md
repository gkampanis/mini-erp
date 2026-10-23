# Προέλευση

`app/infrastructure/importers/legacy_primitives.py` περιέχει επιλεγμένα καθαρά functions και aliases από το EBS Batch Agent v2.9 που παρασχέθηκε από τον χρήστη ειδικά για επιλεκτική επαναχρησιμοποίηση. Ο monetary parser προσαρμόστηκε στο domain και η orchestration/GUI/database είναι νέα. Το πρωτότυπο δεν μεταβάλλεται ούτε εισάγεται ως runtime dependency. Δεν έχει επιβεβαιωθεί άδεια δημόσιας αναδιανομής του baseline: απαιτείται έλεγχος πριν εξωτερική δημοσίευση. Δεν αντιγράφηκε κώδικας ERPNext/Dolibarr.

Η έρευνα ERPNext/OCA/Dolibarr/Paperless-ngx/CustomTkinter χρησιμοποιήθηκε για λειτουργικές και σχεδιαστικές ιδέες μόνο. Δεν εισήχθη δικός τους κώδικας, UI assets ή runtime dependencies. Pinned πηγές και άδειες καταγράφονται στα docs/RESEARCH_WORKFLOW.md και docs/RESEARCH_UI.md.


Η νέα προαιρετική ροή RPA προσαρμόζει τη σειρά πέντε πεδίων και την τεχνική
Unicode SendInput του παραδοθέντος baseline, χωρίς μεταβολή του πρωτοτύπου.
Το βιβλίο *Designing Interfaces* χρησιμοποιήθηκε ως σχεδιαστική αναφορά μόνο·
δεν διανέμεται το PDF, εικόνες ή αποσπάσματά του.

Η μικρή προσαρμογή Windows DPI στο `app/ui/dpi.py` βασίζεται στη σχετική
τεχνική του Legend (gkampanis/legend), MIT, commit
b4f29864df37c92b5ce00071c2f457a263ab8092.

Copyright (c) 2026 File Organizer contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Συγκεκριμένο user-owned myInvoices v0.13.0

Κατόπιν ρητής υπόδειξης του χρήστη επιλέχθηκαν τα modules στο
`app/infrastructure/providers/` από το δικό του `gkampanis/legend`, commit
`36a1539c71102f89ecfdd26bf25283d293f86c8d`. Πρόκειται για διαφορετικό κώδικα από
το παλαιότερο File Organizer HEAD που αναφέρεται παραπάνω. Η αναφορά MIT του
File Organizer δεν αποδίδεται αυτομάτως σε όλο το myInvoices. Δεν βρέθηκε
ξεχωριστό LICENSE στο συγκεκριμένο root. Η επαναχρησιμοποίηση γίνεται στο
έργο του ίδιου χρήστη με την εξουσιοδότησή του. Δεν περιλαμβάνονται δεδομένα,
credentials, PDFs πελατών ή profiles. Βλέπε docs/CONNECTED_WORKFLOW.md.

## Προαιρετικό Camoufox

Η προαιρετική δυνατότητα καλεί το επίσημο Python package Camoufox 0.5.8 (MIT)
σε χωριστή εγκατάσταση και τον επίσημο browser v156.0.1-beta.36 (root MPL-2.0
και άδειες επιμέρους συστατικών). Τα τρίτα binaries/source δεν περιλαμβάνονται
στο ZIP Mini ERP. Η εγκατάσταση διατηρεί τα περιλαμβανόμενα license notices.
https://github.com/daijro/camoufox — https://pypi.org/project/camoufox/0.5.8/
