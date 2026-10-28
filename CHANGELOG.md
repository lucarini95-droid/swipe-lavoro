# Registro delle versioni

Ogni modifica importante ha qui una riga. Il numero è lo stesso di `VERSIONE` in `docs/index.html`
e dell'inizio del titolo del commit su GitHub (vedi README → *Tornare a una versione precedente*).

## v1.4 — 28 ottobre 2026
- **Stelle da 0 a 5** su ogni offerta, con i motivi sotto il titolo. Pesi modificabili in `PESI` (monitor.py).
  Il mazzo e le salvate sono ordinati per stelle, poi per data.
- **Mercati esclusi**: le offerte UK/Irlanda, "English speaking", Africa, Americhe, APAC non vengono più proposte
  (a meno che citino l'italiano). Prima passavano, es. "MDR (UK/IE Markets)", "BDR UKI".
- Per i titoli generici si legge anche il testo dell'annuncio: "fluent in German" o "covering the UK&I" escludono.
- Corretto: l'italiano citato nel testo veniva cercato solo nei primi 900 caratteri. Ora nel testo intero.
- Solo Dublino: escluse Cork, Galway, Limerick, Belfast e altre città (prima "Ireland" bastava).
- Parole chiave del titolo allargate (outbound sales, sales representative, new business representative…);
  aggiunte lingue/mercati: catalano, belga, portoghese "Portugal", lituano, Middle East/UAE.
- Stage/internship: −2 stelle.
- In fondo alla pagina "escluse" (prima "scartate per lingua") con motivo e link all'annuncio.
- Aziende lette passate da 52 a 79. Aggiunte: HubSpot, GitLab, Notion, Gong (ora su Greenhouse), Qualtrics
  (ora leggibile), Anthropic, Vanta, Mews, LearnUpon, Typeform, Squarespace, Abnormal Security, Sitecore,
  New Relic, Wix, Databricks, Coinbase, ZoomInfo, Pipedrive, SurveyMonkey, Wiz, Huntress, Lightspeed,
  Payoneer, SumUp, Etsy, Sprinklr, Circle. Indirizzi Workday diretti per Zendesk e Workday.

## v1.3.1 — 27 ottobre 2026
- Sicurezza/manutenzione: le azioni GitHub passano a `actions/checkout@v6` e `actions/setup-python@v6`,
  che girano su Node 24 (Node 20 è fuori supporto). Toglie l'avviso Node.js nella tab Actions.

## v1.3 — 9 ottobre 2026
- Aziende lette passate da 31 a 49. Aggiunte: Salesforce, Microsoft, Amazon/AWS, Rippling, Docusign,
  Mastercard, PayPal, Adobe, Cisco, Twilio, Snowflake, X/xAI, Guidewire, Zoom/Workvivo, HPE, FIS,
  Veeam, Ericsson, Teamwork.com.
- Nuovi lettori in monitor.py: Eightfold, Jibe, Phenom, Rippling, Amazon, Personio, iCIMS.
- Workday: un indirizzo sbagliato ora dà errore invece di sembrare "zero offerte"; le offerte
  con più sedi ("3 Locations") non vengono più perse.
- Aggiunte anche U.S. Bank/Elavon e Fiserv (51 aziende). Offerte "Switzerland/Austria" scartate (tedesco).
- Le offerte di un'azienda appena aggiunta non risultano "NUOVA" al primo giro; un secondo tentativo se un sito risponde male.
- Nuovo `rileva_fonti.py` + azione "Rileva fonti": trova dove pubblicano le offerte le aziende mancanti.

## v1.2 — 9 ottobre 2026
- Corretto: dal secondo giro tutte le offerte risultavano "NUOVA"; ora la data di prima comparsa resta quella vera.
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
