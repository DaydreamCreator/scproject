import atexit
from functools import wraps
from flask_cors import CORS, cross_origin
from flask import Flask, request, jsonify, make_response
from datetime import datetime
import json
import re
import random
import string
import math
import string
import hashlib
import hmac
from myjwt import JsonWebToken, is_valid_url  # import self-defined functions

from flask_sqlalchemy import SQLAlchemy
import os
import sys
import socket

"""
This is the version for running distributed with multiple replicas,
We use NFS and Docker Volume to implement persistent storage and manage race conflicts

To deployment the pods on Kubernetes using Statefulsets,
the pods were generated in order and with regular identifier as suffix

We use these suffixes to assign every replicas with different ID ranges.
As a result, they can independently finish their ID issuing without repeated,
and they can also do ID recycles locally without any communication.

IF the digit of ID cannot satisfy the amount of ID required, the digit of Key (ID)
will increment by 1 without notifying peers since the new ID will also be issued in its own range.

"""


"""
Initialisation of variables in generating keys

"""
host_suffix = socket.gethostname()[-1] # last number of hostname str
host_suffix = "0"
REPLICAS = 1  # replica number running on the k8s

KEY_LENGTH = 2  # 2-digit code as key 
chars_and_nums = string.digits + string.ascii_lowercase # 0-9, a-z
DIGIT_LENGTH = len(chars_and_nums)  


"""
Functions to help each replica to know their own ID range.
The mechanism is somehow similar to the way of distributed computing with MPI

host_suffix para specify the "rank" of each replica, and all replicas
    share the same total ID space. They just grab the range they owns 
    according to the "rank".
"""
def generate_anchor(host_suffix, KEY_LENGTH):
    for i in range(REPLICAS): 
        if host_suffix == str(i):
            ID_SPACE = pow(DIGIT_LENGTH, KEY_LENGTH) // REPLICAS
            key_anchor = ID_SPACE*i - 1 # -1 for the first key
            my_max = key_anchor + ID_SPACE
            return key_anchor, my_max
    return -1, 0
key_anchor, MAX = generate_anchor(host_suffix, KEY_LENGTH)


# active_ids and deleted_ids are used to manage the IDs
active_ids = set()  
deleted_ids = set()

SALT_LENGTH = 5

app = Flask(__name__)

# https://stackoverflow.com/questions/25594893/how-to-enable-cors-in-flask
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'

# enable the portability with detecting if it is windows system
WIN = sys.platform.startswith('win')
if WIN:
    config_starts = 'sqlite:///'    # windows has the unique prefix
else:
    config_starts = 'sqlite:////'

db_name = 'data.db'

# configure database        // URI not URL
app.config['SQLALCHEMY_DATABASE_URI'] = config_starts + os.path.join(app.root_path, db_name)      # /// for windows, or ////
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'OurGroupNumberIs16'  


db = SQLAlchemy(app)

jwt_api = JsonWebToken()


# create database model
class User(db.Model):
    __tablename__ = 'user'
    #id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String, primary_key = True)
    email = db.Column(db.String)
    salt = db.Column(db.String)
    password = db.Column(db.String)

class Url(db.Model):
    __tablename__ = 'url'
    id = db.Column(db.Integer, primary_key=True)
    urlid = db.Column(db.String)
    text = db.Column(db.String)
    username = db.Column(db.String, db.ForeignKey('user.username'))

# generate the random salt
def random_salt():
    return ''.join(random.choice(chars_and_nums) for i in range(SALT_LENGTH))

# hash the password with the salt
def hash_password(salt, pwd):
    salted_pwd = pwd + salt
    hashed_pwd = hashlib.sha256(salted_pwd.encode())
    return hashed_pwd.hexdigest()

# decorator for authenticating the token
def token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # find the authorization header which contains the token
        auth_header = request.headers.get('Authorization', None)
        if not auth_header:
            print("Token is missing!")
            return jsonify({'message': 'Token is missing!'}), 403
        
        try:
            token_type, token = auth_header.split(' ')
            if token_type.lower() != 'bearer':
                raise ValueError("Authorization header must start with Bearer")
            # compare the old signature with the newly generated one
            if not jwt_api.verify_jwt(token):
                raise ValueError("Invalid token or token has expired")
        except Exception as e:
            print("exception,",e)
            return jsonify({'message': str(e)}), 403

        # decode the payload of the token
        current_user = jwt_api.decode_jwt(token)
        # let POST and PUT receive the current_user
        if request.method == 'POST' or request.method == 'PUT' or request.method == 'DELETE':
            return f(current_user, *args, **kwargs)
        return f( *args, **kwargs)
    
    return decorated_function


