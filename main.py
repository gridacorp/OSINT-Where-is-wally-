#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — Orquestador para osint_tool (estructura simplificada)

Estructura esperada:
 osint_tool/
  ├─ main.py
  ├─ core/
  │  ├─ __init__.py
  │  ├─ site.py          (SiteSearcher)
  │  ├─ name_utils.py    (name_variants_improved, email_variants_from_name)
  │  ├─ extractors.py    (extract_all o extract_entities)
  │  └─ utils.py         (SimpleCache, DomainRateLimiter, save_json, save_dicts_to_csv opcionales)
  ├─ data/
  └─ results/
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pprint import pprint
from typing import Optional, List, Dict

# -------------------------
# Intentar importar módulos core
# -------------------------
MISSING = []
try:
    from core import site as core_site
except Exception:
    core_site = None
    MISSING.append("core.site")

try:
    from core import name_utils
except Exception:
    name_utils = None
    MISSING.append("core.name_utils")

try:
    from core import extractors
except Exception:
    extractors = None
    MISSING.append("core.extractors")

try:
    from core import utils as core_utils
except Exception:
    core_utils = None
    MISSING.append("core.utils")

# Si faltan módulos críticos, informamos pero permitimos ver mensaje de ayuda
if MISSING:
    print(">>> Advertencia: faltan módulos en `core`:", ", ".join(MISSING))
    print("Asegúrate de tener los archivos en core/: site.py, name_utils.py, extractors.py, utils.py (opcional).")
    # no salimos automáticamente; dejamos que el CLI indique error si se intenta buscar

# -------------------------
# Fallbacks y helpers locales
# -------------------------
# Fallback cache / limiter
SimpleCache = getattr(core_utils, "SimpleCache", None) if core_utils else None
DomainRateLimiter = getattr(core_utils, "DomainRateLimiter", None) if core_utils else None

# Try to use SiteSearcher if available
SiteSearcher = getattr(core_site, "SiteSearcher", None) if core_site else None

# Extractors
extract_all = getattr(extractors, "extract_all", None) if extractors else None
extract_entities = getattr(extractors, "extract_entities", None) if extractors else None

# utils export helpers (optional)
save_json = getattr(core_utils, "save_json", None) if core_utils else None
save_dicts_to_csv = getattr(core_utils, "save_dicts_to_csv", None) if core_utils else None
sanitize_filename = getattr(core_utils, "sanitize_filename", None) if core_utils else None

def ensure_results_dir(path: str = "results"):
    os.makedirs(path, exist_ok=True)
    return path

# -------------------------
# Consolidación simple
# -------------------------
def consolidate_blocks(blocks: List[Dict]) -> Dict:
    emails = set()
    phones = set()
    urls = set()
    socials = {}
    hits = []

    for b in blocks:
        ents = b.get("entities", {}) or {}
        for e in ents.get("emails", []) or []:
            emails.add(e)
        for p in ents.get("phones", []) or []:
            phones.add(p)
        for u in ents.get("urls", []) or []:
            urls.add(u)
        for sn, vals in (ents.get("socials") or {}).items():
            socials.setdefault(sn, set()).update(vals if isinstance(vals, list) else [vals])
        for s in (b.get("results") or b.get("sources") or []):
            if not isinstance(s, dict):
                continue
            hits.append({
                "engine": s.get("engine"),
                "title": s.get("title"),
                "link": s.get("link"),
                "snippet": s.get("snippet"),
                "raw": s.get("raw") or ""
            })

    socials = {k: sorted(list(v)) for k, v in socials.items()}
    return {
        "emails": sorted(emails),
        "phones": sorted(phones),
        "urls": sorted(urls),
        "socials": socials,
        "hits": hits
    }

# -------------------------
# Scoring & classification (opcional con core.utils)
# -------------------------
class SimpleClassifier:
    @staticmethod
    def classify(url: str) -> str:
        if not url:
            return "unknown"
        u = url.lower()
        if "instagram.com" in u: return "instagram"
        if "twitter.com" in u or "x.com" in u: return "twitter"
        if "tiktok.com" in u: return "tiktok"
        if "github.com" in u: return "github"
        if "pastebin.com" in u: return "pastebin"
        if "mediafire.com" in u: return "mediafire"
        return "website"

    @staticmethod
    def score(raw: str, q: str, url: Optional[str]=None) -> int:
        s = 0
        if q and q.lower().strip('"') in (raw or "").lower(): s += 3
        if url and q.lower().strip('"') in (url or "").lower(): s += 4
        if "error" in (raw or "").lower(): s -= 2
        return s

classifier = SimpleClassifier()
# if core_utils defines helpers, prefer them
classify_url = getattr(core_utils, "classify_url", classifier.classify) if core_utils else classifier.classify
score_hit = getattr(core_utils, "score_hit", classifier.score) if core_utils else classifier.score

