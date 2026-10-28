#!/usr/bin/env python3
"""
Monitoraggio offerte SDR/BDR e Account Executive a Dublino.

Gira da solo su GitHub Actions (vedi .github/workflows/monitor.yml):
scarica le offerte dagli ATS in ats_mapping_v2.csv, tiene solo i ruoli
SDR/BDR/AE a Dublino, esclude quelli per altre lingue o altri mercati (UK, Americhe...),
da' a ogni offerta da 0 a 5 stelle (vedi PESI) e scrive docs/jobs.json, che la pagina swipe (docs/index.html) legge.

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
    r"lead development|pipeline development|customer development|growth development|"
    r"\bsdr\b|\bbdr\b|\badr\b|\bmdr\b|inside sales|outbound sales|sales representative|"
    r"graduate sales|early careers? sales|sales graduate|new business representative|"
    r"account executive|\bae\b|sales executive|new business executive", re.I)
# Titoli da escludere anche se passano il filtro sopra (ruoli senior o non commerciali).
# "Team Lead" NON e' escluso: un SDR Team Lead e' un passo avanti possibile.
ESCLUDI = re.compile(r"\bmanager\b|\bdirector\b|\bhead of\b|\bvp\b|principal|"
                     r"software|engineer|\bpartner\b", re.I)


# Filtro "largo" usato dai lettori che cercano gia' per Dublino (e da rileva_fonti.py)
LUOGO = re.compile(r"dublin|ireland|irlanda", re.I)


def a_dublino(luogo):
    """True se l'offerta e' a Dublino (o 'Remote - Ireland' / solo 'Ireland').
    Le altre citta' irlandesi e l'Irlanda del Nord non interessano."""
    l = luogo or ""
    # Dublin (California/Ohio): se l'indirizzo parla di Stati Uniti e non di Irlanda, non e' Dublino
    if re.search(r"united states|\busa\b|california|ohio|\b(ca|oh)\b", l, re.I) and \
            not re.search(r"ireland|irlanda|\bie\b", l, re.I):
        return False
    if re.search(r"dublin", l, re.I):
        return True
    return bool(re.search(r"ireland|irlanda", l, re.I)) and not re.search(
        r"northern ireland|belfast|derry|\bcork\b|galway|limerick|waterford|athlone|"
        r"shannon|kilkenny|sligo|letterkenny|dundalk|drogheda", l, re.I)


# Italiano: nel titolo basta la parola; nel testo dell'annuncio si cerca "Italian"
# (non "Italy", che spesso e' solo l'elenco delle sedi dell'azienda).
ITALIANO = re.compile(r"italian|italiano|\bitaly\b|\bitalia\b", re.I)
ITALIANO_TESTO = re.compile(r"\bitalian\b|\bitaliano\b|\bitaly (market|territory|region)", re.I)

# Lingue che NON parlo: se il titolo le richiede (senza l'italiano) l'offerta viene esclusa.
LINGUE = [
    ("Tedesco",    r"german|deutsch|\bdach\b|germanophone|austria|switzerland|swiss"),
    ("Francese",   r"french|fran[cç]ais|francophone|\bfrance\b"),
    ("Olandese",   r"dutch|nederlands|netherlands|benelux|flemish|belgium|belgian"),
    ("Spagnolo",   r"spanish|espa[nñ]ol|castilian|catal[aá]n|\bspain\b|iberia|iberian|\blatam\b"),
    ("Portoghese", r"portuguese|portugu[eê]s|brazil|brasil|\bportugal\b"),
    ("Nordiche",   r"nordic|nordics|scandinavian|swedish|norwegian|danish|finnish|"
                   r"\bsweden\b|\bnorway\b|\bdenmark\b|\bfinland\b"),
    ("CEE/Est",    r"polish|\bpoland\b|czech|slovak|hungarian|romanian|bulgarian|lithuanian|"
                   r"croatian|serbian|slovenian|ukrainian|russian|\bcee\b|"
                   r"central and eastern europe|central eastern europe"),
    ("Greco",      r"\bgreek\b|\bgreece\b"),
    ("Turco",      r"turkish|\bt[uü]rkiye\b"),
    ("Ebraico",    r"hebrew|\bisrael\b"),
    ("Arabo",      r"arabic|\bmena\b|middle east|\bgcc\b|\buae\b|saudi"),
    ("Asiatiche",  r"japanese|korean|mandarin|cantonese|chinese|thai|vietnamese|"
                   r"indonesian|hindi|\bjapan\b|\bkorea\b"),
]
LINGUE = [(nome, re.compile(pat, re.I)) for nome, pat in LINGUE]

# Mercati che NON sono il mio target: se il titolo li cita (senza l'italiano) l'offerta
# non viene proposta. Es. "BDR UKI", "MDR (UK/IE Markets)", "English Speaking", "Africa".
MERCATI_NO = [
    ("UK/Irlanda",   r"\bu\.?k\.?\b|\bukie?\b|\buk ?& ?i(reland)?\b|\buk/i(e|reland)?\b|"
                     r"united kingdom|\bbritish\b|\bireland market|\birish market"),
    ("solo inglese", r"english[- ]speak|\(english\)|english only|english market|native english"),
    ("Africa",       r"\bafrica|south african|\bssa\b"),
    ("Americhe",     r"north america|\bnamer\b|\bamer\b|\bamericas\b|\bus market|\bu\.s\.|"
                     r"\bcanada\b|\busa\b"),
    ("APAC",         r"\bapac\b|\banz\b|australia|new zealand|\bindia\b|singapore|\basia\b"),
]
MERCATI_NO = [(nome, re.compile(pat, re.I)) for nome, pat in MERCATI_NO]

# Nel TESTO dell'annuncio (solo per titoli generici, senza mercato): una lingua chiesta
# come requisito o un mercato di competenza diverso escludono l'offerta.
# Sono frasi precise ("fluent in German", "German-speaking", "covering the UK&I") per
# evitare di scartare annunci che citano solo le sedi dell'azienda.
_LINGUE_NO_TESTO = (r"german|french|dutch|spanish|portuguese|swedish|norwegian|danish|finnish|"
                    r"polish|czech|hebrew|arabic|turkish|greek|japanese|korean|mandarin")
LINGUA_TESTO = re.compile(
    rf"(?:fluen(?:t|cy)|native|proficien\w*|business[- ]level|professional[- ]level|"
    rf"c1|c2|speak|written and (?:spoken|verbal))\W+(?:\w+\W+){{0,3}}?({_LINGUE_NO_TESTO})\b"
    rf"|\b({_LINGUE_NO_TESTO})[- ]speak(?:ing|er)", re.I)
NOMI_IT = {"german": "Tedesco", "french": "Francese", "dutch": "Olandese", "spanish": "Spagnolo",
           "portuguese": "Portoghese", "swedish": "Svedese", "norwegian": "Norvegese",
           "danish": "Danese", "finnish": "Finlandese", "polish": "Polacco", "czech": "Ceco",
           "hebrew": "Ebraico", "arabic": "Arabo", "turkish": "Turco", "greek": "Greco",
           "japanese": "Giapponese", "korean": "Coreano", "mandarin": "Cinese"}
MERCATO_TESTO = re.compile(
    r"(?:cover(?:ing)?|focus(?:ed|ing)? on|responsible for|territory|region|market)\W+"
    r"(?:\w+\W+){0,3}?(uk ?& ?i(?:reland)?|uki\b|uk and ireland|united kingdom|"
    r"north america|\bdach\b|nordics|benelux|\bfrance\b|\bspain\b|\bgermany\b)", re.I)

# Mercati "vicini" che spesso includono l'Italia: valgono una stella in piu'.
MERCATO_VICINO = re.compile(r"southern europe|south(ern)? eur|\bseur\b|mediterranean|"
                            r"\bemea\b|\beurope\b|european|international|multilingual", re.I)
RUOLO_AE = re.compile(r"account executive|\bae\b|sales executive|new business executive", re.I)
# AE con molta esperienza richiesta: un gradino sopra il mio livello attuale
AE_SENIOR = re.compile(r"\bsenior\b|\bsr\.?\b|enterprise|strategic|major accounts?|global accounts?", re.I)
RUOLO_SDR = re.compile(r"sales development|business development|account development|"
                       r"market development|\bsdr\b|\bbdr\b|\badr\b|\bmdr\b", re.I)

# ------------------------------------------------------------ STELLE (0-5)
# Ogni offerta parte da STELLE_BASE e somma i PESI che si applicano, poi si resta tra 0 e 5.
# Per cambiare quanto conta una cosa, cambia il numero qui: il resto si adatta da solo.
STELLE_BASE = 1
PESI = {
    "italiano_titolo": 3,   # "Italian" / "Italy" nel titolo: e' la cosa che conta di piu'
    "italiano_testo":  2,   # titolo generico, ma l'annuncio chiede/cita l'italiano
    "ruolo_sdr":       1,   # titolo esplicito SDR/BDR/ADR/MDR (non solo "inside sales")
    "ruolo_ae":        1,   # Account Executive
    "ae_senior":      -1,   # AE Senior / Enterprise / Strategic: richiede piu' esperienza
    "mercato_vicino":  1,   # Southern Europe / EMEA / International senza lingua precisa
    "altra_lingua":   -1,   # italiano + un'altra lingua che non parlo (es. Italian & Spanish)
    "stage":          -2,   # stage / internship / graduate program: sotto il mio livello
}
STAGE = re.compile(r"\bintern\b|internship|\bstage\b|placement|graduate program", re.I)


def lingue_extra(titolo):
    """Elenco delle lingue (oltre a italiano e inglese) citate nel titolo."""
    return [nome for nome, rx in LINGUE if rx.search(titolo or "")]


def motivo_esclusione(titolo, testo_pieno):
    """Perche' l'offerta NON va proposta, o None se va tenuta.
    Regola base: se il titolo chiede l'italiano l'offerta resta SEMPRE."""
    if ITALIANO.search(titolo or ""):
        return None
    extra = lingue_extra(titolo)
    if extra:
        return extra[0]
    for nome, rx in MERCATI_NO:
        if rx.search(titolo or ""):
            return f"mercato {nome}"
    # titolo generico: si guarda il testo, a meno che citi l'italiano
    if testo_pieno and not ITALIANO_TESTO.search(testo_pieno):
        m = LINGUA_TESTO.search(testo_pieno)
        if m:
            nome = (m.group(1) or m.group(2)).lower()
            return f"{NOMI_IT.get(nome, nome.capitalize())} (nel testo)"
        m = MERCATO_TESTO.search(testo_pieno)
        if m:
            return f"mercato {m.group(1)} (nel testo)"
    return None


def stelle(titolo, testo_pieno, altre):
    """(numero di stelle 0-5, elenco dei motivi) per un'offerta tenuta."""
    punti, motivi = STELLE_BASE, []

    def add(chiave, testo):
        nonlocal punti
        punti += PESI[chiave]
        motivi.append(f"{testo} ({PESI[chiave]:+d})")

    if ITALIANO.search(titolo):
        add("italiano_titolo", "italiano nel titolo")
    elif ITALIANO_TESTO.search(testo_pieno or ""):
        add("italiano_testo", "italiano nel testo")
    if RUOLO_AE.search(titolo):
        add("ruolo_ae", "Account Executive")
        if AE_SENIOR.search(titolo):
            add("ae_senior", "AE senior/enterprise")
    elif RUOLO_SDR.search(titolo):
        add("ruolo_sdr", "ruolo SDR/BDR")
    if MERCATO_VICINO.search(titolo):
        add("mercato_vicino", "mercato europeo/internazionale")
    if STAGE.search(titolo):
        add("stage", "stage/internship")
    if altre:
        add("altra_lingua", "chiede anche " + ", ".join(altre).lower())
    return max(0, min(5, punti)), motivi


