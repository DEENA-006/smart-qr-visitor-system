import os
from run import app, db

# Auto-initialize database tables if running on Vercel and tables do not exist
if os.environ.get('VERCEL'):
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

# Expose WSGI application object for Vercel Python serverless runtime
app = app
