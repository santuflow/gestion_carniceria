from app import app, db, CVProfesional

with app.app_context():
    db.session.query(CVProfesional).delete()
    db.session.commit()
    print("🗑️ Todos los CVs fueron eliminados correctamente.")