"""
Generating IDs:
Starts from 2-digit code as key: _ _, one digit varys from 0 to 9 and a to z.
If the length of key cannot satisfy to represent the number of URLs, the digit length of key will expand.
Deleted ID will be recycled by adding into the [deleted_ids]
"""
def generate_key():
    global key_anchor, KEY_LENGTH, MAX
    if deleted_ids:
        # First will try to reuse recycled IDs
        key = deleted_ids.pop()
    else:
        # Expand the digit length of ID if necessary
        if key_anchor >= MAX - 1:
            KEY_LENGTH += 1
            key_anchor, MAX = generate_anchor(host_suffix, KEY_LENGTH)
        # refresh the key_anchor for the next key
        key_anchor += 1
        # Convert the key_anchor to the key
        key_indices = [(key_anchor // pow(DIGIT_LENGTH, i)) % DIGIT_LENGTH for i in range(KEY_LENGTH - 1, -1, -1)]
        key = ''.join(chars_and_nums[k] for k in key_indices)
    active_ids.add(key)  
    return key

"""
Recycle of deleted IDs:
Delete the ID from [activat_ids] and put it into the [deleted_ids]
"""
def delete_id(del_id):
    if del_id in active_ids:
        active_ids.remove(del_id)
        deleted_ids.add(del_id)
    else:
        print(f"ID '{del_id}' not found.")


"""
Validate the username and password using POST method
return (JWT, 200) if both are correct
       ("forbidden", 403) if any of them are incorrect or not exist or omitted
"""
@app.route('/users/login', methods=['POST'])
def login():
    data = request.get_json()
    if 'username' in data and 'password' in data:
        res = User.query.filter_by(username=data['username']).all()
        if len(res) == 1:
            res = res[0]
            if hmac.compare_digest(hash_password(res.salt, data['password']), res.password):    # compare hashed password
                # generate token
                jwt = jwt_api.generate_jwt(data['username'])  # add the username for verification
                return jsonify(jwt), 200 
            return jsonify({"detail":"forbidden"}), 403 
    else:
        return jsonify({"detail":"forbidden"}), 403

"""
Create an account with POSTed username and password
Return (201) if successfully created
       ("duplicate", 409) if the username was already occupied
       ("username or password not given", 404) if the username or password is not given
"""
@app.route('/users', methods=['POST'])
def users_post():
    #data = request.form
    data = request.get_json()
    if 'username' in data and 'password' in data:
        # res = db.session.execute(db.select(User).filter_by(username=data['username'])).first()
        res = User.query.filter_by(username=data['username']).first()
        if res:
            return jsonify({"detail":"duplicate"}), 409  #make_response(jsonify('duplicate', 409))
        else: 
            # idea: generate a random salt for each user to encrypt the password in case of an attack
            user_salt = random_salt()
            new_user = User(username=data['username'], password=hash_password(user_salt, data['password']), salt=user_salt)
            db.session.add(new_user)
            db.session.commit()
            return jsonify(data['username']), 201
    else:
        return jsonify({"detail":"username or password not given"}), 404 

"""
Get all the users
"""    
@app.route('/users', methods=['GET'])
def users_get():
    users = User.query.all()
    users_data = [{'username': user.username, 'email': user.email} for user in users]
    return jsonify(users_data)

"""
Update the password of the given username using PUT method
Return (200) if successfully updated
       (404) if the username does not exist
       (400) if the username or password is not given
       (403) if the provided old password is incorrect
"""
@app.route('/users', methods=['PUT'])
def users_put():
    data = request.get_json()
    username = data.get('username')
    old_password = data.get('password')
    new_password = data.get('new_password')
    
    if not username or not new_password or not old_password:
        # the username or password is not given
        return jsonify({"detail":"Missing username or password"}), 400

    user = User.query.filter_by(username=username).first()
    if user:
        if not hmac.compare_digest(user.password, hash_password(user.salt, old_password)):
            return jsonify({'detail': 'forbidden'}), 403
        user.password = new_password
        db.session.commit()
        return jsonify(user.username), 200
    else:
        # user does not exist
        return jsonify({"detail":"Username does not exist"}), 404


"""
POST method:
1. Get the URL from the request
2. Check if the URL is valid
3. Generate a unique ID for the URL
4. Store the URL and the author's IP address in the database
5. Return the status code 
"""
@app.route('/', methods=['POST'])
@token_required
def post_by_url(user):
    data = request.get_json()
    url = str(data.get('value'))
    if not is_valid_url(url):
        return make_response({'error': 'Invalid URL'}, 400)
    identifier = generate_key()  # use generate_key() to get ID

    # MOD here
    new_url = Url(text=url, urlid=identifier, username=user)
    db.session.add(new_url)
    db.session.commit()
    return make_response(jsonify(id=identifier, username=user), 201)

"""
GET method:
1. Get all the keys from the database
2. Serialize the list
3. Return the list of keys and the status code
"""
@app.route('/', methods=['GET'])
@token_required
def get_all_keys():
   all_urls = Url.query.all()
   new_res = {url.urlid : url.text for url in all_urls }
   return make_response(new_res, 200)
