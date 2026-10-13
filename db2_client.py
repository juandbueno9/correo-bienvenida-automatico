"""
Cliente de solo lectura para la base de datos DB2 de la empresa (COREDB).

Columnas confirmadas en VW_CLIENTES (segun SYSCAT.COLUMNS):
  - CLIENTE_ID       DECIMAL   -> identificador unico del asociado
  - PRIMER_NOMBRE    VARCHAR   -> nombre para el saludo del correo (solo el nombre, no el apellido)
  - EMAIL            VARCHAR   -> correo del asociado
  - FECHA_INGRESO    DATE      -> fecha de ingreso como asociado
  - FECHA_RETIRO     DATE      -> si no es nula, el asociado ya se retiro
  - NRO_IDENTIFICACION VARCHAR -> numero de documento del asociado

NOTA: el usuario 'readonly' se conecta con CURRENT SCHEMA = READONLY por
defecto, pero la vista VIVE en otro esquema (no en READONLY). Por eso
_resolve_qualified_view() busca automaticamente en SYSCAT.TABLES en que
esquema esta la vista, y arma el nombre completo ESQUEMA.VISTA antes de
consultarla. Asi no hace falta que sepamos el esquema de antemano.
"""

import os
import ibm_db

VIEW = "VW_CLIENTES"

COL_CLIENTE_ID = "CLIENTE_ID"
COL_NOMBRE = "PRIMER_NOMBRE"
COL_EMAIL = "EMAIL"
COL_FECHA_INGRESO = "FECHA_INGRESO"
COL_FECHA_RETIRO = "FECHA_RETIRO"
COL_DOCUMENTO = "NRO_IDENTIFICACION"

_qualified_view_cache = {}


def get_connection():
    host = os.environ["DB2_HOST"]
    port = os.environ["DB2_PORT"]
    database = os.environ["DB2_DATABASE"]
    user = os.environ["DB2_USER"]
    password = os.environ["DB2_PASSWORD"]

    conn_str = (
        f"DATABASE={database};HOSTNAME={host};PORT={port};"
        f"PROTOCOL=TCPIP;UID={user};PWD={password};"
    )
    return ibm_db.connect(conn_str, "", "")


def _resolve_qualified_view(conn, view=VIEW):
    """
    Devuelve 'ESQUEMA.VISTA' buscando el esquema real en SYSCAT.TABLES
    (SYSCAT.TABLES incluye vistas ademas de tablas en DB2). Si `view` ya
    viene con un punto (ya calificada a mano), se usa tal cual.
    """
    if "." in view:
        return view
    if view in _qualified_view_cache:
        return _qualified_view_cache[view]

    sql = "SELECT TABSCHEMA FROM SYSCAT.TABLES WHERE TABNAME = ? FETCH FIRST 1 ROWS ONLY"
    stmt = ibm_db.prepare(conn, sql)
    ibm_db.execute(stmt, (view.upper(),))
    row = ibm_db.fetch_assoc(stmt)
    if not row:
        raise RuntimeError(
            f"No se encontro la vista '{view}' en SYSCAT.TABLES (revisa el nombre, "
            f"o que el usuario 'readonly' tenga permiso para verla)."
        )
    schema = row["TABSCHEMA"].strip()
    qualified = f"{schema}.{view}"
    _qualified_view_cache[view] = qualified
    return qualified


def inspect_columns(view=VIEW):
    """Devuelve la lista de columnas reales de la vista (para verificar el mapeo)."""
    conn = get_connection()
    try:
        qualified = _resolve_qualified_view(conn, view)
        stmt = ibm_db.exec_immediate(conn, f"SELECT * FROM {qualified} FETCH FIRST 1 ROWS ONLY")
        ncols = ibm_db.num_fields(stmt)
        return [ibm_db.field_name(stmt, i) for i in range(ncols)]
    finally:
        ibm_db.close(conn)


def _fetch_all(conn, sql, params):
    stmt = ibm_db.prepare(conn, sql)
    ibm_db.execute(stmt, params)
    rows = []
    row = ibm_db.fetch_assoc(stmt)
    while row:
        rows.append(row)
        row = ibm_db.fetch_assoc(stmt)
    return rows


