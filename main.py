#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py

Punto de entrada modular para la herramienta OSINT.

Este archivo orquesta los módulos del paquete `core`:
  - core.name_utils
  - core.search_engine
  - core.social_media
  - core.repositories
  - core.extractors
  - core.utils

El objetivo es que `main.py` permanezca ligero: recibe argumentos CLI,
genera las queries con name_utils, llama a los motores/socials/repositorios,
consolida resultados, extrae entidades y exporta/visualiza el resumen.

Si aún no has creado los módulos en `core/`, este script detectará
su ausencia y mostrará instrucciones claras para continuar.

Uso:
  python main.py --name "Juan Pérez Lota" --out report_base --json
  python main.py --email juan.perez@gmail.com --limit 6 --workers 4

Recomendación:
  - Implementa los módulos bajo `core/` según la propuesta de estructura.
  - `core.utils` debería exponer HTTPClient y SimpleCache (opcional).
"""
from __future__ import annotations
import sys
import os
import json
import argparse
from pprint import pprint
from typing import Optional

# Intentamos importar los módulos core. Si faltan, informamos.
MISSING_MODULES = []
try:
    from core import name_utils
except Exception:
    name_utils = None
    MISSING_MODULES.append("core.name_utils")

try:
    from core import search_engine
except Exception:
    search_engine = None
    MISSING_MODULES.append("core.search_engine")

try:
    from core import social_media
except Exception:
    social_media = None
    MISSING_MODULES.append("core.social_media")

try:
    from core import repositories
except Exception:
    repositories = None
    MISSING_MODULES.append("core.repositories")

try:
    from core import extractors
except Exception:
    extractors = None
    MISSING_MODULES.append("core.extractors")

try:
    from core import utils
except Exception:
    utils = None
    MISSING_MODULES.append("core.utils")

# Si hay módulos faltantes, presentamos una advertencia clara y sugerencias
if MISSING_MODULES:
    hint = (
        "Faltan módulos obligatorios en el paquete `core`.\n"
        "Se recomienda crear los archivos y funciones indicados en la estructura modular.\n\n"
        "Módulos faltantes:\n  - " + "\n  - ".join(MISSING_MODULES) + "\n\n"
        "Recomendación rápida (ejemplo para core/name_utils.py):\n"
        "  def name_variants_improved(fullname): ...\n"
        "  def email_variants_from_name(fullname, domain_hints=None): ...\n\n"
        "Si quieres, puedo generarte ahora mismo cada módulo (name_utils, search_engine, "
        "social_media, repositories, extractors, utils). Indícame y los creo. "
    )
    # No salir aún: permitimos que el usuario vea el mensaje y decida.
    print(">>> Advertencia: algunos módulos core no están disponibles.")
    print(hint)

# Fallbacks mínimos (si core.utils no está implementado) para permitir ejecución parcial
class _SimpleCacheFallback:
    def __init__(self, path: str = ".osint_cache.json", ttl: int = 86400):
        self.path = path
        self.ttl = ttl
    def get(self, k): return None
    def set(self, k, v): return None

class _HTTPClientFallback:
    def __init__(self, headers=None, timeout: int = 12, proxy: Optional[str] = None, limiter=None, cache=None, use_cache: bool = False):
        self.headers = headers
        self.timeout = timeout
        self.proxy = proxy
        self.limiter = limiter
        self.cache = cache
        self.use_cache = use_cache
    def get(self, url, params=None):
        # fallback: raise so developer knows they need to implement real HTTP client
        raise RuntimeError("HTTPClient no implementado. Implementa core.utils.HTTPClient o instala core.utils.")

# If utils exists, use its classes; otherwise use fallbacks
if utils:
    HTTPClient = getattr(utils, "HTTPClient", None)
    SimpleCache = getattr(utils, "SimpleCache", None)
    classify_url = getattr(utils, "classify_url", None)
    score_hit = getattr(utils, "score_hit", None)
    write_csv_summary = getattr(utils, "write_csv_summary", None)
    write_csv_hits = getattr(utils, "write_csv_hits", None)
    write_csv_emails = getattr(utils, "write_csv_emails", None)
    default_serialize = getattr(utils, "default_serialize", lambda o: str(o))
else:
    HTTPClient = _HTTPClientFallback
    SimpleCache = _SimpleCacheFallback
    classify_url = lambda u: "website"
    score_hit = lambda text, q, url=None: 0
    write_csv_summary = None
    write_csv_hits = None
    write_csv_emails = None
    default_serialize = lambda o: str(o)

def consolidate_results(blocks):
    """
    Recibe una lista de bloques devueltos por search_engine/social_media/repositories
    y consolida hits, urls, emails, phones y perfiles sociales.
    """
    all_emails = set()
    all_phones = set()
    all_urls = set()
    all_socials = {}
    hits = []

    for b in blocks:
        # each block expected to be {"query":..., "sources":[{engine,title,link,snippet,raw,meta}], "entities":{...}}
        entities = b.get("entities", {}) if isinstance(b, dict) else {}
        for e in entities.get("emails", []):
            all_emails.add(e)
        for p in entities.get("phones", []):
            all_phones.add(p)
        for u in entities.get("urls", []):
            all_urls.add(u)
        for sn, vals in (entities.get("socials") or {}).items():
            all_socials.setdefault(sn, set()).update(vals if isinstance(vals, list) else [vals])
        for s in b.get("sources", []):
            sig = (s.get("link") or "") + "|" + (s.get("title") or "") + "|" + (s.get("snippet") or "")
            hits.append({
                "sig": sig,
                "engine": s.get("engine"),
                "link": s.get("link"),
                "title": s.get("title"),
                "snippet": s.get("snippet"),
                "raw": s.get("raw", "")
            })

    # convert sets to sorted lists
    socials_sorted = {k: sorted(list(v)) for k, v in all_socials.items()}
    return {
        "emails": sorted(all_emails),
        "phones": sorted(all_phones),
        "urls": sorted(all_urls),
        "socials": socials_sorted,
        "hits": hits
    }

def score_and_classify_hits(hits, query_main):
    """
    Añade score y category a cada hit usando classify_url y score_hit.
    """
    for h in hits:
        url = h.get("link")
        h["category"] = classify_url(url) if callable(classify_url) else "website"
        h["score"] = score_hit(h.get("raw",""), query_main, url) if callable(score_hit) else 0
    # ordenar por score descendente
    hits_sorted = sorted(hits, key=lambda x: x.get("score", 0), reverse=True)
    return hits_sorted

def build_summary(query_type, query_value, consolidated, hits_sorted):
    top_domains = []
    from collections import Counter
    domain_counts = Counter()
    for u in consolidated["urls"]:
        try:
            d = u.split("/")[2]
        except Exception:
            d = u
        domain_counts[d] += 1
    top_domains = domain_counts.most_common(20)

    summary = {
        "query_type": query_type,
        "query_value": query_value,
        "emails_found": consolidated["emails"],
        "phones_found": consolidated["phones"],
        "urls_found": consolidated["urls"],
        "socials_found": consolidated["socials"],
        "top_domains": top_domains,
        "top_hits": [{"engine": h.get("engine"), "title": h.get("title"), "link": h.get("link"), "score": h.get("score")} for h in hits_sorted[:30]]
    }
    return summary

def export_csvs(base, summary, hits, emails_socials):
    """
    Exporta CSVs usando utilidades de core.utils si existen, si no usa implementaciones simples.
    """
    exported = []
    if write_csv_summary and write_csv_hits and write_csv_emails:
        try:
            p1 = write_csv_summary(base, summary)
            p2 = write_csv_hits(base, hits)
            p3 = write_csv_emails(base, summary.get("emails_found", []), summary.get("socials_found", {}))
            exported = [p1, p2, p3]
        except Exception as e:
            print("Error exportando con core.utils:", e)
    else:
        # Implementación simple de respaldo
        try:
            p1 = f"{base}_summary.csv"
            with open(p1, "w", encoding="utf-8") as f:
                f.write("query_type,query_value,emails_count,phones_count,urls_count,top_domains\n")
                td = ";".join([f"{d}({c})" for d,c in summary.get("top_domains", [])])
                f.write(f'{summary.get("query_type")},{summary.get("query_value")},{len(summary.get("emails_found",[]))},{len(summary.get("phones_found",[]))},{len(summary.get("urls_found",[]))},"{td}"\n')
            p2 = f"{base}_hits.csv"
            with open(p2, "w", encoding="utf-8") as f:
                f.write("engine,title,link,snippet,score,category\n")
                for h in hits:
                    f.write(f'{h.get("engine")},"{(h.get("title") or "").replace("\"","\'")}",{h.get("link")},{(h.get("snippet") or "").replace("\"","\'")},{h.get("score")},{h.get("category")}\n')
            p3 = f"{base}_emails_socials.csv"
            with open(p3, "w", encoding="utf-8") as f:
                f.write("emails\n")
                for e in summary.get("emails_found", []):
                    f.write(e + "\n")
                f.write("\nsocial,users\n")
                for k,v in summary.get("socials_found", {}).items():
                    f.write(f"{k},{';'.join(v)}\n")
            exported = [p1, p2, p3]
        except Exception as e:
            print("Error exportando CSVs (fallback):", e)
    return exported

def run_orchestrator(args):
    # Preparar cache y cliente HTTP según core.utils si existe
    cache = None
    if SimpleCache:
        try:
            cache = SimpleCache(path=(args.cache or ".osint_cache.json"), ttl=(args.cache_ttl or 86400))
        except Exception:
            cache = _SimpleCacheFallback()
    else:
        cache = _SimpleCacheFallback()

    client = None
    try:
        client = HTTPClient(headers=getattr(utils, "HEADERS", None) if utils else None,
                            timeout=getattr(utils, "TIMEOUT", 12) if utils else 12,
                            proxy=args.proxy,
                            limiter=None,
                            cache=cache,
                            use_cache=bool(cache))
    except Exception:
        # fallback
        client = _HTTPClientFallback()

    # Determinar tipo de búsqueda y generar queries
    query_type = None
    query_value = None
    if args.email:
        query_type = "email"
        query_value = args.email.strip()
        queries = [query_value, query_value.split("@")[0], f'"{query_value}"']
    elif args.phone:
        query_type = "phone"
        query_value = args.phone.strip()
        queries = [query_value]
    elif args.name:
        query_type = "name"
        query_value = args.name.strip()
        if name_utils and hasattr(name_utils, "name_variants_improved"):
            name_vars = name_utils.name_variants_improved(query_value)
            # tomamos un número controlado de variantes
            maxq = max(1, min(args.max_name_queries, len(name_vars)))
            # priorizamos variantes con espacio (búsqueda completa) y algunos usernames
            space_vars = [v for v in name_vars if " " in v][:maxq]
            uname_vars = [v for v in name_vars if " " not in v][:maxq]
            # generar también sugerencias de email (limitadas)
            email_sugs = []
            if hasattr(name_utils, "email_variants_from_name"):
                email_sugs = name_utils.email_variants_from_name(query_value, domain_hints=None, max_per_domain=3)[:maxq]
            queries = space_vars + uname_vars + email_sugs
        else:
            # fallback simple: usar el nombre crudo y la versión normalizada
            queries = [query_value, query_value.lower()]
    else:
        raise SystemExit("No hay argumento de búsqueda. Usa --name, --email o --phone.")

    # deduplicar queries
    queries = list(dict.fromkeys([q for q in queries if q]))

    # Ejecutar búsquedas (motores, redes sociales y repositorios) para cada query
    blocks = []
    for q in queries:
        block = {"query": q, "sources": [], "entities": {}}
        # search_engine
        if search_engine and hasattr(search_engine, "search_all_engines"):
            try:
                hits = search_engine.search_all_engines(q, limit=args.limit, client=client)
                # hits: lista de dicts {engine, title, link, snippet, raw}
                block["sources"].extend(hits)
            except Exception as e:
                block["sources"].append({"engine": "search_engine", "error": str(e)})
        else:
            # Informar que el módulo no está implementado
            block["sources"].append({"engine": "search_engine", "error": "Módulo core.search_engine no implementado."})

        # social_media
        if social_media and hasattr(social_media, "search_socials"):
            try:
                soc = social_media.search_socials(q, client=client, limit=args.limit)
                block["sources"].extend(soc)
            except Exception as e:
                block["sources"].append({"engine": "social_media", "error": str(e)})
        else:
            block["sources"].append({"engine": "social_media", "error": "Módulo core.social_media no implementado."})

        # repositories
        if repositories and hasattr(repositories, "search_repositories"):
            try:
                repos = repositories.search_repositories(q, client=client, limit=args.limit)
                block["sources"].extend(repos)
            except Exception as e:
                block["sources"].append({"engine": "repositories", "error": str(e)})
        else:
            block["sources"].append({"engine": "repositories", "error": "Módulo core.repositories no implementado."})

        # Construir texto combinado para extracción (title + snippet + link)
        combined_text = " ".join(" ".join(filter(None, (s.get("title") or "", s.get("snippet") or "", s.get("link") or ""))) for s in block["sources"] if isinstance(s, dict))
        # extractores
        if extractors and hasattr(extractors, "extract_entities"):
            try:
                entities = extractors.extract_entities(combined_text)
            except Exception:
                entities = {"emails": [], "phones": [], "urls": [], "socials": {}}
        else:
            # Fallback: extracción básica (intenta usar name_utils.EMAIL_RE etc. if present)
            entities = {"emails": [], "phones": [], "urls": [], "socials": {}}
        block["entities"] = entities
        blocks.append(block)

    # Consolidar, puntuar y clasificar
    consolidated = consolidate_results(blocks)
    hits = consolidated["hits"]
    hits_scored = score_and_classify_hits(hits, query_value)
    summary = build_summary(query_type, query_value, consolidated, hits_scored)

    # Exportar si es necesario
    exported_files = []
    if args.out:
        exported_files = export_csvs(args.out, summary, hits_scored, consolidated)

    # Impresión / JSON de salida
    output = {
        "summary": summary,
        "hits": hits_scored,
        "url_info": {},  # opcional: podría llenarse con fetch_page_meta
        "raw_blocks": blocks,
        "exported_files": exported_files
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2, default=default_serialize))
    else:
        # Resumen legible
        print("\n=== RESUMEN OSINT ===")
        print(f"Tipo: {summary.get('query_type')}  |  Consulta: {summary.get('query_value')}")
        print(f"Emails detectados: {len(summary.get('emails_found', []))} -> {summary.get('emails_found')}")
        print(f"Téfonos detectados: {len(summary.get('phones_found', []))} -> {summary.get('phones_found')}")
        print(f"Redes detectadas: { {k: len(v) for k,v in (summary.get('socials_found') or {}).items()} }")
        print("Top dominios:")
        for d, c in summary.get("top_domains", [])[:10]:
            print(f" - {d} ({c})")
        print("\nTop fuentes (por score):")
        for src in summary.get("top_hits", [])[:10]:
            print(f" - [{src.get('engine')}] {src.get('title')}\n    {src.get('link')} (score={src.get('score')})")
        if exported_files:
            print("\nCSV exportado:", ", ".join(exported_files))
        if MISSING_MODULES:
            print("\n--- Atención: módulos faltantes ---")
            print("Algunos módulos core no están implementados. El resultado mostrado es parcial.")
            print("Para obtener funcionalidad completa crea/implementa los módulos listados al inicio.")
        print("\nPara obtener la salida completa en JSON usa --json")
    return output

def parse_args():
    p = argparse.ArgumentParser(description="OSINT modular - main.py (orquestador)")
    group = p.add_mutually_exclusive_group(required=False)
    group.add_argument("--email", "-e", help="Correo electrónico a investigar")
    group.add_argument("--phone", "-p", help="Teléfono a investigar")
    group.add_argument("--name", "-n", help="Nombre completo a investigar")
    p.add_argument("--json", action="store_true", help="Salida JSON")
    p.add_argument("--limit", type=int, default=6, help="Límite resultados por motor (por query)")
    p.add_argument("--workers", type=int, default=4, help="Hilos concurrentes (si implementado en módulos)")
    p.add_argument("--mindelay", type=float, default=1.5, help="Demora mínima por dominio (s) (si HTTPClient la usa)")
    p.add_argument("--proxy", type=str, default=None, help="Proxy HTTP/HTTPS (opcional)")
    p.add_argument("--out", type=str, default=None, help="Base name para export CSV (ej: report -> report_summary.csv...)")
    p.add_argument("--cache", type=str, default=".osint_cache.json", help="Archivo cache JSON (opcional)")
    p.add_argument("--cache-ttl", type=int, default=86400, help="TTL cache en segundos")
    p.add_argument("--max-name-queries", type=int, default=4, help="Máximo queries generadas por nombre")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    try:
        run_orchestrator(args)
    except Exception as exc:
        print("Error ejecutando orquestador:", exc)
        if MISSING_MODULES:
            print("\nRecuerda: puedes pedirme que genere los módulos faltantes ahora mismo.")
        sys.exit(1)
