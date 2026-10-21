# Έρευνα GitHub: document workflow και desktop UI

Έλεγχος πηγών: 21 Οκτωβρίου 2026. Η έρευνα αφορά μικρές σχεδιαστικές ιδέες για την υπάρχουσα εφαρμογή. Δεν αντιγράφηκε κώδικας, δεν εγκαταστάθηκε βιβλιοθήκη και δεν μεταφέρθηκαν λειτουργίες OCR/cloud/έκδοσης παραστατικών.

Το GitHub REST API δεν ήταν προσβάσιμο από το υπάρχον proxy (403). Οι αναγνώσεις `git ls-remote` μέσω της υπάρχουσας GitHub πρόσβασης και τα raw αρχεία λειτούργησαν. Τα commits παρακάτω καταγράφηκαν από πραγματική read-only ανάγνωση, όχι από στατιστικά αναζήτησης ή υποθέσεις. Τα versions του source branch δεν δηλώνονται ως τελευταίες σταθερές κυκλοφορίες.

## 1. Paperless-ngx

- Repository: https://github.com/paperless-ngx/paperless-ngx
- Εξετασμένο `main`: `a5c8b82da5b392c812a05289c0d13aeec843d644`.
- [Version στο εξετασμένο source](https://github.com/paperless-ngx/paperless-ngx/blob/a5c8b82da5b392c812a05289c0d13aeec843d644/src/paperless/version.py): tuple `3, 3, 3`.
- [LICENSE του ίδιου commit](https://github.com/paperless-ngx/paperless-ngx/blob/a5c8b82da5b392c812a05289c0d13aeec843d644/LICENSE): κείμενο GNU GPL version 3. Πηγή ιδεών μόνο· δεν γίνεται ενσωμάτωση GPL source/UI assets στο Mini ERP.

Εξετάστηκαν τα ακόλουθα πραγματικά αρχεία:

| Πηγή | Τι επαληθεύτηκε | Μικρή εφαρμογή στο Mini ERP |
|---|---|---|
| [usage.md — Web UI, Document List, Document Detail](https://github.com/paperless-ngx/paperless-ngx/blob/a5c8b82da5b392c812a05289c0d13aeec843d644/docs/usage.md) | Αναζήτηση/φίλτρα με correspondent και document type, document detail με metadata/history, διαχωρισμός issued date από added date. | Χωριστά ορατά πεδία αντισυμβαλλομένου, ημερομηνίας έκδοσης και προέλευσης εισαγωγής. Όχι αντιγραφή full-text/OCR engine. |
| [usage.md — recommended workflow](https://github.com/paperless-ngx/paperless-ngx/blob/a5c8b82da5b392c812a05289c0d13aeec843d644/docs/usage.md#processing-of-documents-in-paperless) | Έλεγχος correspondent/type/date πριν την αφαίρεση inbox tag. Η τεκμηρίωση επισημαίνει ότι η αυτόματη ανάγνωση ημερομηνίας μπορεί να αποτύχει. | Η ένδειξη «Προς έλεγχο» πρέπει να παραμένει εμφανής. Αλλαγή εμφάνισης ή επιτυχής εισαγωγή δεν ισοδυναμεί με λογιστική έγκριση. |
| [document-list.component.html](https://github.com/paperless-ngx/paperless-ngx/blob/a5c8b82da5b392c812a05289c0d13aeec843d644/src-ui/src/app/components/document-list/document-list.component.html) | Table/list controls, filter editor, ένδειξη filtered results και `Reset filters`. | Κεντρική αναζήτηση, εμφανές πλήθος αποτελεσμάτων και εύκολος καθαρισμός φίλτρων αντί συνεχών modal dialogs. |
| [document-detail.component.html](https://github.com/paperless-ngx/paperless-ngx/blob/a5c8b82da5b392c812a05289c0d13aeec843d644/src-ui/src/app/components/document-detail/document-detail.component.html) | Πραγματικά tabs Metadata, Preview, History· στο Metadata εμφανίζονται original filename/checksum/size. | Tabs «Στοιχεία», «Προέλευση», «Ιστορικό», με τα ήδη διαθέσιμα database στοιχεία. Το raw JSON και το SHA256 πάνε στην Προέλευση αντί να κυριαρχούν στη βασική οθόνη. |

Το Paperless-ngx είναι document management/archive σύστημα, όχι πηγή ελληνικών λογιστικών κανόνων ή ελεγμένος EBS connector. Δεν επαληθεύτηκε καμία τέτοια δυνατότητα και δεν πρέπει να του αποδοθεί. Η αντιγραφή αυτόματης ταξινόμησης εγγράφων σε λογιστικές ομάδες θα ήταν λανθασμένη μεταφορά: η ταξινόμηση αγορών/εξόδων χρειάζεται τους δικούς μας εγκεκριμένους κανόνες.

## 2. CustomTkinter

- Repository: https://github.com/TomSchimansky/CustomTkinter
- Εξετασμένο `master`: `1227dca8d5f6be04b527dba51549fce137988b94`.
- [Source version](https://github.com/TomSchimansky/CustomTkinter/blob/1227dca8d5f6be04b527dba51549fce137988b94/customtkinter/__init__.py): `__version__ = "6.0.0"` στο εξετασμένο branch, όχι claim έκδοσης PyPI.
- [LICENSE](https://github.com/TomSchimansky/CustomTkinter/blob/1227dca8d5f6be04b527dba51549fce137988b94/LICENSE): MIT, copyright Tom Schimansky. Δεν χρησιμοποιήθηκε source ή dependency· συνεπώς δεν προστίθεται package μόνο για το styling.
- [Readme.md](https://github.com/TomSchimansky/CustomTkinter/blob/1227dca8d5f6be04b527dba51549fce137988b94/Readme.md): περιγράφει συνεπή widgets, light/dark appearance και HighDPI scaling σε Windows/macOS. Αυτά είναι δηλώσεις του upstream, όχι επικυρωμένα αποτελέσματα του Mini ERP.
- [examples/complex_example.py](https://github.com/TomSchimansky/CustomTkinter/blob/1227dca8d5f6be04b527dba51549fce137988b94/examples/complex_example.py): επαληθεύτηκαν sidebar frame, κύριο grid με weights/sticky, χωριστές περιοχές περιεχομένου και tabview.

Χρήσιμη μεταφορά ως δικός μας `ttk.Style` και layout:

1. Συνεπής μικρή παλέτα: ανοιχτό background, καθαρές επιφάνειες, ένα primary action χρώμα και διακριτό warning χρώμα.
2. Καθαρή τυπογραφική ιεραρχία: τίτλος οθόνης, βοηθητικό κείμενο, πίνακας, ενέργειες. Δεν χρειάζονται διακοσμητικά icons ή theme settings για το πρώτο MVP.
3. Συνεπές padding, ευανάγνωστο row height, ποσά δεξιά και IDs ως κείμενο. Αποφυγή ίσου width σε επωνυμία, ποσό και ημερομηνία.
4. Expandable grid/paned layout και σωστές scrollbars ώστε να δουλεύει σε μικρότερες οθόνες. Δεν αντιγράφεται η περίπλοκη example εφαρμογή.

## Προτεινόμενο μικρό layout με το υπάρχον ttk

```text
Mini ERP                         [Εισαγωγή Excel]
Παραστατικά εισαγωγής             Εταιρεία / πλήθος

[Αναζήτηση ΑΦΜ, επωνυμίας, αριθμού, MARK...] [Καθαρισμός]
[Πλήθος αποτελεσμάτων] [Ένδειξη Προς έλεγχο]

Πίνακας παραστατικών με σωστά πλάτη, zebra rows και scrollbars
Επιλογή γραμμής → σύντομη κατανοητή περίληψη
[Άνοιγμα παραστατικού]

Detail:
[Στοιχεία] [Προέλευση] [Ιστορικό]

Import preview:
[1. Αντιστοίχιση] [2. Έγκυρες γραμμές] [3. Εξαιρέσεις]
Σαφής επανέλεγχος αλλαγμένου mapping → ρητή επιβεβαίωση εισαγωγής
```

Τα εισαγόμενα documents σήμερα είναι όλα `needs_review`. Δεν εμφανίζουμε τεχνητές μετρήσεις «Έτοιμα για EBS» ή «Καταχωρισμένα» και δεν δημιουργούμε ψεύτικα tabs PDF/δελτίων αποστολής πριν υπάρξουν πραγματικά δεδομένα και λειτουργίες. Η μελλοντική τοποθέτησή τους δίπλα στα παραστατικά προβλέπεται στο product plan, αλλά δεν είναι διακοσμητικά placeholders της παρούσας αλλαγής.

## Έλεγχοι κατά την ενσωμάτωση

- Διατηρούνται ακριβώς τα service contracts import/search/detail και η απαίτηση επιβεβαίωσης.
- Επιβεβαιώνεται πραγματική εισαγωγή και duplicate retry μέσω GUI, όχι μόνο styling screenshots.
- Ελέγχεται ότι αλλαγή mapping απαιτεί επανέλεγχο, οι απορρίψεις είναι προσβάσιμες και το κλείσιμο preview δεν εισάγει στοιχεία.
- Ελέγχεται ότι επιλογή γραμμής εμφανίζει ποσά/ΑΦΜ χωρίς απώλεια αρχικών μηδενικών και τα τεχνικά δεδομένα παραμένουν διαθέσιμα στην Προέλευση.
- Επιβεβαιώνεται ελληνική απόδοση στο ήδη επαληθευμένο system Tk 8.6. Η desktop δοκιμή Linux δεν ισοδυναμεί με αποδοχή στα Windows ούτε με επιτυχή καταχώριση στο EBS.
