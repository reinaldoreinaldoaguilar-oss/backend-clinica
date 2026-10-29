import json
import os
import sys
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import JWTManager, create_access_token, jwt_required

print(">> [DIAGNÓSTICO 1] Iniciando servidor Flask...", flush=True)

app = Flask(__name__)
CORS(app)

# ==========================================
# Configuración de Base de Datos y Seguridad
# ==========================================

database_url = os.environ.get('DATABASE_URL')

if not database_url:
    print(">> [DIAGNÓSTICO 2] ADVERTENCIA: No se encontró DATABASE_URL en Render. Usando localhost...", flush=True)
    database_url = 'postgresql+psycopg2://postgres:Argentina*12@localhost:5432/dr_lisandro_db'
else:
    print(">> [DIAGNÓSTICO 2] EXITO: Variable DATABASE_URL detectada en Render.", flush=True)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = 'secreto_medico_super_seguro_2026'

db = SQLAlchemy(app)
jwt = JWTManager(app)

# ==========================================
# 1. MODELOS DE LA BASE DE DATOS
# ==========================================

class Usuario(db.Model):
    __tablename__ = 'usuario'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)

class Paciente(db.Model):
    __tablename__ = 'paciente'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20), nullable=True)
    correo = db.Column(db.String(100), nullable=True)
    citas = db.relationship('Cita', backref='paciente', lazy=True)

class Servicio(db.Model):
    __tablename__ = 'servicio'
    id = db.Column(db.Integer, primary_key=True)
    nombre_servicio = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    citas = db.relationship('Cita', backref='servicio', lazy=True)

class Cita(db.Model):
    __tablename__ = 'cita'
    id = db.Column(db.Integer, primary_key=True)
    fecha_hora = db.Column(db.DateTime, nullable=False)
    estado = db.Column(db.String(20), default='Pendiente')
    paciente_id = db.Column(db.Integer, db.ForeignKey('paciente.id'), nullable=False)
    servicio_id = db.Column(db.Integer, db.ForeignKey('servicio.id'), nullable=False)

# ==========================================
# 2. RUTAS DE LA API (ENDPOINTS)
# ==========================================

@app.route('/', methods=['GET'])
def index():
    return jsonify({"mensaje": "API Segura Dr. Lisandro V2.0 funcionando"})

@app.route('/api/login', methods=['POST'])
def login():
    datos = request.get_json()
    usuario = Usuario.query.filter_by(username=datos.get('username')).first()
    if usuario and check_password_hash(usuario.password, datos.get('password')):
        token_acceso = create_access_token(identity=usuario.username)
        return jsonify({"token": token_acceso, "mensaje": "Login exitoso"}), 200
    return jsonify({"mensaje": "Credenciales incorrectas"}), 401

@app.route('/api/servicios', methods=['GET'])
def obtener_servicios():
    servicios = Servicio.query.all()
    return jsonify([{"id": s.id, "nombre": s.nombre_servicio, "descripcion": s.descripcion} for s in servicios]), 200

@app.route('/api/pacientes', methods=['POST'])
def registrar_paciente():
    datos = request.get_json()
    nuevo_paciente = Paciente(nombre=datos.get('nombre'), telefono=datos.get('telefono'), correo=datos.get('correo'))
    db.session.add(nuevo_paciente)
    db.session.commit()
    return jsonify({"mensaje": "Paciente registrado", "id": nuevo_paciente.id}), 201

# --- DIRECTORIO DE PACIENTES (Protegido con Token) ---
@app.route('/api/pacientes', methods=['GET'])
@jwt_required()
def obtener_pacientes():
    pacientes = Paciente.query.order_by(Paciente.id.asc()).all()
    resultado = [{
        "id": p.id,
        "nombre": p.nombre,
        "telefono": p.telefono or "",
        "correo": p.correo or "",
        "total_citas": len(p.citas),
        "ultima_cita": p.citas[-1].fecha_hora.strftime("%Y-%m-%d %H:%M") if p.citas else None,
        "estado_ultima_cita": p.citas[-1].estado if p.citas else "Sin cita activa"
    } for p in pacientes]
    return jsonify(resultado), 200


@app.route('/api/pacientes/<int:id>', methods=['DELETE'])
@jwt_required()
def eliminar_paciente(id):
    paciente = Paciente.query.get_or_404(id)
    Cita.query.filter_by(paciente_id=paciente.id).delete()
    db.session.delete(paciente)
    db.session.commit()
    return jsonify({"mensaje": f"Paciente #{id} eliminado correctamente"}), 200

