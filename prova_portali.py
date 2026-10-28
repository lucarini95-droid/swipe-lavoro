#!/usr/bin/env python3
"""
Sonda per i portali "chiusi": prova metodi di lettura NUOVI sulle aziende che monitor.py
non riesce a leggere (portali proprietari: Google, TikTok, Meta, IBM, Oracle, SAP...).

Non tocca le offerte: stampa solo, per ogni tentativo, se ha risposto e cosa ha trovato.
Si lancia a mano da GitHub (Actions -> "Prova portali" -> Run workflow) e si legge il log.
Quando un tentativo funziona, il metodo diventa un lettore vero in monitor.py.
"""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import monitor

T = 20
JSON_H = {"Content-Type": "application/json", "Accept": "application/json"}


def titoli_html(html, pattern):
    """Estrae titoli da HTML con una regex (gruppo 1) e li ripulisce."""
    return [re.sub(r"<[^>]+>|\s+", " ", m).strip() for m in re.findall(pattern, html, re.S)]


# Ogni prova ritorna (descrizione breve del risultato, elenco di titoli trovati)

def google(s):
    r = s.get("https://www.google.com/about/careers/applications/jobs/results",
              params={"location": "Dublin, Ireland", "q": "sales"}, timeout=T)
    t = titoli_html(r.text, r'<h3 class="[^"]*">([^<]{5,120})</h3>')
    return f"HTTP {r.status_code}, {len(r.text)} byte", t


def google_api_vecchia(s):
    r = s.get("https://careers.google.com/api/v3/search/",
              params={"location": "Dublin, Ireland", "q": "sales", "page_size": 100}, timeout=T)
    try:
        d = r.json()
        return f"HTTP {r.status_code}, count={d.get('count')}", [j.get("title") for j in d.get("jobs", [])]
    except Exception:
        return f"HTTP {r.status_code}, non JSON", []


def tiktok(s):
    body = {"recruitment_id_list": [], "job_category_id_list": [], "subject_id_list": [],
            "location_code_list": [], "keyword": "Dublin", "limit": 100, "offset": 0}
    r = s.post("https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts",
               json=body, timeout=T, headers={**JSON_H, "website-path": "tiktok",
                                             "Origin": "https://lifeattiktok.com",
                                             "Referer": "https://lifeattiktok.com/"})
    try:
        d = r.json()
        data = d.get("data") or {}
        posts = data.get("job_post_list") or []
        return (f"HTTP {r.status_code}, code={d.get('code')}, count={data.get('count')}",
                [f"{p.get('title')} @ {(p.get('city_info') or {}).get('en_name')}" for p in posts])
    except Exception:
        return f"HTTP {r.status_code}, non JSON: {r.text[:120]!r}", []


def meta(s):
    r = s.get("https://www.metacareers.com/jobs", params={"offices[0]": "Dublin, Ireland"}, timeout=T)
    t = re.findall(r'"title":"([^"]{5,120})"', r.text)
    return f"HTTP {r.status_code}, {len(r.text)} byte", t


def ibm(s):
    body = {"appId": "careers", "scopes": ["careers2"], "size": 50, "lang": "zz",
            "query": {"bool": {"must": [{"simple_query_string": {
                "query": "sales Dublin", "fields": ["title^3", "description^2", "body"]}}]}},
            "_source": ["title", "url", "field_keyword_19", "field_keyword_17"]}
    r = s.post("https://www-api.ibm.com/search/api/v2", json=body, timeout=T, headers=JSON_H)
    try:
        hits = (r.json().get("hits") or {}).get("hits") or []
        return f"HTTP {r.status_code}, {len(hits)} risultati", [
            f"{(h.get('_source') or {}).get('title')} @ {(h.get('_source') or {}).get('field_keyword_19')}"
            for h in hits]
    except Exception:
        return f"HTTP {r.status_code}, non JSON: {r.text[:120]!r}", []


