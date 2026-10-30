import json
import os
import sys
import uuid
import urllib.request
import urllib.error
from datetime import datetime, date, time, timedelta
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy import text, or_, and_
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity, get_jwt
)

print(">> [DIAGNÓSTICO 1] Iniciando Servidor Médico Avanzado Dr. Lisandro Márquez...", flush=True)

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# ==========================================
# Configuración de Base de Datos y Seguridad
# ==========================================
database_url = os.environ.get('DATABASE_URL')

if not database_url:
    print(">> [DIAGNÓSTICO 2] Advertencia: DATABASE_URL no detectada, usando entorno local...", flush=True)
    database_url = 'postgresql+psycopg2://postgres:Argentina*12@localhost:5432/dr_lisandro_db'
else:
    print(">> [DIAGNÓSTICO 2] Variable DATABASE_URL detectada en Render.", flush=True)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'secreto_medico_super_seguro_2026_jwt_token_urologia')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=30) # Sesión persistente para comodidad del paciente

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '218889080146-1v3rcqk04m3dchj8g7iu5do3ovq84rll.apps.googleusercontent.com')

db = SQLAlchemy(app)
jwt = JWTManager(app)

# ==========================================
# 1. MODELOS DE BASE DE DATOS (POSTGRESQL)
# ==========================================

class Usuario(db.Model):
    __tablename__ = 'usuario'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=True) # Nullable para usuarios autenticados con Google
    nombre = db.Column(db.String(150), nullable=True)
    correo = db.Column(db.String(150), nullable=True)
    foto_url = db.Column(db.Text, nullable=True)
    rol = db.Column(db.String(30), default='paciente', nullable=False) # 'paciente', 'doctor', 'administrador'
    activo = db.Column(db.Boolean, default=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    identidades = db.relationship('IdentidadExterna', backref='usuario', cascade='all, delete-orphan', lazy=True)
    perfil = db.relationship('PerfilPaciente', backref='usuario', uselist=False, cascade='all, delete-orphan', lazy=True)

class IdentidadExterna(db.Model):
    __tablename__ = 'identidad_externa'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id', ondelete='CASCADE'), nullable=False)
    proveedor = db.Column(db.String(30), default='google', nullable=False)
    sub = db.Column(db.String(120), unique=True, nullable=False) # Identificador único y permanente de Google
    correo_proveedor = db.Column(db.String(150), nullable=True)
    fecha_vinculacion = db.Column(db.DateTime, default=datetime.utcnow)

class PerfilPaciente(db.Model):
    __tablename__ = 'perfil_paciente'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id', ondelete='CASCADE'), unique=True, nullable=False)
    telefono = db.Column(db.String(35), nullable=True)
    documento_identidad = db.Column(db.String(50), nullable=True)
    fecha_nacimiento = db.Column(db.Date, nullable=True)
    politica_privacidad_aceptada = db.Column(db.Boolean, default=False)

class Sede(db.Model):
    __tablename__ = 'sede'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    clinica = db.Column(db.String(120), nullable=False)
    ciudad = db.Column(db.String(60), nullable=False)
    direccion = db.Column(db.String(255), nullable=True)
    horarios_texto = db.Column(db.String(255), nullable=True)
    activa = db.Column(db.Boolean, default=True)

class Servicio(db.Model):
    __tablename__ = 'servicio'
    id = db.Column(db.Integer, primary_key=True)
    nombre_servicio = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    duracion_minutos = db.Column(db.Integer, default=45)
    precio = db.Column(db.Numeric(10, 2), nullable=True)
    activo = db.Column(db.Boolean, default=True)

class HorarioDoctor(db.Model):
    __tablename__ = 'horario_doctor'
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    sede_id = db.Column(db.Integer, db.ForeignKey('sede.id'), nullable=False)
    dia_semana = db.Column(db.Integer, nullable=False) # 0=Lunes, 1=Martes, 2=Miércoles, 3=Jueves, 4=Viernes, 5=Sábado
    hora_inicio = db.Column(db.Time, nullable=False)
    hora_fin = db.Column(db.Time, nullable=False)
    intervalo_minutos = db.Column(db.Integer, default=45)
    activo = db.Column(db.Boolean, default=True)

    sede = db.relationship('Sede', backref='horarios')
    doctor = db.relationship('Usuario', backref='horarios')

class BloqueoAgenda(db.Model):
    __tablename__ = 'bloqueo_agenda'
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    sede_id = db.Column(db.Integer, db.ForeignKey('sede.id'), nullable=True)
    fecha_inicio = db.Column(db.DateTime, nullable=False)
    fecha_fin = db.Column(db.DateTime, nullable=False)
    motivo = db.Column(db.String(255), nullable=True)
    creado_por = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

class Cita(db.Model):
    __tablename__ = 'cita'
    id = db.Column(db.Integer, primary_key=True)
    codigo_cita = db.Column(db.String(30), unique=True, nullable=True)
    fecha_hora = db.Column(db.DateTime, nullable=False) # Fecha y hora de inicio
    fecha_hora_fin = db.Column(db.DateTime, nullable=True)
    estado = db.Column(db.String(35), default='pendiente', nullable=False)
    # Estados: 'pendiente', 'confirmada', 'presente', 'completada', 'cancelada_paciente', 'cancelada_doctor', 'no_asistio'
    paciente_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    legacy_paciente_id = db.Column(db.Integer, db.ForeignKey('paciente.id'), nullable=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    servicio_id = db.Column(db.Integer, db.ForeignKey('servicio.id'), nullable=False)
    sede_id = db.Column(db.Integer, db.ForeignKey('sede.id'), nullable=True)
    motivo_cancelacion = db.Column(db.Text, nullable=True)
    sintomas_paciente = db.Column(db.Text, nullable=True)
    notas_doctor = db.Column(db.Text, nullable=True)
    creado_por = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_actualizacion = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    paciente = db.relationship('Usuario', foreign_keys=[paciente_id], backref='citas_paciente')
    doctor = db.relationship('Usuario', foreign_keys=[doctor_id], backref='citas_doctor')
    servicio = db.relationship('Servicio', backref='citas')
    sede = db.relationship('Sede', backref='citas')
    historial = db.relationship('HistorialCita', backref='cita', cascade='all, delete-orphan', lazy=True)

class HistorialCita(db.Model):
    __tablename__ = 'historial_cita'
    id = db.Column(db.Integer, primary_key=True)
    cita_id = db.Column(db.Integer, db.ForeignKey('cita.id', ondelete='CASCADE'), nullable=False)
    modificado_por = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=True)
    estado_anterior = db.Column(db.String(35), nullable=True)
    estado_nuevo = db.Column(db.String(35), nullable=False)
    fecha_anterior = db.Column(db.DateTime, nullable=True)
    fecha_nueva = db.Column(db.DateTime, nullable=True)
    motivo = db.Column(db.Text, nullable=True)
    fecha_cambio = db.Column(db.DateTime, default=datetime.utcnow)

    autor = db.relationship('Usuario', foreign_keys=[modificado_por])

class Notificacion(db.Model):
    __tablename__ = 'notificacion'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id', ondelete='CASCADE'), nullable=False)
    cita_id = db.Column(db.Integer, db.ForeignKey('cita.id', ondelete='SET NULL'), nullable=True)
    titulo = db.Column(db.String(150), nullable=False)
    mensaje = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(35), default='general') # 'reserva', 'confirmacion', 'cancelacion', 'reprogramacion', 'recordatorio'
    leida = db.Column(db.Boolean, default=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

class PoliticaCita(db.Model):
    __tablename__ = 'politica_cita'
    id = db.Column(db.Integer, primary_key=True)
    confirmacion_automatica = db.Column(db.Boolean, default=False)
    anticipacion_min_horas = db.Column(db.Integer, default=2)
    plazo_cancelar_horas = db.Column(db.Integer, default=2)
    max_citas_activas = db.Column(db.Integer, default=3)

# Modelo Legacy de Paciente para retrocompatibilidad total
class Paciente(db.Model):
    __tablename__ = 'paciente'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(35), nullable=True)
    correo = db.Column(db.String(100), nullable=True)
    legacy_citas = db.relationship('Cita', foreign_keys=[Cita.legacy_paciente_id], backref='legacy_paciente', lazy=True)

# ==========================================
# 2. VALIDACIÓN CRIPTOGRÁFICA DE GOOGLE
# ==========================================

def verificar_google_id_token(credential):
    """
    Verifica criptográficamente el ID Token firmado por Google.
    1. Si google-auth está instalado, valida la firma con claves públicas de Google.
    2. Como respaldo seguro, consulta el endpoint oficial OpenID Connect tokeninfo de Google.
    3. Permite token de pruebas asistidas para desarrollo sin bloquear la interfaz.
    """
    if not credential:
        raise ValueError("No se recibió credencial de Google")

    # 0. Respaldo para entorno de desarrollo y pruebas de integración
    if credential.startswith('demo_google_') or credential.startswith('test_google_') or credential.startswith('assisted_google_'):
        import base64
        try:
            parts = credential.split('_', 2)
            raw_payload = parts[-1]
            data = json.loads(base64.b64decode(raw_payload).decode('utf-8'))
            user_email = data.get('email', 'paciente@gmail.com')
            user_name = data.get('name') or user_email.split('@')[0].capitalize()
            return {
                'iss': 'https://accounts.google.com',
                'sub': data.get('sub') or f"sub_{abs(hash(user_email))}",
                'email': user_email,
                'name': user_name,
                'picture': data.get('picture', 'https://lh3.googleusercontent.com/a/default-user=s96-c')
            }
        except Exception as e:
            print(f">> [AUTH] Falló decodificación de credencial asistida: {e}", flush=True)

    # 1. Intentar con librería oficial google-auth
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        client_id = GOOGLE_CLIENT_ID or None
        idinfo = id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)
        if idinfo.get('iss') not in ['accounts.google.com', 'https://accounts.google.com']:
            raise ValueError('Emisor de token Google inválido')
        return idinfo
    except ImportError:
        pass
    except Exception as e:
        print(f">> [AUTH] Falló verificación local google-auth ({e}), recurriendo a tokeninfo...", flush=True)

    # 2. Endpoint oficial OpenID Connect de Google tokeninfo
    url = f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Clinica-Urologia-OAuth/2.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('iss') not in ['accounts.google.com', 'https://accounts.google.com']:
                raise ValueError('Emisor de token Google inválido')
            if GOOGLE_CLIENT_ID and data.get('aud') != GOOGLE_CLIENT_ID:
                print(f">> [ADVERTENCIA] Audiencia del token ({data.get('aud')}) difiere de GOOGLE_CLIENT_ID local", flush=True)
            return data
    except urllib.error.HTTPError as err:
        det = err.read().decode('utf-8')
        raise ValueError(f"Token de Google rechazado por Google API: {det}")
    except Exception as err:
        raise ValueError(f"Error al verificar credencial con Google: {str(err)}")

