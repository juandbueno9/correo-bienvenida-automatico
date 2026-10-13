"""
Envio de correo de bienvenida via Microsoft Graph (app registrada
'empresa-bienvenida' en Azure AD), usando flujo client credentials
(aplicacion, sin usuario interactivo).

Requiere que la app tenga el permiso de aplicacion "Mail.Send" en
Microsoft Graph, con consentimiento de administrador otorgado, y que
SENDER_EMAIL sea un buzon valido dentro del tenant.
"""

import os
import io
import base64
import requests
import msal
from PIL import Image, ImageDraw, ImageFont

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]

CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}

# Fuentes del sistema a probar, en orden, antes de usar la de respaldo
# (assets/fonts/Fallback-Bold.ttf). En Mac, Futura viene instalada por
# defecto; Century Gothic solo si hay Microsoft Office instalado.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Futura.ttc",
    "/System/Library/Fonts/Supplemental/Futura.ttc",
    "/Library/Fonts/Futura.ttc",
    "/Library/Fonts/Microsoft/Century Gothic.ttf",
    "/Library/Fonts/Century Gothic.ttf",
]

# Posicion del logo dentro de assets/hero.jpg, como fraccion del ancho/alto
# de la imagen (para que siga funcionando si algun dia se recorta de nuevo
# con otro tamano). Calculado sobre el recorte original de la plantilla.
LOGO_LEFT_FRAC = 0.1807
LOGO_RIGHT_FRAC = 0.4413
LOGO_TOP_FRAC = 0.6030


def get_token():
    tenant_id = os.environ["AZURE_TENANT_ID"]
    client_id = os.environ["AZURE_CLIENT_ID"]
    client_secret = os.environ["AZURE_CLIENT_SECRET"]

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id, authority=authority, client_credential=client_secret
    )
    result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)

    if "access_token" not in result:
        raise RuntimeError(
            "No se pudo obtener el token de Microsoft Graph: "
            f"{result.get('error')}: {result.get('error_description')}"
        )
    return result["access_token"]


def _render_template(nombre, template_path):
    with open(template_path, "r", encoding="utf-8") as f:
        html = f.read()
    return html.replace("{{NOMBRE}}", nombre)


def _load_font(size, assets_dir):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    fallback = os.path.join(assets_dir, "fonts", "Fallback-Bold.ttf")
    if os.path.exists(fallback):
        try:
            return ImageFont.truetype(fallback, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _compose_hero_bytes(nombre, assets_dir):
    """
    Dibuja "Bienvenido(a) Asociado(a) <Nombre>" directamente sobre la foto
    de assets/hero.jpg, justo encima del logo de la empresa, y devuelve el
    JPEG resultante en bytes. Se hace en el momento del envio porque el
    nombre cambia por asociado (no se puede "hornear" en un archivo fijo).
    """
    hero_path = os.path.join(assets_dir, "hero.jpg")
    im = Image.open(hero_path).convert("RGB")
    w, h = im.size
    draw = ImageDraw.Draw(im)

    font_size = max(18, round(w / 30))
    font = _load_font(font_size, assets_dir)

    nombre_fmt = (nombre or "").strip().title()
    text = f"Bienvenido(a) Asociado(a) {nombre_fmt}"

    cx = w * (LOGO_LEFT_FRAC + LOGO_RIGHT_FRAC) / 2
    gap = h * 0.04
    logo_top = h * LOGO_TOP_FRAC

    bbox = draw.textbbox((0, 0), text, font=font)
    # Nombres largos: reducir la letra hasta que el saludo quepa en el 92 % del ancho
    while bbox[2] - bbox[0] > w * 0.92 and font_size > 12:
        font_size -= 1
        font = _load_font(font_size, assets_dir)
        bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Centrado sobre el logo, pero sin salirse de la imagen
    tx = min(max(cx - tw / 2, w * 0.04), w * 0.96 - tw) - bbox[0]
    ty = (logo_top - gap) - th - bbox[1]

    stroke_w = max(1, font_size // 28)
    draw.text((tx, ty), text, font=font, fill=(255, 255, 255),
              stroke_width=stroke_w, stroke_fill=(255, 255, 255))

    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _build_inline_attachments(assets_dir, nombre):
    """
    Adjunta como imagen inline (cid) cada archivo de assets/, usando el
    nombre de archivo sin extension como Content-ID. hero.jpg es un caso
    especial: en vez de adjuntarlo tal cual, se genera al vuelo con el
    saludo dibujado encima del logo. Cualquier imagen nueva que se agregue
    a assets/ se adjunta automaticamente (excepto la carpeta fonts/, que
    no son imagenes).
    """
    attachments = []
    if not os.path.isdir(assets_dir):
        return attachments

    for filename in sorted(os.listdir(assets_dir)):
        path = os.path.join(assets_dir, filename)
        if not os.path.isfile(path):
            continue
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        content_type = CONTENT_TYPES.get(ext)
        if not content_type:
            continue

        content_id = filename.rsplit(".", 1)[0]

        if content_id == "hero":
            raw = _compose_hero_bytes(nombre, assets_dir)
        else:
            with open(path, "rb") as f:
                raw = f.read()

        b64 = base64.b64encode(raw).decode("utf-8")
        attachments.append({
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": filename,
            "contentType": content_type,
            "contentBytes": b64,
            "isInline": True,
            "contentId": content_id,
        })
    return attachments


def send_welcome_email(destinatario, nombre, asunto=None,
                        template_path=None, assets_dir=None):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = template_path or os.path.join(base_dir, "plantilla_bienvenida.html")
    assets_dir = assets_dir or os.path.join(base_dir, "assets")

    token = get_token()
    sender = os.environ["SENDER_EMAIL"]
    nombre_fmt = (nombre or "").strip().title()
    asunto = asunto or f"¡Bienvenido(a) a la empresa, {nombre_fmt}!"

    html = _render_template(nombre, template_path)
    attachments = _build_inline_attachments(assets_dir, nombre)

    message = {
        "message": {
            "subject": asunto,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": destinatario}}],
            "attachments": attachments,
        },
        "saveToSentItems": "true",
    }

    url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=message,
        timeout=30,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Error enviando correo ({resp.status_code}): {resp.text}")
    return True