# Aziende da ignorare: falsi positivi e recruiter
BLACKLIST = {"LinkedIn", "Cognizant", "Ding", "Nutanix", "TransferMate",
             "Gempool", "Cpl Resources", "Accenture"}


def sess():
    s = requests.Session()
    s.headers.update(UA)
    return s


def testo(x, n=900):
    """HTML -> testo semplice, accorciato a n caratteri (n=None: testo intero)."""
    if not x:
        return ""
    x = html.unescape(html.unescape(str(x)))
    x = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", x, flags=re.I)
    x = re.sub(r"<li[^>]*>", "• ", x, flags=re.I)
    x = re.sub(r"<[^>]+>", "", x)
    x = re.sub(r"[ \t\r\f\v]+", " ", x)
    x = re.sub(r"\n\s*\n+", "\n", x).strip()
    if n is None:
        return x
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


def jobs_jibe(s, _, url):
    """Jibe (es. careers.docusign.com): API pubblica /api/jobs filtrata su Dublino.
    URL = sito carriere (es. https://careers.docusign.com)."""
    host = urlparse(url).netloc
    out = []
    for pagina in range(1, 11):
        d = s.get(f"https://{host}/api/jobs", timeout=TIMEOUT,
                  params={"location": "Dublin", "page": pagina, "limit": 100}).json()
        jobs = d.get("jobs") or []
        for x in jobs:
            j = x.get("data") or x
            luogo = j.get("full_location") or j.get("city", "")
            if not LUOGO.search(luogo or ""):      # la ricerca era gia' filtrata su Dublino
                luogo = f"Dublin ({luogo or 'piu sedi'})"
            out.append((j.get("title", ""), luogo,
                        f"https://{host}/jobs/{j.get('slug', '')}", j.get("description", "")))
        if len(out) >= (d.get("totalCount") or 0) or not jobs:
            break
    return out