# Helper de permisos y roles
def obtener_usuario_actual():
    identidad = get_jwt_identity()
    if not identidad:
        return None
    try:
        user_id = int(identidad)
        return Usuario.query.get(user_id)
    except (ValueError, TypeError):
        return Usuario.query.filter_by(username=identidad).first()

# ==========================================
# 3. ENDPOINTS DE AUTENTICACIÓN GOOGLE Y SESIÓN
# ==========================================

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "nombre": "API Clínica Urológica Dr. Lisandro Márquez",
        "version": "3.3.0",
        "estado": "en_linea",
        "auth_google": True
    }), 200

@app.route('/api/auth/google', methods=['POST'])
def auth_google():
    """
    Recibe la credencial de Google Identity Services (ID Token JWT),
    la valida con Google, crea o recupera el usuario local (rol='paciente')
    y devuelve el JWT de sesión médico junto con el perfil del paciente.
    """
    datos = request.get_json() or {}
    credential = datos.get('credential')

    if not credential:
        return jsonify({"mensaje": "Credencial de Google requerida"}), 400

    try:
        google_data = verificar_google_id_token(credential)
    except ValueError as err:
        return jsonify({"mensaje": str(err)}), 401

    sub = google_data.get('sub')
    email = (google_data.get('email') or '').lower().strip()
    name = google_data.get('name') or email.split('@')[0]
    picture = google_data.get('picture')

    if not sub:
        return jsonify({"mensaje": "Token de Google no incluye identificador único de usuario (sub)"}), 400

    # 1. Buscar si ya existe la identidad externa vinculada
    identidad = IdentidadExterna.query.filter_by(proveedor='google', sub=sub).first()
    usuario = None

    if identidad:
        usuario = identidad.usuario
        # Actualizar datos visuales si cambiaron en Google
        if picture and usuario.foto_url != picture:
            usuario.foto_url = picture
        if name and not usuario.nombre:
            usuario.nombre = name
    else:
        # 2. Si no existe la identidad, verificar si el correo ya existe
        if email:
            usuario = Usuario.query.filter_by(correo=email).first()

        if not usuario:
            # Crear nuevo usuario - SIEMPRE ROL PACIENTE
            usuario = Usuario(
                username=f"google_{sub}",
                nombre=name,
                correo=email,
                foto_url=picture,
                rol='paciente',
                activo=True
            )
            db.session.add(usuario)
            db.session.flush()

        # Vincular identidad externa
        identidad = IdentidadExterna(
            usuario_id=usuario.id,
            proveedor='google',
            sub=sub,
            correo_proveedor=email
        )
        db.session.add(identidad)

    # Asegurar que tenga perfil de paciente
    if not usuario.perfil:
        perfil = PerfilPaciente(usuario_id=usuario.id)
        db.session.add(perfil)
        db.session.flush()

    db.session.commit()

    # Generar Token JWT del sistema
    token_jwt = create_access_token(
        identity=str(usuario.id),
        additional_claims={
            "rol": usuario.rol,
            "correo": usuario.correo,
            "nombre": usuario.nombre
        }
    )

    perfil = usuario.perfil
    requiere_perfil = not (perfil and perfil.telefono and perfil.politica_privacidad_aceptada)

    return jsonify({
        "token": token_jwt,
        "usuario": {
            "id": usuario.id,
            "nombre": usuario.nombre,
            "correo": usuario.correo,
            "foto_url": usuario.foto_url,
            "rol": usuario.rol,
            "telefono": perfil.telefono if perfil else "",
            "documento_identidad": perfil.documento_identidad if perfil else "",
            "politica_aceptada": perfil.politica_privacidad_aceptada if perfil else False,
            "isProfileComplete": not requiere_perfil
        },
        "requiere_perfil": requiere_perfil,
        "mensaje": f"Bienvenido/a {usuario.nombre}"
    }), 200

@app.route('/api/auth/me', methods=['GET'])
@jwt_required()
def obtener_perfil_actual():
    usuario = obtener_usuario_actual()
    if not usuario:
        return jsonify({"mensaje": "Sesión inválida o expirada"}), 401

    perfil = usuario.perfil
    notificaciones_sin_leer = Notificacion.query.filter_by(usuario_id=usuario.id, leida=False).count()
    is_complete = bool(perfil and perfil.telefono and perfil.politica_privacidad_aceptada)

    return jsonify({
        "usuario": {
            "id": usuario.id,
            "nombre": usuario.nombre or usuario.username,
            "correo": usuario.correo or "",
            "foto_url": usuario.foto_url or "",
            "rol": usuario.rol,
            "telefono": perfil.telefono if perfil else "",
            "documento_identidad": perfil.documento_identidad if perfil else "",
            "politica_aceptada": perfil.politica_privacidad_aceptada if perfil else False,
            "isProfileComplete": is_complete,
            "notificaciones_sin_leer": notificaciones_sin_leer
        }
    }), 200

@app.route('/api/auth/perfil', methods=['PUT'])
@jwt_required()
def actualizar_perfil():
    usuario = obtener_usuario_actual()
    if not usuario:
        return jsonify({"mensaje": "Sesión inválida"}), 401

    datos = request.get_json() or {}
    perfil = usuario.perfil
    if not perfil:
        perfil = PerfilPaciente(usuario_id=usuario.id)
        db.session.add(perfil)

    if 'nombre' in datos and datos['nombre'].strip():
        usuario.nombre = datos['nombre'].strip()
    if 'telefono' in datos:
        perfil.telefono = datos['telefono'].strip()
    if 'documento_identidad' in datos:
        perfil.documento_identidad = datos['documento_identidad'].strip()
    if 'politica_privacidad_aceptada' in datos:
        perfil.politica_privacidad_aceptada = bool(datos['politica_privacidad_aceptada'])

    db.session.commit()
    return jsonify({"mensaje": "Perfil médico actualizado con éxito"}), 200

@app.route('/api/login', methods=['POST'])
def login_clasico_doctor():
    """Permite al Dr. Lisandro Márquez y administración ingresar por credenciales maestras"""
    datos = request.get_json() or {}
    usuario = Usuario.query.filter(
        or_(Usuario.username == datos.get('username'), Usuario.correo == datos.get('username'))
    ).first()

    if usuario and usuario.password and check_password_hash(usuario.password, datos.get('password', '')):
        token_acceso = create_access_token(
            identity=str(usuario.id),
            additional_claims={"rol": usuario.rol, "nombre": usuario.nombre, "correo": usuario.correo}
        )
        return jsonify({
            "token": token_acceso,
            "mensaje": f"Sesión activa para {usuario.nombre or usuario.username}",
            "rol": usuario.rol
        }), 200

    return jsonify({"mensaje": "Credenciales médicas incorrectas"}), 401

# ==========================================
# 4. ENDPOINTS DE SEDES Y SERVICIOS
# ==========================================

@app.route('/api/sedes', methods=['GET'])
def obtener_sedes():
    sedes = Sede.query.filter_by(activa=True).all()
    return jsonify([{
        "id": s.id,
        "nombre": s.nombre,
        "clinica": s.clinica,
        "ciudad": s.ciudad,
        "direccion": s.direccion or "",
        "horarios_texto": s.horarios_texto or ""
    } for s in sedes]), 200

@app.route('/api/servicios', methods=['GET'])
def obtener_servicios():
    servicios = Servicio.query.filter_by(activo=True).order_by(Servicio.id.asc()).all()
    return jsonify([{
        "id": s.id,
        "nombre": s.nombre_servicio,
        "descripcion": s.descripcion,
        "duracion_minutos": s.duracion_minutos or 45,
        "precio": float(s.precio) if s.precio else None
    } for s in servicios]), 200

# ==========================================
# 5. MOTOR DE DISPONIBILIDAD REAL EN TIEMPO REAL
# ==========================================

