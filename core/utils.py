# core/utils.py
"""
Utils para el proyecto OSINT.

Contiene:
 - HEADERS: user-agent por defecto
 - DomainRateLimiter: control sencillo de tasa por dominio (delay + jitter)
 - SimpleCache: cache local en JSON con TTL (para respuestas HTTP mínimas)
 - fetch_url_text: realiza GET simple y devuelve (status_code, text)
 - make_request: envoltura que aplica limiter y cache (opcional)
 - save_json / load_json: utilidades para persistir resultados
 - save_csv: exportar listas/dicts simples a CSV
 - sanitize_filename: limpiar cadenas para nombres de archivo
 - ahora() : timestamp legible
"""

from __future__ import annotations
import time
import json
import os
import random
import re
import csv
from typing import Optional, Tuple, Any, Dict
from urllib.parse import urlparse

import requests

# User-Agent por defecto (puedes cambiar o ampliar leyendo data/user_agents.txt)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

# -------------------------
# Helper: dominio de URL
# -------------------------
def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

# -------------------------
# Control de tasa por dominio
# -------------------------
class DomainRateLimiter:
    """
    Espera entre peticiones por dominio para evitar bloqueos.
    - min_delay: demora base en segundos
    - jitter: aleatoriza hasta +/- 40% para parecer más humano
    """
    def __init__(self, min_delay: float = 1.5):
        self.min_delay = float(min_delay)
        self._last: dict[str, float] = {}

    def wait(self, url: str):
        d = domain_of(url)
        if not d:
            return
        last = self._last.get(d, 0.0)
        now = time.time()
        jitter = random.uniform(0, self.min_delay * 0.4)
        wait_for = self.min_delay + jitter
        to_wait = last + wait_for - now
        if to_wait > 0:
            time.sleep(to_wait)
        self._last[d] = time.time()

# -------------------------
# Caché simple JSON en disco
# -------------------------
class SimpleCache:
    """
    Caché muy simple basado en un archivo JSON.
    Guarda pares key -> {"value": ..., "_fetched_at": epoch}
    - path: ruta al archivo
    - ttl: tiempo de vida en segundos
    """
    def __init__(self, path: str = ".osint_cache.json", ttl: int = 86400):
        self.path = path
        self.ttl = int(ttl)
        self._data: dict = {}
        self._load()

    def _load(self):
        try:
            if os.path.isfile(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            else:
                self._data = {}
        except Exception:
            # si falla la lectura, empezar vacío
            self._data = {}

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get(self, key: str) -> Optional[Any]:
        rec = self._data.get(key)
        if not rec:
            return None
        ts = rec.get("_fetched_at", 0)
        if time.time() - ts > self.ttl:
            # expirado: eliminar y devolver None
            try:
                del self._data[key]
                self._save()
            except Exception:
                pass
            return None
        return rec.get("value")

    def set(self, key: str, value: Any):
        try:
            self._data[key] = {"value": value, "_fetched_at": time.time()}
            self._save()
        except Exception:
            pass

    def clear(self):
        self._data = {}
        try:
            if os.path.isfile(self.path):
                os.remove(self.path)
        except Exception:
            pass

# -------------------------
# Petición HTTP básica
# -------------------------
def fetch_url_text(url: str, headers: Optional[dict] = None, timeout: int = 12,
                   proxies: Optional[dict] = None) -> Tuple[Optional[int], Optional[str]]:
    """
    Realiza un GET a 'url' y devuelve (status_code, text).
    En caso de error devuelve (None, None).
    No aplica rate-limiter ni cache: función atómica.
    """
    try:
        r = requests.get(url, headers=headers or HEADERS, timeout=timeout, proxies=proxies)
        # algunos sitios devuelven bytes mal codificados; r.text intenta decodificar
        return r.status_code, r.text
    except Exception:
        return None, None

# -------------------------
# make_request: aplicando limiter y cache (opcional)
# -------------------------
def make_request(url: str,
                 limiter: Optional[DomainRateLimiter] = None,
                 cache: Optional[SimpleCache] = None,
                 use_cache: bool = True,
                 timeout: int = 12,
                 headers: Optional[dict] = None,
                 proxy: Optional[str] = None) -> Tuple[Optional[int], Optional[str]]:
    """
    Envoltura que aplica:
      - limiter.wait(url) si se pasa un limiter
      - cache.get / cache.set si se pasa SimpleCache y use_cache=True
      - llama a fetch_url_text para obtener el contenido

    Devuelve (status_code, text) o (None, None) en error.
    """
    if limiter:
        try:
            limiter.wait(url)
        except Exception:
            pass

    key = f"GET:{url}"
    if use_cache and cache:
        cached = cache.get(key)
        if cached and isinstance(cached, dict):
            # cached expected structure: {"status_code": int, "text": str}
            return cached.get("status_code"), cached.get("text")

    proxies = {"http": proxy, "https": proxy} if proxy else None
    status, text = fetch_url_text(url, headers=headers or HEADERS, timeout=timeout, proxies=proxies)

    if use_cache and cache and status is not None:
        try:
            cache.set(key, {"status_code": status, "text": text})
        except Exception:
            pass

    return status, text

# -------------------------
# Utilidades de persistencia y formato
# -------------------------
def sanitize_filename(s: str) -> str:
    """Limpia una cadena para usarla como nombre de archivo."""
    s2 = s.strip().lower()
    s2 = re.sub(r"[^\w\-_\. ]", "_", s2)
    s2 = re.sub(r"\s+", "_", s2)
    return s2[:240]

def save_json(obj: Any, path: str, ensure_ascii: bool = False, indent: int = 2) -> str:
    """Guarda objeto como JSON y devuelve la ruta."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=ensure_ascii, indent=indent)
        return path
    except Exception as e:
        raise

def load_json(path: str) -> Any:
    """Carga JSON desde archivo o devuelve None si falla."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_csv_rows(path: str, headers: list[str], rows: list[list[Any]]) -> str:
    """
    Guarda una lista de filas en CSV.
    - headers: lista de cabeceras
    - rows: lista de filas (listas)
    """
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if headers:
                w.writerow(headers)
            for r in rows:
                w.writerow([str(x) if x is not None else "" for x in r])
        return path
    except Exception:
        raise

def save_dicts_to_csv(path: str, fieldnames: list[str], dicts: list[dict]) -> str:
    """
    Guarda una lista de dicts en CSV respetando fieldnames (orden).
    """
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for d in dicts:
                # convertir listas a ;joined strings para campos simples
                row = {}
                for k in fieldnames:
                    v = d.get(k, "")
                    if isinstance(v, list):
                        row[k] = ";".join([str(x) for x in v])
                    else:
                        row[k] = v
                w.writerow(row)
        return path
    except Exception:
        raise

# -------------------------
# Misc helpers
# -------------------------
def now() -> str:
    """Timestamp legible."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

def random_user_agent_from_file(path: str) -> str:
    """
    Si existe un archivo con varios user-agents (uno por línea), devuelve uno aleatorio.
    Si no existe o falla, devuelve HEADERS['User-Agent'] por defecto.
    """
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                agents = [line.strip() for line in f if line.strip()]
            if agents:
                return random.choice(agents)
    except Exception:
        pass
    return HEADERS.get("User-Agent")

# -------------------------
# Función pequeña para debug
# -------------------------
def simple_log(msg: str):
    ts = now()
    print(f"[{ts}] {msg}")