def oracle(s):
    finder = 'findReqs;siteNumber=CX_45001,limit=100,keyword="sales",location="Dublin"'
    r = s.get("https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
              params={"onlyData": "true", "expand": "requisitionList", "finder": finder}, timeout=T)
    try:
        items = r.json().get("items") or []
        reqs = items[0].get("requisitionList", []) if items else []
        return f"HTTP {r.status_code}, {len(reqs)} offerte", [
            f"{x.get('Title')} @ {x.get('PrimaryLocation')}" for x in reqs]
    except Exception:
        return f"HTTP {r.status_code}, non JSON: {r.text[:120]!r}", []


def sap(s):
    r = s.get("https://jobs.sap.com/search/", params={"q": "", "locationsearch": "Dublin"}, timeout=T)
    t = titoli_html(r.text, r'class="jobTitle-link[^"]*"[^>]*>(.*?)</a>')
    return f"HTTP {r.status_code}", t


def atlassian(s):
    r = s.get("https://www.atlassian.com/endpoint/careers/listings", timeout=T)
    try:
        d = r.json()
        return f"HTTP {r.status_code}, {len(d)} offerte totali", [
            f"{j.get('title')} @ {j.get('locations')}" for j in d
            if re.search("dublin|ireland", json.dumps(j.get("locations")), re.I)]
    except Exception:
        return f"HTTP {r.status_code}, non JSON", []


def radancy(host):
    """Radancy/TalentBrew (jobs.dell.com e altri): risultati di ricerca in JSON con dentro HTML."""
    def prova(s):
        r = s.get(f"https://{host}/search-jobs/results", timeout=T, headers={"X-Requested-With": "XMLHttpRequest"},
                  params={"ActiveFacetID": 0, "CurrentPage": 1, "RecordsPerPage": 100,
                          "Keywords": "", "Location": "Dublin, Ireland", "ShowRadius": "False",
                          "IsPagination": "False", "SearchResultsModuleName": "Search Results",
                          "SearchFiltersModuleName": "Search Filters", "SortCriteria": 0,
                          "SortDirection": 0, "SearchType": 5})
        try:
            h = r.json().get("results", "")
            return f"HTTP {r.status_code}", titoli_html(h, r"<h2[^>]*>(.*?)</h2>")
        except Exception:
            return f"HTTP {r.status_code}, non JSON", []
    return prova


def jibe(host):
    def prova(s):
        return "jibe", [f"{t} @ {l}" for t, l, *_ in monitor.jobs_jibe(s, "", f"https://{host}")]
    return prova


def workday(url):
    def prova(s):
        return "workday", [f"{t} @ {l}" for t, l, *_ in monitor.jobs_workday(s, "", url)]
    return prova


def personio_com(slug):
    def prova(s):
        r = s.get(f"https://{slug}.jobs.personio.com/xml", timeout=T)
        return f"HTTP {r.status_code}", re.findall(r"<name>([^<]+)</name>", r.text)
    return prova


def eightfold(dominio, host):
    def prova(s):
        return "eightfold", [f"{t} @ {l}" for t, l, *_ in
                             monitor.jobs_eightfold(s, dominio, f"https://{host}")]
    return prova


PROVE = [
    ("Google (pagina)", google),
    ("Google (API v3)", google_api_vecchia),
    ("TikTok (API pubblica)", tiktok),
    ("Meta (pagina)", meta),
    ("IBM (API ricerca)", ibm),
    ("Oracle (HCM REST)", oracle),
    ("SAP (SuccessFactors)", sap),
    ("Atlassian (listings)", atlassian),
    ("Dell (Radancy)", radancy("jobs.dell.com")),
    ("Palo Alto (Radancy)", radancy("jobs.paloaltonetworks.com")),
    ("Indeed (Jibe)", jibe("www.indeed.jobs")),
    ("Yahoo (Workday)", workday("https://ouryahoo.wd5.myworkdayjobs.com/careers")),
    ("Flutter (Workday)", workday("https://flutterbe.wd3.myworkdayjobs.com/FlutterUKI")),
    ("Medallia (Workday)", workday("https://medallia.wd5.myworkdayjobs.com/MedalliaCareers")),
    ("Tenable (Workday)", workday("https://tenable.wd1.myworkdayjobs.com/tenablecareers")),
    ("Cvent (Workday)", workday("https://cvent.wd1.myworkdayjobs.com/CVENT")),
    ("Personio (.com)", personio_com("personio")),
    ("Nokia (Eightfold)", eightfold("nokia.com", "jobs.nokia.com")),
    ("Dell (Eightfold)", eightfold("dell.com", "dell.eightfold.ai")),
]



