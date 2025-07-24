from app import app, db
from sqlalchemy import text

with app.app_context():
    try:
        db.session.execute(text("ALTER TABLE cv_profesional ADD COLUMN cv_archivo TEXT"))
        db.session.commit()
        print("✅ Columna 'cv_archivo' agregada correctamente")
    except Exception as e:
        print("🟡 Ya existe o error:", e)
