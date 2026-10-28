#!/usr/bin/env python3
"""
Rileva DOVE pubblicano le offerte le aziende che monitor.py non riesce ancora a leggere.

Non serve a ogni giro: si lancia a mano da GitHub (Actions -> "Rileva fonti" -> Run workflow)
quando si vogliono aggiungere aziende. Scrive report_fonti.csv con, per ogni azienda,
le fonti trovate e quante offerte sales a Dublino contengono.

Per ogni azienda prova, in quest'ordine:
  1. gli ATS con indirizzo pubblico (Greenhouse, Lever, Ashby, SmartRecruiters,
     Workable, Personio) con alcuni nomi probabili ("slug")
  2. la pagina carriere: cerca "impronte" di ATS noti nel codice della pagina
  3. Workday: indirizzi ipotizzati + ricerca automatica del tenant
  4. fonti speciali per i giganti con sito proprio (Amazon, Microsoft, Atlassian)

Le aziende e gli indizi sono nel dizionario AZIENDE qui sotto: per aggiungerne una
basta una riga.
"""

import csv
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import monitor  # riusa lettori ATS, filtri e risoluzione Workday

T = 12  # secondi di attesa massima per ogni richiesta

# --------------------------------------------------------------------------
# Aziende da rilevare: nome -> (pagina carriere, slug da provare, indirizzi Workday ipotizzati)
# Gli indizi Workday vengono da conoscenza generale e vanno VERIFICATI: lo script li prova.
AZIENDE = {
    # --- Giro 3 (ottobre 2026): aziende con ufficio commerciale a Dublino non ancora monitorate.
    # Slug ipotizzati: lo script li prova su tutti gli ATS pubblici e conta le offerte a Dublino.
    # Il giro precedente (giganti con portale proprio) e' nella storia git di questo file.
    'Squarespace': ("", ['squarespace'], []),
    'Coinbase': ("", ['coinbase'], []),
    'New Relic': ("", ['newrelic'], []),
    'Udemy': ("", ['udemy'], []),
    'Etsy': ("", ['etsy'], []),
    'GitLab': ("", ['gitlab'], []),
    'Cloudflare': ("", ['cloudflare'], []),
    'ZoomInfo': ("", ['zoominfo'], []),
    'Vanta': ("", ['vanta'], []),
    'Anthropic': ("", ['anthropic'], []),
    'Notion': ("", ['notion'], []),
    'Clio': ("", ['clio', 'goclio'], []),
    'Seismic': ("", ['seismic', 'seismicsoftware'], []),
    'Salesloft': ("", ['salesloft'], []),
    'Outreach': ("", ['outreach', 'outreachio'], []),
    'Groupon': ("", ['groupon'], []),
    'Wix': ("", ['wix', 'wix2', 'wixcom'], []),
    'Yahoo': ("", ['yahoo', 'yahooinc'], []),
    'Zalando': ("", ['zalando'], []),
    'Deel': ("", ['deel'], []),
    'Remote.com': ("", ['remote', 'remotecom'], []),
    'Airtable': ("", ['airtable'], []),
    'Smartsheet': ("", ['smartsheet'], []),
    'Sprinklr': ("", ['sprinklr'], []),
    'Contentsquare': ("", ['contentsquare'], []),
    'Figma': ("", ['figma'], []),
    'Canva': ("", ['canva'], []),
    'Miro': ("", ['miro', 'realtimeboard'], []),
    'monday.com': ("", ['mondaycom', 'monday'], []),
    'Pipedrive': ("", ['pipedrive'], []),
    'Hootsuite': ("", ['hootsuite'], []),
    'SurveyMonkey': ("", ['surveymonkey', 'momentive'], []),
    'Zapier': ("", ['zapier'], []),
    'Wiz': ("", ['wiz', 'wizinc'], []),
    'Glean': ("", ['glean', 'gleanwork'], []),
    'Perplexity': ("", ['perplexity', 'perplexityai'], []),
    'Cohere': ("", ['cohere'], []),
    'Mistral AI': ("", ['mistral', 'mistralai'], []),
    'ElevenLabs': ("", ['elevenlabs'], []),
    'Revolut': ("", ['revolut'], []),
    'Kraken': ("", ['kraken', 'krakendigitalassetexchange'], []),
    'Bumble': ("", ['bumble'], []),
    'Zuora': ("", ['zuora'], []),
    'Coupa': ("", ['coupa', 'coupasoftware'], []),
    'Medallia': ("", ['medallia'], []),
    'Genesys': ("", ['genesys'], []),
    'Shopify': ("", ['shopify'], []),
    'SumUp': ("", ['sumup'], []),
    'Payhawk': ("", ['payhawk'], []),
    'Pleo': ("", ['pleo'], []),
    'MoonPay': ("", ['moonpay'], []),
    'Circle': ("", ['circle'], []),
    'Algolia': ("", ['algolia'], []),
    'Contentful': ("", ['contentful'], []),
    'Typeform': ("", ['typeform'], []),
    'Brex': ("", ['brex'], []),
    'Ramp': ("", ['ramp'], []),
    'Gorgias': ("", ['gorgias'], []),
    'Attentive': ("", ['attentive'], []),
    'Yotpo': ("", ['yotpo'], []),
    'Similarweb': ("", ['similarweb'], []),
    'Celonis': ("", ['celonis'], []),
    'Databricks': ("", ['databricks'], []),
    'Confluent': ("", ['confluent'], []),
    'Samsara': ("", ['samsara'], []),
    'Docebo': ("", ['docebo'], []),
    'Highspot': ("", ['highspot'], []),
    'Amplitude': ("", ['amplitude'], []),
    'Braze': ("", ['braze'], []),
    'Iterable': ("", ['iterable'], []),
    'Calendly': ("", ['calendly'], []),
    'Dialpad': ("", ['dialpad'], []),
    'Aircall': ("", ['aircall'], []),
    'Talkdesk': ("", ['talkdesk'], []),
    'Five9': ("", ['five9'], []),
    'Xero': ("", ['xero'], []),
    'Phorest': ("", ['phorest'], []),
    'Kitman Labs': ("", ['kitmanlabs'], []),
    'LearnUpon': ("", ['learnupon'], []),
    'Mimecast': ("", ['mimecast'], []),
    'Tenable': ("", ['tenable'], []),
    'Abnormal Security': ("", ['abnormalsecurity'], []),
    'Arctic Wolf': ("", ['arcticwolf'], []),
    'SentinelOne': ("", ['sentinelone'], []),
    'Netskope': ("", ['netskope'], []),
    '1Password': ("", ['1password'], []),
    'Huntress': ("", ['huntress'], []),
    'Vercel': ("", ['vercel'], []),
    'Postman': ("", ['postman'], []),
    'Harness': ("", ['harness'], []),
    'JumpCloud': ("", ['jumpcloud'], []),
    'Drata': ("", ['drata'], []),
    'Cyera': ("", ['cyera'], []),
    'HiBob': ("", ['hibob', 'bob'], []),
    'Factorial': ("", ['factorial', 'factorialhr'], []),
    'Lightspeed': ("", ['lightspeedhq', 'lightspeed'], []),
    'Trustpilot': ("", ['trustpilot'], []),
    'Payoneer': ("", ['payoneer'], []),
    'Checkout.com': ("", ['checkoutcom', 'checkout'], []),
    'Adyen': ("", ['adyen'], []),
    'Airwallex': ("", ['airwallex'], []),
    'Wise': ("", ['wise', 'transferwise'], []),
    'Plaid': ("", ['plaid'], []),
    'Zendesk': ("", ['zendesk'], []),
    'HubSpot': ("", ['hubspot', 'hubspotjobs'], []),
    'Indeed': ("", ['indeed'], []),
    'Workday': ("", ['workday'], []),
    'Qualtrics': ("", ['qualtrics'], []),
    'Gong': ("", ['gong', 'gongio'], []),
    'Hubstaff': ("", ['hubstaff'], []),
    'Personio': ("", ['personio'], []),
    'Unit4': ("", ['unit4'], []),
    'Cvent': ("", ['cvent'], []),
    'Bazaarvoice': ("", ['bazaarvoice'], []),
    'Sitecore': ("", ['sitecore'], []),
    'OneTrust': ("", ['onetrust'], []),
    'Pigment': ("", ['pigment'], []),
    'Agicap': ("", ['agicap'], []),
    'Spendesk': ("", ['spendesk'], []),
    'Mews': ("", ['mews', 'mewssystems'], []),
    'SiteMinder': ("", ['siteminder'], []),
    'Toast': ("", ['toast'], []),
    'Dext': ("", ['dext'], []),
}

