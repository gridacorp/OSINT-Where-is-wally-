# core/extractors.py
import re
from typing import List, Dict, Any
from bs4 import BeautifulSoup


# ------------------------------------------------------------
# FUNCIONES DE EXTRACCIÓN BÁSICA
# ------------------------------------------------------------

def extract_emails(text: str) -> List[str]:
    """
    Extrae todas las direcciones de correo electrónico válidas de un texto o HTML.
    """
    if not text:
        return []
    text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    pattern = re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        re.IGNORECASE
    )
    emails = pattern.findall(text)
    # eliminar duplicados
    emails = list(dict.fromkeys(emails))
    return emails


def extract_phones(text: str) -> List[str]:
    """
    Extrae posibles números telefónicos de texto o HTML.
    Admite formatos internacionales y nacionales comunes.
    """
    if not text:
        return []
    text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    pattern = re.compile(
        r"(?:\+?\d{1,3}[\s\-\.]?)?(?:\(?\d{2,4}\)?[\s\-\.]?)?\d{3,4}[\s\-\.]?\d{3,4}",
        re.MULTILINE
    )
    phones = pattern.findall(text)
    # limpiar resultados
    clean = []
    for ph in phones:
        ph2 = re.sub(r"[^\d+]", "", ph)
        if 7 <= len(ph2) <= 15:
            clean.append(ph2)
    clean = list(dict.fromkeys(clean))
    return clean


def extract_links(text: str) -> List[str]:
    """
    Extrae todos los enlaces HTTP/HTTPS válidos del texto o HTML.
    """
    if not text:
        return []
    pattern = re.compile(
        r"(https?://[^\s\"'<>]+)",
        re.IGNORECASE
    )
    links = pattern.findall(text)
    links = list(dict.fromkeys(links))
    return links


def extract_usernames(text: str) -> List[str]:
    """
    Extrae posibles nombres de usuario o alias de texto.
    Busca patrones típicos de redes sociales (@usuario, usuario_123, etc.).
    """
    if not text:
        return []
    text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    pattern = re.compile(
        r"(?:@|user/|u/)([a-zA-Z0-9._\-]{3,32})",
        re.IGNORECASE
    )
    usernames = pattern.findall(text)
    usernames = [u.lower() for u in usernames]
    usernames = list(dict.fromkeys(usernames))
    return usernames


# ------------------------------------------------------------
# FUNCIONES AVANZADAS
# ------------------------------------------------------------

def extract_social_profiles(text: str) -> Dict[str, List[str]]:
    """
    Identifica posibles enlaces o menciones a perfiles de redes sociales
    dentro del texto o HTML.
    Retorna un diccionario con listas por red detectada.
    """
    if not text:
        return {}

    links = extract_links(text)
    profiles = {
        "facebook": [],
        "instagram": [],
        "twitter": [],
        "tiktok": [],
        "linkedin": [],
        "github": [],
        "youtube": []
    }

    for url in links:
        if "facebook.com" in url and "/profile" not in url:
            profiles["facebook"].append(url)
        elif "instagram.com" in url:
            profiles["instagram"].append(url)
        elif "twitter.com" in url or "x.com" in url:
            profiles["twitter"].append(url)
        elif "tiktok.com" in url:
            profiles["tiktok"].append(url)
        elif "linkedin.com" in url:
            profiles["linkedin"].append(url)
        elif "github.com" in url:
            profiles["github"].append(url)
        elif "youtube.com" in url or "youtu.be" in url:
            profiles["youtube"].append(url)

    # eliminar duplicados
    for k in profiles:
        profiles[k] = list(dict.fromkeys(profiles[k]))
    return profiles


def extract_possible_names(text: str) -> List[str]:
    """
    Extrae posibles nombres propios detectando palabras capitalizadas consecutivas.
    Ejemplo: "Juan Pérez", "María José López"
    """
    if not text:
        return []
    text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    pattern = re.compile(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+")
    names = pattern.findall(text)
    names = list(dict.fromkeys(names))
    return names


# ------------------------------------------------------------
# FUNCIÓN GLOBAL DE EXTRACCIÓN COMPLETA
# ------------------------------------------------------------

def extract_all(text: str) -> Dict[str, Any]:
    """
    Realiza extracción completa de correos, teléfonos, URLs, usernames y redes.
    Retorna un diccionario con todos los resultados.
    """
    return {
        "emails": extract_emails(text),
        "phones": extract_phones(text),
        "links": extract_links(text),
        "usernames": extract_usernames(text),
        "social_profiles": extract_social_profiles(text),
        "names": extract_possible_names(text)
    }


# ------------------------------------------------------------
# PRUEBA LOCAL
# ------------------------------------------------------------
if __name__ == "__main__":
    sample = """
        Contacto: juan.perez@example.com, jperez_1988@hotmail.com
        Tel: +52 55 1234 5678 o (55) 9876-5432
        Instagram: https://instagram.com/juanperez
        Facebook: https://facebook.com/juan.perez
        LinkedIn: https://linkedin.com/in/juanperez
        Twitter: @Juan_Perez
        Archivo: https://mega.nz/file/abc123
        Nombre detectado: Juan José Lota
    """
    data = extract_all(sample)
    for k, v in data.items():
        print(f"\n{k.upper()}:")
        for item in v if isinstance(v, list) else v.keys():
            print(" -", item)
