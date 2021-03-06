import functools, sqlite3
from termcolor import colored
from datetime import datetime

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for, jsonify
)
from werkzeug.security import check_password_hash, generate_password_hash

from actual.db import get_db

bp = Blueprint('posters', __name__, url_prefix='/posters')

@bp.route('/status', methods=['GET'])
def status():
    '''
    Returns a summary of the status of every poster in the db.
    '''
    user_id, user_privilege, error = check_user_and_privilege(session, [1])
    if error: return send_error(error)

    rows, error = get_rows('SELECT * FROM poster', [], 1, 1)
    if error: return send_error(error)

    d = count_statuses(rows)
    return jsonify(d)

@bp.route('/my_status', methods=['GET'])
def my_status():
    '''
    Returns a summary of the status of only posters uploaded by the
    current user.
    '''
    user_id, user_privilege, error = check_user_and_privilege(session, [0, 1])
    if error: return send_error(error)

    rows, error = get_rows('SELECT * FROM poster WHERE uploader_id = ?', (user_id,), 1, 1)
    if error: return send_error(error)

    d = count_statuses(rows)
    return jsonify(d)


@bp.route('/mine', methods=['GET'])
def my_posters():
    '''
    Returns a list of posters uploaded by the current user.
    '''
    requested_status = request.args.get('status')

    user_id, user_privilege, error = check_user_and_privilege(session, [0, 1])
    if error: return send_error(error)

    ignore_image = check_ignore_image(request)

    if requested_status:
        rows, error = get_rows('SELECT * FROM poster WHERE uploader_id = ? AND status = ?', (user_id, requested_status,), 1, ignore_image)
    else:
        rows, error = get_rows('SELECT * FROM poster WHERE uploader_id = ?', (user_id,), 1, ignore_image)

    if error: return send_error(error)
    if rows is None: return send_error('No posters matching the requested status.')
    return jsonify(rows)

@bp.route('/cancel', methods=['POST'])
def cancel():
    '''
    Allows a user to cancel posters uploaded by themselves if they have not
    been displayed, or approved.
    '''
    user_id, user_privilege, error = check_user_and_privilege(session, [0, 1])
    if error: return send_error(error)

    json = request.get_json()
    if 'id' not in json: return send_error('id not provided.')

    # TODO: shorten
    info, error = check_one('SELECT * FROM poster WHERE id = ?', (json['id'],))
    if error: return send_error(error)
    if info is None: return send_error('No poster the given id.')

    info, error = check_one('SELECT * FROM poster WHERE uploader_id = ? AND id = ?', (user_id, json['id'],))
    if error: return send_error(error)
    if info is None: return send_error('Cannot delete poster not uploaded by the current user.')

    info, error = check_one('SELECT * FROM poster WHERE uploader_id = ? AND id = ? AND status IN ("pending", "approved", "rejected", "expired")', (user_id, json['id'],))
    if error: return send_error(error)
    if info is None: return send_error('Poster not pending / approved.')

    db = get_db()
    db.execute('DELETE FROM poster WHERE uploader_id = ? AND id = ?', (user_id, json['id'],))
    db.commit()
    return send_success()

@bp.route('/filter', methods=['GET'])
def filter():
    '''
    Returns posters that are based on the parameters specified.
    Multiple conditions can be set, as well as multple values
    for each paramter (seperated by ',').
    For example:
    - /filter?mine=1&status=posted,approved
    - /filter?status=pending&contact_name=Andre
    '''
    approveAsNeeded()
    expireAsNeeded()

    user_id, user_privilege, error = check_user_and_privilege(session, [-1, 0, 1], ignore_id = True)
    if error: return send_error(error)
    ignore_image = check_ignore_image(request)
    mine = check_mine(request)

    args = request.args.to_dict()

    for key in args.keys():
        args[key] = args[key].split(',')

    s = ''
    if user_privilege == 0: s = 'WHERE (status = "posted" OR uploader_id = "{}") '.format(user_id)
    if user_privilege == -1: s = 'WHERE (status = "posted") '

    for key in args.keys():
        if key == 'ignore_image' or key == 'mine': continue
        if s == '':
            s += 'WHERE '
        else:
            s+= ' AND '

        val = args[key]
        if len(val) == 1:
            s += '{} = "{}"'.format(key, val[0])
        else:
            s += '{} in ({})'.format(key, ','.join('"{}"'.format(i) for i in val))

    if mine:
        if s == '':
            s += 'WHERE uploader_id = "{}"'.format(user_id)
        else:
            s+= ' AND uploader_id = "{}"'.format(user_id)

    command = 'SELECT * FROM poster ' + s

    rows, error = get_rows(command, [], user_privilege, ignore_image)
    if error: return send_error(error)

    return jsonify(rows)