@app.route('/api/citas', methods=['POST'])
def agendar_cita():
    datos = request.get_json() or {}
    try:
        fecha_obj = datetime.strptime(datos.get('fecha_hora'), '%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        fecha_obj = datetime.now()

    # Validar paciente existente
    paciente_id = datos.get('paciente_id')
    paciente = Paciente.query.get(paciente_id)
    if not paciente:
        ultimo = Paciente.query.order_by(Paciente.id.desc()).first()
        paciente_id = ultimo.id if ultimo else 1

    # Validar servicio existente para evitar ForeignKeyViolation
    servicio_id = datos.get('servicio_id')
    servicio = Servicio.query.get(servicio_id)
    if not servicio:
        primer_srv = Servicio.query.first()
        servicio_id = primer_srv.id if primer_srv else 1

    nueva_cita = Cita(fecha_hora=fecha_obj, paciente_id=paciente_id, servicio_id=servicio_id)
    db.session.add(nueva_cita)
    db.session.commit()
    return jsonify({"mensaje": "Cita agendada", "id_cita": nueva_cita.id}), 201

@app.route('/api/citas', methods=['GET'])
@jwt_required()
def obtener_citas():
    citas = Cita.query.order_by(Cita.fecha_hora.asc()).all()
    resultado = [{
        "id": c.id,
        "fecha_hora": c.fecha_hora.strftime('%Y-%m-%d %H:%M'),
        "estado": c.estado,
        "paciente": c.paciente.nombre if c.paciente else "Sin nombre",
        "telefono": c.paciente.telefono if c.paciente else "",
        "correo": c.paciente.correo if c.paciente else "",
        "servicio": c.servicio.nombre_servicio if c.servicio else "Consulta General",
        "servicio_id": c.servicio_id
    } for c in citas]
    return jsonify(resultado), 200

@app.route('/api/citas/<int:id>', methods=['PUT'])
@jwt_required()
def actualizar_estado_cita(id):
    cita = Cita.query.get_or_404(id)
    datos = request.get_json() or {}
    if 'estado' in datos:
        cita.estado = datos['estado']
    if 'fecha_hora' in datos:
        try:
            cita.fecha_hora = datetime.strptime(datos['fecha_hora'], '%Y-%m-%d %H:%M')
        except ValueError:
            pass
    db.session.commit()
    return jsonify({"mensaje": f"Cita #{cita.id} actualizada", "id": cita.id, "estado": cita.estado}), 200

@app.route('/api/citas/<int:id>', methods=['DELETE'])
@jwt_required()
def eliminar_cita(id):
    cita = Cita.query.get_or_404(id)
    db.session.delete(cita)
    db.session.commit()
    return jsonify({"mensaje": "Cita eliminada con éxito"}), 200

@app.route('/api/estadisticas', methods=['GET'])
@jwt_required()
def obtener_estadisticas():
    total_citas = Cita.query.count()
    total_pacientes = Paciente.query.count()
    pendientes = Cita.query.filter_by(estado='Pendiente').count()
    confirmadas = Cita.query.filter(Cita.estado.ilike('%confirmad%')).count()
    servicios_count = Servicio.query.count()
    return jsonify({
        "total_citas": total_citas,
        "total_pacientes": total_pacientes,
        "citas_pendientes": pendientes,
        "citas_confirmadas": confirmadas,
        "total_servicios": servicios_count
    }), 200

# ==========================================
# 3. CARGA AUTOMÁTICA AL INICIAR (CON MANEJO DE ERRORES)
# ==========================================
try:
    with app.app_context():
        print(">> [DIAGNÓSTICO 3] Intentando conectar a la base de datos y crear tablas...", flush=True)
        db.create_all()
        print(">> [DIAGNÓSTICO 4] Tablas verificadas correctamente.", flush=True)
        
        if not Usuario.query.filter_by(username='admin').first():
            doctor = Usuario(username='admin', password=generate_password_hash('admin123'))
            db.session.add(doctor)
            print(">> Usuario administrador creado", flush=True)
            
        if os.path.exists('datos_urologia.json'):
            with open('datos_urologia.json', 'r', encoding='utf-8') as archivo:
                servicios_json = json.load(archivo)
                for s in servicios_json:
                    s_id = s.get('id')
                    srv = Servicio.query.get(s_id) if s_id else Servicio.query.filter_by(nombre_servicio=s['nombre_servicio']).first()
                    if not srv:
                        nuevo_srv = Servicio(nombre_servicio=s['nombre_servicio'], descripcion=s['descripcion'])
                        if s_id:
                            nuevo_srv.id = s_id
                        db.session.add(nuevo_srv)
                    else:
                        srv.nombre_servicio = s['nombre_servicio']
                        srv.descripcion = s['descripcion']
            db.session.commit()
            print(">> Catálogo completo de servicios sincronizado", flush=True)
            
        db.session.commit()
        print(">> [DIAGNÓSTICO 5] Todo listo. ¡Aplicación lista para recibir peticiones!", flush=True)

except Exception as e:
    print(f"\n======================================", flush=True)
    print(f"!!! ERROR FATAL AL CONECTAR A LA BD !!!", flush=True)
    print(f"Detalle del error: {e}", flush=True)
    print(f"======================================\n", flush=True)
    sys.exit(1) # Forzamos cierre inmediato con el error impreso

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)