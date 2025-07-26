from app import app, db
from sqlalchemy import text

with app.app_context():
    columnas = {
        'nombre': 'VARCHAR(100)',
        'foto': 'VARCHAR(300)',
        'tipo_perfil': 'VARCHAR(50)',
        'zona': 'VARCHAR(100)',
        'descripcion': 'TEXT',
        'experiencia': 'TEXT',
        'roles': 'TEXT',
        'cv_archivo': 'VARCHAR(300)',
        'is_admin': 'BOOLEAN'
    }

    for nombre, tipo in columnas.items():
        try:
            db.session.execute(text(f'ALTER TABLE "user" ADD COLUMN IF NOT EXISTS {nombre} {tipo}'))
            db.session.commit()
            print(f'✔ Columna agregada o ya existente: {nombre}')
        except Exception as e:
            print(f'❌ Error al agregar columna {nombre}: {e}')
