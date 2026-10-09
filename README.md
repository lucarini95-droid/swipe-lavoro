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

## Sincronizzazione tra telefono e Mac

Le scelte (salvate, scartate, "Candidato") vengono salvate su GitHub nel file `decisioni.json`
(ramo `decisioni`), così sono le stesse su ogni dispositivo. Serve un **token**, cioè una chiave
che permette alla pagina di scrivere solo in questo repository.

**Crearlo (una volta sola):**
1. GitHub → foto profilo → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
2. Nome: `swipe-lavoro` · Scadenza: 1 anno (o quella che preferisci)
3. **Repository access** → *Only select repositories* → `swipe-lavoro`
4. **Permissions** → *Repository permissions* → **Contents: Read and write**
5. **Generate token** e copialo (si vede una volta sola: salvalo nel portachiavi/password manager)

**Usarlo (una volta per dispositivo):** apri la pagina → tocca **☁︎** in alto a destra → incolla → **Salva e sincronizza**.

L'indicatore ☁︎ dice lo stato: *sincronizzato* (verde), *da salvare…* (sta per inviare), *non sincronizzato* (rosso: tocca ☁︎ per vedere l'errore).
Senza rete le scelte restano sul dispositivo e partono appena torna la connessione.
Se due dispositivi cambiano la stessa offerta, vince la modifica più recente.

Il token resta solo nel browser del dispositivo, non nel codice. Se lo perdi o scade: ne crei uno nuovo e lo reincolli.
Nota: il repository è pubblico, quindi anche `decisioni.json` (l'elenco delle offerte che salvi) è visibile a chi conosce il link.

## Lanciare una ricerca subito
Tab **Actions** → **Cerca offerte** → **Run workflow** → **Run workflow**. Dopo 1–3 minuti la pagina si aggiorna.

## Modificare qualcosa
1. Apri il file su GitHub e premi la matita ✏️ (oppure chiedi a Claude)
2. Fai la modifica, poi **Commit changes**: ogni salvataggio diventa una versione nella cronologia
3. Se è una modifica importante: aggiorna `VERSIONE` in `docs/index.html`, aggiungi una riga in `CHANGELOG.md`
4. La pagina si aggiorna da sola in 1–2 minuti

## Tornare a una versione precedente
Ogni modifica è salvata nella cronologia, niente si perde.

- **Le versioni:** ogni modifica importante è un salvataggio (commit) il cui titolo inizia con il numero
  di versione (`v1.0 - …`, `v1.1 - …`). Il dettaglio di cosa cambia è in `CHANGELOG.md`
- **Vederle:** tab **Code** → link **commits** (icona orologio) sopra l'elenco dei file
- **Tornare indietro:** apri quel commit, copia il suo codice (es. `a1b2c3d`) e chiedi a Claude
  "annulla il commit a1b2c3d" o "torna alla v1.1". Si crea una nuova versione uguale a quella vecchia,
  senza cancellare la storia, quindi si può sempre tornare avanti
- **Scaricare una versione intera:** apri il commit → **Browse files** → **Code** → **Download ZIP**

I commit automatici "Offerte aggiornate …" sono solo dati nuovi, non modifiche al codice.
