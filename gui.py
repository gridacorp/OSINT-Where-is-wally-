import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import json
import os
from datetime import datetime
from core import search_engine, name_utils, utils

class OSINTGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OSINT Tool — Búsqueda Inteligente")
        self.geometry("800x600")
        self.configure(bg="#1e1e1e")

        # Variables
        self.query_type = tk.StringVar(value="name")
        self.query_value = tk.StringVar()
        self.progress_text = tk.StringVar(value="Listo para buscar...")

        # Estilos
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TLabel", background="#1e1e1e", foreground="#ffffff", font=("Arial", 11))
        style.configure("TButton", font=("Arial", 11), padding=6)
        style.configure("TEntry", font=("Arial", 11))

        self.create_widgets()

    def create_widgets(self):
        # Frame superior
        frame_top = ttk.Frame(self)
        frame_top.pack(pady=20)

        ttk.Label(frame_top, text="Tipo de búsqueda:").grid(row=0, column=0, padx=5, pady=5)
        ttk.Radiobutton(frame_top, text="Nombre", variable=self.query_type, value="name").grid(row=0, column=1)
        ttk.Radiobutton(frame_top, text="Correo", variable=self.query_type, value="email").grid(row=0, column=2)
        ttk.Radiobutton(frame_top, text="Teléfono", variable=self.query_type, value="phone").grid(row=0, column=3)

        ttk.Label(frame_top, text="Valor a buscar:").grid(row=1, column=0, padx=5, pady=10)
        ttk.Entry(frame_top, textvariable=self.query_value, width=50).grid(row=1, column=1, columnspan=3, pady=5)

        ttk.Button(frame_top, text="Iniciar búsqueda", command=self.run_search_thread).grid(row=2, column=0, columnspan=4, pady=10)

        # Progreso
        ttk.Label(self, textvariable=self.progress_text).pack(pady=5)
        self.progress = ttk.Progressbar(self, length=600, mode="indeterminate")
        self.progress.pack(pady=10)

        # Caja de resultados
        self.text_box = tk.Text(self, wrap="word", bg="#2d2d2d", fg="#ffffff", insertbackground="#ffffff", height=20)
        self.text_box.pack(padx=10, pady=10, fill="both", expand=True)

        # Botones inferiores
        frame_bottom = ttk.Frame(self)
        frame_bottom.pack(pady=10)

        ttk.Button(frame_bottom, text="Guardar resultados", command=self.save_results).grid(row=0, column=0, padx=10)
        ttk.Button(frame_bottom, text="Limpiar", command=self.clear_text).grid(row=0, column=1, padx=10)
        ttk.Button(frame_bottom, text="Salir", command=self.quit).grid(row=0, column=2, padx=10)

    def run_search_thread(self):
        """Lanza la búsqueda en un hilo separado."""
        query = self.query_value.get().strip()
        if not query:
            messagebox.showwarning("Advertencia", "Por favor, ingresa un valor para buscar.")
            return

        self.progress.start(10)
        self.progress_text.set("Buscando... Por favor espera.")
        threading.Thread(target=self.run_search, args=(query,), daemon=True).start()

    def run_search(self, query):
        try:
            if self.query_type.get() == "name":
                variants = name_utils.generate_name_variants(query)
                self.text_box.insert("end", f"[+] Variantes generadas: {', '.join(variants)}\n\n")
                results = search_engine.run_osint_search(variants)
            else:
                results = search_engine.run_osint_search([query])

            # Mostrar en interfaz
            self.show_results(results)

            # Guardar JSON
            os.makedirs("results", exist_ok=True)
            with open("results/output.json", "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

            self.progress_text.set("Búsqueda completada. Resultados guardados en results/output.json")

        except Exception as e:
            messagebox.showerror("Error", f"Ocurrió un error: {e}")
            self.progress_text.set("Error durante la búsqueda.")
        finally:
            self.progress.stop()

    def show_results(self, results):
        """Muestra resultados en la caja de texto."""
        self.text_box.delete(1.0, "end")
        self.text_box.insert("end", "=== RESULTADOS OSINT ===\n\n")
        for r in results.get("results", []):
            self.text_box.insert("end", f"Origen: {r.get('engine', 'desconocido')}\n")
            self.text_box.insert("end", f"Título: {r.get('title')}\n")
            self.text_box.insert("end", f"Enlace: {r.get('link')}\n")
            self.text_box.insert("end", f"Descripción: {r.get('snippet')}\n")
            self.text_box.insert("end", "-"*60 + "\n")

    def save_results(self):
        """Guarda los resultados visibles en un archivo de texto."""
        text = self.text_box.get(1.0, "end").strip()
        if not text:
            messagebox.showinfo("Información", "No hay resultados para guardar.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Archivo de texto", "*.txt"), ("Todos los archivos", "*.*")]
        )
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(text)
            messagebox.showinfo("Éxito", f"Resultados guardados en:\n{file_path}")

    def clear_text(self):
        self.text_box.delete(1.0, "end")
        self.progress_text.set("Listo para nueva búsqueda.")

if __name__ == "__main__":
    app = OSINTGUI()
    app.mainloop()