def jobs_phenom(s, _, url):
    """Phenom (es. careers.adobe.com/us/en): stesso servizio interno usato dalla pagina
    di ricerca, filtrato sulla citta' Dublin. URL = sito con lingua (…/us/en)."""
    p = urlparse(url)
    parti = [x for x in p.path.split("/") if x]
    paese, lingua = (parti[-2], parti[-1]) if len(parti) >= 2 else ("us", "en")
    base = f"https://{p.netloc}/" + "/".join(parti[:-2])
    out = []
    for da in range(0, 500, 100):
        body = {"lang": f"{lingua}_{paese}", "deviceType": "desktop", "country": paese,
                "pageName": "search-results", "ddoKey": "refineSearch", "sortBy": "",
                "subsearch": "", "from": da, "jobs": True, "counts": True,
                "all_fields": ["category", "country", "city"], "size": 100,
                "clearAll": False, "jdsource": "facets", "isSliderEnable": False,
                "pageId": "page20", "siteType": "external", "keywords": "", "global": True,
                "selected_fields": {"city": ["Dublin"]}, "locationData": {}}
        d = s.post(base.rstrip("/") + "/widgets", json=body, timeout=TIMEOUT).json()
        rs = d.get("refineSearch") or {}
        jobs = (rs.get("data") or {}).get("jobs") or []
        for j in jobs:
            luogo = j.get("cityState") or j.get("location", "")
            if not LUOGO.search(luogo or ""):      # la ricerca era gia' filtrata su Dublino
                luogo = f"Dublin ({luogo or 'piu sedi'})"
            out.append((j.get("title", ""), luogo,
                        f"{url.rstrip('/')}/job/{j.get('jobId', '')}", j.get("descriptionTeaser", "")))
        if len(jobs) < 100:
            break
    return out


