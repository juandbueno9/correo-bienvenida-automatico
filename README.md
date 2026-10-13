# Correo de bienvenida automático

Detecta los clientes nuevos registrados en la base de datos del core (IBM Db2) y les envía un correo de bienvenida personalizado por **Microsoft Graph**. Se ejecuta una vez al día con `launchd` (macOS) o `cron` (Linux).

![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![IBM Db2](https://img.shields.io/badge/IBM_Db2-052FAD?logo=ibm&logoColor=white)
![Microsoft Graph](https://img.shields.io/badge/Microsoft_Graph-0078D4?logo=microsoft&logoColor=white)

## Cómo funciona

```
launchd / cron (9:00 a. m.)
   └─ enviar_bienvenida.py
        ├─ db2_client.py   ──► consulta de SOLO LECTURA: ingresos de ayer, sin fecha de retiro
        ├─ graph_mailer.py ──► token OAuth2 (client credentials) + sendMail
        │                      dibuja el nombre sobre la imagen de encabezado (Pillow)
        └─ enviados.csv    ──► registro para no enviar dos veces al mismo cliente
```

## Instalación

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # credenciales de Entra ID y Db2
```

Las imágenes del correo van en `assets/` (ver [assets/LEEME.md](assets/LEEME.md)).

## Uso

| Comando | Qué hace |
|---|---|
| `python enviar_bienvenida.py --test correo@ejemplo.com` | Envía un correo de prueba sin tocar la base de datos |
| `python enviar_bienvenida.py --listar` | Muestra los clientes que recibirían el correo, sin enviar |
| `python enviar_bienvenida.py --fecha 2026-09-01` | Procesa una fecha de ingreso específica |
| `python enviar_bienvenida.py --dias-atras 7` | Recupera los ingresos de los últimos N días |
| `python enviar_bienvenida.py --inspeccionar` | Muestra las columnas de la vista |
| `python enviar_bienvenida.py` | Ejecución normal (ingresos de ayer) |

## Programarlo

- **macOS**: ajusta las rutas en `com.empresa.bienvenida.plist`, cópialo a `~/Library/LaunchAgents/` y ejecuta `launchctl load`.
- **Linux**: `0 9 * * * cd /ruta/al/proyecto && venv/bin/python enviar_bienvenida.py`

## Seguridad
- Usuario de base de datos de solo lectura.
- Permiso `Mail.Send` de aplicación restringido a un único buzón.
- `.env` y el registro de envíos fuera de git.