@bp.route('/', methods=['GET', 'POST', 'DELETE'])
def posters():
    if request.method == 'GET':
        approveAsNeeded()
        expireAsNeeded()

        user_id, user_privilege, error = check_user_and_privilege(session, [-1, 0, 1], ignore_id = True)
        if error: return send_error(error)
        ignore_image = check_ignore_image(request)

        requested_id = request.args.get('id')
        requested_status = request.args.get('status')

        extra = ' WHERE status="posted"' if user_privilege < 1 else ''

        if requested_id:
            rows, error = get_rows('SELECT * FROM poster WHERE id = ?' + extra, (requested_id,), privilege = user_privilege, ignore_image = ignore_image)
            if error: return send_error(error)
            if rows is None: return send_error('Requested id not found.')
            return jsonify(rows)

        if requested_status:
            if user_privilege < 1: return send_error('Non-admin cannot request for a status.')
            rows, error = get_rows('SELECT * FROM poster WHERE status = ?', (requested_status,), privilege = user_privilege, ignore_image = ignore_image)
            if error: return send_error(error)
            if rows is None: return send_error('No posters matching the requested status.')
            return jsonify(rows)

        rows, error = get_rows('SELECT * FROM poster' + extra, [], privilege = user_privilege, ignore_image = ignore_image)
        if error: return send_error(error)

        return jsonify(rows)

    if request.method == 'POST':
        user_id, user_privilege, error = check_user_and_privilege(session, [0, 1])
        if error: return send_error(error)

        json = request.get_json()
        db = get_db()

        if 'id' not in json:
            # New Posters.

            if 'title' not in json or json['title'] == "":
                return send_error('Missing title. New posters must have a title.')

            title = json['title']
            json['uploader_id'] = user_id

            res, error = check_one('SELECT id FROM poster WHERE title = ?', (title,))
            if error: return send_error(error)
            if res is not None: return send_error('Poster already exists with given title.')

            db.execute('INSERT INTO poster (title, status) VALUES (?, ?)', (title, 'pending'))

            json.pop('title')

            ls = []
            for key in json:
                if key.startswith('date') and json[key]:
                    if ' ' not in json[key]: return send_error('Invalid date format')
                    s = json[key].split(' ')
                    if len(s[0].split('-')) != 3 or len(s[1].split(':')) != 3:
                         return send_error('Invalid date format')

                value = '"{}"'.format(json[key]) if json[key] else 'NULL'
                ls.append('{} = {}'.format(key, value))
            try:
                db.execute('UPDATE poster SET ' + ', '.join(ls) + ' WHERE title = "' + str(title) + '"')
            except sqlite3.OperationalError as e:
                print(e)
                return send_error('Invalid parameter. {}'.format(e))
            except Exception as e:
                print(e)
                return send_error('Error in updating the databse. {}'.format(e))

            db.commit()
            return send_success()

        else:
            # Editing existing posters.

            id = json['id']
            if id == '': return send_error('Missing Id in request.')
            json.pop('id')

            res, error = check_one('SELECT * FROM poster WHERE id = ?', (id,))
            if error: return send_error(error)
            if res is None: return send_error('Requested id not found.')

            ls = []
            for key in json:
                if key.startswith('date'):
                    if json[key] and len(json[key].split(' ')) == 1:
                        return send_error('Invalid date format for {}'.format(key))
                ls.append('{} = "{}"'.format(key, json[key]))
            try:
                db.execute('UPDATE poster SET ' + ', '.join(ls) + ' WHERE id = ' + str(id))
            except sqlite3.OperationalError:
                return send_error('Invalid parameter.')
            except:
                return send_error('Error in updating the databse.')

            db.commit()

            return send_success()

    if request.method == 'DELETE':
        user_id, user_privilege, error = check_user_and_privilege(session, [1])
        if error: return send_error(error)

        requested_id = request.args.get('id')
        if requested_id == None: return send_error('Id not specified.')

        db = get_db()
        info = db.execute('SELECT * FROM poster WHERE id = ?', (requested_id,)).fetchone()
        if info is None: return send_error('Id not found.')

        db.execute('DELETE FROM poster WHERE id = ?', (requested_id,))
        db.commit()
        return send_success()

