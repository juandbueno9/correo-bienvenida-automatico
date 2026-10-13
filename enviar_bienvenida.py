"""
Script principal: envia el correo de bienvenida a los asociados cuya
fecha de ingreso sea la de AYER (pensado para correr todos los dias a
las 9:00 a.m., vía el LaunchAgent de macOS incluido en este proyecto:
com.empresa.bienvenida.plist).

Uso:
  python enviar_bienvenida.py                     -> envia a los de ayer (uso diario/produccion)
  python enviar_bienvenida.py --fecha 2026-08-28   -> envia a una fecha exacta puntual
  python enviar_bienvenida.py --dias-atras 3       -> "catch-up": envia a ingresos de los ultimos 3 dias
  python enviar_bienvenida.py --listar             -> solo CONSULTA (los de ayer), no envia nada
  python enviar_bienvenida.py --listar --fecha ... -> solo CONSULTA una fecha puntual
  python enviar_bienvenida.py --test correo@...    -> correo de PRUEBA, no toca la base de datos
  python enviar_bienvenida.py --inspeccionar       -> lista las columnas reales de la vista
  python enviar_bienvenida.py --documento 1097405228  -> PRUEBA REAL: busca a ese asociado
                                                          en la base (por NRO_IDENTIFICACION)
                                                          y le envia el correo real a su
                                                          correo y con su primer nombre reales
"""

import argparse
import csv
import datetime
import os

from dotenv import load_dotenv

load_dotenv()

from graph_mailer import send_welcome_email  # noqa: E402

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "enviados.csv")


def ya_enviado(identificador):
    if not os.path.exists(LOG_FILE):
        return False
    with open(LOG_FILE, newline="", encoding="utf-8") as f:
        return any(row and row[0] == identificador for row in csv.reader(f))


def registrar_envio(identificador, nombre, email):
    nuevo = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["cliente_id", "nombre", "email", "fecha_envio"])
        w.writerow([identificador, nombre, email, datetime.datetime.now().isoformat()])


def imprimir_tabla(asociados):
    if not asociados:
        print("No se encontraron asociados con ese criterio.")
        return
    print(f"{'CLIENTE_ID':<12} {'NOMBRE':<25} {'EMAIL':<35} FECHA_INGRESO")
    print("-" * 90)
    for a in asociados:
        print(f"{str(a.get('CLIENTE_ID')):<12} {str(a.get('NOMBRE')):<25} "
              f"{str(a.get('EMAIL')):<35} {a.get('FECHA_INGRESO')}")
    print(f"\nTotal: {len(asociados)}")


def enviar_a_lista(asociados):
    enviados, omitidos, errores = 0, 0, 0
    for a in asociados:
        email = a.get("EMAIL")
        nombre = a.get("NOMBRE")
        cliente_id = a.get("CLIENTE_ID")

        if not email:
            print(f"  (omitido) {nombre} (CLIENTE_ID={cliente_id}): no tiene correo registrado")
            omitidos += 1
            continue

        identificador = str(cliente_id)
        if ya_enviado(identificador):
            omitidos += 1
            continue

        try:
            send_welcome_email(email, nombre)
            registrar_envio(identificador, nombre, email)
            print(f"  OK  -> {nombre} <{email}>")
            enviados += 1
        except Exception as e:
            print(f"  ERROR -> {nombre} <{email}>: {e}")
            errores += 1

    print(f"\nEnviados: {enviados} | Omitidos (sin correo o ya enviados): {omitidos} | Errores: {errores}")


def main():
    parser = argparse.ArgumentParser(description="Envia el correo de bienvenida de la empresa")
    parser.add_argument("--test", metavar="CORREO",
                         help="Envia un correo de PRUEBA a esta direccion con un nombre de ejemplo (no consulta la base de datos)")
    parser.add_argument("--nombre-prueba", default="Maria Fernanda Rodriguez",
                         help="Nombre a usar en el envio de prueba con --test")
    parser.add_argument("--documento", metavar="NRO_IDENTIFICACION",
                         help="PRUEBA REAL: busca a ese asociado en la base por numero de "
                              "documento y le envia el correo a su correo y nombre reales")
    parser.add_argument("--fecha", metavar="YYYY-MM-DD",
                         help="Usa esta fecha de ingreso EXACTA en vez de 'ayer' (para listar o para enviar)")
    parser.add_argument("--dias-atras", type=int, default=None,
                         help="Modo catch-up: en vez de una fecha exacta, toma todos los ingresos desde hace N dias")
    parser.add_argument("--listar", action="store_true",
                         help="Solo CONSULTA y muestra los asociados encontrados, sin enviar ningun correo")
    parser.add_argument("--inspeccionar", action="store_true",
                         help="Solo muestra las columnas reales de VW_CLIENTES y termina")
    args = parser.parse_args()

    if args.inspeccionar:
        from db2_client import inspect_columns
        print("Columnas encontradas en VW_CLIENTES:")
        for c in inspect_columns():
            print(" -", c)
        return

    if args.test:
        print(f"Enviando correo de PRUEBA a {args.test} ...")
        send_welcome_email(args.test, args.nombre_prueba)
        print("Listo. Revisa la bandeja de entrada (y la carpeta de correo no deseado).")
        return

    if args.documento:
        from db2_client import get_associate_by_documento
        print(f"Buscando en la base al asociado con documento {args.documento} ...")
        asociado = get_associate_by_documento(args.documento)
        if not asociado:
            print("No se encontro ningun asociado con ese numero de documento.")
            return
        nombre = asociado.get("NOMBRE")
        email = asociado.get("EMAIL")
        print(f"Encontrado: {nombre} <{email}> (CLIENTE_ID={asociado.get('CLIENTE_ID')}, "
              f"FECHA_INGRESO={asociado.get('FECHA_INGRESO')})")
        if not email:
            print("Este asociado no tiene correo registrado en la base. No se puede enviar.")
            return
        send_welcome_email(email, nombre)
        registrar_envio(str(asociado.get("CLIENTE_ID")), nombre, email)
        print(f"Correo real enviado a {nombre} <{email}>. Revisa esa bandeja de entrada.")
        return

    ayer = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

    if args.listar:
        if args.dias_atras is not None:
            from db2_client import get_new_associates
            desde = (datetime.date.today() - datetime.timedelta(days=args.dias_atras)).isoformat()
            print(f"Asociados con FECHA_INGRESO >= {desde} (y sin retiro):\n")
            imprimir_tabla(get_new_associates(desde))
        else:
            from db2_client import get_associates_by_exact_date
            fecha = args.fecha or ayer
            print(f"Asociados con FECHA_INGRESO = {fecha}:\n")
            imprimir_tabla(get_associates_by_exact_date(fecha))
        return

    # --- Envio real ---
    if args.dias_atras is not None:
        from db2_client import get_new_associates
        desde = (datetime.date.today() - datetime.timedelta(days=args.dias_atras)).isoformat()
        print(f"[catch-up] Buscando asociados con ingreso desde {desde} ...")
        asociados = get_new_associates(desde)
    else:
        from db2_client import get_associates_by_exact_date
        fecha = args.fecha or ayer
        print(f"Buscando asociados con FECHA_INGRESO = {fecha} ...")
        asociados = get_associates_by_exact_date(fecha, excluir_retirados=True)

    print(f"Encontrados {len(asociados)} asociado(s).")
    enviar_a_lista(asociados)


if __name__ == "__main__":
    main()