# Fonti specifiche trovate a mano (pagine carriere aperte nel browser o ricerche web):
# azienda -> lista di (ATS, slug, URL) da provare con i lettori di monitor.py
EXTRA = {
    "Microsoft":    [("eightfold", "microsoft.com", "https://apply.careers.microsoft.com")],
    "PayPal":       [("eightfold", "paypal.com", "https://paypal.eightfold.ai")],
    "Ericsson":     [("eightfold", "ericsson.com", "https://jobs.ericsson.com")],
    "Amdocs":       [("eightfold", "amdocs.com", "https://jobs.amdocs.com")],
    "Twilio":       [("eightfold", "twilio.com", "https://jobs.twilio.com")],
    "Amazon / AWS": [("amazon", "", "")],
    "DocuSign":     [("jibe", "", "https://careers.docusign.com")],
    "Rippling":     [("rippling", "rippling", "")],
    "Adobe":        [("phenom", "", "https://careers.adobe.com/us/en")],
    # Phenom da verificare
    "Qualtrics":    [("phenom", "", "https://www.qualtrics.com/careers/us/en")],
    "U.S. Bank / Elavon": [("phenom", "", "https://careers.usbank.com/global/en")],
    "Fiserv":       [("phenom", "", "https://careers.fiserv.com/us/en")],
}

