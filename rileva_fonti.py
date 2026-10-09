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
    "Google":              ("https://www.google.com/about/careers/applications/jobs/results?location=Dublin", ["google"], []),
    "Meta":                ("https://www.metacareers.com/jobs", ["meta", "facebook"], []),
    "Microsoft":           ("https://jobs.careers.microsoft.com/global/en/search?lc=Dublin", ["microsoft"], []),
    "Amazon / AWS":        ("https://www.amazon.jobs/en/", ["amazon", "aws"], []),
    "Salesforce":          ("https://careers.salesforce.com/en/jobs/", ["salesforce"], ["https://salesforce.wd12.myworkdayjobs.com/External_Career_Site"]),
    "TikTok":              ("https://lifeattiktok.com/", ["tiktok", "bytedance"], []),
    "PayPal":              ("https://careers.pypl.com/home/", ["paypal"], ["https://paypal.wd1.myworkdayjobs.com/jobs"]),
    "Indeed":              ("https://www.indeed.jobs/", ["indeed"], []),
    "HubSpot":             ("https://www.hubspot.com/careers/jobs", ["hubspot", "hubspotjobs"], []),
    "Rippling":            ("https://www.rippling.com/careers/open-roles", ["rippling"], []),
    "AMCS Group":          ("https://www.amcsgroup.com/careers/", ["amcs", "amcsgroup"], []),
    "X (ex Twitter)":      ("https://careers.x.com/", ["x", "twitter", "xcorp"], []),
    "Oracle":              ("https://careers.oracle.com/jobs/", ["oracle"], []),
    "IBM":                 ("https://www.ibm.com/careers/search", ["ibm"], []),
    "Atlassian":           ("https://www.atlassian.com/company/careers/all-jobs", ["atlassian"], []),
    "Guidewire Software":  ("https://careers.guidewire.com/", ["guidewire"], ["https://guidewire.wd5.myworkdayjobs.com/external"]),
    "Twilio":              ("https://www.twilio.com/en-us/company/jobs", ["twilio"], []),
    "Personio":            ("https://www.personio.com/about-personio/careers/", ["personio"], []),
    "Mastercard Tech Hub": ("https://careers.mastercard.com/us/en", ["mastercard"], ["https://mastercard.wd1.myworkdayjobs.com/CorporateCareers"]),
    "Adobe":               ("https://careers.adobe.com/us/en", ["adobe"], ["https://adobe.wd5.myworkdayjobs.com/external_experienced"]),
    "Flutter Entertainment": ("https://www.flutter.com/careers/", ["flutter", "flutterentertainment"], []),
    "Procore":             ("https://careers.procore.com/", ["procore", "procoretechnologies"], []),
    "Workvivo / Zoom":     ("https://careers.zoom.us/", ["zoom", "workvivo"], ["https://zoom.wd5.myworkdayjobs.com/Zoom"]),
    "Rapid7":              ("https://careers.rapid7.com/", ["rapid7"], []),
    "FIS":                 ("https://careers.fisglobal.com/", ["fis", "fisglobal"], ["https://fis.wd5.myworkdayjobs.com/SearchJobs"]),
    "Veeam":               ("https://careers.veeam.com/", ["veeam", "veeamsoftware"], []),
    "Palo Alto Networks":  ("https://jobs.paloaltonetworks.com/", ["paloaltonetworks"], []),
    "VMware by Broadcom":  ("https://www.broadcom.com/company/careers", ["broadcom", "vmware"], ["https://broadcom.wd1.myworkdayjobs.com/External_Career"]),
    "Dell Technologies":   ("https://jobs.dell.com/", ["dell"], ["https://dell.wd1.myworkdayjobs.com/External"]),
    "Hewlett Packard Enterprise": ("https://careers.hpe.com/us/en", ["hpe"], ["https://hpe.wd5.myworkdayjobs.com/Jobsathpe"]),
    "Nokia":               ("https://www.nokia.com/about-us/careers/", ["nokia"], ["https://nokia.wd3.myworkdayjobs.com/Nokia"]),
    "Ericsson":            ("https://jobs.ericsson.com/careers", ["ericsson"], []),
    "Amdocs":              ("https://jobs.amdocs.com/", ["amdocs"], ["https://amdocs.wd3.myworkdayjobs.com/Amdocs"]),
    "Teamwork.com":        ("https://www.teamwork.com/careers/", ["teamwork", "teamworkcom"], []),
    "Paddy Power / Betfair": ("https://www.flutter.com/careers/", ["paddypowerbetfair", "betfair"], []),
    # portali "chiusi" nel primo giro: si riprova con metodi diversi
    "DocuSign":            ("https://careers.docusign.com/careers-home", ["docusign"], ["https://docusign.wd1.myworkdayjobs.com/DocuSign"]),
    "Qualtrics":           ("https://www.qualtrics.com/careers/us/en", ["qualtrics"], []),
    "Snowflake":           ("https://careers.snowflake.com/us/en", ["snowflake", "snowflakecomputing"], []),
    "SAP":                 ("https://jobs.sap.com/", ["sap"], []),
    "Cisco":               ("https://careers.cisco.com/global/en", ["cisco"], []),
    "U.S. Bank / Elavon":  ("https://careers.usbank.com/global/en", ["elavon", "usbank"], []),
    "Fiserv":              ("https://careers.fiserv.com/us/en", ["fiserv"], []),
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


