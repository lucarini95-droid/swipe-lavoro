# Swipe Lavoro · SDR/BDR Dublino

Due volte al giorno GitHub cerca da solo le offerte SDR/BDR a Dublino e le mette in una pagina
dove le vedi **una alla volta**: destra = salva, sinistra = scarta.

## Come è fatto

| File | Cosa fa |
|---|---|
| `monitor.py` | Cerca le offerte. **Filtri in cima al file** (TITOLO, ESCLUDI, LINGUE, BLACKLIST) |
| `ats_mapping_v2.csv` | Elenco aziende e dove leggere le loro offerte. Una riga = un'azienda |
| `.github/workflows/monitor.yml` | Dice a GitHub *quando* lanciare `monitor.py` (orari in cima) |
| `docs/index.html` | La pagina swipe. Logica divisa in blocchi numerati e commentati |
| `docs/jobs.json` | Le offerte trovate. Lo scrive `monitor.py`, non va toccato a mano |
| `CHANGELOG.md` | Cosa è cambiato in ogni versione |

## Usarlo sul telefono

Non serve nessuna app da scaricare: è una pagina web che si "installa" sulla schermata Home.

**iPhone (Safari)**
1. Apri il link della pagina in **Safari** (non Chrome)
2. Tocca il pulsante **Condividi** (quadrato con freccia in su)
3. Scorri e tocca **Aggiungi alla schermata Home** → **Aggiungi**
4. Da ora la apri dall'icona: si apre a schermo intero come un'app

**Android (Chrome)**
1. Apri il link in Chrome
2. Menu **⋮** → **Aggiungi a schermata Home** (o **Installa app**)

Le scelte (salvate/scartate) restano sul dispositivo dove le fai: telefono e Mac sono separati.

## Lanciare una ricerca subito
Tab **Actions** → **Cerca offerte** → **Run workflow** → **Run workflow**. Dopo 1–3 minuti la pagina si aggiorna.

## Modificare qualcosa
1. Apri il file su GitHub e premi la matita ✏️ (oppure chiedi a Claude)
2. Fai la modifica, poi **Commit changes**: ogni salvataggio diventa una versione nella cronologia
3. Se è una modifica importante: aggiorna `VERSIONE` in `docs/index.html`, aggiungi una riga in `CHANGELOG.md`
4. La pagina si aggiorna da sola in 1–2 minuti

## Tornare a una versione precedente
Ogni modifica è salvata nella cronologia, niente si perde.

- **Vedere le versioni:** tab **Code** → link **commits** (icona orologio) sopra l'elenco dei file
- **Annullare una modifica:** apri quel commit → copia il suo codice (es. `a1b2c3d`) e chiedi a Claude
  "annulla il commit a1b2c3d" (fa un `git revert`, che crea una nuova versione uguale a prima, senza cancellare la storia)
- **Versioni "fotografate":** ogni versione importante ha un tag (`v1.0`, `v1.1`…) nella sezione **Tags**:
  da lì scarichi tutto com'era a quella versione

I commit automatici "Offerte aggiornate …" sono solo dati nuovi, non modifiche al codice.
