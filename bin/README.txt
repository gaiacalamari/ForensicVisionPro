Questa cartella è gestita da tools/fetch_tools.py, avviato automaticamente da build_windows.bat.

  tools.json       elenco degli strumenti da scaricare (modificabile)
  tools.lock.json  cosa è stato installato: URL, SHA-256, data, versione verificata (generato)

Per aggiungere uno strumento, aggiungere un blocco in tools.json con:
  name        nome dello strumento (quello che il programma cerca, es. "mediainfo")
  platform    win32, linux, darwin o any
  urls        uno o più indirizzi dell'archivio .zip, provati in ordine
  sha256      hash atteso dell'archivio, oppure sha256_url con l'indirizzo dove il fornitore lo pubblica
  extract     { "percorso/nell/archivio/*.exe": "nome_in_bin.exe" }  (sono ammessi i caratteri jolly)
  dirs        { "*/cartella": "cartella" } per copiare intere cartelle (facoltativo)
  check       [ "nome_in_bin.exe", "--version" ] per verificare che si avvii (facoltativo)
Poi rieseguire build_windows.bat oppure:  python tools\fetch_tools.py --only nome

Se l'hash non corrisponde l'archivio viene scartato e non viene estratto nulla.
Ordine di ricerca nel programma: percorso nelle Impostazioni, poi questa cartella, poi il PATH di sistema.
