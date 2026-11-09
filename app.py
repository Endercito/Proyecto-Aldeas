import sqlite3
from flask import Flask, render_template, request, jsonify, redirect, url_for

app = Flask(__name__)
DB_NAME = "inscripciones.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Tabla de preinscripciones
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
    
    # Tabla de configuración de cupos por nivel
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS niveles_config (
            nivel TEXT PRIMARY KEY,
            cupo_maximo INTEGER NOT NULL
        )
    ''')
    
    # Insertar cupos por defecto para cada nivel si no existen
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
    """Obtiene los inscriptos actuales y el cupo máximo para un nivel específico."""
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
    # Por defecto cargamos el estado del Nivel Inicial al abrir la página
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

# Panel para Secretarios y Directivos
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if request.method == 'POST':
        nivel_a_modificar = request.form['nivel']
        nuevo_cupo = int(request.form['cupo_maximo'])
        cursor.execute("UPDATE niveles_config SET cupo_maximo = ? WHERE nivel = ?", (nuevo_cupo, nivel_a_modificar))
        conn.commit()
    
    cursor.execute("SELECT * FROM niveles_config")
    config_niveles = cursor.fetchall()
    
    cursor.execute("SELECT * FROM preinscripciones ORDER BY fecha_registro DESC")
    lista = cursor.fetchall()
    
    conn.close()
    return render_template('admin.html', config_niveles=config_niveles, lista=lista)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)