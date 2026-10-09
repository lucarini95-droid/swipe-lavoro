#!/usr/bin/env python3
"""
Monitoraggio offerte SDR/BDR a Dublino.

Gira da solo su GitHub Actions (vedi .github/workflows/monitor.yml):
scarica le offerte dagli ATS in ats_mapping_v2.csv, tiene solo i ruoli
SDR/BDR a Dublino, scarta quelli che chiedono lingue diverse da italiano e
inglese e scrive docs/jobs.json, che la pagina swipe (docs/index.html) legge.

Per ogni offerta ricorda la data in cui e' comparsa la prima volta, cosi' la
pagina mostra prima le piu' fresche. Le offerte chiuse spariscono dal file.

Si puo' lanciare anche a mano:  python3 monitor.py
"""

import csv
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
TIMEOUT = 25
OUT = "docs/jobs.json"
CACHE_WD = "docs/workday_urls.json"

# ------------------------------------------------------------------ FILTRI
# Modifica qui se vuoi allargare o stringere la ricerca.
TITOLO = re.compile(
    r"sales development|business development|account development|market development|"
    r"lead development|pipeline development|\bsdr\b|\bbdr\b|\badr\b|\bmdr\b|"
    r"inside sales|graduate sales|early careers? sales|sales graduate", re.I)
LUOGO = re.compile(r"dublin|ireland|irlanda", re.I)
# Titoli da escludere anche se passano il filtro sopra
ESCLUDI = re.compile(r"\bmanager\b|\bdirector\b|\bhead of\b|\bvp\b|principal|"
                     r"software|engineer|\bpartner\b", re.I)
# Segnala in evidenza i ruoli per italofoni
ITALIANO = re.compile(r"italian|italiano|\bitaly\b|\bitalia\b", re.I)

# Lingue che NON parlo: se il titolo le richiede, l'offerta viene scartata.
# Italiano e inglese non sono in lista, quindi passano sempre.
LINGUE = [
    ("Tedesco",    r"german|deutsch|\bdach\b|germanophone"),
    ("Francese",   r"french|fran[cç]ais|francophone|\bfrance\b"),
    ("Olandese",   r"dutch|nederlands|netherlands|benelux|flemish"),
    ("Spagnolo",   r"spanish|espa[nñ]ol|castilian|\bspain\b|iberia|iberian|\blatam\b"),
    ("Portoghese", r"portuguese|portugu[eê]s|brazil|brasil"),
    ("Nordiche",   r"nordic|scandinavian|swedish|norwegian|danish|finnish|"
                   r"\bsweden\b|\bnorway\b|\bdenmark\b|\bfinland\b"),
    ("CEE/Est",    r"polish|\bpoland\b|czech|slovak|hungarian|romanian|bulgarian|"
                   r"croatian|serbian|slovenian|ukrainian|russian|\bcee\b|"
                   r"central and eastern europe|central eastern europe"),
    ("Greco",      r"\bgreek\b|\bgreece\b"),
    ("Turco",      r"turkish|\bt[uü]rkiye\b"),
    ("Ebraico",    r"hebrew|\bisrael\b"),
    ("Arabo",      r"arabic|\bmena\b"),
    ("Asiatiche",  r"japanese|korean|mandarin|cantonese|chinese|thai|vietnamese|"
                   r"indonesian|hindi|\bjapan\b|\bkorea\b"),
]
LINGUE = [(nome, re.compile(pat, re.I)) for nome, pat in LINGUE]


def lingue_extra(titolo):
    """Elenco delle lingue (oltre a italiano e inglese) citate nel titolo."""
    return [nome for nome, rx in LINGUE if rx.search(titolo or "")]


def lingua_richiesta(titolo):
    """Nome della lingua che esclude l'offerta, o None se l'offerta va tenuta.
    Regola (v1.1): se il titolo chiede l'italiano l'offerta resta SEMPRE,
    anche se chiede un'altra lingua in piu' (es. 'Italian & Spanish').
    Viene scartata solo se chiede un'altra lingua SENZA l'italiano."""
    if ITALIANO.search(titolo or ""):
        return None
    extra = lingue_extra(titolo)
    return extra[0] if extra else None


