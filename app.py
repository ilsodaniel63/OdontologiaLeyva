import mimetypes
mimetypes.add_type('application/wasm', '.wasm')

from flask import Flask, render_template, request, redirect, url_for, flash, Response, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from functools import wraps
import sqlite3
import os
import csv
import io
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "cambia_esto_por_algo_seguro")

# ──────────── CONFIGURACIÓN DE EMAIL ────────────
# Para Gmail, necesitas una "Contraseña de aplicación".
# Configúrala en .env para no exponerla en el código [citation:1][citation:6].
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_DEBUG'] = True

mail = Mail(app)

# ──────────── CONFIGURACIÓN DE LOGIN ────────────
login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# ──────────── MODELO DE USUARIO (Simplificado) ────────────
# Usamos una sola cuenta de administrador definida en .env.
# Para múltiples usuarios, se necesitaría una tabla de usuarios en la BD [citation:2][citation:7].
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    # Solo permitimos un ID de admin
    if user_id == "1":
        return User("1", os.getenv("ADMIN_USERNAME", "admin"))
    return None

# ──────────── DECORADOR DE ADMIN ────────────
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Necesitas iniciar sesión para acceder.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

DB = "clinica.db"

# ──────────── BASE DE DATOS ────────────
def init_db():
    with sqlite3.connect(DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS solicitudes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                telefono TEXT NOT NULL,
                email TEXT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Añadir columnas nuevas si no existen (migración)
        columnas = [row[1] for row in con.execute("PRAGMA table_info(solicitudes)").fetchall()]
        
        if "estado" not in columnas:
            con.execute("ALTER TABLE solicitudes ADD COLUMN estado TEXT DEFAULT 'Pendiente'")
            print("✅ Columna 'estado' añadida.")
        
        if "observaciones" not in columnas:
            con.execute("ALTER TABLE solicitudes ADD COLUMN observaciones TEXT DEFAULT ''")
            print("✅ Columna 'observaciones' añadida.")

# ──────────── RUTAS PÚBLICAS ────────────
@app.route("/")
def inicio():
    return render_template("index.html")

@app.route("/contacto", methods=["POST"])
def contacto():
    nombre = request.form.get("nombre")
    telefono = request.form.get("telefono")
    email = request.form.get("email")

    # Guardar en BD
    with sqlite3.connect(DB) as con:
        con.execute(
            "INSERT INTO solicitudes (nombre, telefono, email) VALUES (?, ?, ?)",
            (nombre, telefono, email)
        )

    # ──────────── ENVIAR EMAIL ────────────
    # Se envía una notificación. Si falla, no rompemos la app [citation:1].
    try:
        msg = Message(
            subject=f"Nueva Solicitud de Cita - {nombre}",
            recipients=[os.getenv('MAIL_USERNAME')]  # Te llega a ti mismo
        )
        msg.html = f"""
        <h3>Nueva solicitud desde la web</h3>
        <p><strong>Nombre:</strong> {nombre}</p>
        <p><strong>Teléfono:</strong> {telefono}</p>
        <p><strong>Email:</strong> {email or 'No proporcionado'}</p>
        """
        mail.send(msg)
        print("Email enviado correctamente.")
    except Exception as e:
        print(f"Error al enviar email: {e}")

    return render_template("gracias.html", nombre=nombre)

# ──────────── RUTAS DE LOGIN ────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        if username == os.getenv("ADMIN_USERNAME", "admin") and password == os.getenv("ADMIN_PASSWORD", "admin123"):
            user = User("1", username)
            login_user(user)
            return redirect(url_for('admin'))
        else:
            flash("Usuario o contraseña incorrectos.", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Has cerrado sesión.", "success")
    return redirect(url_for('login'))

# ──────────── RUTAS DE ADMIN (PROTEGIDAS) ────────────
@app.route("/admin")
@admin_required
def admin():
    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        filas = con.execute("SELECT * FROM solicitudes ORDER BY fecha DESC").fetchall()
    return render_template("admin.html", solicitudes=filas)

# ──────────── EXPORTAR A CSV ────────────
@app.route("/admin/export")
@admin_required
def export_csv():
    with sqlite3.connect(DB) as con:
        con.row_factory = sqlite3.Row
        filas = con.execute("SELECT * FROM solicitudes ORDER BY fecha DESC").fetchall()

    # Crear el CSV en memoria
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'Nombre', 'Teléfono', 'Email', 'Fecha', 'Estado', 'Observaciones'])
    for f in filas:
        cw.writerow([f['id'], f['nombre'], f['telefono'], f['email'], f['fecha'], f['estado'], f['observaciones']])
    
    output = si.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=solicitudes.csv"}
    )
    
@app.route("/admin/editar/<int:id>", methods=["POST"])
@admin_required
def editar_solicitud(id):
    estado = request.form.get("estado")
    observaciones = request.form.get("observaciones")
    
    with sqlite3.connect(DB) as con:
        con.execute(
            "UPDATE solicitudes SET estado = ?, observaciones = ? WHERE id = ?",
            (estado, observaciones, id)
        )
    
    flash(f"Solicitud #{id} actualizada correctamente.", "success")
    return redirect(url_for('admin'))


@app.route("/admin/borrar/<int:id>", methods=["POST"])
@admin_required
def borrar_solicitud(id):
    with sqlite3.connect(DB) as con:
        con.execute("DELETE FROM solicitudes WHERE id = ?", (id,))
    
    flash(f"Solicitud #{id} eliminada.", "success")
    return redirect(url_for('admin'))    

if __name__ == "__main__":
    init_db()
    #app.run(debug=True)
    app.run(host="0.0.0.0", port=5000, debug=True)