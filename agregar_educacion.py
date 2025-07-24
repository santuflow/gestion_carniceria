from app import app, db
from sqlalchemy import text  # <-- IMPORTANTE

with app.app_context():
    try:
        db.session.execute(text('ALTER TABLE cv_profesional ADD COLUMN educacion TEXT;'))
        db.session.commit()
        print("✅ Columna 'educacion' agregada correctamente.")
    except Exception as e:
        print("❌ Error al agregar la columna:", e)
