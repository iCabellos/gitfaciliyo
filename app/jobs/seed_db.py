"""
Reconstruye la base de datos a partir de documentos (PDF/CSV).

Procesa todos los archivos de una carpeta (por defecto data/inbox/) — extractos
del banco, Trade Republic, Nexo — y guarda sus snapshots mensuales en la DB.

Uso:
    python -m jobs.seed_db [carpeta]      # por defecto data/inbox
    python -m jobs.seed_db --reset [carpeta]   # vacía snapshots antes de sembrar
"""

import glob
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from sources import ingest, db   # noqa: E402

DATA_DIR = os.environ.get("PATRIMONIO_DATA_DIR") or os.path.join(HERE, "data")
DEFAULT_INBOX = os.path.join(DATA_DIR, "inbox")


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    reset = "--reset" in argv
    argv = [a for a in argv if a != "--reset"]
    inbox = argv[0] if argv else DEFAULT_INBOX

    if reset:
        db.reset_snapshots()
        print("Snapshots vaciados.")

    files = sorted(glob.glob(os.path.join(inbox, "*.pdf")) +
                   glob.glob(os.path.join(inbox, "*.csv")))
    if not files:
        print(f"No hay documentos en {inbox}. Copia ahí tus PDFs/CSV.")
        return
    print(f"Base de datos: {db.backend()} · {len(files)} documento(s) en {inbox}")
    for f in files:
        try:
            res = ingest.process(f)
            print(" ✔", os.path.basename(f), "→", res["summary"])
        except Exception as exc:  # noqa: BLE001
            print(" ✖", os.path.basename(f), "→", exc)
    print("\nSnapshots actuales:")
    for month, cats in sorted(db.get_snapshots().items()):
        for cat, val in cats.items():
            print(f"  {month}  {cat:24s} {val:>12.2f} €")


if __name__ == "__main__":
    main()