def score_hits(hits: List[Dict], query_main: str) -> List[Dict]:
    for h in hits:
        h["category"] = classify_url(h.get("link"))
        h["score"] = score_hit(h.get("raw",""), query_main, h.get("link"))
    hits_sorted = sorted(hits, key=lambda x: x.get("score", 0), reverse=True)
    return hits_sorted

# -------------------------
# Orquestador principal
# -------------------------
def run_orchestrator(args):
    # GUI option: try to run gui.py if requested
    if args.gui:
        try:
            import gui
            if hasattr(gui, "run_app"):
                gui.run_app()
                return
            elif hasattr(gui, "OSINTGUI"):
                gui.OSINTGUI().mainloop()
                return
            else:
                print("Se encontró gui.py pero no exporta run_app() ni OSINTGUI. Asegúrate de que exista.")
        except Exception as e:
            print("No se pudo iniciar GUI:", e)
            print("Continuando en modo CLI...")

    # verificar módulos requeridos
    if not SiteSearcher:
        print("Error: core.site.SiteSearcher no está disponible. Crea core/site.py con SiteSearcher.")
        sys.exit(1)
    if not name_utils:
        print("Error: core.name_utils no está disponible. Crea core/name_utils.py.")
        sys.exit(1)
    if not (extract_all or extract_entities):
        print("Aviso: core.extractors no está disponible. La extracción de entidades será limitada.")

    # preparar cache y limiter si están disponibles
    cache = None
    if SimpleCache:
        try:
            cache = SimpleCache(path=args.cache, ttl=args.cache_ttl)
        except Exception:
            cache = None
    limiter = None
    if DomainRateLimiter:
        try:
            limiter = DomainRateLimiter(min_delay=args.mindelay)
        except Exception:
            limiter = None

    # crear SiteSearcher (usa cache y limiter si el constructor lo acepta)
    try:
        searcher = SiteSearcher(client_headers=getattr(core_utils, "HEADERS", None) if core_utils else None,
                                timeout=getattr(core_utils, "TIMEOUT", 12) if core_utils else 12,
                                proxy=args.proxy,
                                limiter=limiter,
                                cache=cache)
    except Exception as e:
        print("Error instanciando SiteSearcher:", e)
        searcher = None

    # construir queries según tipo
    queries = []
    query_type = None
    query_value = None
    if args.name:
        query_type = "name"
        query_value = args.name.strip()
        name_vars = name_utils.name_variants_improved(query_value) if hasattr(name_utils, "name_variants_improved") else [query_value]
        # limitar queries: priorizar variantes con espacios y usernames
        maxq = max(1, min(args.max_name_queries, len(name_vars)))
        space_vars = [v for v in name_vars if " " in v][:maxq]
        uname_vars = [v for v in name_vars if " " not in v][:maxq]
        email_sugs = []
        if hasattr(name_utils, "email_variants_from_name"):
            email_sugs = name_utils.email_variants_from_name(query_value, domain_hints=None, max_per_domain=3)[:maxq]
        queries = space_vars + uname_vars + email_sugs
    elif args.email:
        query_type = "email"
        query_value = args.email.strip()
        queries = [query_value, query_value.split("@")[0], f'"{query_value}"']
    elif args.phone:
        query_type = "phone"
        query_value = args.phone.strip()
        queries = [query_value]
    else:
        print("No hay argumento de búsqueda. Usa --name, --email o --phone.")
        sys.exit(1)

    queries = list(dict.fromkeys(q for q in queries if q))
    print(f"[+] Ejecutando búsquedas para {len(queries)} queries (tipo={query_type})")

    # ejecutar búsquedas
    blocks = []
    for q in queries:
        print(f"  -> Query: {q}")
        try:
            if searcher:
                block = searcher.unified_search(q, limit=args.limit, include_socials=True, include_repos=True)
                # expected block: {"results": [...], "entities": {...}}
                # adaptamos a formato consistente: 'results' y 'entities'
                if not isinstance(block, dict):
                    block = {"query": q, "results": [], "entities": {}}
                block.setdefault("query", q)
                blocks.append(block)
            else:
                print("  ! No hay searcher válido, saltando query.")
        except Exception as e:
            print("  ! Error en query:", e)
            blocks.append({"query": q, "results": [], "entities": {}, "error": str(e)})

    # consolidar entidades
    consolidated = consolidate_blocks(blocks)
    hits = consolidated.get("hits", [])
    hits_scored = score_hits(hits, query_value)
    summary = {
        "query_type": query_type,
        "query_value": query_value,
        "emails_found": consolidated.get("emails", []),
        "phones_found": consolidated.get("phones", []),
        "urls_found": consolidated.get("urls", []),
        "socials_found": consolidated.get("socials", {}),
        "top_hits": hits_scored[:50]
    }

    # exportar JSON
    ensure_results_dir("results")
    out_obj = {
        "summary": summary,
        "hits": hits_scored,
        "raw_blocks": blocks
    }
    out_path = os.path.join("results", (sanitize_filename(query_value) if sanitize_filename else (query_value.replace(" ", "_")) ) + ".json")
    try:
        if save_json:
            save_json(out_obj, out_path, ensure_ascii=False, indent=2)
        else:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(out_obj, f, ensure_ascii=False, indent=2, default=str)
        print(f"[+] Resultado guardado en {out_path}")
    except Exception as e:
        print("Error guardando JSON:", e)

    # exportar CSVs si se solicitó --out
    exported = []
    if args.out:
        base = args.out
        try:
            # try using core.utils helper
            if save_dicts_to_csv:
                # hits -> csv
                csv_hits = base + "_hits.csv"
                fieldnames = ["engine", "title", "link", "snippet", "score", "category"]
                dicts = []
                for h in hits_scored:
                    dicts.append({
                        "engine": h.get("engine"),
                        "title": h.get("title"),
                        "link": h.get("link"),
                        "snippet": h.get("snippet"),
                        "score": h.get("score"),
                        "category": h.get("category")
                    })
                save_dicts_to_csv(csv_hits, fieldnames, dicts)
                exported.append(csv_hits)
                # emails/socials
                csv_es = base + "_emails_socials.csv"
                with open(csv_es, "w", encoding="utf-8") as f:
                    f.write("emails\n")
                    for e in consolidated.get("emails", []):
                        f.write(e + "\n")
                    f.write("\nsocial,users\n")
                    for k, v in consolidated.get("socials", {}).items():
                        f.write(f"{k},{';'.join(v)}\n")
                exported.append(csv_es)
            else:
                # simple fallback
                p1 = base + "_summary.csv"
                with open(p1, "w", encoding="utf-8") as f:
                    f.write("query_type,query_value,emails_count,phones_count,urls_count\n")
                    f.write(f"{summary['query_type']},{summary['query_value']},{len(summary['emails_found'])},{len(summary['phones_found'])},{len(summary['urls_found'])}\n")
                exported.append(p1)
        except Exception as e:
            print("Error exportando CSVs:", e)

    # output en pantalla
    if args.json:
        print(json.dumps(out_obj, ensure_ascii=False, indent=2, default=str))
    else:
        print("\n=== RESUMEN ===")
        print(f"Tipo: {summary.get('query_type')} | Consulta: {summary.get('query_value')}")
        print(f"Emails detectados: {len(summary.get('emails_found', []))} -> {summary.get('emails_found')}")
        print(f"Teléfonos detectados: {len(summary.get('phones_found', []))} -> {summary.get('phones_found')}")
        print(f"URLs detectadas: {len(summary.get('urls_found', []))}")
        print(f"Perfiles detectados: { {k: len(v) for k,v in summary.get('socials_found', {}).items()} }")
        if exported:
            print("CSV exportados:", exported)
        if MISSING:
            print("\n--- Atención: módulos faltantes ---")
            print("Faltan módulos:", ", ".join(MISSING))
            print("Algunas funcionalidades pueden estar limitadas.")
    return out_obj

