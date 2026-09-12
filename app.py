# ==================== IMPORTS ====================
import os
import time
from dotenv import load_dotenv
from flask import Flask, request, jsonify, render_template
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

from openai import OpenAI # [OPENAI]
from google import genai  # [GEMINI ONLY]
from cryptography.fernet import Fernet  # [ENCRYPTION]
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user  # [FLASK LOGIN]
from werkzeug.security import generate_password_hash, check_password_hash  # [FLASK LOGIN]
from flask import redirect
from authlib.integrations.flask_client import OAuth  # [GOOGLE OAUTH]
from werkzeug.exceptions import HTTPException  # [BUG REPORT]
# ==================== END IMPORTS ====================


# ==================== APP + ENV SETUP ====================
load_dotenv()
app = Flask(__name__)

# [FLASK LOGIN] --- secret key needed for login sessions ---
app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("FLASK_SECRET_KEY is not set. Add it to your .env file.")
# ==================== END APP + ENV SETUP ====================


# ==================== API KEYS + VALIDATION ====================
openai_api_key = os.environ.get("OPENAI_API_KEY")
gemini_api_key = os.environ.get("GEMINI_API_KEY")  # [GEMINI ONLY]

if not openai_api_key:
    raise RuntimeError("OPENAI_API_KEY is not set. Add it to your .env file.")
if not gemini_api_key:  # [GEMINI ONLY]
    raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")  # [GEMINI ONLY]

app_secret = os.environ.get("APP_SECRET_KEY")
if not app_secret:
    raise RuntimeError("APP_SECRET_KEY is not set. Add it to your .env file.")

# [ENCRYPTION] --- start ---
encryption_key = os.environ.get("ENCRYPTION_KEY")
if not encryption_key:
    raise RuntimeError("ENCRYPTION_KEY is not set. Add it to your .env file.")
fernet = Fernet(encryption_key.encode())
# [ENCRYPTION] --- end ---
# ==================== END API KEYS + VALIDATION ====================


# ==================== AI CLIENTS ====================
openai_client = OpenAI(api_key=openai_api_key)
gemini_client = genai.Client(api_key=gemini_api_key)  # [GEMINI ONLY]

MAX_MESSAGE_LENGTH = 1000
# ==================== END AI CLIENTS ====================


# ==================== DATABASE SETUP & DEPLOYMENT USES NEON ON RENDER ====================
'''
-------OLD VERSION — replaced with deployment logic below--------
DB_PASSWORD = os.environ.get("DB_PASSWORD")
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://postgres:{DB_PASSWORD}@localhost:5432/flask-chat-app'
'''
# [DEPLOYMENT] — uses Neon on Render if DATABASE_URL is set, otherwise falls back to local Postgres
if os.environ.get("RENDER"):
    # Running on Render — always use Neon
    DATABASE_URL = os.environ.get("NEON_DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set. Add it in Render's environment variables.")
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
else:
    # Running locally in terminal — always use local Postgres
    DB_PASSWORD = os.environ.get("DB_PASSWORD")
    app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://postgres:{DB_PASSWORD}@localhost:5432/flask-chat-app'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # [SIDEBAR]
    conversation_id = db.Column(db.String(64), nullable=True)  # [SIDEBAR]
    role = db.Column(db.String(10), nullable=False)
    message = db.Column(db.Text, nullable=False) # stores ENCRYPTED text now [ENCRYPTION]
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    source = db.Column(db.String(20), nullable=True)  # tracks which AI answered — safe to keep either way



