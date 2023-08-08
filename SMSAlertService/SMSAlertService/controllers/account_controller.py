import json
import secrets
import os
import markupsafe
from bcrypt import checkpw
from flask import Blueprint, request, redirect, render_template, session, url_for, jsonify, abort
from SMSAlertService import app
from SMSAlertService.dao import DAO
from SMSAlertService.decorators import protected
from SMSAlertService.resources.config import SUCCESS, FAIL, MAX_LOGIN_ATTEMPTS, BLOCKED
from SMSAlertService.resources.screen_templates import INVALID_LOGIN_MSG, BLOCKED_MSG, PW_RESET_FAIL_MSG, \
    PW_RESET_SUCCESS_MSG, USERNAME_TAKEN_MSG, FAIL_MSG, CREATE_ACCOUNT_FAIL_MSG
from SMSAlertService.services.alert_service import AlertService

account_bp = Blueprint('account_controller', __name__)


@account_bp.route("/account", methods=["GET"])
@protected
def account():
    user_id = session.get('user_id')
    user = DAO.get_user_by_id(user_id)
    keywords = user.get_keywords_json()
    watched_subreddits = user.get_subreddits_json()
    all_subreddits = json.dumps(DAO.get_subreddit_names())
    # PAYPAL_CLIENT_ID = os.environ['PAYPAL_SANDBOX_CLIENT_ID']
    PAYPAL_CLIENT_ID = os.environ['PAYPAL_CLIENT_ID']
    return render_template('account.html',
                           username=user.username,
                           message_count=user.units_left,
                           keywords=keywords,
                           watched_subreddits=watched_subreddits,
                           all_subreddits=all_subreddits,
                           client_id=PAYPAL_CLIENT_ID)


@account_bp.route("/account/login", methods=["POST"])
def login():
    username = markupsafe.escape(request.json['Username'].upper().strip())
    pw_input = markupsafe.escape(request.json['Password'])
    user = DAO.get_user_by_username(username)

    if user is None:
        app.logger.error(f'Failed log in attempt: User {username} does not exist.')
        return jsonify({'Status': FAIL, 'Message': INVALID_LOGIN_MSG})

    elif session['login_attempts'] >= MAX_LOGIN_ATTEMPTS or user.blocked:
        app.logger.error(f'User {user.username} has exceeded max log in attempts.')
        DAO.block_user(user)
        return jsonify({'Status': BLOCKED, 'Message': BLOCKED_MSG})

    elif checkpw(pw_input.encode('utf-8'), user.password):
        token = secrets.token_hex(16)
        session['token'] = token
        session['user_id'] = user.id
        DAO.set_cookie(user, token)
        resp = jsonify({'Status': SUCCESS})
        resp.set_cookie('sms_alert_service_login', value=token, secure=True, httponly=True)
        app.logger.info(f'{user.username} logged in.')
        return resp

    else:
        session['login_attempts'] += 1
        app.logger.error(f'Incorrect password entered by {user.username}. Login attempts = {session.get("login_attempts")}')
        return jsonify({'Status': FAIL, 'Message': INVALID_LOGIN_MSG})


@account_bp.route("/account/logout", methods=["GET"])
def logout():
    session.clear()
    return redirect(url_for("site_nav_controller.login"))


@account_bp.route("/account/create", methods=["POST"])
def create():
    if session.get('authenticated'):
        session.pop('authenticated', None)
        username = markupsafe.escape(request.json['Username'])
        ph = markupsafe.escape(request.json['PhoneNumber'])
        pw = markupsafe.escape(request.json['Password'])

        if DAO.get_user_by_username(username):
            return jsonify({'Status': SUCCESS})

        token = secrets.token_hex(16)
        insertion = DAO.create_account(username=username.upper(),
                                       phonenumber=ph,
                                       password=pw,
                                       verified=True,
                                       cookie=token)
        if insertion.acknowledged:
            session['user_id'] = str(insertion.inserted_id)
            session['token'] = token
            resp = jsonify({'Status': SUCCESS})
            resp.set_cookie('sms_alert_service_login', value=token, secure=True, httponly=True)
            AlertService.send_admin(f'{username} created an account.')
            return resp
        else:
            return jsonify({'Status': FAIL, 'Message': CREATE_ACCOUNT_FAIL_MSG})
    else:
        abort(403, "Access denied")