def jobs_rippling(s, slug, _):
    """Rippling ATS: elenco pubblico del job board."""
    d = s.get(f"https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs",
              timeout=TIMEOUT).json()
    return [(j.get("name", ""), (j.get("workLocation") or {}).get("label", ""),
             j.get("url", ""), "") for j in d]


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


# ------------------------------------------------ PORTALI PROPRIETARI (v1.5)
# Trovati con prova_portali.py: siti senza ATS standard ma con dati leggibili.

def jobs_google(s, _, __):
    """Google: la pagina di ricerca carriere contiene le offerte nei dati iniziali (ds:1).
    Si leggono le pagine filtrate su Dublino finche' non compaiono offerte nuove."""
    out, visti = [], set()
    for pagina in range(1, 40):
        r = s.get("https://www.google.com/about/careers/applications/jobs/results",
                  params={"location": "Dublin, Ireland", "q": "", "page": pagina}, timeout=TIMEOUT)
        nuovi = 0
        for jid, titolo in re.findall(
                r'\["(\d{15,20})","((?:[^"\\]|\\.){3,200})","https://www\.google\.com/about/careers/applications/signin',
                r.text):
            if jid in visti:
                continue
            visti.add(jid)
            nuovi += 1
            titolo = json.loads(f'"{titolo}"')          # toglie gli escape (& ecc.)
            out.append((titolo, "Dublin, Ireland",
                        f"https://www.google.com/about/careers/applications/jobs/results/{jid}", ""))
        if not nuovi:
            break
    return out


