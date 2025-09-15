from pytz import timezone
arg_tz = timezone('America/Argentina/Buenos_Aires')

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
import os
import json
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from datetime import datetime
from authlib.integrations.flask_client import OAuth


app = Flask(__name__)
app.secret_key = 'clave_secreta'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

from datetime import timedelta  # asegurate de tenerlo

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_SECURE'] = False  # permite cookies sin HTTPS (necesario en móviles si usás http)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # compatible con la mayoría de navegadores
app.config['SESSION_COOKIE_HTTPONLY'] = True  # protege la cookie de accesos por JavaScript



# Base de datos
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

from io import BytesIO

login_manager = LoginManager(app)
login_manager.login_view = 'index'


# ————— MODELOS —————

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    nombre = db.Column(db.String(100))  # Para nombre real desde Gmail
    foto = db.Column(db.String(300))  # URL de imagen de perfil (Gmail o manual)
    tipo_perfil = db.Column(db.String(50))  # busca trabajo / ofrece empleo / proveedor
    zona = db.Column(db.String(100), default='sin especificar')
    descripcion = db.Column(db.Text)
    experiencia = db.Column(db.Text)
    roles = db.Column(db.String(200))  # carnicero, franquero, etc.
    cv_archivo = db.Column(db.String(200))  # ruta al archivo subido
    is_admin = db.Column(db.Boolean, default=False)

    balances = db.relationship('Balance', backref='user', lazy=True)



class Balance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # Etiqueta
    tipo_animal = db.Column(db.String(50))
    frigorifico = db.Column(db.String(100))
    fecha_faena = db.Column(db.Date)
    observaciones = db.Column(db.Text)
    # Media res
    fecha_compra = db.Column(db.Date, nullable=False)
    precio_kilo_media_res = db.Column(db.Float, nullable=False)
    peso_total_media_res = db.Column(db.Float, nullable=False)
    costo_total_media_res = db.Column(db.Float, nullable=False)
    # Resultados
    total_ingresos_cortes = db.Column(db.Float, nullable=False)
    ganancias_netas_totales = db.Column(db.Float, nullable=False)
    detalles_cortes_json = db.Column(db.Text, nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=lambda: datetime.now(arg_tz))
    # Público?
    is_public = db.Column(db.Boolean, default=False)