def campioni(s):
    """Secondo giro: salva pezzi di risposta grezza per capire la struttura dei dati."""
    out = []
    r = s.get("https://www.google.com/about/careers/applications/jobs/results",
              params={"location": "Dublin, Ireland", "q": "", "page": 1}, timeout=T)
    h = r.text
    i = h.find("<h3")
    out.append(("GOOGLE html attorno al primo h3", h[max(0, i-3000):i+2500]))
    out.append(("GOOGLE link jobs/results", "\n".join(sorted(set(re.findall(r'href="([^"]*jobs/results/\d+[^"]*)"', h)))[:10])))
    out.append(("GOOGLE AF_initDataCallback (inizio)", "\n".join(m[:1500] for m in re.findall(r"AF_initDataCallback\((\{key: 'ds:[^']+'.{0,2000})", h)[:3])))

    body = {"recruitment_id_list": [], "job_category_id_list": [], "subject_id_list": [],
            "location_code_list": [], "keyword": "Dublin", "limit": 2, "offset": 0}
    r = s.post("https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts", json=body, timeout=T,
               headers={**JSON_H, "website-path": "tiktok", "Origin": "https://lifeattiktok.com",
                        "Referer": "https://lifeattiktok.com/"})
    out.append(("TIKTOK primo risultato", json.dumps((r.json().get("data") or {}).get("job_post_list", [])[:1], ensure_ascii=False)[:3000]))

    for kw in ("Dublin", "Ireland"):
        finder = f'findReqs;siteNumber=CX_45001,limit=50,offset=0,keyword="{kw}"'
        r = s.get("https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                  params={"onlyData": "true", "expand": "requisitionList", "finder": finder}, timeout=T)
        items = r.json().get("items") or []
        reqs = items[0].get("requisitionList", []) if items else []
        tot = items[0].get("TotalJobsCount") if items else None
        out.append((f"ORACLE keyword={kw} tot={tot}", "\n".join(f"{x.get('Title')} @ {x.get('PrimaryLocation')} id={x.get('Id')}" for x in reqs[:25])))
    out.append(("ORACLE chiavi primo", json.dumps(reqs[:1])[:1500] if reqs else ""))

    body = {"appId": "careers", "scopes": ["careers2"], "size": 50, "lang": "zz",
            "query": {"bool": {"must": [{"simple_query_string": {"query": "Dublin",
                      "fields": ["field_keyword_19^3", "title", "body"]}}]}}}
    r = s.post("https://www-api.ibm.com/search/api/v2", json=body, timeout=T, headers=JSON_H)
    hits = (r.json().get("hits") or {}).get("hits") or []
    out.append(("IBM query Dublin", "\n".join(f"{(h.get('_source') or {}).get('title')} @ {(h.get('_source') or {}).get('field_keyword_19')} {(h.get('_source') or {}).get('url')}" for h in hits[:25])))
    out.append(("IBM chiavi primo", json.dumps(hits[:1])[:2000]))

    r = s.get("https://jobs.sap.com/search/", params={"q": "", "locationsearch": "Dublin"}, timeout=T)
    i = r.text.find("jobTitle")
    out.append((f"SAP HTML (len {len(r.text)})", r.text[max(0, i-500):i+1500] if i > 0 else r.text[:1500]))
    r = s.get("https://personio.jobs.personio.com/xml", timeout=T)
    out.append(("PERSONIO .com xml", r.text[:1200]))
    return out


def main():
    s = monitor.sess()
    for titolo, testo in campioni(s):
        print(f"\n##### {titolo}\n{testo}")


if __name__ == "__main__":
    sys.exit(main())
