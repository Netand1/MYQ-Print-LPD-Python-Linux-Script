#!/usr/bin/env python3
"""Client LPD (RFC 1179) minimal : interroge l'état d'une file d'impression.

Usage :
    python3 lpq_client.py                       # valeurs par défaut 
    python3 lpq_client.py --long                # état détaillé (commande 0x04)
    python3 lpq_client.py --user bob            # filtrer sur un utilisateur
    sudo python3 lpq_client.py --rfc-port       # port source 721-731 (strict RFC)
    python3 lpq_client.py --send rapport.docx   # n'importe quel fichier → converti en PDF
    python3 lpq_client.py --send photo.jpg --format ps   # sortie PostScript (Ghostscript)
    python3 lpq_client.py --send doc.pdf --duplex long --color mono   # options via PJL
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile

DEFAULT_HOST = "myq-01"
DEFAULT_QUEUE = "Follow_Me"
DEFAULT_PORT = 515
DEFAULT_USER = "bob"

CMD_SHORT = b"\x03"  # Send queue state (short)
CMD_LONG = b"\x04"   # Send queue state (long)


def connect(host: str, port: int, rfc_port: bool, timeout: float) -> socket.socket:
    """Ouvre la connexion TCP, éventuellement depuis un port source 721-731."""
    if not rfc_port:
        return socket.create_connection((host, port), timeout=timeout)

    last_err = None
    for src in range(721, 732):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(timeout)
        try:
            s.bind(("", src))
            s.connect((host, port))
            return s
        except OSError as e:  # port occupé, ou pas root
            last_err = e
            s.close()
    raise ConnectionError(f"Aucun port source 721-731 utilisable : {last_err}")


def query_queue(host, port, queue, long=False, users=(), rfc_port=False, timeout=10.0) -> str:
    """Envoie la commande d'état et renvoie la réponse brute du serveur."""
    cmd = (CMD_LONG if long else CMD_SHORT) + queue.encode("ascii")
    if users:
        cmd += b" " + " ".join(users).encode("ascii")
    cmd += b"\n"

    with connect(host, port, rfc_port, timeout) as s:
        s.sendall(cmd)
        chunks = []
        while True:  # le serveur ferme la connexion à la fin de la réponse
            data = s.recv(4096)
            if not data:
                break
            chunks.append(data)

    # MyQ tourne sous Windows : on tente UTF-8 puis CP1252 (accents français)
    raw = b"".join(chunks)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _expect_ack(s: socket.socket, step: str) -> None:
    """Chaque étape LPD doit être acquittée par un unique octet 0x00."""
    ack = s.recv(1)
    if ack != b"\x00":
        raise ConnectionError(f"Refus du serveur à l'étape « {step} » (réponse : {ack!r})")


def send_job(host, port, queue, user, job_name, data: bytes,
             rfc_port=False, timeout=30.0) -> str:
    """Envoie un travail LPR (commande 0x02) : control file puis data file."""
    import random
    client = "".join(c for c in socket.gethostname() if c.isalnum())[:31] or "client"
    num = f"{random.randint(0, 999):03d}"
    cf_name, df_name = f"cfA{num}{client}", f"dfA{num}{client}"

    control = (
        f"H{client}\n"
        f"P{user}\n"
        f"J{job_name}\n"
        f"L{user}\n"          # page de garde (bannière) au nom de l'utilisateur
        f"l{df_name}\n"       # 'l' = imprimer tel quel (raw)
        f"N{job_name}\n"
        f"U{df_name}\n"
    ).encode("ascii", errors="replace")

    with connect(host, port, rfc_port, timeout) as s:
        s.sendall(b"\x02" + queue.encode("ascii") + b"\n")
        _expect_ack(s, "ouverture de la file")

        s.sendall(f"\x02{len(control)} {cf_name}\n".encode("ascii"))
        _expect_ack(s, "annonce du control file")
        s.sendall(control + b"\x00")
        _expect_ack(s, "réception du control file")

        s.sendall(f"\x03{len(data)} {df_name}\n".encode("ascii"))
        _expect_ack(s, "annonce du data file")
        s.sendall(data + b"\x00")
        _expect_ack(s, "réception du data file")

    return df_name