# ==================== ANALYTICS LOGGING ====================
class RequestLog(db.Model):
    """Analytics-only log — metadata about each request, no message content.
    Safe for Power BI to read directly since nothing here is sensitive."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    conversation_id = db.Column(db.String(64), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    model_used = db.Column(db.String(20), nullable=True)  # 'openai', 'gemini', or null if both failed
    success = db.Column(db.Boolean, nullable=False)
    response_time_ms = db.Column(db.Integer, nullable=True)
    category = db.Column(db.String(20), nullable=True)
# =================== END ANALYTICS LOGGING ====================

#==================== ERROR LOGGING ====================
class ErrorLog(db.Model):
    """Captures actual error details for a live bug-report dashboard.
    Safe for Power BI — these are library/API error messages, never user message content."""
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    endpoint = db.Column(db.String(50), nullable=False)      # e.g. 'chat', 'history', 'conversations'
    error_type = db.Column(db.String(50), nullable=False)    # e.g. 'openai_failed', 'gemini_failed', 'decrypt_failed'
    error_message = db.Column(db.Text, nullable=True)        # the actual exception text, truncated
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
#==================== END ERROR LOGGING ====================

# ==================== USER ACCOUNTS [FLASK LOGIN] ====================
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)  # empty for Google-only accounts
    google_id = db.Column(db.String(120), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'  # redirects here if login is required and user isn't logged in


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
# ==================== END USER ACCOUNTS ====================

# ==================== GOOGLE OAUTH SETUP [LOGIN] ====================
google_client_id = os.environ.get("GOOGLE_CLIENT_ID")
google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

if not google_client_id or not google_client_secret:
    raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set. Add them to your .env file.")

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=google_client_id,
    client_secret=google_client_secret,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)
# ==================== END GOOGLE OAUTH SETUP ====================

with app.app_context():
    db.create_all()
# ==================== END DATABASE SETUP ====================

# ==================== ENCRYPTION HELPERS ====================
# [ENCRYPTION] --- start ---
def encrypt_text(plain_text):
    return fernet.encrypt(plain_text.encode()).decode()

def decrypt_text(encrypted_text):
    return fernet.decrypt(encrypted_text.encode()).decode()
# [ENCRYPTION] --- end ---
# ==================== END ENCRYPTION HELPERS ====================

# ==================== ERROR LOGGING [BUG REPORT] ====================
def log_error(endpoint, error_type, error_message, user_id=None):
    """Writes an error to the database so Power BI can show it live."""
    try:
        db.session.add(ErrorLog(
            endpoint=endpoint,
            error_type=error_type,
            error_message=str(error_message)[:500],
            user_id=user_id
        ))
        db.session.commit()
    except Exception as e:
        print(f"Failed to log error: {e}")
        db.session.rollback()
# ==================== END ERROR LOGGING ====================

# ==================== QUESTION CATEGORIZATION [POWER BI] ====================
def categorize_message(text):
    """Simple keyword-based classifier — good enough for a demo dashboard,
    not real NLP/ML classification."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ['code', 'python', 'javascript', 'function', 'bug', 'debug', 'script', 'programming', 'html', 'css', 'api']):
        return 'Programming'
    if any(kw in text_lower for kw in ['sql', 'database', 'query', 'table', 'postgres', 'schema']):
        return 'Data/SQL'
    if any(kw in text_lower for kw in ['ai', 'model', 'gpt', 'gemini', 'llm', 'machine learning', 'chatbot']):
        return 'AI'
    if any(kw in text_lower for kw in ['recipe', 'food', 'cook', 'weather', 'joke', 'story']):
        return 'General'
    return 'Other'
# ==================== END QUESTION CATEGORIZATION ====================