# ------------------------------------------------- fonti speciali (siti propri)

def speciale_amazon(s):
    url = ("https://www.amazon.jobs/en/search.json?loc_query=Dublin%2C%20Ireland"
           "&base_query=&result_limit=100&offset=0&sort=recent")
    d = s.get(url, timeout=T).json()
    return [(j.get("title", ""), j.get("normalized_location", "") or j.get("location", ""),
             "https://www.amazon.jobs" + j.get("job_path", ""), j.get("description_short", ""))
            for j in d.get("jobs", [])]


def speciale_microsoft(s):
    url = ("https://gcsservices.careers.microsoft.com/search/api/v1/search"
           "?lc=Dublin%2C%20Dublin%2C%20Ireland&l=en_us&pg=1&pgSz=100&o=Recent")
    d = s.get(url, timeout=T).json()
    jobs = (d.get("operationResult") or {}).get("result", {}).get("jobs", [])
    return [(j.get("title", ""), ", ".join((j.get("properties") or {}).get("locations", [])),
             f"https://jobs.careers.microsoft.com/global/en/job/{j.get('jobId','')}", "")
            for j in jobs]


def speciale_atlassian(s):
    d = s.get("https://www.atlassian.com/endpoint/careers/listings", timeout=T).json()
    return [(j.get("title", ""), ", ".join(j.get("locations", []) or []),
             j.get("portalJobPost", {}).get("portalUrl", "") if isinstance(j.get("portalJobPost"), dict) else "",
             "") for j in d]


SPECIALI = {"Amazon / AWS": speciale_amazon, "Microsoft": speciale_microsoft,
            "Atlassian": speciale_atlassian}


# ----------------------------------------------------------------- Personio

def jobs_personio(s, slug, _):
    import xml.etree.ElementTree as ET
    r = s.get(f"https://{slug}.jobs.personio.de/xml", timeout=T)
    if r.status_code != 200 or "<position" not in r.text:
        return None
    root = ET.fromstring(r.content)
    out = []
    for p in root.findall("position"):
        out.append((p.findtext("name", ""), p.findtext("office", ""),
                    f"https://{slug}.jobs.personio.de/job/{p.findtext('id','')}", ""))
    return out


# ------------------------------------------------------------------ rileva

def prova_slug(s, azienda, slug):
    """Prova uno slug su tutti gli ATS con indirizzo pubblico. Ritorna le fonti che rispondono."""
    trovate = []
    prove = [("greenhouse", monitor.jobs_greenhouse), ("lever", monitor.jobs_lever),
             ("ashby", monitor.jobs_ashby), ("smartrecruiters", monitor.jobs_smartrecruiters),
             ("workable", monitor.jobs_workable), ("personio", jobs_personio)]
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
            off = monitor.jobs_workday(s, "", u)
            if off is not None:
                wd_ok = u
                righe.append(("workday", "", u, off))
                break
        except Exception:
            pass
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

    # 4. fonti speciali
    if azienda in SPECIALI:
        try:
            righe.append(("speciale", azienda, "", SPECIALI[azienda](s)))
        except Exception as e:
            note.append(f"speciale errore {type(e).__name__}")

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