def make_test_page(user: str) -> bytes:
    """Page de test en texte brut (CRLF + saut de page final pour le mode texte PCL)."""
    import datetime
    lines = [
        "Test d'impression LPR (RFC 1179)",
        "",
        f"Utilisateur : {user}",
        f"Poste       : {socket.gethostname()}",
        f"Date        : {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
        "Envoye par lpq_client.py",
    ]
    return ("\r\n".join(lines) + "\r\n\f").encode("ascii", errors="replace")


# --------------------------------------------------------------------------
# Conversion : n'importe quel fichier → langage d'imprimante (PDF / PS / PCL)
# --------------------------------------------------------------------------
PRINTER_FORMATS = ("pdf", "ps", "pcl")

# Périphériques Ghostscript utilisés pour PDF → PS / PCL
GS_DEVICES = {"ps": ["-sDEVICE=ps2write"], "pcl": ["-sDEVICE=pxlcolor"]}

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"}


class ConversionError(RuntimeError):
    pass


def detect_format(data: bytes, filename: str = "") -> str:
    """Identifie le format d'après les octets magiques (puis l'extension en secours).

    Renvoie : 'pdf', 'ps', 'pcl', 'image', 'text' ou 'document' (à confier à LibreOffice).
    """
    head = data[:1024]
    if head.startswith(b"%PDF"):
        return "pdf"
    # Un en-tête PJL (UEL) peut précéder PS ou PCL : on regarde ce qui suit
    if head.startswith(b"\x1b%-12345X"):
        return "ps" if b"POSTSCRIPT" in head.upper() else "pcl"
    if head.startswith(b"%!") or head.startswith(b"\x04%!"):
        return "ps"
    if head.startswith(b"\x1bE") or head.startswith(b") HP-PCL XL"):
        return "pcl"
    if (head.startswith((b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"BM", b"II*\x00", b"MM\x00*"))
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")):
        return "image"
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in {".txt", ".log", ".csv", ".md", ""} or not ext:
        try:
            head.decode("utf-8")
            return "text"
        except UnicodeDecodeError:
            if b"\x00" not in head:
                return "text"
    return "document"   # docx, xlsx, pptx, odt, rtf, html, ...


def _soffice_to_pdf(path: str, workdir: str) -> bytes:
    """Conversion via LibreOffice headless (bureautique, HTML, texte, ...)."""
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise ConversionError("LibreOffice (soffice) introuvable : impossible de convertir ce document")
    # Profil isolé : évite le conflit avec une instance LibreOffice déjà ouverte
    profile = "file://" + os.path.join(workdir, "lo_profile")
    cmd = [exe, f"-env:UserInstallation={profile}", "--headless", "--norestore",
           "--convert-to", "pdf", "--outdir", workdir, path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    out = os.path.join(workdir, os.path.splitext(os.path.basename(path))[0] + ".pdf")
    if r.returncode != 0 or not os.path.exists(out):
        raise ConversionError(f"Échec LibreOffice : {(r.stderr or r.stdout).strip() or 'aucun PDF produit'}")
    with open(out, "rb") as f:
        return f.read()


def _image_to_pdf(path: str) -> bytes:
    """Image(s) → PDF via Pillow (une page par image, GIF/TIFF multipages compris)."""
    try:
        from PIL import Image, ImageSequence
    except ImportError:
        raise ConversionError("Pillow absent : pip install pillow") from None
    import io
    with Image.open(path) as im:
        pages = [fr.convert("RGB") for fr in ImageSequence.Iterator(im)]
    buf = io.BytesIO()
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:], resolution=150)
    return buf.getvalue()