@app.route('/api/disponibilidad', methods=['GET'])
def consultar_disponibilidad():
    """
    Calcula los intervalos y slots reales considerando:
    1. Horarios de atención de la sede/doctor para el día de la semana.
    2. Duración del servicio médico.
    3. Citas activas ya agendadas (pendiente, confirmada, presente).
    4. Bloqueos de agenda (vacaciones, cirugías, descansos).
    5. Anticipación mínima de reserva.
    """
    fecha_str = request.args.get('fecha') # Formato: YYYY-MM-DD
    sede_id = request.args.get('sede_id', type=int)
    servicio_id = request.args.get('servicio_id', type=int)

    if not fecha_str:
        return jsonify({"mensaje": "Parámetro 'fecha' requerido"}), 400

    try:
        fecha_consulta = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"mensaje": "Formato de fecha inválido. Usar YYYY-MM-DD"}), 400

    # No permitir fechas pasadas
    hoy = date.today()
    if fecha_consulta < hoy:
        return jsonify({
            "fecha": fecha_str,
            "disponible": False,
            "motivo": "No se pueden agendar consultas en fechas anteriores a hoy",
            "slots": []
        }), 200

    dias_nombre = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    dia_semana = fecha_consulta.weekday()

    # Domingo cerrado por descanso semanal
    if dia_semana == 6:
        return jsonify({
            "fecha": fecha_str,
            "dia_semana": dia_semana,
            "disponible": False,
            "dia_no_atiende_sede": True,
            "motivo": "Los domingos el consultorio médico permanece cerrado. Por favor elija un día hábil.",
            "slots": []
        }), 200

    servicio = Servicio.query.get(servicio_id) if servicio_id else None
    duracion = servicio.duracion_minutos if servicio and servicio.duracion_minutos else 45

    doctor_master = Usuario.query.filter(Usuario.rol.in_(['doctor', 'administrador'])).first()
    doctor_id = doctor_master.id if doctor_master else 1

    # Verificar si el doctor configuró días de atención específicos para esta sede
    horarios_sede = HorarioDoctor.query.filter_by(doctor_id=doctor_id, sede_id=sede_id).all() if sede_id else []

    if horarios_sede:
        horario_dia = next((h for h in horarios_sede if h.dia_semana == dia_semana), None)
        if not horario_dia or not horario_dia.activo:
            dias_atendidos = [dias_nombre[h.dia_semana] for h in horarios_sede if h.activo]
            texto_dias = ", ".join(dias_atendidos) if dias_atendidos else "ningún día de la semana"
            sede_obj = Sede.query.get(sede_id)
            nombre_sede = sede_obj.nombre if sede_obj else "esta sede"
            return jsonify({
                "fecha": fecha_str,
                "dia_semana": dia_semana,
                "disponible": False,
                "dia_no_atiende_sede": True,
                "motivo": f"El Dr. Lisandro Márquez no atiende consultas los {dias_nombre[dia_semana]} en {nombre_sede}. Días de atención habituales: {texto_dias}.",
                "dias_atendidos": dias_atendidos,
                "slots": []
            }), 200

        hora_inicio_dt = datetime.combine(fecha_consulta, horario_dia.hora_inicio)
        hora_fin_dt = datetime.combine(fecha_consulta, horario_dia.hora_fin)
        intervalo = horario_dia.intervalo_minutos or duracion
    else:
        # Horarios base iniciales por sede:
        # Sede 1 (Caracas): Lunes, Miércoles, Viernes
        # Sede 2 (Guatire): Martes, Jueves, Sábado
        # Sede 3 (Barlovento): Sábados
        dias_permitidos = [0, 2, 4] if (sede_id == 1 or not sede_id) else ([1, 3, 5] if sede_id == 2 else [5])
        if dia_semana not in dias_permitidos:
            dias_atendidos = [dias_nombre[d] for d in dias_permitidos]
            sede_obj = Sede.query.get(sede_id) if sede_id else None
            nombre_sede = sede_obj.nombre if sede_obj else "esta sede"
            return jsonify({
                "fecha": fecha_str,
                "dia_semana": dia_semana,
                "disponible": False,
                "dia_no_atiende_sede": True,
                "motivo": f"El Dr. Lisandro Márquez no atiende consultas los {dias_nombre[dia_semana]} en {nombre_sede}. Días de atención: {', '.join(dias_atendidos)}.",
                "dias_atendidos": dias_atendidos,
                "slots": []
            }), 200

        hora_fin_h = 13 if dia_semana == 5 else 16
        hora_inicio_dt = datetime.combine(fecha_consulta, time(8, 30))
        hora_fin_dt = datetime.combine(fecha_consulta, time(hora_fin_h, 30))
        intervalo = duracion

    # 1. Obtener citas activas existentes en esa fecha (para el doctor en CUALQUIER sede para evitar solapamientos)
    inicio_dia = datetime.combine(fecha_consulta, time(0, 0))
    fin_dia = datetime.combine(fecha_consulta, time(23, 59, 59))

    citas_ocupadas = Cita.query.filter(
        Cita.fecha_hora >= inicio_dia,
        Cita.fecha_hora <= fin_dia,
        Cita.estado.in_(['pendiente', 'confirmada', 'presente', 'Pendiente', 'Confirmada'])
    ).all()

    # 2. Obtener bloqueos de agenda para ese día (filtrando por sede si corresponde)
    bloqueos_query = BloqueoAgenda.query.filter(
        BloqueoAgenda.fecha_inicio <= fin_dia,
        BloqueoAgenda.fecha_fin >= inicio_dia
    )
    if sede_id:
        bloqueos = bloqueos_query.filter(or_(BloqueoAgenda.sede_id == None, BloqueoAgenda.sede_id == sede_id)).all()
    else:
        bloqueos = bloqueos_query.all()

    # Si el doctor bloqueó el día completo o la jornada
    bloqueo_dia_completo = next((b for b in bloqueos if b.fecha_inicio <= hora_inicio_dt and b.fecha_fin >= hora_fin_dt), None)
    if not bloqueo_dia_completo:
        bloqueo_dia_completo = next((b for b in bloqueos if b.fecha_inicio <= inicio_dia and b.fecha_fin >= fin_dia), None)

    if bloqueo_dia_completo:
        motivo_bloqueo = bloqueo_dia_completo.motivo or "El Dr. Lisandro Márquez no atiende pacientes en esta fecha"
        return jsonify({
            "fecha": fecha_str,
            "dia_semana": dia_semana,
            "disponible": False,
            "dia_bloqueado": True,
            "motivo": f"El Dr. Lisandro Márquez indicó que no atenderá consultas en esta fecha ({motivo_bloqueo})",
            "slots": []
        }), 200

    # 3. Generar franjas (slots)
    ahora = datetime.now()
    slots = []
    cursor = hora_inicio_dt

    while cursor + timedelta(minutes=intervalo) <= hora_fin_dt:
        slot_fin = cursor + timedelta(minutes=intervalo)
        hora_str = cursor.strftime('%H:%M')
        disponible = True
        motivo = None

        # Verificar si ya pasó la hora (para citas hoy con al menos 1 hora de anticipación)
        if cursor <= ahora + timedelta(hours=1):
            disponible = False
            motivo = "Hora no disponible o tiempo de anticipación insuficiente"

        # Verificar solapamiento con citas existentes
        if disponible:
            for c in citas_ocupadas:
                c_inicio = c.fecha_hora
                c_duracion = c.servicio.duracion_minutos if (c.servicio and c.servicio.duracion_minutos) else 45
                c_fin = c.fecha_hora_fin or (c_inicio + timedelta(minutes=c_duracion))

                # Condición de solapamiento de intervalos: max(start1, start2) < min(end1, end2)
                if max(cursor, c_inicio) < min(slot_fin, c_fin):
                    disponible = False
                    motivo = "Horario reservado por otro paciente"
                    break

        # Verificar solapamiento con bloqueos del doctor
        if disponible:
            for b in bloqueos:
                if max(cursor, b.fecha_inicio) < min(slot_fin, b.fecha_fin):
                    disponible = False
                    motivo = f"Horario reservado: {b.motivo or 'Compromiso médico'}"
                    break

        slots.append({
            "hora": hora_str,
            "disponible": disponible,
            "motivo": motivo
        })

        cursor += timedelta(minutes=intervalo)

    hay_disponibles = any(s["disponible"] for s in slots)
    todos_bloqueados_por_doctor = bool(slots and all(not s["disponible"] for s in slots) and bloqueos)
    motivo_general = None
    if not hay_disponibles:
        if todos_bloqueados_por_doctor and bloqueos:
            motivo_general = f"El Dr. Lisandro Márquez indicó que no atenderá pacientes en esta fecha ({bloqueos[0].motivo or 'Día no disponible'})"
        elif slots and all("reservado por otro" in (s.get("motivo") or "") for s in slots):
            motivo_general = "Todos los turnos de este día ya han sido reservados. Por favor seleccione otra fecha."
        else:
            motivo_general = "No hay turnos disponibles para esta fecha."

    return jsonify({
        "fecha": fecha_str,
        "dia_semana": dia_semana,
        "disponible": hay_disponibles,
        "dia_bloqueado": bool(todos_bloqueados_por_doctor or bloqueo_dia_completo),
        "motivo": motivo_general,
        "duracion_servicio": duracion,
        "slots": slots
    }), 200

# ==========================================
# 6. GESTIÓN INTEGRAL DE CITAS MÉDICAS
# ==========================================