def jobs_tiktok(s, _, __):
    """TikTok: API pubblica del sito lifeattiktok.com, ricerca 'Dublin' filtrata sulla citta'."""
    out = []
    for offset in range(0, 1000, 100):
        body = {"recruitment_id_list": [], "job_category_id_list": [], "subject_id_list": [],
                "location_code_list": [], "keyword": "Dublin", "limit": 100, "offset": offset}
        d = s.post("https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts",
                   json=body, timeout=TIMEOUT,
                   headers={"Content-Type": "application/json", "website-path": "tiktok",
                            "Origin": "https://lifeattiktok.com",
                            "Referer": "https://lifeattiktok.com/"}).json()
        dati = d.get("data") or {}
        posts = dati.get("job_post_list") or []
        for p in posts:
            citta = (p.get("city_info") or {}).get("en_name") or ""
            out.append((p.get("title", ""), citta,
                        f"https://lifeattiktok.com/search/{p.get('id', '')}",
                        (p.get("description") or "") + "\n" + (p.get("requirement") or "")))
        if len(posts) < 100 or offset + 100 >= (dati.get("count") or 0):
            break
    return out


def jobs_oraclehcm(s, sito, url):
    """Oracle Recruiting Cloud (es. Oracle stessa). Slug = codice sito (es. CX_45001),
    URL = indirizzo del servizio (es. https://eeho.fa.us2.oraclecloud.com).
    La ricerca per citta' non e' affidabile: si cerca per parole chiave e si filtra dopo."""
    host = urlparse(url).netloc
    out, visti = [], set()
    for kw in ("Dublin", "Ireland", "Italian", "Sales Development", "Account Executive"):
        for offset in range(0, 500, 100):
            finder = f'findReqs;siteNumber={sito},limit=100,offset={offset},keyword="{kw}"'
            d = s.get(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                      params={"onlyData": "true", "expand": "requisitionList", "finder": finder},
                      timeout=TIMEOUT).json()
            items = d.get("items") or []
            reqs = items[0].get("requisitionList", []) if items else []
            for x in reqs:
                if x.get("Id") in visti:
                    continue
                visti.add(x.get("Id"))
                out.append((x.get("Title", ""), x.get("PrimaryLocation", ""),
                            f"https://careers.oracle.com/jobs/#en/sites/jobsearch/job/{x.get('Id')}",
                            x.get("ShortDescriptionStr") or ""))
            if len(reqs) < 100:
                break
    return out


def jobs_ibm(s, _, __):
    """IBM: motore di ricerca pubblico del sito carriere, cercando 'Dublin'."""
    out = []
    for da in range(0, 500, 100):
        body = {"appId": "careers", "scopes": ["careers2"], "size": 100, "from": da, "lang": "zz",
                "query": {"bool": {"must": [{"simple_query_string": {
                    "query": "Dublin", "fields": ["field_keyword_19^3", "title", "body"]}}]}},
                "_source": ["title", "url", "description", "field_keyword_19"]}
        d = s.post("https://www-api.ibm.com/search/api/v2", json=body, timeout=TIMEOUT,
                   headers={"Content-Type": "application/json"}).json()
        hits = (d.get("hits") or {}).get("hits") or []
        for h in hits:
            x = h.get("_source") or {}
            out.append((x.get("title") or "", x.get("field_keyword_19") or "",
                        x.get("url") or "https://www.ibm.com/careers/search?q=Dublin",
                        x.get("description") or ""))
        if len(hits) < 100:
            break
    return out