class Caja(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    fecha_inicio = db.Column(db.DateTime, default=lambda: datetime.now(arg_tz))
    cerrada = db.Column(db.Boolean, default=False)
    ventas = db.relationship('Venta', backref='caja', lazy=True)



class Venta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    caja_id = db.Column(db.Integer, db.ForeignKey('caja.id'), nullable=False)
    numero_venta = db.Column(db.Integer, nullable=False)
    monto = db.Column(db.Float, nullable=False)
    tipo_pago = db.Column(db.String(50), nullable=False)

class CVProfesional(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    nombre = db.Column(db.String(100))
    fecha_nacimiento = db.Column(db.Date)
    zona = db.Column(db.String(100))
    descripcion = db.Column(db.Text)
    educacion = db.Column(db.Text)
    experiencia = db.Column(db.Text)
    habilidades = db.Column(db.Text)
    telefono = db.Column(db.String(50))
    email = db.Column(db.String(100))
    foto = db.Column(db.String(255))
    cv_archivo = db.Column(db.String(255))


class Provider(db.Model):
    __tablename__ = 'provider'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    nombre = db.Column(db.String(100), nullable=False)
    direccion = db.Column(db.String(200), nullable=False)
    zona = db.Column(db.String(100))
    contacto = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    zonas_reparto_json = db.Column(db.Text, default='[]')
    portada_path = db.Column(db.String(300))
    avatar_path  = db.Column(db.String(300))
    productos = db.relationship('ProviderProduct', backref='provider', cascade='all, delete-orphan', lazy=True)

class ProviderProduct(db.Model):
    __tablename__ = 'provider_product'
    id = db.Column(db.Integer, primary_key=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('provider.id'), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    precio = db.Column(db.String(50), nullable=False)
    imagen_path = db.Column(db.String(300))


# ====== FUNCIONES AUXILIARES ======
import time
from werkzeug.utils import secure_filename

ALLOWED_EXT = {'png','jpg','jpeg','webp'}

def save_image(file_storage, subdir='providers'):
    """Guarda la imagen en static/uploads/<subdir>/ con nombre único.
       Devuelve la ruta absoluta web: /static/uploads/<subdir>/<archivo>"""
    if not file_storage or file_storage.filename == '':
        return None

    # extensión segura
    filename = secure_filename(file_storage.filename)
    base, ext = os.path.splitext(filename)
    ext = ext.lower().lstrip('.')
    if ext not in ALLOWED_EXT:
        return None

    # carpeta destino
    folder = os.path.join(app.root_path, 'static', 'uploads', subdir)
    os.makedirs(folder, exist_ok=True)

    # nombre único
    unique = f"{current_user.id}_{int(time.time()*1000)}.{ext}"
    path_abs = os.path.join(folder, unique)
    file_storage.save(path_abs)

    # ruta para usar en <img src="...">
    return f"/static/uploads/{subdir}/{unique}"



# ————— LOGIN —————

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@login_manager.unauthorized_handler
def unauthorized():
    flash('Debes iniciar sesión para acceder.', 'info')
    return redirect(url_for('index'))




# ————— AUTENTICACIÓN —————

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json(force=True)
    u = data.get('username', '').lower()
    e = data.get('email')
    p = data.get('password')
    t = data.get('accept_terms')
    if not u or not e or not p:
        return jsonify(success=False, message='Faltan campos.'), 400
    if not t:
        return jsonify(success=False, message='Acepta términos.'), 400
    if User.query.filter(db.func.lower(User.username) == u).first():
        return jsonify(success=False, message='Usuario existe.'), 409
    if User.query.filter_by(email=e).first():
        return jsonify(success=False, message='Email registrado.'), 409
    user = User(
        username=u, email=e,
        password_hash=generate_password_hash(p, method='pbkdf2:sha256', salt_length=8)
    )
    db.session.add(user)
    db.session.commit()
    return jsonify(success=True, message='Registro OK'), 201


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(force=True)
    username_input = data.get('username', '').lower()
    user = User.query.filter(db.func.lower(User.username) == username_input).first()
    if user and check_password_hash(user.password_hash, data.get('password')):
        login_user(user)
        session.permanent = True
        return jsonify(success=True, redirect_url=url_for('index')), 200
    return jsonify(success=False, message='Credenciales inválidas'), 401



@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada.', 'success')
    return redirect(url_for('index'))




# ————— VISTAS PRINCIPALES —————



@app.route('/')
def index():
    visita = Visita.query.first()
    visitas_total = 0  # <--- Definimos un valor por defecto

    if not (current_user.is_authenticated and current_user.username.lower() == 'santua'):
        if visita:
            visita.total += 1
            db.session.commit()
    
    if visita:
        visitas_total = visita.total
        
    return render_template('index.html', visitas=visitas_total)




@app.route('/hacer_balance')
@login_required
def hacer_balance():
    return render_template('balance_form.html')


@app.route('/guardar_balance', methods=['POST'])
@login_required
def guardar_balance():
    d = request.get_json(force=True)
    # datos de etiqueta
    tipo = d.get('tipo_animal', '')
    fri = d.get('frigorifico', '')
    faena = d.get('fecha_faena', '')
    try:
        fecha_fa = datetime.strptime(faena, '%Y-%m-%d').date() if faena else None
    except:
        return jsonify(success=False, message='Fecha faena inválida'), 400
    obs = d.get('observaciones', '')
    # media res
    try:
        fecha_compra = datetime.strptime(d['fecha_compra'], '%Y-%m-%d').date()
    except:
        return jsonify(success=False, message='Fecha compra inválida'), 400
    precio = float(d.get('precio_kilo_media_res', 0))
    peso = float(d.get('peso_total_media_res', 0))
    if precio<=0 or peso<=0:
        return jsonify(success=False, message='Precio/peso inválido'), 400
    detalles = d.get('detalles_cortes', [])
    total_ing = sum([c.get('ingreso_bruto',0) for c in detalles])
    ganancia = total_ing - (precio*peso)
    b = Balance(
        user_id=current_user.id,
        tipo_animal=tipo,
        frigorifico=fri,
        fecha_faena=fecha_fa,
        observaciones=obs,
        fecha_compra=fecha_compra,
        precio_kilo_media_res=precio,
        peso_total_media_res=peso,
        costo_total_media_res=round(precio*peso,2),
        total_ingresos_cortes=round(total_ing,2),
        ganancias_netas_totales=round(ganancia,2),
        detalles_cortes_json=json.dumps(detalles),
        is_public=False
    )
    db.session.add(b)
    db.session.commit()
    return jsonify(success=True, balance_id=b.id), 201


@app.route('/balances')
@login_required
def balances():
    page = request.args.get('page', 1, type=int)
    pag = Balance.query.filter_by(is_public=True)\
        .order_by(Balance.fecha_creacion.desc())\
        .paginate(page=page, per_page=20, error_out=False)
    for bal in pag.items:
        bal.detalles = json.loads(bal.detalles_cortes_json or '[]')
    return render_template('balances.html',
        balances=pag.items, pagination=pag
    )


@app.route('/mis_balances')
@login_required
def mis_balances():
    page = request.args.get('page', 1, type=int)
    pag = Balance.query.filter_by(user_id=current_user.id)\
        .order_by(Balance.fecha_creacion.desc())\
        .paginate(page=page, per_page=20, error_out=False)
    for bal in pag.items:
        bal.detalles = json.loads(bal.detalles_cortes_json or '[]')
    return render_template('mis_balances.html',
        balances=pag.items, pagination=pag
    )


@app.route('/api/balance/<int:balance_id>')
@login_required
def api_get_balance(balance_id):
    b = db.session.get(Balance, balance_id)
    if not b:
        return jsonify(error='No existe'), 404
    detalles = json.loads(b.detalles_cortes_json or '[]')
    return jsonify({
        'id': b.id,
        'fecha_compra': b.fecha_compra.strftime('%d/%m/%Y'),
        'precio_kilo_media_res': b.precio_kilo_media_res,
        'peso_total_media_res': b.peso_total_media_res,
        'costo_total_media_res': b.costo_total_media_res,
        'total_ingresos_cortes': b.total_ingresos_cortes,
        'ganancias_netas_totales': b.ganancias_netas_totales,
        'detalles_cortes': detalles,
        'fecha_creacion': b.fecha_creacion.strftime('%d/%m/%Y %H:%M'),
        'tipo_animal': b.tipo_animal,
        'frigorifico': b.frigorifico,
        'fecha_faena': b.fecha_faena.strftime('%d/%m/%Y') if b.fecha_faena else '',
        'observaciones': b.observaciones
    })


@app.route('/download_balance/<int:balance_id>')
@login_required
def download_balance(balance_id):
    b = db.session.get(Balance, balance_id)
    if not b:
        flash('No encontrado', 'error')
        return redirect(url_for('balances'))
    dets = json.loads(b.detalles_cortes_json or '[]')
    out = BytesIO()
    out.write(f"Balance ID: {b.id}\nUsuario: {b.user.username}\n".encode())
    out.write(f"Fecha Compra: {b.fecha_compra.strftime('%d/%m/%Y')}\n".encode())
    out.write(f"Tipo Animal: {b.tipo_animal}\n".encode())
    out.write(f"Frigorífico: {b.frigorifico}\n".encode())
    out.write(f"Fecha Faena: {b.fecha_faena.strftime('%d/%m/%Y') if b.fecha_faena else ''}\n".encode())
    out.write(f"Observaciones: {b.observaciones}\n\n".encode())
    out.write(f"Total Ingresos Cortes: ${b.total_ingresos_cortes:.2f}\n".encode())
    out.write(f"Ganancia Neta: ${b.ganancias_netas_totales:.2f}\n\n".encode())
    out.write("Detalles de Cortes:\n".encode())
    for c in dets:
        out.write(f"- {c['nombre']}: {c['peso']}kg x ${c['precio_venta']} = ${c['ingreso_bruto']}\n".encode())
    out.seek(0)
    fn = f"balance_{b.id}_{b.fecha_compra.strftime('%Y%m%d')}.txt"
    return send_file(out, as_attachment=True, download_name=fn, mimetype='text/plain')


@app.route('/delete_balance/<int:balance_id>', methods=['POST'])
@login_required
def delete_balance(balance_id):
    b = db.session.get(Balance, balance_id)
    if not b or b.user_id!=current_user.id:
        flash('No tienes permiso', 'error')
        return redirect(url_for('balances'))
    db.session.delete(b)
    db.session.commit()
    flash('Eliminado', 'success')
    return redirect(url_for('balances'))


@app.route('/actualizar_balance_publico', methods=['POST'])
@login_required
def actualizar_balance_publico():
    data = request.get_json(force=True)
    bid = data.get('balance_id')
    b = db.session.get(Balance, bid)
    if not b or b.user_id!=current_user.id:
        return jsonify(success=False, message='No permitido'), 403
    b.is_public = True
    db.session.commit()
    return jsonify(success=True, message='Balance compartido públicamente')


# ————— GESTIÓN DE CAJA (VENTAS) —————

@app.route('/abrir_caja')
@login_required
def abrir_caja():

    return render_template('abrir_caja.html')

@app.route('/armar_cv')
@login_required
def armar_cv():
    return render_template('armar_cv.html')




@app.route('/api/iniciar_caja', methods=['POST'])
@login_required
def iniciar_caja():
    # Verificar si ya hay una caja abierta
    caja_abierta = Caja.query.filter_by(user_id=current_user.id, cerrada=False).first()
    if caja_abierta:
        return jsonify(success=True, caja_id=caja_abierta.id), 200

    # Si no hay caja abierta, crear una nueva
    nueva_caja = Caja(user_id=current_user.id, cerrada=False)
    db.session.add(nueva_caja)
    db.session.commit()
    return jsonify(success=True, caja_id=nueva_caja.id), 201





@app.route('/api/ventas_dia', methods=['GET'])
@login_required
def api_ventas_dia():
    # Buscar la última caja abierta del usuario
    caja = Caja.query.filter_by(user_id=current_user.id, cerrada=False).order_by(Caja.id.desc()).first()
    if not caja:
        return jsonify(ventas=[]), 200

    ventas = Venta.query.filter_by(caja_id=caja.id).all()
    data = [
        {
            'numero_venta': v.numero_venta,
            'monto': v.monto,
            'tipo_pago': v.tipo_pago
        } for v in ventas
    ]
    return jsonify(ventas=data), 200




@app.route('/api/registrar_venta', methods=['POST'])
@login_required
def api_registrar_venta():
    d = request.get_json(force=True)


    caja = Caja.query.filter_by(user_id=current_user.id, cerrada=False).order_by(Caja.id.desc()).first()
    if not caja:
        return jsonify(success=False, message='Caja no iniciada'), 400

    try:
        monto = float(d.get('monto', 0))
        tipo = d.get('tipo_pago', 'Efectivo')
    except:
        return jsonify(success=False, message='Datos inválidos'), 400

    num = Venta.query.filter_by(caja_id=caja.id).count() + 1

    venta = Venta(
        user_id=current_user.id,
        caja_id=caja.id,
        numero_venta=num,
        monto=monto,
        tipo_pago=tipo
    )

    db.session.add(venta)
    db.session.commit()
    return jsonify(success=True), 201


@app.route('/subir_cv_profesional', methods=['POST'])
@login_required
def subir_cv_profesional():
    nombre = request.form.get('nombre') or 'No especificado'
    fecha_nacimiento_raw = request.form.get('fecha_nacimiento')
    fecha_nacimiento = None

    if fecha_nacimiento_raw:
        try:
            if isinstance(fecha_nacimiento_raw, datetime):
                fecha_nacimiento_raw = fecha_nacimiento_raw.strftime('%d/%m/%Y')
            else:
                fecha_nacimiento_raw = str(fecha_nacimiento_raw).strip()

            if '/' in fecha_nacimiento_raw:
                fecha_nacimiento = datetime.strptime(fecha_nacimiento_raw, '%d/%m/%Y').date()
            elif '-' in fecha_nacimiento_raw:
                fecha_nacimiento = datetime.strptime(fecha_nacimiento_raw, '%d-%m-%Y').date()
            else:
                raise ValueError("Formato inválido")
        except ValueError:
            flash('Fecha de nacimiento inválida. Usá el formato DD/MM/AAAA o DD-MM-AAAA.')
            return redirect(request.referrer or url_for('index'))

    zona = request.form.get('zona') or 'No especificado'
    descripcion = request.form.get('descripcion') or 'Sin descripción'
    experiencia = request.form.get('experiencia') or 'No especificado'
    habilidades = request.form.get('habilidades') or 'No especificado'
    telefono = request.form.get('telefono') or 'No disponible'
    email = request.form.get('email') or current_user.email

    # Guardar archivo de foto si viene
    foto = request.files.get('foto')
    foto_filename = None
    if foto and foto.filename != '':
        from werkzeug.utils import secure_filename
        import os
        user_id = current_user.id
        ext = os.path.splitext(foto.filename)[1]
        foto_filename = f"{user_id}_{secure_filename(foto.filename)}"
        foto.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], foto_filename))

    educacion = request.form.get('educacion') or 'No especificada'

    empresa1 = request.form.get("empresa1") or ''
    cargo1 = request.form.get("cargo1") or ''
    exp1 = request.form.get("exp1") or ''

    empresa2 = request.form.get("empresa2") or ''
    cargo2 = request.form.get("cargo2") or ''
    exp2 = request.form.get("exp2") or ''

    experiencia = ""
    if empresa1 or cargo1 or exp1:
        experiencia += f"- {empresa1} ({cargo1}): {exp1}\n"
    if empresa2 or cargo2 or exp2:
        experiencia += f"- {empresa2} ({cargo2}): {exp2}"
    if not experiencia.strip():
        experiencia = "No especificado"


    nuevo_cv = CVProfesional(
        user_id=current_user.id,
        nombre=nombre,
        fecha_nacimiento=fecha_nacimiento,
        zona=zona,
        descripcion=descripcion,
        educacion=educacion,
        experiencia=experiencia,
        habilidades=habilidades,
        telefono=telefono,
        email=email,
        foto=foto_filename
    )
    db.session.add(nuevo_cv)
    db.session.commit()

    flash('CV cargado exitosamente.')
    return redirect(url_for('carniceros_cv'))