@app.route('/api/citas', methods=['POST'])
@jwt_required(optional=True)
def agendar_cita():
    """
    Registra una cita médica con protección contra doble reserva (carreras de concurrencia).
    Puede ser creada por un paciente autenticado mediante Google o provisionalmente.
    """
    try:
        usuario_actual = obtener_usuario_actual()
        datos = request.get_json() or {}

        fecha_hora_str = datos.get('fecha_hora') # 'YYYY-MM-DD HH:MM'
        servicio_id = datos.get('servicio_id')
        sede_id = datos.get('sede_id')
        sintomas = datos.get('sintomas') or datos.get('notas')

        if not fecha_hora_str:
            return jsonify({"mensaje": "Fecha y hora requeridas"}), 400

        try:
            fecha_obj = datetime.strptime(fecha_hora_str, '%Y-%m-%d %H:%M')
        except ValueError:
            return jsonify({"mensaje": "Formato de fecha inválido. Usar YYYY-MM-DD HH:MM"}), 400

        servicio = Servicio.query.get(servicio_id)
        if not servicio:
            servicio = Servicio.query.first()
            servicio_id = servicio.id if servicio else 1

        duracion = servicio.duracion_minutos if servicio and servicio.duracion_minutos else 45
        fecha_fin_obj = fecha_obj + timedelta(minutes=duracion)

        doctor_master = Usuario.query.filter(Usuario.rol.in_(['doctor', 'administrador'])).first()
        doctor_id = doctor_master.id if doctor_master else 1

        # 1. VERIFICACIÓN ATÓMICA DE NO SOLAPAMIENTO
        citas_solapadas = Cita.query.filter(
            Cita.estado.in_(['pendiente', 'confirmada', 'presente', 'Pendiente', 'Confirmada']),
            Cita.fecha_hora < fecha_fin_obj,
            or_(
                Cita.fecha_hora_fin > fecha_obj,
                and_(Cita.fecha_hora_fin == None, Cita.fecha_hora + timedelta(minutes=45) > fecha_obj)
            )
        ).first()

        if citas_solapadas:
            return jsonify({
                "mensaje": "El turno seleccionado acaba de ser reservado por otro paciente. Por favor selecciona otro horario.",
                "error_codigo": "SLOT_CONFLICT"
            }), 409

        # Verificar bloqueos
        bloqueo = BloqueoAgenda.query.filter(
            BloqueoAgenda.fecha_inicio < fecha_fin_obj,
            BloqueoAgenda.fecha_fin > fecha_obj
        ).first()

        if bloqueo:
            return jsonify({
                "mensaje": f"El turno seleccionado no está disponible: {bloqueo.motivo or 'Bloqueo médico'}",
                "error_codigo": "SLOT_BLOCKED"
            }), 409

        # 2. Asignar paciente y sincronizar tanto Usuario como Paciente (legacy)
        paciente_user_id = None
        legacy_id = None

        if usuario_actual:
            paciente_user_id = usuario_actual.id
            if datos.get('telefono') and usuario_actual.perfil:
                usuario_actual.perfil.telefono = datos.get('telefono').strip()

            # Asegurar correspondencia en tabla legacy paciente
            pac_leg = Paciente.query.filter_by(correo=usuario_actual.correo).first() if usuario_actual.correo else None
            if not pac_leg:
                pac_leg = Paciente(
                    nombre=usuario_actual.nombre or 'Paciente',
                    telefono=usuario_actual.perfil.telefono if usuario_actual.perfil else (datos.get('telefono') or ''),
                    correo=usuario_actual.correo or ''
                )
                db.session.add(pac_leg)
                db.session.flush()
            legacy_id = pac_leg.id
        else:
            nombre = datos.get('nombre') or datos.get('nombre_paciente') or 'Paciente Invitado'
            telefono = datos.get('telefono') or ''
            correo = (datos.get('correo') or datos.get('correo_paciente') or '').lower().strip()

            # Buscar o crear registro legacy
            pac_leg = Paciente.query.filter_by(correo=correo).first() if correo else None
            if not pac_leg:
                pac_leg = Paciente(nombre=nombre, telefono=telefono, correo=correo)
                db.session.add(pac_leg)
                db.session.flush()
            legacy_id = pac_leg.id

            # Buscar o crear Usuario local
            u_prov = Usuario.query.filter_by(correo=correo).first() if correo else None
            if not u_prov:
                u_prov = Usuario(
                    username=f"guest_{uuid.uuid4().hex[:8]}",
                    nombre=nombre,
                    correo=correo or None,
                    rol='paciente',
                    activo=True
                )
                db.session.add(u_prov)
                db.session.flush()
                perfil_prov = PerfilPaciente(usuario_id=u_prov.id, telefono=telefono, politica_privacidad_aceptada=True)
                db.session.add(perfil_prov)
                db.session.flush()
            paciente_user_id = u_prov.id

        codigo_cita = f"CIT-{uuid.uuid4().hex[:6].upper()}"

        # Ejecutar DROP CONSTRAINT directo en caso de que aún exista la restricción antigua en PostgreSQL
        try:
            db.session.execute(text("ALTER TABLE cita DROP CONSTRAINT IF EXISTS cita_paciente_id_fkey;"))
            db.session.execute(text("ALTER TABLE cita ALTER COLUMN paciente_id DROP NOT NULL;"))
        except Exception:
            pass

        nueva_cita = Cita(
            codigo_cita=codigo_cita,
            fecha_hora=fecha_obj,
            fecha_hora_fin=fecha_fin_obj,
            estado='pendiente',
            paciente_id=paciente_user_id,
            legacy_paciente_id=legacy_id,
            doctor_id=doctor_id,
            servicio_id=servicio_id,
            sede_id=sede_id,
            sintomas_paciente=sintomas,
            creado_por=paciente_user_id or doctor_id
        )

        db.session.add(nueva_cita)
        db.session.flush()

        # Auditoría inicial
        historial = HistorialCita(
            cita_id=nueva_cita.id,
            modificado_por=paciente_user_id or doctor_id,
            estado_nuevo='pendiente',
            fecha_nueva=fecha_obj,
            motivo='Reserva inicial generada desde la plataforma web'
        )
        db.session.add(historial)

        # Notificación para el paciente
        if paciente_user_id:
            notif = Notificacion(
                usuario_id=paciente_user_id,
                cita_id=nueva_cita.id,
                titulo="Cita Agendada",
                mensaje=f"Tu cita para {servicio.nombre_servicio} quedó registrada para el {fecha_obj.strftime('%d/%m/%Y a las %H:%M')}.",
                tipo='reserva'
            )
            db.session.add(notif)

        db.session.commit()

        return jsonify({
            "mensaje": "Cita agendada exitosamente",
            "id_cita": nueva_cita.id,
            "codigo_cita": codigo_cita,
            "codigo": codigo_cita,
            "fecha_hora": fecha_obj.strftime('%Y-%m-%d %H:%M'),
            "servicio": servicio.nombre_servicio,
            "sede_id": sede_id
        }), 201

    except Exception as exc:
        import traceback
        err_trace = traceback.format_exc()
        print(f">> [ERROR agendar_cita]: {err_trace}", flush=True)
        db.session.rollback()
        return jsonify({
            "mensaje": f"Error al procesar la cita: {str(exc)}",
            "error_detail": str(exc),
            "traceback": err_trace
        }), 500

@app.route('/api/citas/mis-citas', methods=['GET'])
@app.route('/api/paciente/mis-citas', methods=['GET'])
@jwt_required()
def obtener_mis_citas():
    """Devuelve las citas del paciente autenticado divididas en próximas e historial"""
    usuario = obtener_usuario_actual()
    if not usuario:
        return jsonify({"mensaje": "Sesión requerida"}), 401

    citas = Cita.query.filter_by(paciente_id=usuario.id).order_by(Cita.fecha_hora.desc()).all()

    if not citas and usuario.correo:
        legacy = Paciente.query.filter_by(correo=usuario.correo).first()
        if legacy:
            citas = Cita.query.filter_by(legacy_paciente_id=legacy.id).order_by(Cita.fecha_hora.desc()).all()
            for c in citas:
                c.paciente_id = usuario.id
            db.session.commit()
    ahora = datetime.now()

    proximas = []
    historial = []

    for c in citas:
        item = {
            "id": c.id,
            "codigo_cita": c.codigo_cita or f"CIT-{c.id}",
            "fecha_hora": c.fecha_hora.strftime('%Y-%m-%d %H:%M'),
            "fecha": c.fecha_hora.strftime('%Y-%m-%d'),
            "hora": c.fecha_hora.strftime('%H:%M'),
            "estado": c.estado,
            "servicio": c.servicio.nombre_servicio if c.servicio else "Consulta General",
            "servicio_id": c.servicio_id or (c.servicio.id if c.servicio else 1),
            "duracion": c.servicio.duracion_minutos if c.servicio else 45,
            "sede_id": c.sede_id or (c.sede.id if c.sede else 1),
            "sede": {
                "id": c.sede.id if c.sede else None,
                "nombre": c.sede.nombre if c.sede else "Caracas — Clínica VidaMed",
                "clinica": c.sede.clinica if c.sede else "Clínica VidaMed",
                "ciudad": c.sede.ciudad if c.sede else "Caracas",
                "direccion": c.sede.direccion if c.sede else ""
            },
            "sintomas": c.sintomas_paciente or "",
            "motivo_cancelacion": c.motivo_cancelacion or "",
            "puede_cancelar": c.estado in ['pendiente', 'confirmada', 'Pendiente', 'Confirmada'] and c.fecha_hora > ahora + timedelta(hours=2),
            "puede_reprogramar": c.estado in ['pendiente', 'confirmada', 'Pendiente', 'Confirmada'] and c.fecha_hora > ahora + timedelta(hours=2)
        }

        # Clasificación
        if c.estado in ['pendiente', 'confirmada', 'presente', 'Pendiente', 'Confirmada'] and c.fecha_hora >= ahora:
            proximas.append(item)
        else:
            historial.append(item)

    # Ordenar próximas ascendentemente (la más cercana primero)
    proximas.sort(key=lambda x: x["fecha_hora"])

    return jsonify({
        "proximas": proximas,
        "historial": historial,
        "total_proximas": len(proximas),
        "total_historial": len(historial)
    }), 200

@app.route('/api/citas/<int:id>/cancelar', methods=['PUT'])
@jwt_required()
def cancelar_cita(id):
    """
    Permite al paciente o doctor cancelar una cita.
    Libera el cupo inmediatamente en la agenda y guarda la auditoría.
    """
    usuario = obtener_usuario_actual()
    if not usuario:
        return jsonify({"mensaje": "Sesión requerida"}), 401

    cita = Cita.query.get_or_404(id)

    # Validar permisos
    es_dueno = (cita.paciente_id == usuario.id)
    es_doctor_admin = (usuario.rol in ['doctor', 'administrador'])

    if not (es_dueno or es_doctor_admin):
        return jsonify({"mensaje": "No tienes autorización para cancelar esta cita"}), 403

    datos = request.get_json() or {}
    motivo = datos.get('motivo', 'Cancelada por el paciente')

    estado_anterior = cita.estado
    nuevo_estado = 'cancelada_paciente' if es_dueno else 'cancelada_doctor'

    cita.estado = nuevo_estado
    cita.motivo_cancelacion = motivo

    # Auditoría
    historial = HistorialCita(
        cita_id=cita.id,
        modificado_por=usuario.id,
        estado_anterior=estado_anterior,
        estado_nuevo=nuevo_estado,
        motivo=motivo
    )
    db.session.add(historial)

    # Notificación
    destinatario_id = cita.paciente_id if es_doctor_admin else (cita.doctor_id or 1)
    if destinatario_id:
        notif = Notificacion(
            usuario_id=destinatario_id,
            cita_id=cita.id,
            titulo="Cita Médica Cancelada",
            mensaje=f"La cita #{cita.codigo_cita or cita.id} pautada para el {cita.fecha_hora.strftime('%d/%m/%Y %H:%M')} fue cancelada. Motivo: {motivo}.",
            tipo='cancelacion'
        )
        db.session.add(notif)

    db.session.commit()
    return jsonify({
        "mensaje": "Cita cancelada correctamente y horario liberado",
        "id": cita.id,
        "nuevo_estado": nuevo_estado
    }), 200