def get_new_associates(desde_fecha, view=VIEW,
                        col_id=COL_CLIENTE_ID, col_nombre=COL_NOMBRE,
                        col_email=COL_EMAIL, col_fecha_ingreso=COL_FECHA_INGRESO,
                        col_fecha_retiro=COL_FECHA_RETIRO):
    """
    Trae asociados cuya fecha de ingreso sea >= desde_fecha (string 'YYYY-MM-DD'),
    excluyendo a quienes ya tengan fecha de retiro registrada. Sirve para un
    "catch-up" de varios dias (ver --dias-atras en enviar_bienvenida.py).
    Solo lectura: usa el usuario 'readonly'.
    """
    conn = get_connection()
    try:
        qualified = _resolve_qualified_view(conn, view)
        sql = (
            f"SELECT {col_id} AS CLIENTE_ID, {col_nombre} AS NOMBRE, "
            f"{col_email} AS EMAIL, {col_fecha_ingreso} AS FECHA_INGRESO "
            f"FROM {qualified} "
            f"WHERE {col_fecha_ingreso} >= ? "
            f"AND {col_fecha_retiro} IS NULL"
        )
        return _fetch_all(conn, sql, (desde_fecha,))
    finally:
        ibm_db.close(conn)


def get_associates_by_exact_date(fecha, view=VIEW,
                                  col_id=COL_CLIENTE_ID, col_nombre=COL_NOMBRE,
                                  col_email=COL_EMAIL, col_fecha_ingreso=COL_FECHA_INGRESO,
                                  col_fecha_retiro=COL_FECHA_RETIRO,
                                  excluir_retirados=False):
    """
    Trae los asociados cuya fecha de ingreso sea EXACTAMENTE `fecha`
    (string 'YYYY-MM-DD'). Esta es la consulta que usa el envio diario:
    "los que tengan fecha de ingreso de ayer".

    excluir_retirados=True agrega "AND FECHA_RETIRO IS NULL" (se usa al
    enviar el correo real, para no saludar a alguien que ya se retiro el
    mismo dia). Para solo listar/consultar se deja en False por defecto,
    asi se ve la foto completa.
    Solo lectura: usa el usuario 'readonly'.
    """
    conn = get_connection()
    try:
        qualified = _resolve_qualified_view(conn, view)
        sql = (
            f"SELECT {col_id} AS CLIENTE_ID, {col_nombre} AS NOMBRE, "
            f"{col_email} AS EMAIL, {col_fecha_ingreso} AS FECHA_INGRESO "
            f"FROM {qualified} "
            f"WHERE {col_fecha_ingreso} = ? "
        )
        if excluir_retirados:
            sql += f"AND {col_fecha_retiro} IS NULL "
        sql += f"ORDER BY {col_nombre}"
        return _fetch_all(conn, sql, (fecha,))
    finally:
        ibm_db.close(conn)


def get_associate_by_documento(numero_documento, view=VIEW,
                                col_id=COL_CLIENTE_ID, col_nombre=COL_NOMBRE,
                                col_email=COL_EMAIL, col_fecha_ingreso=COL_FECHA_INGRESO,
                                col_documento=COL_DOCUMENTO):
    """
    Busca UN asociado por su numero de identificacion (NRO_IDENTIFICACION).
    Util para probar el envio real (plantilla + datos reales de la base)
    con una sola persona conocida, en vez de datos ficticios.
    Devuelve None si no lo encuentra. Solo lectura: usa el usuario 'readonly'.
    """
    conn = get_connection()
    try:
        qualified = _resolve_qualified_view(conn, view)
        sql = (
            f"SELECT {col_id} AS CLIENTE_ID, {col_nombre} AS NOMBRE, "
            f"{col_email} AS EMAIL, {col_fecha_ingreso} AS FECHA_INGRESO "
            f"FROM {qualified} "
            f"WHERE {col_documento} = ? "
            f"FETCH FIRST 1 ROWS ONLY"
        )
        rows = _fetch_all(conn, sql, (str(numero_documento),))
        return rows[0] if rows else None
    finally:
        ibm_db.close(conn)