# Aziende da ignorare: falsi positivi e recruiter
BLACKLIST = {"LinkedIn", "Cognizant", "Ding", "Nutanix", "TransferMate",
             "Gempool", "Cpl Resources", "Accenture"}


def sess():
    s = requests.Session()
    s.headers.update(UA)
    return s


def testo(x, n=900):
    """HTML -> testo semplice, accorciato."""
    if not x:
        return ""
    x = html.unescape(html.unescape(str(x)))
    x = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", x, flags=re.I)
    x = re.sub(r"<li[^>]*>", "• ", x, flags=re.I)
    x = re.sub(r"<[^>]+>", "", x)
    x = re.sub(r"[ \t\r\f\v]+", " ", x)
    x = re.sub(r"\n\s*\n+", "\n", x).strip()
    return x[:n].rsplit(" ", 1)[0] + "…" if len(x) > n else x


# -------------------------------------------------------------- LETTORI ATS
# Ogni lettore ritorna una lista di (titolo, luogo, url, descrizione)

def jobs_greenhouse(s, slug, _):
    d = s.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
              timeout=TIMEOUT).json()
    return [(j.get("title", ""), (j.get("location") or {}).get("name", ""),
             j.get("absolute_url", ""), j.get("content", "")) for j in d.get("jobs", [])]


def jobs_lever(s, slug, _):
    d = s.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=TIMEOUT).json()
    return [(j.get("text", ""), (j.get("categories") or {}).get("location", ""),
             j.get("hostedUrl", ""), j.get("descriptionPlain", "")) for j in d]


def jobs_ashby(s, slug, _):
    d = s.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=TIMEOUT).json()
    return [(j.get("title", ""), j.get("location", ""), j.get("jobUrl", ""),
             j.get("descriptionPlain", "")) for j in d.get("jobs", [])]


def jobs_smartrecruiters(s, slug, _):
    out, offset = [], 0
    while offset <= 1000:
        d = s.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
                  f"?limit=100&offset={offset}", timeout=TIMEOUT).json()
        c = d.get("content", [])
        for j in c:
            loc = j.get("location") or {}
            out.append((j.get("name", ""),
                        f"{loc.get('city','')} {loc.get('country','')}".strip(),
                        f"https://jobs.smartrecruiters.com/{slug}/{j.get('id','')}", ""))
        if len(c) < 100:
            break
        offset += 100
    return out


def jobs_workable(s, slug, _):
    d = s.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
              timeout=TIMEOUT).json()
    return [(j.get("title", ""), f"{j.get('city','')} {j.get('country','')}".strip(),
             j.get("url", "") or j.get("shortlink", ""), j.get("description", ""))
            for j in d.get("jobs", [])]


def jobs_bamboohr(s, slug, _):
    d = s.get(f"https://{slug}.bamboohr.com/careers/list", timeout=TIMEOUT).json()
    return [(j.get("jobOpeningName", ""), (j.get("location") or {}).get("city", ""),
             f"https://{slug}.bamboohr.com/careers/{j.get('id','')}", "")
            for j in d.get("result", [])]