# ==================== AI FALLBACK LOGIC ====================
def get_ai_reply(user_message):
    """Try OpenAI first. If it fails for any reason, fall back to Gemini."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-5.6-luna",
            messages=[{"role": "user", "content": user_message}],
            max_tokens=150
        )
        return response.choices[0].message.content.strip(), "openai"
    except Exception as e:
        print(f"OPENAI FAILED, falling back to Gemini: {e}")  # [GEMINI ONLY] — change message if removing fallback and adding a return or jsonify right after that print would break the fallback — it would stop the function before ever trying Gemini.
        log_error('chat', 'openai_failed', e)  # [BUG REPORT]

    # ---- [GEMINI ONLY] block start ----
    try:
        response = gemini_client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=user_message
        )
        return response.text.strip(), "gemini"
    except Exception as e:
        print(f"GEMINI ALSO FAILED: {e}")
        log_error('chat', 'gemini_failed', e)  # [BUG REPORT]
        raise
    # ---- [GEMINI ONLY] block end ----
# ==================== END AI FALLBACK LOGIC ====================


# ==================== ROUTES ====================
@app.route('/')
@login_required
def home():
    return render_template('index.html')

'''
OLD VERSION — replaced with Power BI logging support below.
Kept here for reference.

@app.route('/chat', methods=['POST'])
@login_required
def chat():
    data = request.get_json(silent=True)
    if not data or 'message' not in data:
        return jsonify({'error': 'Missing "message" in request body'}), 400

    user_message = str(data.get('message', '')).strip()
    conversation_id = str(data.get('conversation_id', '')).strip()

    if not conversation_id:
        return jsonify({'error': 'Missing conversation_id'}), 400

    if not user_message:
        return jsonify({'error': 'Message cannot be empty'}), 400

    if len(user_message) > MAX_MESSAGE_LENGTH:
        return jsonify({'error': f'Message too long (max {MAX_MESSAGE_LENGTH} characters)'}), 400

    try:
        ai_reply, source = get_ai_reply(user_message)
    except Exception:
        return jsonify({'error': 'Both AI providers failed. Please try again later.'}), 500

    db.session.add(ChatMessage(
        user_id=current_user.id, conversation_id=conversation_id,
        role='user', message=encrypt_text(user_message), source=source
    ))
    db.session.add(ChatMessage(
        user_id=current_user.id, conversation_id=conversation_id,
        role='assistant', message=encrypt_text(ai_reply), source=source
    ))
    db.session.commit()

    return jsonify({'response': ai_reply, 'source': source})
'''
@app.route('/chat', methods=['POST'])
@login_required
def chat():
    data = request.get_json(silent=True)
    if not data or 'message' not in data:
        return jsonify({'error': 'Missing "message" in request body'}), 400

    user_message = str(data.get('message', '')).strip()
    conversation_id = str(data.get('conversation_id', '')).strip()

    if not conversation_id:
        return jsonify({'error': 'Missing conversation_id'}), 400

    if not user_message:
        return jsonify({'error': 'Message cannot be empty'}), 400

    if len(user_message) > MAX_MESSAGE_LENGTH:
        return jsonify({'error': f'Message too long (max {MAX_MESSAGE_LENGTH} characters)'}), 400

    category = categorize_message(user_message)  # [POWER BI]
    start_time = time.time()  # [POWER BI]

    try:
        ai_reply, source = get_ai_reply(user_message)
        response_time_ms = int((time.time() - start_time) * 1000)  # [POWER BI]

        # [POWER BI] --- log analytics metadata (no message content) ---
        db.session.add(RequestLog(
            user_id=current_user.id, conversation_id=conversation_id,
            model_used=source, success=True,
            response_time_ms=response_time_ms, category=category
        ))

        # --- log actual encrypted content ---
        db.session.add(ChatMessage(
            user_id=current_user.id, conversation_id=conversation_id,
            role='user', message=encrypt_text(user_message), source=source
        ))
        db.session.add(ChatMessage(
            user_id=current_user.id, conversation_id=conversation_id,
            role='assistant', message=encrypt_text(ai_reply), source=source
        ))
        db.session.commit()

        return jsonify({'response': ai_reply, 'source': source})

    except Exception:
        # [POWER BI] --- log the failure too, so error rate isn't invisible ---
        response_time_ms = int((time.time() - start_time) * 1000)
        db.session.add(RequestLog(
            user_id=current_user.id, conversation_id=conversation_id,
            model_used=None, success=False,
            response_time_ms=response_time_ms, category=category
        ))
        db.session.commit()
        return jsonify({'error': 'Both AI providers failed. Please try again later.'}), 500

    
# [ENCRYPTION] --- encrypt before saving to the database ---
    db.session.add(ChatMessage(role='user', message=encrypt_text(user_message), source=source))
    db.session.add(ChatMessage(role='assistant', message=encrypt_text(ai_reply), source=source))
    db.session.commit()

    # Note: the response sent back to the browser is still plain text —
    # only what's stored in the database is encrypted.
    return jsonify({'response': ai_reply, 'source': source})



# [ENCRYPTION] --- new route: view decrypted history (protected by the same app secret) ---
@app.route('/history')
def history():
    if request.headers.get('X-App-Key') != app_secret:
        return jsonify({'error': 'Unauthorized'}), 401

    messages = ChatMessage.query.order_by(ChatMessage.timestamp).all()
    decrypted = []
    for m in messages:
        try:
            decrypted.append({
                'id': m.id,
                'role': m.role,
                'message': decrypt_text(m.message),
                'timestamp': m.timestamp.isoformat(),
                'source': m.source
            })
        except Exception as e:
            log_error('history', 'decrypt_failed', e, user_id=current_user.id if current_user.is_authenticated else None)  # [BUG REPORT]
            decrypted.append({'id': m.id, 'role': m.role, 'message': '[COULD NOT DECRYPT]', 'timestamp': m.timestamp.isoformat(), 'source': m.source})

    return jsonify(decrypted)
# [ENCRYPTION] --- end ---

# ==================== EMAIL/PASSWORD AUTH [LOGIN] ====================
@app.route('/login-page')
def login_page():
    return render_template('login.html')

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json(silent=True)
    if not data or 'email' not in data or 'password' not in data:
        return jsonify({'error': 'Email and password required'}), 400

    email = data['email'].strip().lower()
    password = data['password']

    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'An account with this email already exists'}), 409

    new_user = User(email=email, password_hash=generate_password_hash(password))
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user)

    return jsonify({'message': 'Account created', 'email': new_user.email})


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True)
    if not data or 'email' not in data or 'password' not in data:
        return jsonify({'error': 'Email and password required'}), 400

    email = data['email'].strip().lower()
    password = data['password']

    user = User.query.filter_by(email=email).first()
    if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Invalid email or password'}), 401

    login_user(user)
    return jsonify({'message': 'Logged in', 'email': user.email})


@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return jsonify({'message': 'Logged out'})
# ==================== END EMAIL/PASSWORD AUTH ====================

# ==================== GOOGLE LOGIN [LOGIN] ====================
'''
OLD VERSION — replaced with new version below that links Google to existing email/password accounts if the email matches.
@app.route('/login/google')
def login_google():
    redirect_uri = 'http://127.0.0.1:5000/login/google/callback'
    return google.authorize_redirect(redirect_uri)
'''
@app.route('/login/google')
def login_google():
    if os.environ.get("RENDER"):
        redirect_uri = 'https://flask-chatgpt-app.onrender.com/login/google/callback'
    else:
        redirect_uri = 'http://127.0.0.1:5000/login/google/callback'
    return google.authorize_redirect(redirect_uri)


@app.route('/login/google/callback')
def login_google_callback():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')

    if not user_info or 'email' not in user_info:
        return jsonify({'error': 'Google login failed'}), 400

    email = user_info['email'].strip().lower()
    google_id = user_info['sub']

    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        # No account with this Google ID — check if the email is already used another way
        user = User.query.filter_by(email=email).first()
        if user:
            # Existing email/password account — link Google to it
            user.google_id = google_id
        else:
            # Brand new account
            user = User(email=email, google_id=google_id)
            db.session.add(user)
        db.session.commit()

    login_user(user)
    return redirect('/')  # back to the chat page, now logged in
# ==================== END GOOGLE LOGIN ====================

# ==================== USER INFO + CONVERSATIONS [SIDEBAR] ====================
@app.route('/me')
@login_required
def me():
    return jsonify({'email': current_user.email})


@app.route('/conversations')
@login_required
def conversations():
    rows = (ChatMessage.query
            .filter_by(user_id=current_user.id)
            .order_by(ChatMessage.timestamp)
            .all())

    convos = {}
    for m in rows:
        if not m.conversation_id:
            continue
        if m.conversation_id not in convos:
            convos[m.conversation_id] = {
                'conversation_id': m.conversation_id,
                'title': None,
                'last_timestamp': m.timestamp.isoformat()
            }
        convos[m.conversation_id]['last_timestamp'] = m.timestamp.isoformat()
        if convos[m.conversation_id]['title'] is None and m.role == 'user':
            try:
                text = decrypt_text(m.message)
                convos[m.conversation_id]['title'] = text[:40] + ('...' if len(text) > 40 else '')
            except Exception:
                convos[m.conversation_id]['title'] = 'Conversation'

    result = sorted(convos.values(), key=lambda c: c['last_timestamp'], reverse=True)
    return jsonify(result)


@app.route('/conversations/<conversation_id>')
@login_required
def get_conversation(conversation_id):
    rows = (ChatMessage.query
            .filter_by(user_id=current_user.id, conversation_id=conversation_id)
            .order_by(ChatMessage.timestamp)
            .all())

    messages = []
    for m in rows:
        try:
            text = decrypt_text(m.message)
        except Exception as e:
            log_error('conversations', 'decrypt_failed', e, user_id=current_user.id)  # [BUG REPORT]
            text = '[COULD NOT DECRYPT]'
        messages.append({'role': m.role, 'message': text, 'timestamp': m.timestamp.isoformat()})

    return jsonify(messages)
# ==================== END USER INFO + CONVERSATIONS ====================

# ==================== GLOBAL ERROR HANDLER [BUG REPORT] ====================
'''
OLD VERSION — replaced with new version below that skips routine HTTP errors like 404s.
@app.errorhandler(Exception)
def handle_unexpected_error(e):
    """Catches ANY unhandled crash anywhere in the app and logs it."""
    import traceback
    log_error(
        endpoint=request.path,
        error_type=type(e).__name__,
        error_message=traceback.format_exc(),
        user_id=current_user.id if current_user.is_authenticated else None
    )
    return jsonify({'error': 'Something went wrong on our end.'}), 500
'''
@app.errorhandler(Exception)
def handle_unexpected_error(e):
    """Catches unhandled crashes and logs them — but skips routine HTTP
    errors like 404s, which aren't actual bugs."""
    if isinstance(e, HTTPException):
        # Normal HTTP errors (404, 405, etc.) — not real bugs, don't log them
        return jsonify({'error': e.description}), e.code

    import traceback
    log_error(
        endpoint=request.path,
        error_type=type(e).__name__,
        error_message=traceback.format_exc(),
        user_id=current_user.id if current_user.is_authenticated else None
    )
    return jsonify({'error': 'Something went wrong on our end.'}), 500
# ==================== END GLOBAL ERROR HANDLER ====================
# ==================== END ROUTES ====================


# ==================== RUN SERVER ====================
if __name__ == '__main__':
    debug_mode = os.environ.get("FLASK_DEBUG", "False") == "True"
    app.run(debug=debug_mode)
# ==================== END RUN SERVER ====================