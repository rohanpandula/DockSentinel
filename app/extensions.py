from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy(session_options={"expire_on_commit": False})
