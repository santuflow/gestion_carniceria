from pytz import timezone
arg_tz = timezone('America/Argentina/Buenos_Aires')

from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    jsonify, send_file, session
)
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json
from io import BytesIO

app = Flask(__name__)
from flask import Flask, request, redirect
app.config['SECRET_KEY'] = 'tu_clave_secreta_aqui_CAMBIA_ESTO_POR_UNA_CLAVE_SEGURA_Y_UNICA!'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///carniceria.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'index'


# ————— MODELOS —————

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
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
    u = data.get('username'); e = data.get('email')
    p = data.get('password'); t = data.get('accept_terms')
    if not u or not e or not p:
        return jsonify(success=False, message='Faltan campos.'), 400
    if not t:
        return jsonify(success=False, message='Acepta términos.'), 400
    if User.query.filter_by(username=u).first():
        return jsonify(success=False, message='Usuario existe.'), 409
    if User.query.filter_by(email=e).first():
        return jsonify(success=False, message='Email registrado.'), 409
    user = User(
        username=u, email=e,
        password_hash=generate_password_hash(p)
    )
    db.session.add(user)
    db.session.commit()
    return jsonify(success=True, message='Registro OK'), 201


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(force=True)
    user = User.query.filter_by(username=data.get('username')).first()
    if user and check_password_hash(user.password_hash, data.get('password')):
        login_user(user)
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
    return render_template('index.html')


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
    # inicializar ventas del día
    session.setdefault('ventas', [])
    return render_template('abrir_caja.html')


@app.route('/api/ventas_dia', methods=['GET'])
@login_required
def api_ventas_dia():
    return jsonify({'ventas': session.get('ventas', [])}), 200


@app.route('/api/registrar_venta', methods=['POST'])
@login_required
def api_registrar_venta():
    d = request.get_json(force=True)
    ventas = session.get('ventas', [])
    try:
        monto = float(d.get('monto', 0))
    except:
        return jsonify(success=False, message='Monto inválido'), 400
    tipo = d.get('tipo_pago') or 'Efectivo'
    num = int(d.get('numero_venta') or len(ventas)+1)
    venta = {'numero_venta': num, 'monto': monto, 'tipo_pago': tipo}
    ventas.append(venta)
    session['ventas'] = ventas
    return jsonify(success=True), 201


@app.route('/api/cerrar_caja', methods=['POST'])
@login_required
def api_cerrar_caja():
    ventas = session.pop('ventas', [])
    tot = {'Efectivo': 0.0, 'Tarjeta': 0.0, 'Transferencia': 0.0}
    for v in ventas:
        tot[v['tipo_pago']] += v['monto']
    resumen = {'total_ventas': len(ventas), 'totales': tot}
    # Guardar historial en sesión
    hist = session.get('historial_cajas', [])
    hist.append({
        'fecha_inicio': datetime.now(arg_tz).strftime('%d/%m/%Y'),
        'ventas': ventas,
        'resumen': resumen
    })
    session['historial_cajas'] = hist
    return jsonify(success=True, resumen=resumen), 200


@app.route('/historial_cajas')
@login_required
def historial_cajas():
    cajas = session.get('historial_cajas', [])
    return render_template('historial_cajas.html', cajas=cajas)


@app.route('/ver_caja/<int:caja_index>')
@login_required
def ver_caja(caja_index):
    cajas = session.get('historial_cajas', [])
    if caja_index<0 or caja_index>=len(cajas):
        flash('Caja no existe', 'error')
        return redirect(url_for('historial_cajas'))
    caja = cajas[caja_index]
    return render_template('ver_caja.html', caja=caja, index=caja_index)


# ————— ARRANQUE —————

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0')

