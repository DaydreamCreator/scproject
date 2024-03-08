import base64
import json
import secrets
import hmac
import hashlib
import re

# https://docs.python.org/3/library/base64.html
# https://docs.python.org/3/library/json.html

class JsonWebToken:
    def __init__(self):
        # there are two methods to generate private key
        # 1/ use user-defined key (mostly static)
        # 2/ use secrets library to generate random key such like secrets.token_urlsafe
        # https://docs.python.org/3/library/secrets.html#module-secrets

        # 1/ 
        self.MY_KEY = "OurGroupNumberIs16"
        #myKey = MY_KEY.encode()

        # 2/ 
        self.randomKey = secrets.token_urlsafe(16)  # or 32 or other    private key
        
        # selection
        self.key = self.MY_KEY


    """
    base64.urlsafe_b64encode(s)
    Encode bytes-like object s using the URL- and filesystem-safe alphabet, 
        which substitutes - instead of + and _ instead of / in the standard Base64 
        alphabet, and return the encoded bytes. The result can still contain =.
        
        Reference : https://docs.python.org/3/library/base64.html

    Encode the string using url and file system safe alphabets into the binary form.

    :text_bytes <bytes> : string needed to be encoded
    Return encoded_string <string>  TODO

    Normal input should use my_jsonify() to get bytes objects.
    """
    def encode_base64url(self, text_bytes):
        # should it encode with "ascii"?
        return base64.urlsafe_b64encode(text_bytes).decode('utf-8')# .replace('=', '')
    """
    base64.urlsafe_b64decode(s)
    Decode bytes-like object or ASCII string s using the URL- and 
        filesystem-safe alphabet, which substitutes - instead of + and _ 
        instead of / in the standard Base64 alphabet, and return the decoded bytes.

        Reference : https://docs.python.org/3/library/base64.html
    """
    """
    Decode the url and file system safe format into string.

    :encoded_string <bytes> : string needed to be decoded
    Return encoded_string <string>  TODO
    """

    def decode_base64url(self, encoded_string):
        return base64.urlsafe_b64decode(encoded_string) # + '=='


    """
    Compact encode the python object(dictionary) to JSON

    :dic <dict> : dictionary object needs to be jsonfied
    Return encoded JSON object
    """
    def my_jsonify(self, dic):
        return json.dumps(dic, separators=(",", ":")).encode()


    """
    hmac.new(key, msg=None, digestmod)
    Return a new hmac object. key is a bytes or bytearray object giving the secret key.
        Parameter msg can be of any type supported by hashlib. 
        Parameter digestmod can be the name of a hash algorithm.

    hmac(key, msg, digest).digest()
    Return digest of msg for given secret key and digest. 
        Reference : https://docs.python.org/3/library/hmac.html

    Generate JSON Web Token using given content

    JWT is a piece of information together with a signature,
    the signature was produced using a private key 
    """
    def generate_jwt(self, content):

        header = {
            'typ': 'JWT',           
            'alg': 'HS256'
        }

        # package the sent msg with concatenating in '.'
        all_content = str(self.encode_base64url(self.my_jsonify(header))) + '.' + str(self.encode_base64url(self.my_jsonify(content)))

        # generate signature using private key
        signature = hmac.new(self.key.encode(), all_content.encode(), hashlib.sha256).digest()   #TODO or hexdigest()

        # token: encoded information + encoded signature
        token = all_content + '.' + str(self.encode_base64url(signature))

        return token

    # decode the payload and return the username
    # token's structure: header.payload.signature
    def decode_jwt(self, encoded_string):
        if encoded_string.startswith('Bearer '):
            encoded_string = encoded_string[7:]
        try:
            header, payload, signature = encoded_string.split('.')
            # payload_decoded = decode_base64url(payload).decode('utf-8')
            # username = json.loads(payload_decoded)
            username = json.loads(self.decode_base64url(payload))

        except Exception as e:
            print(f"Error decoding JWT: {e}")
        return username

    # get the header and payload from the token, and sign them again to compare with the original signature in the token
    def verify_jwt(self, token):
        try:
            header, payload, signature = token.split('.')
            header_payload = f"{header}.{payload}"
            signature = base64.urlsafe_b64decode(signature + '==') 
            
            # decode the Header to acquire the algorithm: https://blog.csdn.net/LC_Liangchao/article/details/122041219
            #  json.loaads()  decode JSON to python objects, in this case a dict
            header_decoded = json.loads(self.decode_base64url(header))
           
            if header_decoded['alg'].upper() != 'HS256':
                raise ValueError("Unsupported signature algorithm")
            
            # use the alg defined in header to generate the new signature
            new_signature = hmac.new(self.key.encode(), header_payload.encode(), hashlib.sha256).digest()
            
            # compare the new signature with the old one
            if not hmac.compare_digest(signature, new_signature):
                return False 
            
            return True 
            
        except Exception as e:
            print(f"Error verifying JWT: {e}")
            return False


"""
Check if the URL is valid
"""
def is_valid_url(url):
    regex = re.compile(
        r'^(?:http)s?://'  # http or https
        r'(?:'  # IP address or domain name
        r'(?:[0-9]{1,3}\.){3}[0-9]{1,3}'  # IPv4 address
        r'|'  # OR
        r'localhost'  # localhost
        r'|'  # OR
        r'(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+'  # 
        r'(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)'  # top domain
        r')'
        r'(?::[0-9]+)?'  # port number(optional)
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)  # path
    return re.match(regex, url)