@app.route('/carniceros_cv')
def carniceros_cv():
    cvs = CVProfesional.query.order_by(CVProfesional.id.desc()).all()
    zonas = sorted(set(cv.zona for cv in cvs if cv.zona))  # para el filtro por zona
    return render_template('carniceros_cv.html', cvs=cvs, zonas=zonas, now=datetime.now())



@app.route('/ver_cv/<int:id>')
def ver_cv(id):
    cv = CVProfesional.query.get_or_404(id)
    return render_template('ver_cv.html', cv=cv)



@app.route('/api/cerrar_caja', methods=['POST'])
@login_required
def api_cerrar_caja():
    caja = Caja.query.filter_by(user_id=current_user.id, cerrada=False).order_by(Caja.id.desc()).first()
    if not caja:
        return jsonify(success=False, message='No hay caja activa'), 400

    ventas = Venta.query.filter_by(caja_id=caja.id).all()
    resumen = {
        'total_ventas': len(ventas),
        'totales': {'Efectivo': 0.0, 'Tarjeta': 0.0, 'Transferencia': 0.0}
    }

    for v in ventas:
        resumen['totales'][v.tipo_pago] += v.monto

    caja.cerrada = True
    db.session.commit()

    return jsonify(success=True, resumen=resumen), 200

# --- PROVEEDORES ---

