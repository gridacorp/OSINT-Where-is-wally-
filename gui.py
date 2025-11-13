# gui.py
# Interfaz gráfica para osint_tool (Tkinter) - VERSIÓN CORREGIDA

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import json
import os
import traceback
import time
import random

# Importaciones CORRECTAS desde el paquete core
try:
    from core.site import SiteSearcher
except ImportError as e:
    print("Error importando SiteSearcher:", e)
    SiteSearcher = None

try:
    from core.name_utils import name_variants_improved, email_variants_from_name
except ImportError:
    name_variants_improved = None
    email_variants_from_name = None

try:
    from core.extractors import extract_all
except ImportError:
    extract_all = None

try:
    from core.utils import DomainRateLimiter, SimpleCache, save_json, sanitize_filename
except ImportError:
    DomainRateLimiter = None
    SimpleCache = None
    save_json = None
    sanitize_filename = None

# Fallback si sanitize_filename no está disponible
if sanitize_filename is None:
    def sanitize_filename(name: str) -> str:
        """Sanitiza nombre para sistema de archivos (versión segura)"""
        if not name:
            return "unnamed_result"
        # Eliminar SOLO caracteres peligrosos para sistemas de archivos
        invalid = r'[<>:"/\\|?*\x00-\x1f]'
        s2 = re.sub(invalid, "_", name.strip())
        # Reemplazar espacios consecutivos
        s2 = re.sub(r'\s+', "_", s2)
        # Evitar nombres que comiencen/terminen con puntos o guiones bajos
        s2 = s2.strip("._")
        return s2[:240] or "file"

APP_TITLE = "OSINT Tool — GUI"

class OSINTGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("920x700")

        self.type_var = tk.StringVar(value="name")
        self.query_var = tk.StringVar()
        self.limit_var = tk.IntVar(value=4)
        self.workers_var = tk.IntVar(value=4)
        self.delay_var = tk.DoubleVar(value=1.5)
        self.use_cache_var = tk.BooleanVar(value=True)
        self.cache_file_var = tk.StringVar(value=".osint_cache.json")
        self.status_var = tk.StringVar(value="Listo")

        self.search_result = None

        self._build_ui()

    def _build_ui(self):
        frm = ttk.Frame(self, padding=8)
        frm.pack(fill="both", expand=True)

        row = 0
        ttk.Label(frm, text="Tipo:").grid(row=row, column=0, sticky="w")
        ttk.Radiobutton(frm, text="Nombre", variable=self.type_var, value="name").grid(row=row, column=1, sticky="w")
        ttk.Radiobutton(frm, text="Correo", variable=self.type_var, value="email").grid(row=row, column=2, sticky="w")
        ttk.Radiobutton(frm, text="Teléfono", variable=self.type_var, value="phone").grid(row=row, column=3, sticky="w")

        ttk.Label(frm, text="Consulta:").grid(row=row+1, column=0, sticky="w", pady=(8,0))
        ttk.Entry(frm, textvariable=self.query_var, width=60).grid(row=row+1, column=1, columnspan=5, sticky="w", pady=(8,0))

        ttk.Label(frm, text="Límite por motor:").grid(row=row+2, column=0, sticky="w", pady=(8,0))
        ttk.Spinbox(frm, from_=1, to=20, textvariable=self.limit_var, width=6).grid(row=row+2, column=1, sticky="w", pady=(8,0))

        ttk.Label(frm, text="Hilos:").grid(row=row+2, column=2, sticky="w", pady=(8,0))
        ttk.Spinbox(frm, from_=1, to=10, textvariable=self.workers_var, width=6).grid(row=row+2, column=3, sticky="w", pady=(8,0))

        ttk.Label(frm, text="Delay dominio (s):").grid(row=row+2, column=4, sticky="w", pady=(8,0))
        ttk.Entry(frm, textvariable=self.delay_var, width=6).grid(row=row+2, column=5, sticky="w", pady=(8,0))

        ttk.Checkbutton(frm, text="Usar cache", variable=self.use_cache_var).grid(row=row+3, column=0, sticky="w", pady=(8,0))
        ttk.Label(frm, text="Archivo cache:").grid(row=row+3, column=1, sticky="w", pady=(8,0))
        ttk.Entry(frm, textvariable=self.cache_file_var, width=28).grid(row=row+3, column=2, columnspan=2, sticky="w", pady=(8,0))

        self.run_btn = ttk.Button(frm, text="Iniciar búsqueda", command=self._on_run)
        self.run_btn.grid(row=row+4, column=0, pady=12, sticky="w")

        self.save_btn = ttk.Button(frm, text="Guardar JSON", command=self._on_save, state="disabled")
        self.save_btn.grid(row=row+4, column=1, pady=12, sticky="w")

        self.clear_btn = ttk.Button(frm, text="Limpiar", command=self._on_clear)
        self.clear_btn.grid(row=row+4, column=2, pady=12, sticky="w")

        self.progress = ttk.Progressbar(frm, mode="indeterminate", length=600)
        self.progress.grid(row=row+5, column=0, columnspan=6, pady=(4,8))
        ttk.Label(frm, textvariable=self.status_var).grid(row=row+6, column=0, columnspan=6, sticky="w")

        self.results_text = tk.Text(frm, height=28, wrap="word", bg="#111", fg="#e6e6e6", insertbackground="#fff")
        self.results_text.grid(row=row+7, column=0, columnspan=6, sticky="nsew", pady=(8,0))
        frm.rowconfigure(row+7, weight=1)
        frm.columnconfigure(1, weight=1)

    def _log(self, line: str):
        self.results_text.insert("end", line + "\n")
        self.results_text.see("end")
        self.update_idletasks()  # Actualizar UI inmediatamente

    def _on_clear(self):
        self.results_text.delete("1.0", "end")
        self.search_result = None
        self.save_btn.config(state="disabled")
        self.status_var.set("Listo")

    def _on_save(self):
        if not self.search_result:
            messagebox.showinfo("Nada para guardar", "Primero ejecuta una búsqueda.")
            return
        
        # Usar fallback si sanitize_filename no está disponible
        base = sanitize_filename(self.search_result.get("query", "result"))
        os.makedirs("results", exist_ok=True)
        path = os.path.join("results", f"{base}_output.json")
        
        try:
            if save_json:
                save_json(self.search_result, path, ensure_ascii=False, indent=2)
            else:
                # Fallback de guardado si save_json no está disponible
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(self.search_result, f, ensure_ascii=False, indent=2, default=str)
            messagebox.showinfo("Guardado", f"Resultados guardados en:\n{path}")
        except Exception as e:
            messagebox.showerror("Error al guardar", str(e))

    def _on_run(self):
        query = self.query_var.get().strip()
        if not query:
            messagebox.showwarning("Entrada requerida", "Escribe un nombre, correo o teléfono para buscar.")
            return
        self.run_btn.config(state="disabled")
        self.save_btn.config(state="disabled")
        self.progress.start(10)
        self.status_var.set("Ejecutando búsqueda...")
        threading.Thread(target=self._run_search_thread, daemon=True).start()

    def _run_search_thread(self):
        try:
            q = self.query_var.get().strip()
            t = self.type_var.get()
            limit = max(1, min(20, int(self.limit_var.get())))
            delay = float(self.delay_var.get())
            use_cache = bool(self.use_cache_var.get())
            cache_file = self.cache_file_var.get().strip() or ".osint_cache.json"

            # Verificar módulos críticos
            if not SiteSearcher:
                error_msg = "No se encontró SiteSearcher. Asegúrate de que core/site.py exista y esté correctamente implementado."
                self.after(0, lambda: messagebox.showerror("Módulo faltante", error_msg))
                self.after(0, lambda: self.status_var.set("Error de módulo"))
                return
                
            if t == "name" and not name_variants_improved:
                error_msg = "No se encontró name_variants_improved. Asegúrate de que core/name_utils.py exista."
                self.after(0, lambda: messagebox.showerror("Módulo faltante", error_msg))
                self.after(0, lambda: self.status_var.set("Error de módulo"))
                return

            # Configurar Cache
            cache = None
            if use_cache and SimpleCache:
                try:
                    # TTL de 24 horas (86400 segundos)
                    cache = SimpleCache(path=cache_file, ttl=86400)
                except Exception as e:
                    self.after(0, lambda: self._log(f"[!] Error inicializando caché: {e}"))
            
            # Configurar Rate Limiter
            limiter = None
            if DomainRateLimiter:
                try:
                    limiter = DomainRateLimiter(min_delay=delay)
                except Exception as e:
                    self.after(0, lambda: self._log(f"[!] Error inicializando rate limiter: {e}"))

            # Crear SiteSearcher SIN el parámetro limit (se pasa en unified_search)
            searcher = SiteSearcher(
                client_headers=None,
                timeout=12,
                proxy=None,
                limiter=limiter,
                cache=cache
            )

            queries = []
            if t == "name" and name_variants_improved:
                variants = name_variants_improved(q)
                max_queries = 4  # Límite razonable para no saturar
                queries = variants[:max_queries]
                if email_variants_from_name:
                    email_sugs = email_variants_from_name(q, max_per_domain=2)[:max_queries]
                    queries.extend(email_sugs)
                self.after(0, lambda: self._log(f"[+] Variantes usadas: {', '.join(queries[:max_queries])}"))
                if email_sugs:
                    self.after(0, lambda: self._log(f"[+] Sugerencias de emails: {', '.join(email_sugs)}"))
            else:
                queries = [q]

            all_results = []
            aggregated_entities = {
                "emails": set(), 
                "phones": set(), 
                "urls": set(), 
                "socials": {},
                "usernames": set(),
                "names": set()
            }

            for qi in queries:
                if not qi.strip():
                    continue
                    
                self.after(0, lambda qi=qi: self._log(f"Buscando: {qi}"))
                try:
                    # Pasar el límite en unified_search, no en el constructor
                    block = searcher.unified_search(
                        qi, 
                        limit=limit, 
                        include_socials=True, 
                        include_repos=True
                    )
                except Exception as exc:
                    self.after(0, lambda qi=qi, exc=exc: self._log(f"Error buscando '{qi}': {exc}"))
                    block = {"results": [], "entities": {}}
                
                res = block.get("results", [])
                ents = block.get("entities", {})

                for r in res:
                    all_results.append(r)
                    
                # Agregar entidades encontradas
                for e in ents.get("emails", []):
                    aggregated_entities["emails"].add(e)
                for p in ents.get("phones", []):
                    aggregated_entities["phones"].add(p)
                for u in ents.get("links", []):  # Cambiado de "urls" a "links" según extractors.py
                    aggregated_entities["urls"].add(u)
                for u in ents.get("usernames", []):
                    aggregated_entities["usernames"].add(u)
                for n in ents.get("names", []):
                    aggregated_entities["names"].add(n)
                    
                # Procesar perfiles sociales correctamente
                socials = ents.get("socials", {})
                if socials:
                    for platform, urls in socials.items():
                        if platform not in aggregated_entities["socials"]:
                            aggregated_entities["socials"][platform] = set()
                        if isinstance(urls, list):
                            for url in urls:
                                aggregated_entities["socials"][platform].add(url)
                        elif isinstance(urls, str):
                            aggregated_entities["socials"][platform].add(urls)

                self.after(0, lambda res=len(res), ents=len(ents.get('emails', [])), qi=qi: 
                    self._log(f"  -> enlaces: {res}  emails encontrados en bloque: {ents}"))

            # Convertir sets a listas para el resultado final
            for key in ["emails", "phones", "urls", "usernames", "names"]:
                aggregated_entities[key] = sorted(list(aggregated_entities[key]))
                
            # Procesar perfiles sociales
            socials_result = {}
            for platform, urls in aggregated_entities["socials"].items():
                socials_result[platform] = sorted(list(urls))

            out = {
                "query": q,
                "query_type": t,
                "variants_used": queries,
                "results": all_results,
                "entities": {
                    "emails": aggregated_entities["emails"],
                    "phones": aggregated_entities["phones"],
                    "urls": aggregated_entities["urls"],
                    "usernames": aggregated_entities["usernames"],
                    "names": aggregated_entities["names"],
                    "socials": socials_result
                }
            }

            self.search_result = out
            os.makedirs("results", exist_ok=True)
            # Usar sanitize_filename con fallback
            base = sanitize_filename(q)
            outpath = os.path.join("results", f"{base}_output.json")
            
            try:
                if save_json:
                    save_json(out, outpath, ensure_ascii=False, indent=2)
                else:
                    # Fallback de guardado si save_json no está disponible
                    with open(outpath, "w", encoding="utf-8") as f:
                        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
                self.after(0, lambda: self._log(f"[+] Resultados guardados en {outpath}"))
            except Exception as e:
                self.after(0, lambda e=e: self._log(f"[!] Error guardando JSON: {e}"))

            self.after(0, lambda: self._log("\n=== RESUMEN ==="))
            self.after(0, lambda: self._log(f"Emails: {len(out['entities']['emails'])} -> {out['entities']['emails']}"))
            self.after(0, lambda: self._log(f"Teléfonos: {len(out['entities']['phones'])} -> {out['entities']['phones']}"))
            self.after(0, lambda: self._log(f"URLs: {len(out['entities']['urls'])}"))
            self.after(0, lambda: self._log(f"Nombres detectados: {out['entities']['names']}"))
            self.after(0, lambda: self._log(f"Nombres de usuario: {out['entities']['usernames']}"))
            
            social_summary = {k: len(v) for k, v in out['entities']['socials'].items()}
            self.after(0, lambda: self._log(f"Perfiles detectados: {social_summary}"))

            # Actualizar la UI desde el hilo secundario
            self.after(0, lambda: self.save_btn.config(state="normal"))
            self.after(0, lambda: self.status_var.set("Búsqueda completada"))
        except Exception as e:
            error_msg = f"Error inesperado:\n{traceback.format_exc()}"
            self.after(0, lambda: self._log(error_msg))
            self.after(0, lambda: self.status_var.set("Error"))
        finally:
            self.after(0, lambda: self.progress.stop())
            self.after(0, lambda: self.run_btn.config(state="normal"))

def run_app():
    app = OSINTGUI()
    app.mainloop()

if __name__ == "__main__":
    run_app()