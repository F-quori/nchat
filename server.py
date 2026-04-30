import random
import string
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# セキュリティキー（本番運用時はより複雑な文字列にしてください）
app.config['SECRET_KEY'] = 'chat-secret-key-123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat_app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
# 他のPCからのSocket.IO接続を許可するためにcors_allowed_originsを設定
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- データベースモデル ---

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.String(8), nullable=False) # 32進数8桁
    username = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- 補助関数 (32進数ID生成) ---

def generate_room_id():
    # 0-9 + a-v (合計32文字)
    chars = string.digits + "abcdefghijklmnopqrstuv"
    return ''.join(random.choice(chars) for _ in range(8))

# --- ルーティング ---

# トップページにアクセスしたらログイン画面へ
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('このユーザー名は既に使用されています。')
            return redirect(url_for('signup'))
        
        new_user = User(username=username, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home'))
        flash('ログインに失敗しました。ユーザー名とパスワードを確認してください。')
    return render_template('login.html')

@app.route('/home', methods=['GET', 'POST'])
@login_required
def home():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            room_id = generate_room_id()
            return redirect(url_for('chat', room_id=room_id))
        elif action == 'join':
            room_id = request.form.get('room_id').lower().strip()
            if len(room_id) == 8:
                return redirect(url_for('chat', room_id=room_id))
            flash('ルームIDは8桁で入力してください。')
            
    return render_template('home.html', user=current_user)

@app.route('/chat/<room_id>')
@login_required
def chat(room_id):
    # その部屋の過去ログを取得（古い順）
    past_messages = Message.query.filter_by(room_id=room_id).order_by(Message.timestamp.asc()).all()
    return render_template('chat.html', username=current_user.username, room_id=room_id, messages=past_messages)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- SocketIO リアルタイム通信 ---

@socketio.on('join')
def handle_join(data):
    room = data['room']
    join_room(room)
    emit('render_msg', {'user': 'System', 'msg': f'{current_user.username}が入室しました。'}, to=room)

@socketio.on('message')
def handle_message(data):
    room = data['room']
    content = data['msg']
    
    # 1. DBに保存
    new_msg = Message(room_id=room, username=current_user.username, content=content)
    db.session.add(new_msg)
    db.session.commit()
    
    # 2. その部屋の全員に送信
    emit('render_msg', {'user': current_user.username, 'msg': content}, to=room)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # host='0.0.0.0' で外部接続を許可、port=5000 で待ち受け
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)