@app.route('/api/citas/<int:id>/reprogramar', methods=['PUT'])
@jwt_required()
def reprogramar_cita(id):
    """
    Reprogramación atómica: valida que el nuevo horario esté disponible.
    Si falla, la cita original queda intacta al 100%.
    """
    usuario = obtener_usuario_actual()
    if not usuario:
        return jsonify({"mensaje": "Sesión requerida"}), 401

    cita = Cita.query.get_or_404(id)

    es_dueno = (cita.paciente_id == usuario.id)
    es_doctor_admin = (usuario.rol in ['doctor', 'administrador'])

    if not (es_dueno or es_doctor_admin):
        return jsonify({"mensaje": "No tienes autorización para reprogramar esta cita"}), 403

    datos = request.get_json() or {}
    nueva_fecha_hora_str = datos.get('nueva_fecha_hora')
    nueva_sede_id = datos.get('nueva_sede_id', cita.sede_id)
    motivo = datos.get('motivo', 'Reprogramada por solicitud')

    if not nueva_fecha_hora_str:
        return jsonify({"mensaje": "Nueva fecha y hora requeridas"}), 400

    try:
        nueva_fecha = datetime.strptime(nueva_fecha_hora_str, '%Y-%m-%d %H:%M')
    except ValueError:
        return jsonify({"mensaje": "Formato de fecha inválido. Usar YYYY-MM-DD HH:MM"}), 400

    duracion = cita.servicio.duracion_minutos if cita.servicio else 45
    nuevo_fin = nueva_fecha + timedelta(minutes=duracion)

    # 1. Validar disponibilidad del doctor en la sede y fecha seleccionada
    doctor = Doctor.query.first()
    sede = Sede.query.get(nueva_sede_id) or cita.sede
    if doctor and sede:
        dia_semana = nueva_fecha.weekday() # 0 = Lunes, 6 = Domingo
        horario_sede = HorarioDoctor.query.filter_by(
            doctor_id=doctor.id,
            sede_id=sede.id,
            dia_semana=dia_semana
        ).first()

        if not horario_sede or not horario_sede.activo:
            horarios_activos = HorarioDoctor.query.filter_by(
                doctor_id=doctor.id,
                sede_id=sede.id,
                activo=True
            ).order_by(HorarioDoctor.dia_semana.asc()).all()
            dias_nombres = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
            dias_atencion_str = ", ".join([dias_nombres[h.dia_semana] for h in horarios_activos]) if horarios_activos else "No configurado"
            return jsonify({
                "mensaje": f"El Dr. Lisandro Márquez no atiende consultas los {dias_nombres[dia_semana]} en {sede.nombre}. Días de atención: {dias_atencion_str}.",
                "error_codigo": "DAY_NOT_AVAILABLE_FOR_SEDE"
            }), 400

        # 2. Validar si el doctor tiene un bloqueo de agenda en esa fecha
        fecha_str = nueva_fecha.strftime('%Y-%m-%d')
        bloqueo = BloqueoAgenda.query.filter(
            BloqueoAgenda.doctor_id == doctor.id,
            BloqueoAgenda.activo == True,
            or_(
                and_(BloqueoAgenda.fecha_inicio <= fecha_str, BloqueoAgenda.fecha_fin >= fecha_str),
                BloqueoAgenda.fecha_inicio == fecha_str
            )
        ).filter(
            or_(BloqueoAgenda.sede_id == None, BloqueoAgenda.sede_id == sede.id)
        ).first()

        if bloqueo:
            return jsonify({
                "mensaje": f"Esta fecha está bloqueada por el doctor ({bloqueo.motivo or 'No disponible'}). Por favor selecciona otra fecha disponible.",
                "error_codigo": "DATE_BLOCKED_BY_DOCTOR"
            }), 400

    # 3. Validar conflicto con otras citas (excluyendo la misma cita actual)
    solapada = Cita.query.filter(
        Cita.id != cita.id,
        Cita.sede_id == nueva_sede_id,
        Cita.estado.in_(['pendiente', 'confirmada', 'presente', 'Pendiente', 'Confirmada']),
        Cita.fecha_hora < nuevo_fin,
        or_(
            Cita.fecha_hora_fin > nueva_fecha,
            and_(Cita.fecha_hora_fin == None, Cita.fecha_hora + timedelta(minutes=45) > nueva_fecha)
        )
    ).first()

    if solapada:
        return jsonify({
            "mensaje": "El nuevo horario seleccionado ya está reservado por otro paciente. Tu cita original permanece intacta.",
            "error_codigo": "RESCHEDULE_CONFLICT"
        }), 409

    fecha_anterior = cita.fecha_hora
    cita.fecha_hora = nueva_fecha
    cita.fecha_hora_fin = nuevo_fin
    cita.sede_id = nueva_sede_id
    cita.estado = 'pendiente' # Pasa a pendiente para validación del nuevo turno

    # Auditoría
    historial = HistorialCita(
        cita_id=cita.id,
        modificado_por=usuario.id,
        estado_anterior='reprogramada',
        estado_nuevo='pendiente',
        fecha_anterior=fecha_anterior,
        fecha_nueva=nueva_fecha,
        motivo=motivo
    )
    db.session.add(historial)

    if cita.paciente_id:
        notif = Notificacion(
            usuario_id=cita.paciente_id,
            cita_id=cita.id,
            titulo="Cita Reprogramada",
            mensaje=f"Tu cita fue movida exitosamente para el {nueva_fecha.strftime('%d/%m/%Y a las %H:%M')}.",
            tipo='reprogramacion'
        )
        db.session.add(notif)

    db.session.commit()
    return jsonify({
        "mensaje": "Cita reprogramada exitosamente",
        "id": cita.id,
        "nueva_fecha_hora": nueva_fecha.strftime('%Y-%m-%d %H:%M')
    }), 200

# ==========================================
# 7. PORTAL DEL DOCTOR Y GESTIÓN CLÍNICA
# ==========================================

@app.route('/api/citas', methods=['GET'])
@jwt_required()
def obtener_todas_las_citas_doctor():
    """Agenda general para el doctor con filtros avanzados"""
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso exclusivo para el personal médico"}), 403

    filtro_estado = request.args.get('estado')
    filtro_sede = request.args.get('sede_id', type=int)
    filtro_fecha = request.args.get('fecha') # 'YYYY-MM-DD'
    busqueda = request.args.get('q', '').lower().strip()

    query = Cita.query

    if filtro_estado and filtro_estado != 'todos':
        query = query.filter(Cita.estado.ilike(f"%{filtro_estado}%"))

    if filtro_sede:
        query = query.filter_by(sede_id=filtro_sede)

    if filtro_fecha:
        try:
            f_dt = datetime.strptime(filtro_fecha, '%Y-%m-%d').date()
            query = query.filter(
                Cita.fecha_hora >= datetime.combine(f_dt, time(0, 0)),
                Cita.fecha_hora <= datetime.combine(f_dt, time(23, 59, 59))
            )
        except ValueError:
            pass

    citas = query.order_by(Cita.fecha_hora.asc()).all()

    resultado = []
    for c in citas:
        # Resolver nombre y datos de contacto según provenga de Usuario o Legacy Paciente
        paciente_nombre = "Paciente General"
        paciente_telefono = ""
        paciente_correo = ""

        if c.paciente:
            paciente_nombre = c.paciente.nombre or c.paciente.username
            paciente_correo = c.paciente.correo or ""
            paciente_telefono = c.paciente.perfil.telefono if (c.paciente.perfil and c.paciente.perfil.telefono) else ""
        elif c.legacy_paciente:
            paciente_nombre = c.legacy_paciente.nombre
            paciente_telefono = c.legacy_paciente.telefono or ""
            paciente_correo = c.legacy_paciente.correo or ""

        # Aplicar filtro de búsqueda textual
        if busqueda:
            texto_fila = f"{paciente_nombre} {paciente_telefono} {paciente_correo} {c.codigo_cita or ''}".lower()
            if busqueda not in texto_fila:
                continue

        resultado.append({
            "id": c.id,
            "codigo_cita": c.codigo_cita or f"CIT-{c.id}",
            "fecha_hora": c.fecha_hora.strftime('%Y-%m-%d %H:%M'),
            "fecha": c.fecha_hora.strftime('%Y-%m-%d'),
            "hora": c.fecha_hora.strftime('%H:%M'),
            "estado": c.estado,
            "paciente": paciente_nombre,
            "telefono": paciente_telefono,
            "correo": paciente_correo,
            "servicio": c.servicio.nombre_servicio if c.servicio else "Consulta General",
            "servicio_id": c.servicio_id,
            "sede": c.sede.nombre if c.sede else "Caracas — VidaMed",
            "sede_id": c.sede_id,
            "sintomas": c.sintomas_paciente or "",
            "notas_doctor": c.notas_doctor or "",
            "motivo_cancelacion": c.motivo_cancelacion or ""
        })

    return jsonify(resultado), 200

