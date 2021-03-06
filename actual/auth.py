import functools

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, jsonify
)
from werkzeug.security import check_password_hash, generate_password_hash

from actual.db import get_db

bp = Blueprint('auth', __name__, url_prefix='/auth')

@bp.route('/register', methods=['POST'])
def register():
    if request.method == 'POST':
        json = request.get_json()
        # requested_privilege = request.get_json()['requested_privilege']
        db = get_db()
        error = None

        if 'username' not in json or json['username'] == '': return send_error('Username is required.')
        if 'password' not in json or json['password'] == '': return send_error('Password is required.')
        if 'privilege' not in json or json['privilege'] == '': return send_error('Privilege is required.')

        username = json['username']
        password = json['password']
        privilege = -1
        if json['privilege'] == 'administrator':
            privilege = 1
        elif json['privilege'] == 'user':
            privilege = 0
        if privilege == -1:
            return send_error('Invalid privilege.')


        if db.execute(
            'SELECT id FROM user WHERE username = ?', (username,)
        ).fetchone() is not None:
            return send_error('Username already exists.')

        db.execute(
            'INSERT INTO user (username, password, privilege) VALUES (?, ?, ?)',
            (username, generate_password_hash(password), privilege)
        )
        db.commit()
        return send_success()

    return ""

@bp.route('/login', methods=['POST'])
def login():
    if request.method == 'POST':
        json = request.get_json()
        privilege = -1
        db = get_db()
        error = None

        if 'username' not in json or json['username'] == '': return send_error('Username is required.')
        if 'password' not in json or json['password'] == '': return send_error('Password is required.')
        if 'requested_privilege' in json:
            if json['requested_privilege'] == 'administrator': privilege = 1
            elif json['requested_privilege'] == 'user': privilege = 0
        else:
            return send_error('Privilege is required.')

        if privilege == -1: return send_error('Invalid privilege requested.')

        username = json['username']
        password = json['password']

        user = db.execute(
            'SELECT * FROM user WHERE username = ?', (username,)
        ).fetchone()

        if not user: return send_error('Invalid username or password.')
        if not check_password_hash(user['password'], password):
            return send_error('Invalid username or password.')
        if privilege > user['privilege']:
            return send_error('Unauthorized')

        session.clear()
        session['user_id'] = user['id']
        session['user_privilege'] = user['privilege']
        return jsonify(status = 'success', privilege = user['privilege'])

    return ""

@bp.route('/logout')
def logout():
    session.clear()
    return send_success()


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get('user_id')
    user_privilege = session.get('user_privilege')
    if user_id is None:
        g.user = None
    else:
        g.user = get_db().execute(
            'SELECT * FROM user WHERE id = ?', (user_id,)
        ).fetchone()


def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for('auth.login'))

        return view(**kwargs)

    return wrapped_view

def send_error(text):
    return jsonify(status = 'failure', error_message = text)

def send_success(text = None):
    if not text: return jsonify(status = 'success')
    return jsonify(status = 'success', description = text)
