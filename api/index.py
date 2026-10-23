import os
from run import app, db

# Auto-initialize database tables if running on Vercel and tables do not exist
if os.environ.get('VERCEL'):
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass


import urllib.parse


class VercelPathFixer:
    """WSGI middleware to normalize PATH_INFO and SCRIPT_NAME on Vercel serverless."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        query_string = environ.get('QUERY_STRING', '')

        # Diagnostic hook for production environment troubleshooting
        if '__debug_env=1' in query_string:
            import json
            dump = {k: str(v) for k, v in environ.items() if isinstance(v, (str, int, float, bool))}
            body = json.dumps(dump, indent=2).encode('utf-8')
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [body]

        # Extract __path passed from Vercel rewrite rule: destination: "/api/index?__path=$1"
        if '__path=' in query_string:
            parsed = urllib.parse.parse_qs(query_string, keep_blank_values=True)
            if '__path' in parsed:
                raw_path = parsed.pop('__path')[0]
                environ['QUERY_STRING'] = urllib.parse.urlencode(parsed, doseq=True)
                clean_path = '/' + raw_path.lstrip('/')
                environ['PATH_INFO'] = clean_path
                environ['SCRIPT_NAME'] = ''
                return self.wsgi_app(environ, start_response)

        # Fallback for direct function calls or non-rewritten paths
        path_info = environ.get('PATH_INFO', '')
        if path_info in ('/api/index', '/api/index.py', '/api', '/api/'):
            environ['PATH_INFO'] = '/'
        elif path_info.startswith('/api/index/'):
            environ['PATH_INFO'] = '/' + path_info[len('/api/index/'):]
        elif path_info.startswith('/api/index.py/'):
            environ['PATH_INFO'] = '/' + path_info[len('/api/index.py/'):]
        elif path_info.startswith('/api/'):
            environ['PATH_INFO'] = '/' + path_info[len('/api/'):]

        # Ensure SCRIPT_NAME is clean so url_for builds clean URLs like /login
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