# ==== RUTAS CORREGIDAS PARA PROVEEDOR ====

@app.route("/soy_proveedor")
@login_required
def soy_proveedor():
    existing = Provider.query.filter_by(user_id=current_user.id).first()
    if existing:
        return redirect(url_for('ver_proveedor', id=existing.id))
    return render_template("soy_proveedor.html")


@app.route('/publicar_proveedor', methods=['POST'])
@login_required
def publicar_proveedor():
    nombre      = (request.form.get('nombre') or '').strip()
    direccion   = (request.form.get('direccion') or '').strip()
    contacto    = (request.form.get('contacto') or '').strip()
    descripcion = (request.form.get('descripcion') or '').strip()
    zonas_reparto = request.form.getlist('zonas_reparto[]')

    if not nombre or not direccion or not contacto or not zonas_reparto:
        flash('Completá nombre, dirección, contacto y zonas de reparto.', 'warning')
        return redirect(request.referrer or url_for('soy_proveedor'))

    # 1) Crear o actualizar el proveedor **sin** imágenes todavía
    provider = Provider.query.filter_by(user_id=current_user.id).first()
    if not provider:
        provider = Provider(
            user_id=current_user.id,
            nombre=nombre,
            direccion=direccion,
            contacto=contacto,
            descripcion=descripcion,
            zonas_reparto_json=json.dumps(zonas_reparto),
            portada_path=None,
            avatar_path=None
        )
        db.session.add(provider)
        db.session.flush()  # Necesitamos provider.id para armar subcarpetas
    else:
        provider.nombre = nombre
        provider.direccion = direccion
        provider.contacto = contacto
        provider.descripcion = descripcion
        provider.zonas_reparto_json = json.dumps(zonas_reparto)
        db.session.flush()  # Aseguramos que provider.id esté disponible

    # 2) Guardar imágenes (ya con provider.id disponible)
    portada_fs = request.files.get('portada')
    avatar_fs  = request.files.get('avatar')

    if portada_fs and portada_fs.filename:
        # guarda en /static/uploads/providers/<id>/
        provider.portada_path = save_image(portada_fs, f'providers/{provider.id}')
    if avatar_fs and avatar_fs.filename:
        provider.avatar_path = save_image(avatar_fs, f'providers/{provider.id}')

    # 3) Guardar productos NUEVOS (no borramos los existentes)
    nombres  = request.form.getlist('producto_nombre[]')
    precios  = request.form.getlist('producto_precio[]')
    imagenes = request.files.getlist('producto_imagen[]')

    # Nota: si querés forzar imagen obligatoria, verificá img_url antes de crear
    for i in range(len(nombres)):
        nom = (nombres[i] or '').strip()
        pre = (precios[i] or '').strip()
        if not (nom and pre):
            continue

        img_fs = imagenes[i] if i < len(imagenes) else None
        img_url = save_image(img_fs, f'providers/{provider.id}/products') if (img_fs and img_fs.filename) else None

        db.session.add(ProviderProduct(
            provider_id=provider.id,
            nombre=nom,
            precio=pre,
            imagen_path=img_url
        ))

    db.session.commit()
    flash('Perfil de proveedor publicado/actualizado.', 'success')
    return redirect(url_for('ver_proveedor', id=provider.id))