def _pdf_to(fmt: str, pdf: bytes, workdir: str) -> bytes:
    """PDF → PostScript ou PCL XL via Ghostscript."""
    gs = shutil.which("gs") or shutil.which("gswin64c")
    if not gs:
        raise ConversionError(f"Ghostscript (gs) requis pour produire du {fmt.upper()} "
                              "(sudo apt install ghostscript) — ou utilisez --format pdf")
    src, dst = os.path.join(workdir, "in.pdf"), os.path.join(workdir, f"out.{fmt}")
    with open(src, "wb") as f:
        f.write(pdf)
    cmd = [gs, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", *GS_DEVICES[fmt], f"-sOutputFile={dst}", src]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise ConversionError(f"Échec Ghostscript : {r.stderr.strip()}")
    with open(dst, "rb") as f:
        return f.read()


def convert_for_printer(path: str, target: str = "pdf") -> tuple[bytes, str, str]:
    """Lit `path` et renvoie (données, format_source, format_envoyé).

    Les formats déjà compris par l'imprimante (PDF, PS, PCL) sont transmis tels quels
    quand ils correspondent à la cible ; sinon tout passe par un PDF intermédiaire.
    """
    with open(path, "rb") as f:
        data = f.read()
    src = detect_format(data, path)

    if src == target or (src in PRINTER_FORMATS and target == "auto"):
        return data, src, src
    if target == "auto":
        target = "pdf"
    if src in ("ps", "pcl"):
        raise ConversionError(f"Conversion {src.upper()} → {target.upper()} non prise en charge ; "
                              "envoyez-le tel quel avec --format auto")

    with tempfile.TemporaryDirectory(prefix="lpr_") as tmp:
        if src == "pdf":
            pdf = data
        elif src == "image":
            pdf = _image_to_pdf(path)
        else:  # texte ou document bureautique
            pdf = _soffice_to_pdf(path, tmp)
        out = pdf if target == "pdf" else _pdf_to(target, pdf, tmp)
    return out, src, target


# --------------------------------------------------------------------------
# Options d'impression (recto verso, couleur) via un en-tête PJL
# --------------------------------------------------------------------------
UEL = b"\x1b%-12345X"   # Universal Exit Language : remet l'interpréteur à zéro

# Format détecté → langage annoncé à l'imprimante (le texte brut part en mode PCL)
PJL_LANGUAGE = {"pdf": "PDF", "ps": "POSTSCRIPT", "pcl": "PCL", "text": "PCL"}

PJL_DUPLEX = {
    "off":   ["DUPLEX=OFF"],
    "long":  ["DUPLEX=ON", "BINDING=LONGEDGE"],
    "short": ["DUPLEX=ON", "BINDING=SHORTEDGE"],
}
# Les noms varient selon les marques ; une commande PJL inconnue est ignorée,
# on peut donc en ajouter ici sans risque (ex. "COLORMODE=MONO" pour certains Kyocera).
PJL_COLOR = {
    "mono":  ["RENDERMODE=GRAYSCALE"],
    "color": ["RENDERMODE=COLOR"],
}


def add_pjl_header(data: bytes, fmt: str, job_name: str, user: str,
                   duplex: str | None = None, color: str = "auto") -> bytes:
    """Encadre les données d'un en-tête PJL portant les options demandées.

    Les données qui ont déjà leur propre en-tête PJL sont laissées intactes
    (le pilote d'origine a fixé ses options, on ne les écrase pas).
    """
    if data.startswith(UEL):
        print("Le fichier contient déjà un en-tête PJL : options --duplex/--color ignorées",
              file=sys.stderr)
        return data
    lang = PJL_LANGUAGE.get(fmt)
    if lang is None:
        raise ConversionError(f"Impossible d'ajouter des options PJL à un fichier de type « {fmt} »")

    def clean(v: str) -> str:   # pas de guillemets ni de sauts de ligne dans une valeur PJL
        return "".join(c for c in v if c.isprintable() and c != '"')[:80]

    sets = [*PJL_DUPLEX.get(duplex, []), *PJL_COLOR.get(color, [])]
    lines = [f'@PJL JOB NAME="{clean(job_name)}"',
             f'@PJL SET USERNAME="{clean(user)}"',
             *(f"@PJL SET {s}" for s in sets),
             f"@PJL ENTER LANGUAGE={lang}"]
    header = UEL + "\r\n".join(lines).encode("ascii", errors="replace") + b"\r\n"
    footer = UEL + b"@PJL EOJ\r\n" + UEL
    return header + data + footer


def parse_queue_listing(text: str) -> list[dict] | None:
    """Transforme la réponse texte du serveur en liste de travaux.

    Chaque travail : {"rank": ..., "owner": ..., "job_id": ..., "name": ..., "size": ...}
    Renvoie None si le format n'est pas reconnu → le script affichera la réponse brute.

    TODO (à vous) : implémenter après avoir vu la réponse réelle de MyQ.
    """
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="Interroge une file LPD (port 515).")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--queue", default=DEFAULT_QUEUE)
    p.add_argument("--long", action="store_true", help="état détaillé (0x04)")
    p.add_argument("--user", action="append", default=None,
                   help=f"filtrer par utilisateur (défaut : {DEFAULT_USER})")
    p.add_argument("--all-users", action="store_true", help="ne pas filtrer par utilisateur")
    p.add_argument("--rfc-port", action="store_true", help="port source 721-731 (root)")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--send-test", action="store_true", help="envoyer une page de test")
    p.add_argument("--send", metavar="FICHIER",
                   help="envoyer un fichier de n'importe quel format (converti si nécessaire)")
    p.add_argument("--format", choices=("auto", *PRINTER_FORMATS), default="auto",
                   help="langage envoyé à l'imprimante (auto : PDF/PS/PCL tels quels, "
                        "le reste converti en PDF)")
    p.add_argument("--raw", action="store_true", help="envoyer le fichier sans aucune conversion")
    p.add_argument("--duplex", choices=tuple(PJL_DUPLEX),
                   help="recto verso : off, long (reliure bord long), short (bord court)")
    p.add_argument("--color", choices=("auto", *PJL_COLOR), default="auto",
                   help="mode couleur demandé à l'imprimante (auto : laisser le défaut)")
    p.add_argument("--job-name", help="nom du travail affiché dans MyQ")
    a = p.parse_args()
    if a.all_users:
        a.user = []
    elif a.user is None:
        a.user = [DEFAULT_USER]

    if a.send or a.send_test:
        owner = a.user[0] if a.user else DEFAULT_USER
        if a.send:
            name = a.job_name or os.path.basename(a.send)
            try:
                if a.raw:
                    with open(a.send, "rb") as f:
                        data = f.read()
                else:
                    data, src, dst = convert_for_printer(a.send, a.format)
                    if src != dst:
                        print(f"Conversion {src} → {dst} ({len(data)} octets)")
            except (OSError, ConversionError, subprocess.TimeoutExpired) as e:
                print(f"Échec de la préparation de « {a.send} » : {e}", file=sys.stderr)
                return 1
        else:
            data, name = make_test_page(owner), a.job_name or "Test LPR"

        if a.duplex or a.color != "auto":
            try:
                data = add_pjl_header(data, detect_format(data, a.send or ""),
                                      name, owner, a.duplex, a.color)
            except ConversionError as e:
                print(f"Échec : {e}", file=sys.stderr)
                return 1
        try:
            df = send_job(a.host, a.port, a.queue, owner, name, data, a.rfc_port, max(a.timeout, 30))
        except (OSError, ConnectionError) as e:
            print(f"Échec de l'envoi : {e}", file=sys.stderr)
            return 1
        print(f"Travail « {name} » envoyé à {a.queue} pour {owner} ({len(data)} octets, {df})")
        return 0

    try:
        text = query_queue(a.host, a.port, a.queue, a.long, a.user, a.rfc_port, a.timeout)
    except (OSError, ConnectionError) as e:
        print(f"Erreur de connexion à {a.host}:{a.port} : {e}", file=sys.stderr)
        return 1

    if not text.strip():
        print("(réponse vide : file vide, ou le serveur ne gère pas la requête d'état)")
        return 0

    jobs = parse_queue_listing(text)
    if jobs is None:
        print(text, end="" if text.endswith("\n") else "\n")
    else:
        for j in jobs:
            print(f"{j.get('rank',''):<6} {j.get('owner',''):<15} "
                  f"{j.get('job_id',''):<8} {j.get('size',''):>10}  {j.get('name','')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
