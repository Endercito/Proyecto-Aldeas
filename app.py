import os
import sqlite3
from pathlib import Path
from functools import wraps

from werkzeug.security import check_password_hash, generate_password_hash

from flask import (
    Flask, render_template, request, jsonify,
    redirect, url_for, session
)

BASE_DIR = Path(__file__).resolve().parent
DB_NAME = os.environ.get("DATABASE_PATH", str(BASE_DIR / "inscripciones.db"))

app = Flask(__name__)
# En producción, configurar SECRET_KEY como variable de entorno en el hosting.
app.secret_key = os.environ.get("SECRET_KEY", "cambiar-esta-clave-en-produccion")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
)


def conectar_db():
    """Abre una conexión a la base de datos ubicada junto a app.py."""
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Crea las tablas necesarias sin borrar los datos que ya existen."""
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    conn = conectar_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS preinscripciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_alumno TEXT NOT NULL,
            nombre_tutor TEXT NOT NULL,
            telefono TEXT NOT NULL,
            email TEXT NOT NULL,
            nivel TEXT NOT NULL,
            fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS niveles_config (
            nivel TEXT PRIMARY KEY,
            cupo_maximo INTEGER NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alumnos_curso (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_alumno TEXT NOT NULL,
            curso TEXT NOT NULL,
            division TEXT NOT NULL,
            turno TEXT NOT NULL,
            inasistencias INTEGER DEFAULT 0,
            tardanzas INTEGER DEFAULT 0,
            justificadas INTEGER DEFAULT 0
        )
    """)

    # Agrega las columnas de asistencia si la base de datos es de una versión anterior.
    for columna in ("inasistencias", "tardanzas", "justificadas"):
        try:
            cursor.execute(
                f"ALTER TABLE alumnos_curso ADD COLUMN {columna} INTEGER DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # La columna ya existe.

    # Mantiene el usuario inicial solo si todavía no hay uno con ese nombre.
    # IMPORTANTE: cambiar estas credenciales desde la base de datos antes de publicar.
    cursor.execute(
        "INSERT OR IGNORE INTO usuarios (username, password) VALUES (?, ?)",
        ("secretaria", "aldeas2026")
    )

    niveles_iniciales = [
        ("Inicial", 30),
        ("Primario", 40),
        ("Secundario", 50),
        ("Talleres Extracurriculares", 25),
    ]
    for nivel, cupo in niveles_iniciales:
        cursor.execute(
            "INSERT OR IGNORE INTO niveles_config (nivel, cupo_maximo) VALUES (?, ?)",
            (nivel, cupo)
        )

    conn.commit()
    conn.close()


def obtener_estado_nivel(nivel):
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT cupo_maximo FROM niveles_config WHERE nivel = ?", (nivel,)
    )
    resultado = cursor.fetchone()

    if resultado is None:
        conn.close()
        return None, None, False

    cupo_maximo = resultado[0]
    cursor.execute(
        "SELECT COUNT(*) FROM preinscripciones WHERE nivel = ?", (nivel,)
    )
    actuales = cursor.fetchone()[0]
    conn.close()
    return actuales, cupo_maximo, actuales >= cupo_maximo


def admin_requerido(funcion):
    @wraps(funcion)
    def decorada(*args, **kwargs):
        if not session.get("admin_logueado"):
            return redirect(url_for("admin"))
        return funcion(*args, **kwargs)
    return decorada


@app.route("/")
def inicio():
    return render_template("index.html")


