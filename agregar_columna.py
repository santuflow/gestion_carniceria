from app import app, db
from sqlalchemy import text  # <-- agregá esto

with app.app_context():
    try:
        db.session.execute(text('ALTER TABLE "user" ADD COLUMN is_admin BOOLEAN DEFAULT FALSE'))
        db.session.commit()
        print("Columna is_admin agregada correctamente.")
    except Exception as e:
        print("Error al agregar la columna:", e)
