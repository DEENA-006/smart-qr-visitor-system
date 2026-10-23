import os
from run import app, db

# Auto-initialize database tables if running on Vercel and tables do not exist
if os.environ.get('VERCEL'):
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass


class VercelPathFixer:
    """WSGI middleware to normalize PATH_INFO and SCRIPT_NAME on Vercel serverless."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        path_info = environ.get('PATH_INFO', '')

        # Handle entrypoint paths rewritten by Vercel
        if path_info in ('/api/index', '/api/index.py', '/api', '/api/'):
            real_path = (
                environ.get('HTTP_X_MATCHED_PATH') or
                environ.get('HTTP_X_FORWARDED_PATH') or
                environ.get('HTTP_X_FORWARDED_URI') or
                environ.get('HTTP_X_ORIGINAL_URI') or
                environ.get('RAW_URI', '').split('?')[0] or
                environ.get('REQUEST_URI', '').split('?')[0]
            )
            if real_path and real_path not in ('/api/index', '/api/index.py', '/api', '/api/'):
                environ['PATH_INFO'] = real_path
            else:
                environ['PATH_INFO'] = '/'
        elif path_info.startswith('/api/index/'):
            environ['PATH_INFO'] = '/' + path_info[len('/api/index/'):]
        elif path_info.startswith('/api/index.py/'):
            environ['PATH_INFO'] = '/' + path_info[len('/api/index.py/'):]
        elif path_info.startswith('/api/'):
            environ['PATH_INFO'] = '/' + path_info[len('/api/'):]

        # Ensure SCRIPT_NAME is empty so url_for builds clean URLs like /login instead of /api/index/login
        environ['SCRIPT_NAME'] = ''

        return self.wsgi_app(environ, start_response)


# Apply WSGI path fixer middleware
app.wsgi_app = VercelPathFixer(app.wsgi_app)


# Fallback route aliases in case Vercel routes directly to the function name
@app.route('/api/index', methods=['GET', 'POST'])
@app.route('/api/index.py', methods=['GET', 'POST'])
@app.route('/api', methods=['GET', 'POST'])
def vercel_entrypoint_redirect():
    from flask import redirect, url_for
    return redirect(url_for('main.index'))


# Expose WSGI application object for Vercel Python serverless runtime
app = app