@account_bp.route("/account/update", methods=["GET"])
@protected
def edit_info():
    user_id = session.get('user_id')
    user = DAO.get_user_by_id(user_id)
    return render_template('edit-info.html', username=user.username, current_phone=user.phonenumber)


@account_bp.route("/account/update/username", methods=["POST"])
@protected
def update_username():
    user_id = session.get('user_id')
    user = DAO.get_user_by_id(user_id)
    new_username = markupsafe.escape(request.json['NewUsername'].upper())
    available = DAO.get_credential_availability(username=new_username, ph=None)
    if available['Username']:
        success = DAO.update_username(user, new_username)
        session["username"] = new_username
        return jsonify({'Status': SUCCESS}) if success \
            else jsonify({'Status': FAIL, 'Message': FAIL_MSG})
    else:
        return jsonify({'Status': FAIL, 'Message': USERNAME_TAKEN_MSG})


@account_bp.route("/account/update/password", methods=["POST"])
def reset_password():
    if session.get('authenticated'):
        session.pop('authenticated')
        user_id = session.get('user_id')
        user = DAO.get_user_by_id(user_id)
        new_password = markupsafe.escape(request.json['NewPassword'])
        success = DAO.reset_password(user, new_password)
        return jsonify({'Status': SUCCESS, 'Message': PW_RESET_SUCCESS_MSG}) if success \
            else jsonify({'Status': FAIL, 'Message': PW_RESET_FAIL_MSG})
    else:
        return abort(403, 'Access Denied')


@account_bp.route("/account/recover", methods=["GET"])
def recover_account():
    authenticated = session.get('authenticated')
    return render_template('reset-password.html') if authenticated \
        else abort(403, 'Access Denied')


@account_bp.route("/account/keyword/add", methods=["POST"])
@protected
def add_keyword():
    user_id = session.get('user_id')
    user = DAO.get_user_by_id(user_id)
    keyword = markupsafe.escape(request.json['keyword'].strip())
    success = DAO.add_keyword(user, keyword)
    return jsonify({'Status': SUCCESS}) if success \
        else jsonify({'Status': FAIL})


@account_bp.route("/account/keyword/delete", methods=["POST"])
@protected
def delete_keyword():
    user_id = session.get('user_id')
    user = DAO.get_user_by_id(user_id)
    keyword = markupsafe.escape(request.json['DeleteKeyword'])
    success = DAO.delete_keyword(user, keyword)
    return jsonify({'Status': SUCCESS}) if success \
        else jsonify({'Status': FAIL})


@account_bp.route("/account/keyword/delete-all", methods=["POST"])
@protected
def delete_all_keywords():
    user_id = session.get('user_id')
    user = DAO.get_user_by_id(user_id)
    success = DAO.delete_all_keywords(user)
    return jsonify({'Status': SUCCESS}) if success \
        else jsonify({'Status': FAIL})


@account_bp.route("/account/subreddit/add", methods=["POST"])
@protected
def add_subreddit():
    user_id = session.get('user_id')
    user = DAO.get_user_by_id(user_id)
    subreddit = markupsafe.escape(request.json['Subreddit'])
    success = DAO.add_subreddit(user=user, subreddit=subreddit)
    return jsonify({'Status': SUCCESS}) if success \
        else jsonify({'Status': FAIL})


@account_bp.route("/account/subreddit/delete", methods=["POST"])
@protected
def delete_subreddit():
    user_id = session.get('user_id')
    user = DAO.get_user_by_id(user_id)
    subreddit = markupsafe.escape(request.json['Subreddit'])
    success = DAO.delete_subreddit(user=user, subreddit=subreddit)
    return jsonify({'Status': SUCCESS}) if success \
        else jsonify({'Status': FAIL})