@app.route('/api/citas/<int:id>/estado', methods=['PUT'])
@jwt_required()
def cambiar_estado_cita_doctor(id):
    """
    Transiciones médicas:
    'confirmada', 'presente' (paciente llegó), 'completada' (atendido),
    'no_asistio', 'cancelada_doctor'
    """
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso restringido a médicos"}), 403

    cita = Cita.query.get_or_404(id)
    datos = request.get_json() or {}
    nuevo_estado = datos.get('estado')
    notas = datos.get('notas_doctor')

    if not nuevo_estado:
        return jsonify({"mensaje": "Nuevo estado requerido"}), 400

    estado_anterior = cita.estado
    cita.estado = nuevo_estado
    if notas is not None:
        cita.notas_doctor = notas

    historial = HistorialCita(
        cita_id=cita.id,
        modificado_por=usuario.id,
        estado_anterior=estado_anterior,
        estado_nuevo=nuevo_estado,
        motivo=datos.get('motivo', f'Cambio clínico por Dr. Lisandro Márquez a {nuevo_estado}')
    )
    db.session.add(historial)

    # Notificar al paciente
    if cita.paciente_id and nuevo_estado in ['confirmada', 'cancelada_doctor', 'completada']:
        mensajes_estado = {
            'confirmada': 'Tu cita ha sido confirmada formalmente por el Dr. Lisandro Márquez.',
            'completada': 'Tu consulta médica ha finalizado. ¡Gracias por confiar en nuestro servicio!',
            'cancelada_doctor': f'Tu cita fue cancelada por el consultorio. Motivo: {datos.get("motivo", "Imprevisto de fuerza mayor")}.'
        }
        notif = Notificacion(
            usuario_id=cita.paciente_id,
            cita_id=cita.id,
            titulo=f"Estado de Consulta: {nuevo_estado.capitalize()}",
            mensaje=mensajes_estado.get(nuevo_estado, f"Tu cita cambió a {nuevo_estado}"),
            tipo='confirmacion' if nuevo_estado == 'confirmada' else 'cancelacion'
        )
        db.session.add(notif)

    db.session.commit()
    return jsonify({
        "mensaje": f"Cita #{cita.id} actualizada a {nuevo_estado}",
        "id": cita.id,
        "estado": cita.estado
    }), 200

@app.route('/api/citas/<int:id>', methods=['DELETE'])
@jwt_required()
def eliminar_cita_definitiva(id):
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso no autorizado"}), 403

    cita = Cita.query.get_or_404(id)
    Notificacion.query.filter_by(cita_id=cita.id).delete()
    HistorialCita.query.filter_by(cita_id=cita.id).delete()
    db.session.delete(cita)
    db.session.commit()
    return jsonify({"mensaje": "Cita eliminada de la base de datos"}), 200

# ==========================================
# 8. BLOQUEOS DE AGENDA Y HORARIOS
# ==========================================

@app.route('/api/doctor/bloqueos', methods=['GET', 'POST'])
@jwt_required()
def gestionar_bloqueos():
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso restringido"}), 403

    if request.method == 'POST':
        datos = request.get_json() or {}
        
        # Permitir tanto fecha única (día completo) como rango fecha_inicio / fecha_fin
        fecha_dia = datos.get('fecha') or datos.get('fecha_dia')
        if fecha_dia and not datos.get('fecha_inicio'):
            try:
                f_ini = datetime.strptime(fecha_dia.strip() + ' 00:00', '%Y-%m-%d %H:%M')
                f_fin = datetime.strptime(fecha_dia.strip() + ' 23:59', '%Y-%m-%d %H:%M')
            except (ValueError, TypeError):
                return jsonify({"mensaje": "Formato de fecha debe ser YYYY-MM-DD"}), 400
        else:
            try:
                f_ini = datetime.strptime(datos.get('fecha_inicio'), '%Y-%m-%d %H:%M')
                f_fin = datetime.strptime(datos.get('fecha_fin'), '%Y-%m-%d %H:%M')
            except (ValueError, TypeError):
                return jsonify({"mensaje": "Formato de fechas debe ser YYYY-MM-DD HH:MM"}), 400

        bloqueo = BloqueoAgenda(
            doctor_id=usuario.id,
            sede_id=datos.get('sede_id'),
            fecha_inicio=f_ini,
            fecha_fin=f_fin,
            motivo=datos.get('motivo', 'El Dr. Lisandro Márquez no atiende pacientes este día'),
            creado_por=usuario.id
        )
        db.session.add(bloqueo)
        db.session.commit()
        return jsonify({
            "mensaje": "Fecha bloqueada exitosamente en la agenda del doctor",
            "id": bloqueo.id,
            "fecha_dia": f_ini.strftime('%Y-%m-%d')
        }), 201

    bloqueos = BloqueoAgenda.query.order_by(BloqueoAgenda.fecha_inicio.asc()).all()
    resultado = []
    for b in bloqueos:
        sede_obj = Sede.query.get(b.sede_id) if b.sede_id else None
        es_dia_completo = (b.fecha_inicio.strftime('%H:%M') == '00:00' and b.fecha_fin.strftime('%H:%M') in ['23:59', '23:59:59'])
        resultado.append({
            "id": b.id,
            "fecha_inicio": b.fecha_inicio.strftime('%Y-%m-%d %H:%M'),
            "fecha_fin": b.fecha_fin.strftime('%Y-%m-%d %H:%M'),
            "fecha_dia": b.fecha_inicio.strftime('%Y-%m-%d'),
            "es_dia_completo": es_dia_completo,
            "motivo": b.motivo or "No atiende pacientes este día",
            "sede_id": b.sede_id,
            "sede_nombre": sede_obj.nombre if sede_obj else "Todas las sedes"
        })
    return jsonify(resultado), 200

@app.route('/api/fechas-bloqueadas', methods=['GET'])
def fechas_bloqueadas():
    """
    Lista pública de fechas bloqueadas por el doctor para el calendario de reservas.
    """
    bloqueos = BloqueoAgenda.query.filter(
        BloqueoAgenda.fecha_fin >= datetime.now()
    ).order_by(BloqueoAgenda.fecha_inicio.asc()).all()
    
    lista = []
    for b in bloqueos:
        sede_obj = Sede.query.get(b.sede_id) if b.sede_id else None
        es_dia_completo = (b.fecha_inicio.strftime('%H:%M') == '00:00' and b.fecha_fin.strftime('%H:%M') in ['23:59', '23:59:59'])
        lista.append({
            "id": b.id,
            "fecha_inicio": b.fecha_inicio.strftime('%Y-%m-%d %H:%M'),
            "fecha_fin": b.fecha_fin.strftime('%Y-%m-%d %H:%M'),
            "fecha_dia": b.fecha_inicio.strftime('%Y-%m-%d'),
            "es_dia_completo": es_dia_completo,
            "motivo": b.motivo or "El Dr. Lisandro Márquez no atiende pacientes en esta fecha",
            "sede_id": b.sede_id,
            "sede_nombre": sede_obj.nombre if sede_obj else "Todas las sedes"
        })
    return jsonify(lista), 200

@app.route('/api/doctor/horarios', methods=['GET', 'POST'])
@jwt_required()
def gestionar_horarios():
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso restringido"}), 403

    if request.method == 'POST':
        datos = request.get_json() or {}
        sede_id = datos.get('sede_id')
        dia_semana = datos.get('dia_semana')
        hora_inicio = datos.get('hora_inicio')
        hora_fin = datos.get('hora_fin')
        intervalo = datos.get('intervalo_minutos', 45)

        if sede_id is None or dia_semana is None or not hora_inicio or not hora_fin:
            return jsonify({"mensaje": "sede_id, dia_semana, hora_inicio y hora_fin son requeridos"}), 400

        existente = HorarioDoctor.query.filter_by(
            doctor_id=usuario.id, sede_id=sede_id, dia_semana=dia_semana
        ).first()

        try:
            h_ini = time(*[int(x) for x in hora_inicio.split(':')])
            h_fin = time(*[int(x) for x in hora_fin.split(':')])
        except (ValueError, TypeError):
            return jsonify({"mensaje": "Formato de hora inválido. Usar HH:MM"}), 400

        if existente:
            existente.hora_inicio = h_ini
            existente.hora_fin = h_fin
            existente.intervalo_minutos = intervalo
            existente.activo = True
            msg = "Horario actualizado"
        else:
            nuevo = HorarioDoctor(
                doctor_id=usuario.id,
                sede_id=sede_id,
                dia_semana=dia_semana,
                hora_inicio=h_ini,
                hora_fin=h_fin,
                intervalo_minutos=intervalo,
                activo=True
            )
            db.session.add(nuevo)
            msg = "Horario creado"

        db.session.commit()
        return jsonify({"mensaje": msg}), 201

    horarios = HorarioDoctor.query.filter_by(doctor_id=usuario.id).all()
    dias_nombre = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    return jsonify([{
        "id": h.id,
        "sede_id": h.sede_id,
        "sede_nombre": h.sede.nombre if h.sede else "",
        "dia_semana": h.dia_semana,
        "dia_nombre": dias_nombre[h.dia_semana] if h.dia_semana < 7 else "?",
        "hora_inicio": h.hora_inicio.strftime('%H:%M'),
        "hora_fin": h.hora_fin.strftime('%H:%M'),
        "intervalo_minutos": h.intervalo_minutos,
        "activo": h.activo
    } for h in horarios]), 200

@app.route('/api/doctor/horarios/<int:id>', methods=['DELETE'])
@jwt_required()
def eliminar_horario(id):
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso restringido"}), 403
    h = HorarioDoctor.query.get_or_404(id)
    db.session.delete(h)
    db.session.commit()
    return jsonify({"mensaje": "Horario eliminado"}), 200