@app.route('/ver_proveedor/<int:id>')
def ver_proveedor(id):
    provider = Provider.query.get_or_404(id)
    zonas = json.loads(provider.zonas_reparto_json or '[]')
    productos = ProviderProduct.query.filter_by(provider_id=provider.id).all()
    es_dueno = current_user.is_authenticated and (provider.user_id == current_user.id)
    return render_template('ver_proveedor.html',
                           p=provider, zonas=zonas, productos=productos, es_dueno=es_dueno)

# --- EDITAR PERFIL (muestra el mismo form con datos precargados) ---
@app.route('/proveedor/<int:id>/editar', methods=['GET'])
@login_required
def editar_proveedor(id):
    p = Provider.query.get_or_404(id)
    if p.user_id != current_user.id:
        flash('No podes editar este perfil.', 'warning')
        return redirect(url_for('ver_proveedor', id=id))

    productos = ProviderProduct.query.filter_by(provider_id=p.id).all()
    zonas = json.loads(p.zonas_reparto_json or '[]')
    # usamos el mismo template "soy_proveedor.html" pero en modo edición
    return render_template('soy_proveedor.html', p=p, zonas_existentes=zonas, productos_existentes=productos, modo_edicion=True)


# --- CREAR PRODUCTO DESDE EL PERFIL ---
@app.route('/proveedor/<int:provider_id>/producto/nuevo', methods=['POST'])
@login_required
def crear_producto(provider_id):
    prov = Provider.query.get_or_404(provider_id)
    if prov.user_id != current_user.id:
        flash('No tenés permiso para agregar productos aquí.', 'warning')
        return redirect(url_for('ver_proveedor', id=provider_id))

    nombre = (request.form.get('nombre') or '').strip()
    precio = (request.form.get('precio') or '').strip()
    img_fs = request.files.get('imagen')

    if not nombre or not precio:
        flash('Completá nombre y precio.', 'warning')
        return redirect(url_for('ver_proveedor', id=provider_id))

    img_url = None
    if img_fs and img_fs.filename:
        img_url = save_image(img_fs, f'providers/{prov.id}/products')

    prod = ProviderProduct(
        provider_id=prov.id,
        nombre=nombre,
        precio=precio,
        imagen_path=img_url
    )
    db.session.add(prod)
    db.session.commit()
    flash('Producto agregado.', 'success')
    return redirect(url_for('ver_proveedor', id=provider_id))