@app.route("/inscripciones")
def inscripciones():
    """Muestra el formulario público de preinscripción, nunca el panel admin."""
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT n.nivel, n.cupo_maximo, COUNT(p.id)
        FROM niveles_config AS n
        LEFT JOIN preinscripciones AS p ON p.nivel = n.nivel
        GROUP BY n.nivel, n.cupo_maximo
        ORDER BY CASE n.nivel
            WHEN 'Inicial' THEN 1
            WHEN 'Primario' THEN 2
            WHEN 'Secundario' THEN 3
            ELSE 4
        END
    """)
    niveles = cursor.fetchall()
    conn.close()
    return render_template("inscripciones.html", niveles=niveles)


@app.route("/api/estado-cupo/<path:nivel>")
def api_estado_cupo(nivel):
    actuales, maximo, alcanzado = obtener_estado_nivel(nivel)
    if maximo is None:
        return jsonify({"status": "error", "mensaje": "Nivel no encontrado."}), 404

    return jsonify({
        "actuales": actuales,
        "maximo": maximo,
        "cupo_lleno": alcanzado
    })


@app.route("/preinscribir", methods=["POST"])
def preinscribir():
    datos = request.form
    campos = ["nombre_alumno", "nombre_tutor", "telefono", "email", "nivel"]
    valores = {campo: (datos.get(campo) or "").strip() for campo in campos}

    if any(not valores[campo] for campo in campos):
        return jsonify({
            "status": "error",
            "mensaje": "Completá todos los campos del formulario."
        }), 400

    conn = conectar_db()
    cursor = conn.cursor()

    try:
        # La consulta y el alta se realizan en una misma transacción.
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT cupo_maximo FROM niveles_config WHERE nivel = ?",
            (valores["nivel"],)
        )
        fila_nivel = cursor.fetchone()

        if fila_nivel is None:
            conn.rollback()
            return jsonify({
                "status": "error",
                "mensaje": "El nivel seleccionado no es válido."
            }), 400

        cursor.execute(
            "SELECT COUNT(*) FROM preinscripciones WHERE nivel = ?",
            (valores["nivel"],)
        )
        actuales = cursor.fetchone()[0]

        if actuales >= fila_nivel[0]:
            conn.rollback()
            return jsonify({
                "status": "error",
                "mensaje": f"Los cupos para {valores['nivel']} están completos."
            }), 400

        cursor.execute("""
            INSERT INTO preinscripciones
                (nombre_alumno, nombre_tutor, telefono, email, nivel)
            VALUES (?, ?, ?, ?, ?)
        """, (
            valores["nombre_alumno"],
            valores["nombre_tutor"],
            valores["telefono"],
            valores["email"],
            valores["nivel"]
        ))
        conn.commit()

    except sqlite3.Error:
        conn.rollback()
        return jsonify({
            "status": "error",
            "mensaje": "No se pudo guardar la preinscripción. Intentá nuevamente."
        }), 500
    finally:
        conn.close()

    return jsonify({
        "status": "success",
        "mensaje": "Preinscripción recibida correctamente. La institución se pondrá en contacto."
    })


# ---------------- PANEL DE ADMINISTRACIÓN ----------------

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST" and "intentar_login" in request.form:
        usuario = (request.form.get("usuario") or "").strip()
        password = request.form.get("password") or ""

        conn = conectar_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, password FROM usuarios WHERE username = ?",
            (usuario,)
        )
        usuario_encontrado = cursor.fetchone()
        conn.close()

        acceso_correcto = False
        if usuario_encontrado:
            password_guardada = usuario_encontrado[1]
            if password_guardada.startswith(("pbkdf2:", "scrypt:")):
                acceso_correcto = check_password_hash(password_guardada, password)
            else:
                # Compatibilidad con las contraseñas antiguas en texto plano.
                acceso_correcto = password == password_guardada
                if acceso_correcto:
                    conn = conectar_db()
                    conn.execute(
                        "UPDATE usuarios SET password = ? WHERE id = ?",
                        (generate_password_hash(password), usuario_encontrado[0])
                    )
                    conn.commit()
                    conn.close()

        if acceso_correcto:
            session.clear()
            session["admin_logueado"] = True
            session["admin_usuario"] = usuario
            return redirect(url_for("admin"))

        return render_template(
            "admin.html",
            login_requerido=True,
            error="Usuario o contraseña incorrectos."
        )

    if not session.get("admin_logueado"):
        return render_template("admin.html", login_requerido=True)

    conn = conectar_db()
    cursor = conn.cursor()

    if request.method == "POST":
        accion = request.form.get("accion")

        if accion == "actualizar_cupo":
            nivel = (request.form.get("nivel") or "").strip()
            try:
                nuevo_cupo = int(request.form.get("cupo_maximo", ""))
                if nuevo_cupo >= 0:
                    cursor.execute(
                        "UPDATE niveles_config SET cupo_maximo = ? WHERE nivel = ?",
                        (nuevo_cupo, nivel)
                    )
            except ValueError:
                pass
            conn.commit()

        elif accion == "vaciar_todo":
            cursor.execute("DELETE FROM preinscripciones")
            conn.commit()

        elif accion == "vaciar_todo_alumnos":
            cursor.execute("DELETE FROM alumnos_curso")
            conn.commit()

        elif accion == "crear_alumno":
            nombre = (request.form.get("nombre_alumno") or "").strip()
            curso = request.form.get("curso")
            division = request.form.get("division")
            turno = request.form.get("turno")
            if nombre and curso and division in ("A", "B") and turno in ("Mañana", "Tarde"):
                cursor.execute("""
                    INSERT INTO alumnos_curso
                        (nombre_alumno, curso, division, turno)
                    VALUES (?, ?, ?, ?)
                """, (nombre, curso, division, turno))
                conn.commit()

        elif accion in ("sumar_inasistencia", "restar_inasistencia"):
            alumno_id = request.form.get("alumno_id")
            tipo = request.form.get("tipo")
            try:
                cantidad = int(request.form.get("cantidad", "1"))
            except ValueError:
                cantidad = 0

            columnas_permitidas = ("inasistencias", "tardanzas", "justificadas")
            if alumno_id and tipo in columnas_permitidas and 1 <= cantidad <= 10:
                if accion == "sumar_inasistencia":
                    cursor.execute(
                        f"UPDATE alumnos_curso SET {tipo} = {tipo} + ? WHERE id = ?",
                        (cantidad, alumno_id)
                    )
                else:
                    cursor.execute(
                        f"UPDATE alumnos_curso SET {tipo} = MAX(0, {tipo} - ?) WHERE id = ?",
                        (cantidad, alumno_id)
                    )
                conn.commit()

        elif accion == "eliminar_alumno":
            alumno_id = request.form.get("alumno_id")
            if alumno_id:
                cursor.execute("DELETE FROM alumnos_curso WHERE id = ?", (alumno_id,))
                conn.commit()

    cursor.execute("SELECT * FROM niveles_config ORDER BY nivel")
    config_niveles = cursor.fetchall()

    cursor.execute("SELECT * FROM preinscripciones ORDER BY fecha_registro DESC")
    lista = cursor.fetchall()

    cursor.execute("""
        SELECT * FROM alumnos_curso
        ORDER BY curso, division, turno, nombre_alumno
    """)
    lista_alumnos = cursor.fetchall()

    conn.close()
    return render_template(
        "admin.html",
        login_requerido=False,
        config_niveles=config_niveles,
        lista=lista,
        lista_alumnos=lista_alumnos
    )


@app.route("/admin/eliminar/<int:id_inscripcion>", methods=["POST"])
@admin_requerido
def eliminar_inscripcion(id_inscripcion):
    conn = conectar_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM preinscripciones WHERE id = ?", (id_inscripcion,))
    conn.commit()
    conn.close()
    return redirect(url_for("admin"))


@app.route("/admin/logout")
@admin_requerido
def admin_logout():
    session.clear()
    return redirect(url_for("admin"))


# Gunicorn importa app.py sin ejecutar el bloque __main__.
# Por eso la base de datos se inicializa al importar este módulo.
init_db()


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=puerto, debug=False)