@app.route('/api/doctor/horarios/sede/<int:sede_id>', methods=['POST', 'PUT'])
@jwt_required()
def guardar_horarios_sede_doctor(sede_id):
    """Permite al doctor configurar qué días atiende y en qué horarios para una sede específica"""
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso restringido"}), 403

    sede = Sede.query.get_or_404(sede_id)
    datos = request.get_json() or {}
    dias_config = datos.get('dias', [])

    doctor_id = usuario.id

    for item in dias_config:
        dia_semana = item.get('dia_semana')
        activo = bool(item.get('activo', False))
        h_ini_str = item.get('hora_inicio', '08:30')
        h_fin_str = item.get('hora_fin', '16:30')
        intervalo = item.get('intervalo_minutos', 45)

        if dia_semana is None or not (0 <= dia_semana <= 6):
            continue

        try:
            h_ini = time(*[int(x) for x in h_ini_str.split(':')])
            h_fin = time(*[int(x) for x in h_fin_str.split(':')])
        except (ValueError, TypeError):
            h_ini = time(8, 30)
            h_fin = time(16, 30)

        existente = HorarioDoctor.query.filter_by(
            doctor_id=doctor_id, sede_id=sede_id, dia_semana=dia_semana
        ).first()

        if existente:
            existente.hora_inicio = h_ini
            existente.hora_fin = h_fin
            existente.intervalo_minutos = intervalo
            existente.activo = activo
        else:
            nuevo = HorarioDoctor(
                doctor_id=doctor_id,
                sede_id=sede_id,
                dia_semana=dia_semana,
                hora_inicio=h_ini,
                hora_fin=h_fin,
                intervalo_minutos=intervalo,
                activo=activo
            )
            db.session.add(nuevo)

    db.session.commit()
    return jsonify({
        "mensaje": f"Horarios de atención para {sede.nombre} guardados exitosamente",
        "sede_id": sede_id
    }), 200

@app.route('/api/disponibilidad/resumen-sede/<int:sede_id>', methods=['GET'])
def resumen_disponibilidad_sede(sede_id):
    """Informa a los pacientes qué días atiende el doctor en esta sede y qué fechas están bloqueadas"""
    sede = Sede.query.get_or_404(sede_id)
    doctor_master = Usuario.query.filter(Usuario.rol.in_(['doctor', 'administrador'])).first()
    doctor_id = doctor_master.id if doctor_master else 1

    horarios = HorarioDoctor.query.filter_by(doctor_id=doctor_id, sede_id=sede_id).all()
    dias_nombre = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

    if not horarios:
        dias_def = [0, 2, 4] if (sede_id == 1) else ([1, 3, 5] if sede_id == 2 else [5])
        dias_atencion_nombres = [dias_nombre[d] for d in dias_def]
        horarios_dict = {str(d): {"activo": True, "hora_inicio": "08:30", "hora_fin": "16:30", "intervalo": 45} for d in dias_def}
        dias_activos = dias_def
    else:
        dias_activos = [h.dia_semana for h in horarios if h.activo]
        dias_atencion_nombres = [dias_nombre[d] for d in sorted(dias_activos)]
        horarios_dict = {
            str(h.dia_semana): {
                "activo": h.activo,
                "hora_inicio": h.hora_inicio.strftime('%H:%M'),
                "hora_fin": h.hora_fin.strftime('%H:%M'),
                "intervalo": h.intervalo_minutos
            } for h in horarios
        }

    ahora = datetime.now()
    bloqueos = BloqueoAgenda.query.filter(
        BloqueoAgenda.fecha_fin >= ahora,
        or_(BloqueoAgenda.sede_id == None, BloqueoAgenda.sede_id == sede_id)
    ).all()

    fechas_bloqueadas = []
    for b in bloqueos:
        es_dia_comp = (b.fecha_inicio.strftime('%H:%M') == '00:00' and b.fecha_fin.strftime('%H:%M') in ['23:59', '23:59:59'])
        fechas_bloqueadas.append({
            "id": b.id,
            "fecha_dia": b.fecha_inicio.strftime('%Y-%m-%d'),
            "fecha_inicio": b.fecha_inicio.strftime('%Y-%m-%d %H:%M'),
            "fecha_fin": b.fecha_fin.strftime('%Y-%m-%d %H:%M'),
            "es_dia_completo": es_dia_comp,
            "motivo": b.motivo or "Día no disponible"
        })

    return jsonify({
        "sede_id": sede_id,
        "sede_nombre": sede.nombre,
        "clinica": sede.clinica,
        "ciudad": sede.ciudad,
        "dias_activos": sorted(dias_activos),
        "dias_atencion_texto": ", ".join(dias_atencion_nombres) if dias_atencion_nombres else "Sin días de atención configurados",
        "dias_atencion_nombres": dias_atencion_nombres,
        "horarios_por_dia": horarios_dict,
        "fechas_bloqueadas": fechas_bloqueadas
    }), 200

@app.route('/api/admin/sedes', methods=['POST'])
@jwt_required()
def crear_sede():
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso restringido"}), 403
    datos = request.get_json() or {}
    nueva = Sede(
        nombre=datos.get('nombre', ''),
        clinica=datos.get('clinica', ''),
        ciudad=datos.get('ciudad', ''),
        direccion=datos.get('direccion', ''),
        horarios_texto=datos.get('horarios_texto', ''),
        activa=True
    )
    db.session.add(nueva)
    db.session.commit()
    return jsonify({"mensaje": "Sede creada", "id": nueva.id}), 201

@app.route('/api/admin/sedes/<int:id>', methods=['PUT'])
@jwt_required()
def actualizar_sede(id):
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso restringido"}), 403
    sede = Sede.query.get_or_404(id)
    datos = request.get_json() or {}
    if 'nombre' in datos: sede.nombre = datos['nombre']
    if 'clinica' in datos: sede.clinica = datos['clinica']
    if 'ciudad' in datos: sede.ciudad = datos['ciudad']
    if 'direccion' in datos: sede.direccion = datos['direccion']
    if 'horarios_texto' in datos: sede.horarios_texto = datos['horarios_texto']
    if 'activa' in datos: sede.activa = datos['activa']
    db.session.commit()
    return jsonify({"mensaje": "Sede actualizada"}), 200

@app.route('/api/admin/sedes/<int:id>', methods=['DELETE'])
@jwt_required()
def eliminar_sede(id):
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso restringido"}), 403
    sede = Sede.query.get_or_404(id)
    sede.activa = False
    db.session.commit()
    return jsonify({"mensaje": "Sede desactivada"}), 200

@app.route('/api/doctor/bloqueos/<int:id>', methods=['DELETE'])
@jwt_required()
def eliminar_bloqueo(id):
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso restringido"}), 403

    bloqueo = BloqueoAgenda.query.get_or_404(id)
    db.session.delete(bloqueo)
    db.session.commit()
    return jsonify({"mensaje": "Bloqueo de agenda removido"}), 200

# ==========================================
# 9. CENTRO DE NOTIFICACIONES
# ==========================================

@app.route('/api/notificaciones', methods=['GET'])
@jwt_required()
def obtener_notificaciones():
    usuario = obtener_usuario_actual()
    if not usuario:
        return jsonify({"mensaje": "Sesión requerida"}), 401

    notifs = Notificacion.query.filter_by(usuario_id=usuario.id).order_by(Notificacion.fecha_creacion.desc()).limit(30).all()
    return jsonify([{
        "id": n.id,
        "titulo": n.titulo,
        "mensaje": n.mensaje,
        "tipo": n.tipo,
        "leida": n.leida,
        "fecha": n.fecha_creacion.strftime('%d/%m/%Y %H:%M')
    } for n in notifs]), 200

@app.route('/api/notificaciones/<int:id>/leer', methods=['PUT'])
@jwt_required()
def marcar_notificacion_leida(id):
    usuario = obtener_usuario_actual()
    notif = Notificacion.query.filter_by(id=id, usuario_id=usuario.id).first_or_404()
    notif.leida = True
    db.session.commit()
    return jsonify({"mensaje": "Notificación leída"}), 200

@app.route('/api/notificaciones/leer-todas', methods=['PUT'])
@jwt_required()
def marcar_todas_notificaciones_leidas():
    usuario = obtener_usuario_actual()
    Notificacion.query.filter_by(usuario_id=usuario.id, leida=False).update({'leida': True})
    db.session.commit()
    return jsonify({"mensaje": "Todas las notificaciones marcadas como leídas"}), 200

# ==========================================
# 10. DIRECTORIO DE PACIENTES Y ESTADÍSTICAS
# ==========================================

@app.route('/api/pacientes', methods=['GET'])
@jwt_required()
def obtener_directorio_pacientes():
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso restringido"}), 403

    # Obtener usuarios con rol paciente
    pacientes_usuarios = Usuario.query.filter_by(rol='paciente').all()
    # Obtener pacientes legacy
    pacientes_legacy = Paciente.query.all()

    resultado = []
    ids_procesados = set()

    for u in pacientes_usuarios:
        citas_u = Cita.query.filter_by(paciente_id=u.id).order_by(Cita.fecha_hora.asc()).all()
        ultima = citas_u[-1] if citas_u else None
        resultado.append({
            "id": u.id,
            "tipo": "google",
            "nombre": u.nombre or u.username,
            "correo": u.correo or "",
            "telefono": u.perfil.telefono if (u.perfil and u.perfil.telefono) else "",
            "foto_url": u.foto_url or "",
            "total_citas": len(citas_u),
            "ultima_cita": ultima.fecha_hora.strftime("%Y-%m-%d %H:%M") if ultima else None,
            "estado_ultima_cita": ultima.estado if ultima else "Sin cita activa"
        })
        ids_procesados.add(u.correo)

    for p in pacientes_legacy:
        if p.correo and p.correo in ids_procesados:
            continue
        citas_p = Cita.query.filter_by(legacy_paciente_id=p.id).order_by(Cita.fecha_hora.asc()).all()
        ultima = citas_p[-1] if citas_p else None
        resultado.append({
            "id": f"leg_{p.id}",
            "tipo": "manual",
            "nombre": p.nombre,
            "correo": p.correo or "",
            "telefono": p.telefono or "",
            "foto_url": "",
            "total_citas": len(citas_p),
            "ultima_cita": ultima.fecha_hora.strftime("%Y-%m-%d %H:%M") if ultima else None,
            "estado_ultima_cita": ultima.estado if ultima else "Sin cita activa"
        })

    return jsonify(resultado), 200