def jobs_workday(s, _, url):
    p = urlparse(url)
    parti = [x for x in p.path.split("/") if x and not re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", x)]
    if not parti:
        return []
    tenant, site = p.netloc.split(".")[0], parti[0]
    out = []
    for offset in range(0, 400, 20):
        r = s.post(f"https://{p.netloc}/wday/cxs/{tenant}/{site}/jobs",
                   json={"appliedFacets": {}, "limit": 20, "offset": offset,
                         "searchText": "Dublin"},
                   headers={"Content-Type": "application/json", "Accept": "application/json"},
                   timeout=TIMEOUT)
        d = r.json()
        if "jobPostings" not in d:
            # risposta senza elenco = indirizzo Workday sbagliato (non "zero offerte")
            raise ValueError("sito Workday non valido")
        posts = d.get("jobPostings") or []
        for j in posts:
            luogo = j.get("locationsText", "")
            # "3 Locations": la ricerca era per "Dublin", quindi Dublino e' tra le sedi
            if re.fullmatch(r"\d+ Locations?", luogo or ""):
                luogo = f"Dublin + altre sedi ({luogo})"
            out.append((j.get("title", ""), luogo,
                        urljoin(f"https://{p.netloc}/{site}/",
                                (j.get("externalPath") or "").lstrip("/")), ""))
        if len(posts) < 20:
            break
    return out


def jobs_eightfold(s, dominio, url):
    """Eightfold (Microsoft, PayPal, Ericsson, Amdocs...).
    Slug = dominio dell'azienda (es. microsoft.com), URL = sito carriere Eightfold."""
    host = urlparse(url).netloc
    out, start = [], 0
    while start < 500:
        d = s.get(f"https://{host}/api/pcsx/search", timeout=TIMEOUT, params={
            "domain": dominio, "query": "", "location": "Dublin, Ireland",
            "start": start, "sort_by": "timestamp", "filter_distance": 50}).json()
        dati = d.get("data") or {}
        pos = dati.get("positions") or []
        for j in pos:
            out.append((j.get("name", ""), "; ".join(j.get("locations") or []),
                        urljoin(f"https://{host}/", j.get("positionUrl", "")), ""))
        start += len(pos)
        if not pos or start >= (dati.get("count") or 0):
            break
    return out


def jobs_icims(s, _, url):
    """iCIMS (es. Docusign): legge le pagine di ricerca in formato 'iframe', HTML semplice.
    URL = indirizzo del portale iCIMS (es. https://hubcareers-docusign.icims.com)."""
    host = urlparse(url).netloc
    out = []
    for pagina in range(0, 30):
        r = s.get(f"https://{host}/jobs/search", timeout=TIMEOUT,
                  params={"pr": pagina, "in_iframe": 1, "searchKeyword": "", "ss": 1})
        blocchi = re.split(r'class="[^"]*iCIMS_Anchor', r.text)[1:]
        if not blocchi:
            break
        for b in blocchi:
            m_url = re.search(r'href="([^"]*/jobs/\d+/[^"]*)"', b) or re.search(r'href="([^"]+)"', b)
            m_tit = re.search(r"<h3[^>]*>(.*?)</h3>", b, re.S) or re.search(r'title="([^"]+)"', b)
            m_loc = re.search(r"Locations?\s*</span>\s*<span[^>]*>(.*?)</span>", b, re.S)
            if not (m_url and m_tit):
                continue
            titolo = re.sub(r"<[^>]+>|\s+", " ", m_tit.group(1)).strip()
            luogo = re.sub(r"<[^>]+>|\s+", " ", m_loc.group(1)).strip() if m_loc else ""
            out.append((titolo, luogo, m_url.group(1).split("?")[0], ""))
        if len(blocchi) < 5:
            break
    return out


def jobs_amazon(s, _, __):
    """Amazon / AWS: ricerca pubblica di amazon.jobs filtrata su Irlanda."""
    out = []
    for offset in range(0, 500, 100):
        d = s.get("https://www.amazon.jobs/en/search.json", timeout=TIMEOUT, params={
            "normalized_country_code[]": "IRL", "result_limit": 100,
            "offset": offset, "sort": "recent"}).json()
        jobs = d.get("jobs") or []
        for j in jobs:
            out.append((j.get("title", ""),
                        j.get("normalized_location") or j.get("location", ""),
                        "https://www.amazon.jobs" + j.get("job_path", ""),
                        j.get("description_short", "")))
        if len(jobs) < 100:
            break
    return out


def jobs_personio(s, slug, _):
    """Personio: feed XML pubblico."""
    r = s.get(f"https://{slug}.jobs.personio.de/xml", timeout=TIMEOUT)
    if r.status_code != 200 or "<position" not in r.text:
        return []
    import xml.etree.ElementTree as ET
    root = ET.fromstring(r.content)
    return [(p.findtext("name", ""), p.findtext("office", ""),
             f"https://{slug}.jobs.personio.de/job/{p.findtext('id', '')}", "")
            for p in root.findall("position")]


LETTORI = {"greenhouse": jobs_greenhouse, "lever": jobs_lever, "ashby": jobs_ashby,
           "smartrecruiters": jobs_smartrecruiters, "workable": jobs_workable,
           "bamboohr": jobs_bamboohr, "workday": jobs_workday,
           "eightfold": jobs_eightfold, "icims": jobs_icims, "amazon": jobs_amazon,
           "personio": jobs_personio}


# ----------------------------------------------------- RIPARAZIONE WORKDAY

WD_NUMERI = [5, 1, 3, 2, 103, 101, 12, 4, 6, 7]


def _prova_sito(s, host, slug, site):
    try:
        r = s.post(f"https://{host}/wday/cxs/{slug}/{site}/jobs",
                   json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                   headers={"Content-Type": "application/json"}, timeout=8)
        return r.status_code == 200 and "jobPostings" in r.text
    except Exception:
        return False


def risolvi_workday(s, azienda, slug, url_careers, cache):
    """Trova l'URL myworkdayjobs completo: career page, redirect del tenant, nomi tipici."""
    if cache.get(azienda):
        return cache[azienda]

    if url_careers:
        try:
            r = s.get(url_careers, timeout=TIMEOUT, allow_redirects=True)
            m = re.search(r"https?://[a-zA-Z0-9_.-]*myworkdayjobs\.com/[a-zA-Z0-9_/-]+",
                          r.url + " " + r.text[:400000], re.I)
            if m:
                cache[azienda] = m.group(0).rstrip("/")
                return cache[azienda]
        except Exception:
            pass

    siti = [slug, slug.capitalize(), slug.upper(), f"{slug}careers",
            f"{slug}Careers", f"{slug.capitalize()}Careers", f"{slug}_careers",
            f"{slug.upper()}_Careers", "External", "Careers", "careers", "Jobs",
            "External_Career_Site", "External_Career_Site_Career_Site"]

    for n in WD_NUMERI:
        host = f"{slug}.wd{n}.myworkdayjobs.com"
        try:
            r = s.get(f"https://{host}/", timeout=8, allow_redirects=True)
        except Exception:
            continue
        parti = [x for x in urlparse(r.url).path.split("/")
                 if x and not re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", x)]
        if parti and _prova_sito(s, host, slug, parti[0]):
            cache[azienda] = f"https://{host}/{parti[0]}"
            return cache[azienda]
        for site in siti:
            if _prova_sito(s, host, slug, site):
                cache[azienda] = f"https://{host}/{site}"
                return cache[azienda]
    return None


# ------------------------------------------------------------------- MAIN

def carica_fonti():
    fonti = []
    with open("ats_mapping_v2.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            azienda, ats = r["Azienda"], r["ATS"]
            if azienda in BLACKLIST or ats not in LETTORI:
                continue
            if ats == "workday":
                fonti.append((azienda, ats, r["Slug"], r["URL"]))
            elif r["Stato"] in ("OK", "DA CONTROLLARE") and int(r["Offerte totali"] or 0) > 2:
                fonti.append((azienda, ats, r["Slug"], r["URL"]))
    return fonti


def filtra(azienda, offerte):
    """Ritorna (tenute, scartate) a partire dalle offerte grezze di un'azienda."""
    tenute, scartate = [], []
    for t, l, u, d in offerte:
        t, l = (t or "").strip(), (l or "").strip()
        if not (TITOLO.search(t) and LUOGO.search(l)) or ESCLUDI.search(t):
            continue
        lingua = lingua_richiesta(t)
        if lingua:
            scartate.append({"azienda": azienda, "titolo": t, "lingua": lingua})
            continue
        desc = testo(d)
        tenute.append({
            "id": f"{azienda}|{t}|{l}",
            "azienda": azienda,
            "titolo": t,
            "luogo": l,
            "url": u,
            "descrizione": desc,
            "italiano": bool(ITALIANO.search(t) or ITALIANO.search(desc[:2000])),
            # lingue in piu' richieste insieme all'italiano: la pagina le mostra come badge
            # se il titolo elenca lingue in alternativa ("German, Italian OR Nordic")
            # l'italiano da solo basta: niente badge di lingue in piu'
            "altre_lingue": [] if re.search(r"\bor\b|\boppure\b", t, re.I) else lingue_extra(t),
        })
    return tenute, scartate


def scarica(args):
    """Ritorna (azienda, tenute, scartate, errore)."""
    azienda, ats, slug, url, cache = args
    s = sess()
    try:
        if ats == "workday":
            url = risolvi_workday(s, azienda, slug, url, cache)
            if not url:
                return azienda, [], [], "workday non risolto"
        offerte = LETTORI[ats](s, slug, url)
    except Exception as e:
        return azienda, [], [], f"errore lettura ({type(e).__name__})"
    tenute, scartate = filtra(azienda, offerte)
    return azienda, tenute, scartate, None


def leggi_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.exists("ats_mapping_v2.csv"):
        sys.exit("Manca ats_mapping_v2.csv")
    os.makedirs("docs", exist_ok=True)

    cache = leggi_json(CACHE_WD, {})
    precedente = leggi_json(OUT, {})
    prima_vista = {j["id"]: j.get("prima_vista") for j in precedente.get("offerte", [])}
    primo_giro = not precedente

    fonti = carica_fonti()
    print(f"Controllo {len(fonti)} aziende...")
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        risultati = list(ex.map(scarica, [(a, b, c, d, cache) for a, b, c, d in fonti]))

    adesso = datetime.now(timezone.utc)
    oggi = adesso.strftime("%Y-%m-%d")
    offerte, scartate, problemi, ok = [], [], [], 0
    for azienda, tenute, sc, errore in risultati:
        if errore:
            problemi.append(f"{azienda}: {errore}")
            continue
        ok += 1
        offerte += tenute
        scartate += sc

    # niente doppioni (stessa offerta su due board)
    uniche = {}
    for j in offerte:
        uniche.setdefault(j["id"], j)
    offerte = list(uniche.values())

    for j in offerte:
        if j["id"] in prima_vista:
            # gia' vista in un giro precedente: si tiene la data originale
            # (vuota = era online gia' prima dell'avvio del monitor)
            j["prima_vista"] = prima_vista[j["id"]]
        else:
            # al primo giro non si sa da quando sono online: si marcano come "gia' presenti"
            j["prima_vista"] = "" if primo_giro else oggi
    offerte.sort(key=lambda j: (j["prima_vista"] or "0000", j["italiano"]), reverse=True)

    # Se quasi tutte le fonti falliscono (es. rete giu') non si sovrascrive il file buono
    if fonti and ok < len(fonti) * 0.3 and precedente:
        sys.exit(f"Solo {ok}/{len(fonti)} fonti lette: tengo i dati precedenti.")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({
            "aggiornato": adesso.isoformat(timespec="minutes"),
            "fonti_lette": ok,
            "fonti_totali": len(fonti),
            "problemi": sorted(problemi),
            "scartate_lingua": sorted(scartate, key=lambda x: (x["azienda"], x["titolo"])),
            "offerte": offerte,
        }, f, ensure_ascii=False, indent=1)
    with open(CACHE_WD, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1)

    nuove = [j for j in offerte if j["prima_vista"] == oggi]
    print(f"Fatto in {int(time.time()-t0)}s: {ok}/{len(fonti)} fonti lette, "
          f"{len(offerte)} offerte attive, {len(nuove)} nuove oggi, "
          f"{len(scartate)} scartate per lingua.")
    for j in nuove:
        print(f"  NUOVA  {j['azienda']:<20} {j['titolo']}")
    for p in problemi:
        print(f"  ! {p}")


if __name__ == "__main__":
    main()
