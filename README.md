# Νεότερη έκδοση: εκκίνηση με διαγνωστικά

[Λήψη νέου ZIP](https://github.com/gkampanis/mini-erp/raw/refs/heads/downloads/MiniERP-Startup-Fix-20261022-080100.zip)

Αποσυμπίεση όλων των αρχείων και διπλό κλικ στο **ANOIGMA_MINI_ERP.bat**. Χρησιμοποιεί την υπάρχουσα Python, κρατά ανοιχτή την κονσόλα και καταγράφει το σφάλμα στο `%LOCALAPPDATA%\MiniERP\Logs`. Δεν εγκαθιστά λογισμικό, δεν αλλάζει EBS ή πραγματικά δεδομένα. Η αιτία αποτυχίας στο συγκεκριμένο Windows PC δεν έχει ακόμη επιβεβαιωθεί. Η νέα Python εκκίνηση ελέγχθηκε σε cloud στον source και στο ZIP· πραγματικό Windows BAT/CMD acceptance παραμένει NOT_RUN.

---

# Mini ERP — δοκιμαστικό πακέτο

[Λήψη MiniERP-Demo.zip](https://github.com/gkampanis/mini-erp/raw/refs/heads/downloads/MiniERP-Demo.zip)

Αποσυμπιέστε το ZIP και τρέξτε START_DEMO.cmd. Απαιτείται Python 3.12+ με Tcl/Tk. Περιέχει μόνο συνθετικά demo δεδομένα, όχι πραγματικά παραστατικά. Δεν συνδέεται στο EBS και δεν κάνει λογιστικές καταχωρίσεις.

Οι έλεγχοι cloud έχουν περάσει. Windows/live EBS: NOT_RUN. Δείτε τη συνοδευτική verification αναφορά και το SHA-256.