LETTORI = {"greenhouse": jobs_greenhouse, "lever": jobs_lever, "ashby": jobs_ashby,
           "smartrecruiters": jobs_smartrecruiters, "workable": jobs_workable,
           "bamboohr": jobs_bamboohr, "workday": jobs_workday,
           "eightfold": jobs_eightfold, "icims": jobs_icims, "amazon": jobs_amazon,
           "personio": jobs_personio, "jibe": jobs_jibe, "phenom": jobs_phenom,
           "rippling": jobs_rippling, "google": jobs_google, "tiktok": jobs_tiktok,
           "oraclehcm": jobs_oraclehcm, "ibm": jobs_ibm}


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
    """Ritorna (tenute, escluse) a partire dalle offerte grezze di un'azienda."""
    tenute, escluse = [], []
    for t, l, u, d in offerte:
        t, l = (t or "").strip(), (l or "").strip()
        if not (TITOLO.search(t) and a_dublino(l)) or ESCLUDI.search(t):
            continue
        pieno = testo(d, None)            # testo intero: serve a lingue e stelle
        motivo = motivo_esclusione(t, pieno)
        if motivo:
            escluse.append({"azienda": azienda, "titolo": t, "motivo": motivo, "url": u})
            continue
        # lingue in piu' richieste insieme all'italiano: la pagina le mostra come badge.
        # Se il titolo elenca lingue in alternativa ("German, Italian OR Nordic")
        # l'italiano da solo basta: niente badge di lingue in piu'.
        altre = [] if re.search(r"\bor\b|\boppure\b", t, re.I) else lingue_extra(t)
        n, motivi = stelle(t, pieno, altre)
        tenute.append({
            "id": f"{azienda}|{t}|{l}",
            "azienda": azienda,
            "titolo": t,
            "luogo": l,
            "url": u,
            "descrizione": testo(d),
            "italiano": bool(ITALIANO.search(t) or ITALIANO_TESTO.search(pieno)),
            "altre_lingue": altre,
            "stelle": n,
            "motivi": motivi,
        })
    return tenute, escluse


def scarica(args):
    """Ritorna (azienda, tenute, scartate, errore)."""
    azienda, ats, slug, url, cache = args
    s = sess()
    try:
        if ats == "workday":
            url = risolvi_workday(s, azienda, slug, url, cache)
            if not url:
                return azienda, [], [], "workday non risolto"
        try:
            offerte = LETTORI[ats](s, slug, url)
        except Exception:
            # alcuni siti (es. Microsoft) a volte rispondono male: si riprova una volta
            time.sleep(5)
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
    # aziende gia' lette nei giri precedenti: per quelle appena aggiunte al monitor
    # le offerte trovate al primo giro sono "gia' presenti", non nuove
    aziende_prima = set(precedente.get("aziende_lette") or
                        [j["azienda"] for j in precedente.get("offerte", [])])

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
            nuova_azienda = j["azienda"] not in aziende_prima and precedente.get("aziende_lette") is not None
            j["prima_vista"] = "" if (primo_giro or nuova_azienda) else oggi
    # prima le offerte con piu' stelle, a parita' di stelle le piu' fresche
    offerte.sort(key=lambda j: (j["stelle"], j["prima_vista"] or "0000"), reverse=True)

    # Se quasi tutte le fonti falliscono (es. rete giu') non si sovrascrive il file buono
    if fonti and ok < len(fonti) * 0.3 and precedente:
        sys.exit(f"Solo {ok}/{len(fonti)} fonti lette: tengo i dati precedenti.")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({
            "aggiornato": adesso.isoformat(timespec="minutes"),
            "fonti_lette": ok,
            "fonti_totali": len(fonti),
            "aziende_lette": sorted(a for a, _, _, e in risultati if not e),
            "problemi": sorted(problemi),
            "pesi": {"base": STELLE_BASE, **PESI},
            "escluse": sorted(scartate, key=lambda x: (x["motivo"], x["azienda"], x["titolo"])),
            "offerte": offerte,
        }, f, ensure_ascii=False, indent=1)
    with open(CACHE_WD, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1)

    nuove = [j for j in offerte if j["prima_vista"] == oggi]
    print(f"Fatto in {int(time.time()-t0)}s: {ok}/{len(fonti)} fonti lette, "
          f"{len(offerte)} offerte attive, {len(nuove)} nuove oggi, "
          f"{len(scartate)} escluse (lingua/mercato).")
    for j in nuove:
        print(f"  NUOVA  {j['azienda']:<20} {j['titolo']}")
    for p in problemi:
        print(f"  ! {p}")


if __name__ == "__main__":
    main()