# --- ACTUALIZAR PRODUCTO DESDE EL PERFIL ---
@app.route('/producto/<int:prod_id>/actualizar', methods=['POST'])
@login_required
def actualizar_producto(prod_id):
    prod = ProviderProduct.query.get_or_404(prod_id)
    prov = Provider.query.get_or_404(prod.provider_id)
    if prov.user_id != current_user.id:
        flash('No tenés permiso para editar este producto.', 'warning')
        return redirect(url_for('ver_proveedor', id=prov.id))

    nombre = (request.form.get('nombre') or '').strip()
    precio = (request.form.get('precio') or '').strip()
    img_fs = request.files.get('imagen')

    if nombre:
        prod.nombre = nombre
    if precio:
        prod.precio = precio
    if img_fs and img_fs.filename:
        prod.imagen_path = save_image(img_fs, f'providers/{prov.id}/products')

    db.session.commit()
    flash('Producto actualizado.', 'success')
    return redirect(url_for('ver_proveedor', id=prov.id))


# --- ELIMINAR PRODUCTO ---
@app.route('/producto/<int:prod_id>/eliminar', methods=['POST'])
@login_required
def eliminar_producto(prod_id):
    prod = ProviderProduct.query.get_or_404(prod_id)
    prov = Provider.query.get_or_404(prod.provider_id)
    if prov.user_id != current_user.id:
        flash('No tenés permiso para eliminar este producto.', 'warning')
        return redirect(url_for('ver_proveedor', id=prov.id))

    db.session.delete(prod)
    db.session.commit()
    flash('Producto eliminado.', 'success')
    return redirect(request.referrer or url_for('ver_proveedor', id=prov.id))