# -------------------------
# CLI
# -------------------------
def parse_args():
    p = argparse.ArgumentParser(description="osint_tool - main.py (simplified)")
    group = p.add_mutually_exclusive_group(required=False)
    group.add_argument("--email", "-e", help="Correo electrónico a investigar")
    group.add_argument("--phone", "-p", help="Teléfono a investigar")
    group.add_argument("--name", "-n", help="Nombre completo a investigar")
    p.add_argument("--gui", action="store_true", help="Iniciar GUI (si existe gui.py con run_app())")
    p.add_argument("--json", action="store_true", help="Imprimir JSON completo en salida estándar")
    p.add_argument("--limit", type=int, default=6, help="Límite por motor")
    p.add_argument("--workers", type=int, default=4, help="Hilos (si implementado)")
    p.add_argument("--mindelay", type=float, default=1.5, help="Delay mínimo por dominio")
    p.add_argument("--proxy", type=str, default=None, help="Proxy HTTP/HTTPS (opcional)")
    p.add_argument("--out", type=str, default=None, help="Base name para export CSV (ej: report)")
    p.add_argument("--cache", type=str, default=".osint_cache.json", help="Archivo cache JSON")
    p.add_argument("--cache-ttl", type=int, default=86400, help="TTL cache (segundos)")
    p.add_argument("--max-name-queries", type=int, default=4, help="Máx queries generadas por nombre")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    try:
        run_orchestrator(args)
    except KeyboardInterrupt:
        print("\nInterrumpido por usuario.")
        sys.exit(0)
    except Exception as exc:
        print("Error inesperado:", exc)
        sys.exit(1)