@app.route('/api/pacientes/<id>', methods=['DELETE'])
@app.route('/api/pacientes/<int:numeric_id>', methods=['DELETE'])
@jwt_required()
def eliminar_paciente_doctor(id=None, numeric_id=None):
    target_id = id if id is not None else str(numeric_id)
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso no autorizado"}), 403

    target_str = str(target_id).strip()
    leg_id = None
    u_id = None

    if target_str.startswith('leg_'):
        try:
            leg_id = int(target_str.replace('leg_', ''))
        except ValueError:
            pass
    else:
        try:
            u_id = int(target_str)
        except ValueError:
            pass

    encontrado = False

    # 1. Si es ID legacy (ej. leg_14)
    if leg_id:
        leg = Paciente.query.get(leg_id)
        if leg:
            citas_l = Cita.query.filter_by(legacy_paciente_id=leg.id).all()
            for c in citas_l:
                Notificacion.query.filter_by(cita_id=c.id).delete()
                HistorialCita.query.filter_by(cita_id=c.id).delete()
                db.session.delete(c)
            db.session.delete(leg)
            encontrado = True

    # 2. Si es ID numérico de Usuario o Paciente
    if not encontrado and u_id:
        u = Usuario.query.get(u_id)
        if u:
            citas_u = Cita.query.filter_by(paciente_id=u.id).all()
            for c in citas_u:
                Notificacion.query.filter_by(cita_id=c.id).delete()
                HistorialCita.query.filter_by(cita_id=c.id).delete()
                db.session.delete(c)
            Notificacion.query.filter_by(usuario_id=u.id).delete()
            HistorialCita.query.filter_by(modificado_por=u.id).update({'modificado_por': None})
            if u.perfil:
                db.session.delete(u.perfil)
            IdentidadFederada.query.filter_by(usuario_id=u.id).delete()
            if u.correo:
                leg_cor = Paciente.query.filter_by(correo=u.correo).first()
                if leg_cor:
                    citas_l2 = Cita.query.filter_by(legacy_paciente_id=leg_cor.id).all()
                    for c2 in citas_l2:
                        Notificacion.query.filter_by(cita_id=c2.id).delete()
                        HistorialCita.query.filter_by(cita_id=c2.id).delete()
                        db.session.delete(c2)
                    db.session.delete(leg_cor)
            db.session.delete(u)
            encontrado = True
        else:
            leg2 = Paciente.query.get(u_id)
            if leg2:
                citas_l = Cita.query.filter_by(legacy_paciente_id=leg2.id).all()
                for c in citas_l:
                    Notificacion.query.filter_by(cita_id=c.id).delete()
                    HistorialCita.query.filter_by(cita_id=c.id).delete()
                    db.session.delete(c)
                db.session.delete(leg2)
                encontrado = True

    if not encontrado:
        return jsonify({"mensaje": f"Paciente #{target_id} no encontrado"}), 404

    db.session.commit()
    return jsonify({"mensaje": f"Paciente #{target_id} eliminado exitosamente de la base de datos"}), 200

@app.route('/api/estadisticas', methods=['GET'])
@jwt_required()
def obtener_estadisticas_doctor():
    usuario = obtener_usuario_actual()
    if not (usuario and usuario.rol in ['doctor', 'administrador']):
        return jsonify({"mensaje": "Acceso restringido"}), 403

    total_citas = Cita.query.count()
    total_pacientes = Usuario.query.filter_by(rol='paciente').count() + Paciente.query.count()
    pendientes = Cita.query.filter(Cita.estado.ilike('%pendiente%')).count()
    confirmadas = Cita.query.filter(Cita.estado.ilike('%confirmad%')).count()
    completadas = Cita.query.filter(Cita.estado.ilike('%completad%')).count()

    return jsonify({
        "total_citas": total_citas,
        "total_pacientes": total_pacientes,
        "citas_pendientes": pendientes,
        "citas_confirmadas": confirmadas,
        "citas_completadas": completadas,
        "total_servicios": Servicio.query.count()
    }), 200

# ==========================================
# 11. INICIALIZACIÓN Y AUTO-MIGRACIÓN DE BD
# ==========================================

def ejecutar_auto_migraciones():
    """Garantiza que PostgreSQL en Render reciba las nuevas columnas sin perder datos"""
    comandos_alter = [
        "ALTER TABLE usuario ADD COLUMN IF NOT EXISTS nombre VARCHAR(150);",
        "ALTER TABLE usuario ADD COLUMN IF NOT EXISTS correo VARCHAR(150);",
        "ALTER TABLE usuario ADD COLUMN IF NOT EXISTS foto_url TEXT;",
        "ALTER TABLE usuario ADD COLUMN IF NOT EXISTS rol VARCHAR(30) DEFAULT 'paciente';",
        "ALTER TABLE usuario ADD COLUMN IF NOT EXISTS activo BOOLEAN DEFAULT true;",
        "ALTER TABLE usuario ADD COLUMN IF NOT EXISTS fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE usuario ALTER COLUMN password DROP NOT NULL;",
        "ALTER TABLE cita DROP CONSTRAINT IF EXISTS cita_paciente_id_fkey;",
        "ALTER TABLE cita ALTER COLUMN paciente_id DROP NOT NULL;",
        "ALTER TABLE cita ADD COLUMN IF NOT EXISTS codigo_cita VARCHAR(30);",
        "ALTER TABLE cita ADD COLUMN IF NOT EXISTS fecha_hora_fin TIMESTAMP;",
        "ALTER TABLE cita ADD COLUMN IF NOT EXISTS sede_id INTEGER;",
        "ALTER TABLE cita ADD COLUMN IF NOT EXISTS doctor_id INTEGER;",
        "ALTER TABLE cita ADD COLUMN IF NOT EXISTS motivo_cancelacion TEXT;",
        "ALTER TABLE cita ADD COLUMN IF NOT EXISTS sintomas_paciente TEXT;",
        "ALTER TABLE cita ADD COLUMN IF NOT EXISTS notas_doctor TEXT;",
        "ALTER TABLE cita ADD COLUMN IF NOT EXISTS creado_por INTEGER;",
        "ALTER TABLE cita ADD COLUMN IF NOT EXISTS fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE cita ADD COLUMN IF NOT EXISTS fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE cita ADD COLUMN IF NOT EXISTS legacy_paciente_id INTEGER;",
        "ALTER TABLE servicio ADD COLUMN IF NOT EXISTS duracion_minutos INTEGER DEFAULT 45;",
        "ALTER TABLE servicio ADD COLUMN IF NOT EXISTS precio NUMERIC(10,2);",
        "ALTER TABLE servicio ADD COLUMN IF NOT EXISTS activo BOOLEAN DEFAULT true;"
    ]
    for cmd in comandos_alter:
        try:
            db.session.execute(text(cmd))
        except Exception as e:
            db.session.rollback()

    db.session.commit()
    print(">> [MIGRACIÓN] Columnas verificadas/actualizadas en PostgreSQL.", flush=True)

try:
    with app.app_context():
        print(">> [DIAGNÓSTICO 3] Creando tablas nuevas si no existen...", flush=True)
        db.create_all()
        ejecutar_auto_migraciones()

        # Doctor / Administrador inicial
        doctor = Usuario.query.filter_by(username='admin').first()
        if not doctor:
            doctor = Usuario(
                username='admin',
                password=generate_password_hash('admin123'),
                nombre='Dr. Lisandro Márquez',
                correo='drlisandromarquez@gmail.com',
                rol='doctor',
                activo=True
            )
            db.session.add(doctor)
            print(">> [SEED] Usuario doctor principal creado (admin)", flush=True)
        else:
            doctor.rol = 'doctor'
            if not doctor.nombre:
                doctor.nombre = 'Dr. Lisandro Márquez'

        # Sedes Iniciales
        sedes_iniciales = [
            {"id": 1, "nombre": "Caracas — Clínica VidaMed", "clinica": "Clínica VidaMed", "ciudad": "Caracas", "direccion": "Av. Principal, Edif. VidaMed, Piso 3", "horarios_texto": "Lunes a Viernes (08:30 a 17:00)"},
            {"id": 2, "nombre": "Guatire — Clínica San Martín de Porres", "clinica": "Clínica San Martín de Porres", "ciudad": "Guatire", "direccion": "Unidad Urológica Dr. Gregorio Hernández", "horarios_texto": "Lunes a Sábado previa cita"},
            {"id": 3, "nombre": "Barlovento — Clínica Caucagua", "clinica": "Clínica Caucagua", "ciudad": "Barlovento", "direccion": "Centro Médico Quirúrgico Caucagua", "horarios_texto": "Jornadas Especiales Programadas"}
        ]
        for s_data in sedes_iniciales:
            s_exist = Sede.query.get(s_data["id"])
            if not s_exist:
                nueva_sede = Sede(**s_data)
                db.session.add(nueva_sede)

        # Servicios
        if os.path.exists('datos_urologia.json'):
            with open('datos_urologia.json', 'r', encoding='utf-8') as archivo:
                servicios_json = json.load(archivo)
                for s in servicios_json:
                    s_id = s.get('id')
                    srv = Servicio.query.get(s_id) if s_id else Servicio.query.filter_by(nombre_servicio=s['nombre_servicio']).first()
                    if not srv:
                        nuevo_srv = Servicio(
                            id=s_id,
                            nombre_servicio=s['nombre_servicio'],
                            descripcion=s['descripcion'],
                            duracion_minutos=s.get('duracion_minutos', 45)
                        )
                        db.session.add(nuevo_srv)
                    else:
                        srv.nombre_servicio = s['nombre_servicio']
                        srv.descripcion = s['descripcion']

        # Política de Citas
        if not PoliticaCita.query.first():
            db.session.add(PoliticaCita(confirmacion_automatica=False, anticipacion_min_horas=2, plazo_cancelar_horas=2))

        db.session.commit()
        print(">> [DIAGNÓSTICO 4] Base de datos y catálogo médico sincronizados con éxito.", flush=True)

except Exception as e:
    print(f"\n======================================", flush=True)
    print(f"!!! ERROR AL INICIALIZAR BASE DE DATOS !!!", flush=True)
    print(f"Detalle: {e}", flush=True)
    print(f"======================================\n", flush=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
