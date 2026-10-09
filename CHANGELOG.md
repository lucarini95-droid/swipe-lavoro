# Registro delle versioni

Ogni modifica importante ha qui una riga. Il numero è lo stesso di `VERSIONE` in `docs/index.html`
e dell'inizio del titolo del commit su GitHub (vedi README → *Tornare a una versione precedente*).

## v1.2 — 9 ottobre 2026
- Titoli con lingue in alternativa ("German, Italian OR Nordic") non mostrano i badge "+ lingua".
- Sincronizzazione tra dispositivi: salvate, scartate e "Candidato" sono comuni a telefono e Mac.
  Le scelte vanno nel file `decisioni.json` sul ramo `decisioni` (non tocca la pagina).
- Indicatore ☁︎ in alto: sincronizzato / da salvare / non sincronizzato. Senza rete le scelte
  restano nel dispositivo e partono appena torna la connessione.
- "Annulla" ora marca la decisione come annullata invece di cancellarla (serve alla sincronizzazione).

## v1.1 — 9 ottobre 2026
- Le offerte che chiedono l'italiano restano anche se chiedono un'altra lingua in più
  (es. "Italian & Spanish"): sulla carta compare il badge rosso "+ Spagnolo".
- Restano scartate solo le offerte che chiedono un'altra lingua senza l'italiano.

## v1.0 — 9 ottobre 2026
- Prima versione online.
- Ricerca automatica alle 8 e alle 17 (ora italiana) su 31 aziende con hub a Dublino.
- Solo ruoli SDR/BDR. Scartate le offerte che chiedono lingue diverse da italiano e inglese
  (anche "Italian & Spanish").
- Pagina swipe: destra salva, sinistra scarta, annulla, lista salvate con spunta "Candidato".
- Badge "NUOVA" (comparsa da ≤ 2 giorni) e "🇮🇹 Italiano"; installabile sul telefono come app.
