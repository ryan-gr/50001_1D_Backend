import os
from flask import Flask, jsonify, session

def create_app(test_config = None):
    app = Flask(__name__, instance_relative_config = True)
    app.config.from_mapping(
        SECRET_KEY = 'dev',
        DATABASE = os.path.join(app.instance_path, 'flaskr.sqlite'),
    )

    if test_config is None:
        app.config.from_pyfile('config.py', silent = True)
    else:
        app.config.from_mapping(test_config)

    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    @app.route('/current')
    def current():
        d = {}
        d['user_id'] = session.get('user_id')
        d['privelage'] = session.get('privelage')
        return jsonify(d)

    from . import db
    db.init_app(app)

    from . import auth, posters
    app.register_blueprint(auth.bp)
    app.register_blueprint(posters.bp)

    return app