@app.route('/proveedores')
def proveedores():
    # parámetros de búsqueda
    q = (request.args.get('q') or '').strip().lower()
    zona_filtro = (request.args.get('zona') or '').strip().lower()

    # traemos todo y filtramos en Python (zonas están guardadas como JSON en un Text)
    all_provs = Provider.query.order_by(Provider.id.desc()).all()

    # todas las zonas únicas (para el combo)
    zonas_unicas = set()
    for p in all_provs:
        try:
            for z in json.loads(p.zonas_reparto_json or '[]'):
                zonas_unicas.add(z)
        except Exception:
            pass
    zonas_unicas = sorted(zonas_unicas)

    # filtrado por nombre y zona
    items = []
    for p in all_provs:
        zonas = []
        try:
            zonas = json.loads(p.zonas_reparto_json or '[]')
        except Exception:
            zonas = []

        if q and q not in (p.nombre or '').lower():
            continue
        if zona_filtro and zona_filtro not in [z.lower() for z in zonas]:
            continue

        items.append({'p': p, 'zonas': zonas})

    return render_template('proveedores.html',
                           items=items,
                           zonas=zonas_unicas,
                           q=q,
                           zona=zona_filtro)

@app.route('/historial_cajas')
@login_required
def historial_cajas():
    cajas = Caja.query.filter_by(user_id=current_user.id).order_by(Caja.fecha_inicio.desc()).all()

    cajas_con_resumen = []
    for caja in cajas:
        ventas = Venta.query.filter_by(caja_id=caja.id).all()
        resumen = {
            'total_ventas': len(ventas),
            'totales': {
                'Efectivo': 0,
                'Tarjeta': 0,
                'Transferencia': 0
            }
        }
        for venta in ventas:
            tipo = venta.tipo_pago
            if tipo in resumen['totales']:
                resumen['totales'][tipo] += venta.monto

        caja_data = {
            'id': caja.id,
            'fecha': caja.fecha_inicio.strftime('%d/%m/%Y %H:%M'),
            'resumen': resumen if ventas else None
        }
        cajas_con_resumen.append(caja_data)

    return render_template('historial_cajas.html', cajas=cajas_con_resumen)



@app.route('/ver_caja/<int:caja_id>')
@login_required
def ver_caja(caja_id):
    caja = Caja.query.filter_by(id=caja_id, user_id=current_user.id).first()
    if not caja:
        flash('Caja no encontrada o acceso no autorizado', 'error')
        return redirect(url_for('historial_cajas'))

    ventas = Venta.query.filter_by(caja_id=caja.id).all()

    totales = {'Efectivo': 0.0, 'Tarjeta': 0.0, 'Transferencia': 0.0}
    for v in ventas:
        totales[v.tipo_pago] += v.monto

    resumen = {
        'total_ventas': len(ventas),
        'totales': totales
    }

    caja_data = {
        'id': caja.id,
        'fecha_inicio': caja.fecha_inicio.strftime('%d/%m/%Y %H:%M'),
        'resumen': resumen,
        'ventas': ventas
    }

    return render_template('ver_caja.html', caja=caja_data)



# ————— ARRANQUE —————

class Visita(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Integer, default=0)