@bp.route('/debug_all', methods = ['GET'])
def debug():
    ignore_image = 0
    if request.args.get('ignore_image') and request.args.get('ignore_image') == '1':
        ignore_image = 1

    db = get_db()
    info = db.execute('SELECT * FROM poster').fetchall()
    posters = [buildRowDictNonNull(i, 1, ignore_image, 1) for i in info]

    if len(posters) == 0: return 'No posters.'
    return jsonify(posters)


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

def send_error(text):
    print(colored('Error encountered: {}'.format(text), 'red'))
    return jsonify(status = 'failure', error_message = text)

def send_success():
    return jsonify(status = 'success')

def buildRowDict(row, force_uploader = 0):
    d = {}
    d['id'] = row[0]
    if force_uploader == 1:
        d['uploader_id'] = row[1]
    d['title'] = row[2]
    d['status'] = row[3]
    d['serialized_image_data'] = row[4]
    d['description'] = row[5]
    d['link'] = row[6]
    d['category'] = row[7]
    d['locations'] = row[8]
    d['contact_name'] = row[9]
    d['contact_email'] = row[10]
    d['contact_number'] = row[11]
    d['date_submitted'] = str(row[12])
    d['date_approved'] = str(row[13])
    d['date_posted'] = str(row[14])
    d['date_expiry'] = str(row[15])

    return d

def approveAsNeeded():
    db = get_db()
    info = db.execute('Select * from poster WHERE status = "approved"').fetchall()
    if info is None or len(info) == 0:
        return
    for i in info:
        if i[14] == None: continue
        to_post = i[14]
        now = datetime.now()
        if now > to_post:
            db.execute('UPDATE poster set status="posted" WHERE id = {}'.format(i[0]))
            print('Posted {}'.format(i[0]))
    db.commit()

def expireAsNeeded():
    db = get_db()
    info = db.execute('Select * from poster WHERE status = "posted"').fetchall()
    if info is None or len(info) == 0:
        return
    for i in info:
        if i[15] == None: continue
        to_expire = i[15]
        now = datetime.now()
        if now > to_expire:
            db.execute('UPDATE poster set status="expired" WHERE id = {}'.format(i[0]))
            print('Expired {}'.format(i[0]))
    db.commit()

def get_rows(command, args, privilege = -1, ignore_image = 0, force_uploader = 0):
    try:
        db = get_db()
        info = db.execute(command, args).fetchall()
        rows = [buildRowDictNonNull(i, privilege, ignore_image, force_uploader) for i in info]
        return [rows, None]

    except Exception as e:
        print(e)
        return [None, e]

def check_one(command, args):
    try:
        db = get_db()
        info = db.execute(command, args).fetchone()
        return [info, None]

    except Exception as e:
        print(e)
        return [None, e]

def buildRowDictNonNull(row, privilege = -1, ignore_image = 0, force_uploader = 0):
    d = buildRowDict(row, force_uploader)
    if privilege == -1:
        d['date_submitted'] = None
        d['date_approved'] = None
        d['date_posted'] = None
        d['date_expiry'] = None
    if ignore_image == 1:
        d['serialized_image_data'] = None
    return {k:d[k] for k in d if d[k] and d[k] != 'None'}

def count_statuses(rows):
    d = {}
    d['posted'] = len([r for r in rows if r['status'] == 'posted'])
    d['pending'] = len([r for r in rows if r['status'] == 'pending'])
    d['approved'] = len([r for r in rows if r['status'] == 'approved'])
    d['expired'] = len([r for r in rows if r['status'] == 'expired'])
    d['rejected'] = len([r for r in rows if r['status'] == 'rejected'])
    return d

def check_user_and_privilege(session, allowed_privileges, ignore_id = False):

    user_id = session.get('user_id')
    user_privilege = session.get('user_privilege')
    if user_privilege == None: user_privilege = -1

    if ignore_id == False:
        if not user_id: return [None, None, 'Not logged in.']

    if check_privilege(session, allowed_privileges) == False:
        return [None, None, 'Unauthorized.']

    return [user_id, user_privilege, None]

def check_privilege(session, allowed_privileges):
    user_privilege = session.get('user_privilege')
    allowed = [str(i) for i in allowed_privileges]
    if user_privilege == None and '-1' in allowed: return True
    if str(user_privilege) in allowed: return True
    return False

def check_ignore_image(request):
    ignore = request.args.get('ignore_image')
    return 1 if ignore == '1' else 0

def check_mine(request):
    mine = request.args.get('mine')
    return 1 if mine == '1' else 0
