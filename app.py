import sqlite3
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import os

app = Flask(__name__)
app.secret_key = 'clave_secreta_super_segura_para_las_sesiones'
DB_NAME = "inscripciones.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Preinscripciones
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS preinscripciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_alumno TEXT NOT NULL,
            nombre_tutor TEXT NOT NULL,
            telefono TEXT NOT NULL,
            email TEXT NOT NULL,
            nivel TEXT NOT NULL,
            fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Configuración de cupos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS niveles_config (
            nivel TEXT PRIMARY KEY,
            cupo_maximo INTEGER NOT NULL
        )
    ''')

    # Usuarios administradores
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    
    # Alumnos con Curso (1° a 5°), División ('A' o 'B') y Turno
    cursor.execute('''
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
    ''')

    # Seguridad para bases de datos anteriores
    for col, tipo in [('inasistencias', 'INTEGER DEFAULT 0'), ('tardanzas', 'INTEGER DEFAULT 0'), ('justificadas', 'INTEGER DEFAULT 0')]:
        try:
            cursor.execute(f"ALTER TABLE alumnos_curso ADD COLUMN {col} {tipo}")
        except sqlite3.OperationalError:
            pass

    cursor.execute("INSERT OR IGNORE INTO usuarios (username, password) VALUES (?, ?)", ("secretaria", "aldeas2026"))
    
    niveles_iniciales = [
        ('Inicial', 30),
        ('Primario', 40),
        ('Secundario', 50),
        ('Talleres Extracurriculares', 25)
    ]
    for nivel, cupo in niveles_iniciales:
        cursor.execute("INSERT OR IGNORE INTO niveles_config (nivel, cupo_maximo) VALUES (?, ?)", (nivel, cupo))
    
    conn.commit()
    conn.close()

def obtener_estado_nivel(nivel):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT cupo_maximo FROM niveles_config WHERE nivel = ?", (nivel,))
    resultado = cursor.fetchone()
    cupo_maximo = resultado[0] if resultado else 50
    
    cursor.execute("SELECT COUNT(*) FROM preinscripciones WHERE nivel = ?", (nivel,))
    actuales = cursor.fetchone()[0]
    conn.close()
    return actuales, cupo_maximo, actuales >= cupo_maximo

@app.route('/')
def inicio():
    return render_template('index.html')

@app.route('/inscripciones')
def inscripciones():
    actuales, maximo, alcanzado = obtener_estado_nivel('Inicial')
    return render_template('inscripciones.html', actuales=actuales, maximo=maximo, alcanzado=alcanzado)

@app.route('/api/estado-cupo/<path:nivel>')
def api_estado_cupo(nivel):
    actuales, maximo, alcanzado = obtener_estado_nivel(nivel)
    return jsonify({
        'actuales': actuales,
        'maximo': maximo,
        'cupo_lleno': alcanzado
    })

@app.route('/preinscribir', methods=['POST'])
def preinscribir():
    datos = request.form
    nivel_elegido = datos['nivel']
    actuales, maximo, alcanzado = obtener_estado_nivel(nivel_elegido)
    
    if alcanzado:
        return jsonify({'status': 'error', 'mensaje': f'Cupos agotados para {nivel_elegido}.'}), 400

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO preinscripciones (nombre_alumno, nombre_tutor, telefono, email, nivel)
        VALUES (?, ?, ?, ?, ?)
    ''', (datos['nombre_alumno'], datos['nombre_tutor'], datos['telefono'], datos['email'], nivel_elegido))
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'success', 'mensaje': 'Preinscripción completada con éxito.'})

# --- PANEL DE ADMINISTRACIÓN ---
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST' and 'intentar_login' in request.form:
        usuario = request.form.get('usuario')
        password = request.form.get('password')
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE username = ? AND password = ?", (usuario, password))
        user_row = cursor.fetchone()
        conn.close()
        
        if user_row:
            session['admin_logueado'] = True
            return redirect(url_for('admin'))
        else:
            return render_template('admin.html', login_requerido=True, error="Usuario o contraseña incorrectos.")

    if not session.get('admin_logueado'):
        return render_template('admin.html', login_requerido=True)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    if request.method == 'POST':
        accion = request.form.get('accion')
        
        if accion == 'actualizar_cupo':
            nivel_a_modificar = request.form['nivel']
            nuevo_cupo = int(request.form['cupo_maximo'])
            cursor.execute("UPDATE niveles_config SET cupo_maximo = ? WHERE nivel = ?", (nuevo_cupo, nivel_a_modificar))
            conn.commit()
            
        elif accion == 'vaciar_todo':
            cursor.execute("DELETE FROM preinscripciones")
            conn.commit()

        elif accion == 'vaciar_todo_alumnos':
            cursor.execute("DELETE FROM alumnos_curso")
            conn.commit()

        elif accion == 'crear_alumno':
            nombre = request.form.get('nombre_alumno')
            curso = request.form.get('curso')
            division = request.form.get('division')
            turno = request.form.get('turno')
            if nombre and curso and division and turno:
                cursor.execute("INSERT INTO alumnos_curso (nombre_alumno, curso, division, turno) VALUES (?, ?, ?, ?)", 
                               (nombre, curso, division, turno))
                conn.commit()

        elif accion == 'sumar_inasistencia':
            alumno_id = request.form.get('alumno_id')
            tipo = request.form.get('tipo') 
            cantidad = int(request.form.get('cantidad', 1))
            if alumno_id and tipo in ['inasistencias', 'tardanzas', 'justificadas']:
                cursor.execute(f"UPDATE alumnos_curso SET {tipo} = {tipo} + ? WHERE id = ?", (cantidad, alumno_id))
                conn.commit()

        elif accion == 'restar_inasistencia':
            alumno_id = request.form.get('alumno_id')
            tipo = request.form.get('tipo')
            cantidad = int(request.form.get('cantidad', 1))
            if alumno_id and tipo in ['inasistencias', 'tardanzas', 'justificadas']:
                # Evitar que baje de 0
                cursor.execute(f"UPDATE alumnos_curso SET {tipo} = MAX(0, {tipo} - ?) WHERE id = ?", (cantidad, alumno_id))
                conn.commit()

        elif accion == 'eliminar_alumno':
            alumno_id = request.form.get('alumno_id')
            if alumno_id:
                cursor.execute("DELETE FROM alumnos_curso WHERE id = ?", (alumno_id,))
                conn.commit()

    cursor.execute("SELECT * FROM niveles_config")
    config_niveles = cursor.fetchall()
    
    cursor.execute("SELECT * FROM preinscripciones ORDER BY fecha_registro DESC")
    lista = cursor.fetchall()

    cursor.execute("SELECT * FROM alumnos_curso ORDER BY curso, division, turno")
    lista_alumnos = cursor.fetchall()

    conn.close()
    return render_template('admin.html', login_requerido=False, config_niveles=config_niveles, lista=lista, lista_alumnos=lista_alumnos)

@app.route('/admin/eliminar/<int:id_inscripcion>', methods=['POST'])
def eliminar_inscripcion(id_inscripcion):
    if not session.get('admin_logueado'):
        return redirect(url_for('admin'))
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM preinscripciones WHERE id = ?", (id_inscripcion,))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logueado', None)
    return redirect(url_for('admin'))

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)