# Impronte nel codice di una pagina carriere -> nome ATS (+ gruppo che estrae lo slug/indirizzo)
IMPRONTE = [
    ("workday",         r"https?://[a-z0-9_.-]+\.myworkdayjobs\.com/[A-Za-z0-9_/-]+"),
    ("greenhouse",      r"(?:boards|job-boards)(?:-api)?\.greenhouse\.io/(?:v1/boards/|embed/job_board\?for=)?([a-z0-9_-]+)"),
    ("lever",           r"jobs\.lever\.co/([a-z0-9_-]+)"),
    ("ashby",           r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("workable",        r"apply\.workable\.com/([a-z0-9_-]+)"),
    ("personio",        r"([a-z0-9-]+)\.jobs\.personio\.(?:de|com)"),
    ("eightfold",       r"([a-z0-9-]+)\.eightfold\.ai"),
    ("icims",           r"([a-z0-9-]+)\.icims\.com"),
    ("phenom",          r"phenompeople|phenom\.com|cdn\.phenom"),
    ("successfactors",  r"successfactors|sapsf\.com|career\d*\.successfactors"),
    ("oracle",          r"([a-z0-9-]+)\.fa\.[a-z0-9]+\.oraclecloud\.com"),
    ("avature",         r"([a-z0-9-]+)\.avature\.net"),
    ("taleo",           r"([a-z0-9-]+)\.taleo\.net"),
]


def conta(azienda, offerte):
    """(totali, sales a Dublino tenute, scartate per lingua) per una lista grezza di offerte."""
    tenute, scartate = monitor.filtra(azienda, offerte)
    dublino = sum(1 for o in offerte if monitor.LUOGO.search(o[1] or ""))
    return len(offerte), dublino, len(tenute), len(scartate), [t["titolo"] for t in tenute][:5]


# ------------------------------------------------------------------ rileva

def prova_slug(s, azienda, slug):
    """Prova uno slug su tutti gli ATS con indirizzo pubblico. Ritorna le fonti che rispondono."""
    trovate = []
    prove = [("greenhouse", monitor.jobs_greenhouse), ("lever", monitor.jobs_lever),
             ("ashby", monitor.jobs_ashby), ("smartrecruiters", monitor.jobs_smartrecruiters),
             ("workable", monitor.jobs_workable), ("personio", monitor.jobs_personio)]
    for ats, fn in prove:
        try:
            off = fn(s, slug, "")
            if off:  # almeno un'offerta: la fonte esiste
                trovate.append((ats, slug, "", off))
        except Exception:
            pass
    return trovate


def rileva(args):
    azienda, (careers, slugs, wd_ipotesi) = args
    s = monitor.sess()
    righe, impronte, note = [], [], []

    # 1. slug sugli ATS pubblici
    for slug in slugs:
        for ats, sl, url, off in prova_slug(s, azienda, slug):
            righe.append((ats, sl, url, off))

    # 2. impronte nella pagina carriere
    try:
        r = s.get(careers, timeout=T, allow_redirects=True)
        testo = r.url + " " + r.text[:600000]
        note.append(f"pagina {r.status_code} -> {r.url[:80]}")
        for ats, rx in IMPRONTE:
            m = re.search(rx, testo, re.I)
            if m:
                impronte.append(f"{ats}:{(m.group(1) if m.groups() else m.group(0))[:60]}")
                if ats == "workday":
                    wd_ipotesi = [m.group(0).rstrip("/")] + list(wd_ipotesi)
                elif ats in ("greenhouse", "lever", "ashby", "smartrecruiters", "workable", "personio"):
                    sl = m.group(1)
                    if sl not in slugs:
                        for f in prova_slug(s, azienda, sl):
                            righe.append(f)
    except Exception as e:
        note.append(f"pagina errore {type(e).__name__}")

    # 3. Workday: indirizzi ipotizzati, poi ricerca automatica sui nomi
    wd_ok = None
    for u in wd_ipotesi:
        try:
            off = monitor.jobs_workday(s, "", u)   # da' errore se l'indirizzo e' sbagliato
            wd_ok = u
            righe.append(("workday", "", u, off))
            break
        except Exception:
            note.append(f"workday ipotesi KO {u.split('/')[2]}")
    if not wd_ok:
        for slug in slugs:
            try:
                u = monitor.risolvi_workday(s, azienda, slug, "", {})
            except Exception:
                u = None
            if u:
                try:
                    righe.append(("workday", slug, u, monitor.jobs_workday(s, slug, u)))
                    break
                except Exception:
                    pass

    # 4. fonti specifiche trovate a mano
    for ats, slug, url in EXTRA.get(azienda, []):
        try:
            righe.append((ats, slug, url, monitor.LETTORI[ats](s, slug, url)))
        except Exception as e:
            note.append(f"{ats} errore {type(e).__name__}: {str(e)[:60]}")

    risultati = []
    for ats, slug, url, off in righe:
        tot, dub, ten, sc, esempi = conta(azienda, off)
        risultati.append({"Azienda": azienda, "ATS": ats, "Slug": slug, "URL": url,
                          "Offerte totali": tot, "A Dublino": dub, "SDR tenute": ten,
                          "SDR scartate lingua": sc, "Esempi": " | ".join(esempi),
                          "Impronte": "; ".join(impronte), "Note": "; ".join(note)})
    if not risultati:
        risultati.append({"Azienda": azienda, "ATS": "NON TROVATO", "Slug": "", "URL": "",
                          "Offerte totali": 0, "A Dublino": 0, "SDR tenute": 0,
                          "SDR scartate lingua": 0, "Esempi": "",
                          "Impronte": "; ".join(impronte), "Note": "; ".join(note)})
    return risultati


def main():
    with ThreadPoolExecutor(max_workers=8) as ex:
        tutte = [r for gruppo in ex.map(rileva, AZIENDE.items()) for r in gruppo]

    campi = ["Azienda", "ATS", "Slug", "URL", "Offerte totali", "A Dublino", "SDR tenute",
             "SDR scartate lingua", "Esempi", "Impronte", "Note"]
    with open("report_fonti.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campi)
        w.writeheader()
        w.writerows(tutte)

    for r in tutte:
        print(f"{r['Azienda'][:24]:<24} {r['ATS']:<15} {str(r['Slug'] or r['URL'])[:55]:<55} "
              f"tot={r['Offerte totali']:<5} dub={r['A Dublino']:<4} sdr={r['SDR tenute']} "
              f"| {r['Impronte'][:80]}")


if __name__ == "__main__":
    sys.exit(main())