with app.app_context():
    db.create_all()

    try:
        result = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='caja' AND column_name='cerrada';"))
        column_exists = result.fetchone() is not None

        if not column_exists:
            db.session.execute(text("ALTER TABLE caja ADD COLUMN cerrada BOOLEAN DEFAULT FALSE;"))
            db.session.commit()
            print("✅ Columna 'cerrada' agregada con éxito")
        else:
            print("✅ La columna 'cerrada' ya existe")
    except Exception as e:
        print("❌ Error al verificar/agregar la columna 'cerrada':", str(e))

    # Verificar y agregar columnas faltantes a la tabla cv_profesiona
    columnas_cv = {
        'nombre': 'VARCHAR(100)',
        'fecha_nacimiento': 'DATE',
        'zona': 'VARCHAR(100)',
        'descripcion': 'TEXT',
        'experiencia': 'TEXT',
        'habilidades': 'TEXT',
        'telefono': 'VARCHAR(50)',
        'email': 'VARCHAR(100)',
        'foto': 'VARCHAR(255)',
        'cv_archivo': 'VARCHAR(255)'
    }

    for columna, tipo in columnas_cv.items():
        try:
            resultado = db.session.execute(text(
                f"SELECT column_name FROM information_schema.columns WHERE table_name='cv_profesional' AND column_name='{columna}'"
            ))
            existe = resultado.fetchone() is not None
            if not existe:
                db.session.execute(text(
                    f"ALTER TABLE cv_profesional ADD COLUMN {columna} {tipo};"
                ))
                print(f"✅ Columna '{columna}' agregada a cv_profesional")
            else:
                print(f"🟢 Columna '{columna}' ya existe")
        except Exception as e:
            print(f"❌ Error al verificar/agregar columna '{columna}':", str(e))





@app.route('/total_usuarios')
@login_required
def total_usuarios():
    if current_user.email != 'santua@gmail.com' :
        return 'Acceso denegado', 403

    cantidad = User.query.count()
    return f'Total de usuarios registrados: {cantidad}'

# --- CONFIGURACIÓN DEL LOGIN CON GOOGLE ---
oauth = OAuth(app)

google = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)


from flask import session



@app.route('/login/gmail')
def login_gmail():
    return google.authorize_redirect(
        redirect_uri='https://carni0.com/login/callback'
    )

@app.route('/login/callback')
def gmail_callback():
    try:
        token = google.authorize_access_token()
        # 🚨 Usa el endpoint correcto de Google desde los metadatos
        userinfo_endpoint = google.load_server_metadata()["userinfo_endpoint"]
        resp = google.get(userinfo_endpoint, token=token)
        user_info = resp.json()

        email = user_info.get("email")
        name = user_info.get("name")
        picture = user_info.get("picture")

        if not email:
            flash("No se pudo obtener el correo electrónico desde Google.", "danger")
            return redirect(url_for("index"))

        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(
                username=email.split("@")[0],
                email=email,
                password_hash='',  # ✅ CORREGIDO
                nombre=name,
                tipo_perfil='busca trabajo',
                zona='sin especificar',
                descripcion='',
                experiencia='',
                roles='',
                cv_archivo='',
                foto=picture or '',
                is_admin=False
            )
            db.session.add(user)
            db.session.commit()

        login_user(user)
        flash("Sesión iniciada con Gmail correctamente", "success")
        return redirect(url_for("index"))

    except Exception as e:
        flash(f"Error durante el login con Gmail: {str(e)}", "danger")
        return redirect(url_for("index"))

from flask import request, render_template_string

IP_PERMITIDA = '190.99.71.6'  # ← tu IP real

@app.before_request
def limitar_acceso_por_ip():
    ip_cliente = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ',' in ip_cliente:
        ip_cliente = ip_cliente.split(',')[0].strip()

    if ip_cliente != IP_PERMITIDA:
        return render_template_string("""
            <!DOCTYPE html>
            <html>
            <head>
              <title>Este sitio está en desarrollo.</title>
              <style>
                body {
                  background-color: #111;
                  color: white;
                  font-family: Arial, sans-serif;
                  text-align: center;
                  padding-top: 100px;
                }
              </style>
            </head>
            <body>
              <h1>🚧 Sitio en desarrollo</h1>
              <p>Acceso restringido temporalmente</p>
            </body>
            </html>
        """), 403




if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')

# SOLO UNA VEZ para agregar columnas si no existen
with app.app_context():
    from sqlalchemy import text
    columnas = {
        'nombre': 'VARCHAR(100)',
        'foto': 'VARCHAR(300)',
        'tipo_perfil': 'VARCHAR(50)',
        'zona': 'VARCHAR(100)',
        'descripcion': 'TEXT',
        'experiencia': 'TEXT',
        'roles': 'TEXT',
        'cv_archivo': 'VARCHAR(300)',
        'is_admin': 'BOOLEAN DEFAULT false'
    }

    for columna, tipo in columnas.items():
        try:
            db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN {columna} {tipo}'))
            print(f'Columna {columna} agregada.')
        except Exception as e:
            print(f'Columna {columna} ya existe o error: {e}')

    db.session.commit()
