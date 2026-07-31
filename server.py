import os
import sqlite3
import datetime
import socket
import json
import subprocess
import sys
from flask import Flask, request, jsonify, send_from_directory, render_template_string
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'volexturn_secret_key_2026'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# پوشه‌های ذخیره‌سازی فایل‌ها
UPLOAD_FOLDER = 'uploads'
FOLDERS = ['profiles', 'chat', 'stories', 'posts']
for f in FOLDERS:
    os.makedirs(os.path.join(UPLOAD_FOLDER, f), exist_ok=True)

DB_FILE = 'database.db'

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        full_name TEXT,
        bio TEXT,
        avatar TEXT,
        role TEXT DEFAULT 'user',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER,
        receiver_id INTEGER,
        content TEXT,
        file_path TEXT,
        file_type TEXT,
        file_name TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS stories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        file_path TEXT,
        file_type TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        expires_at DATETIME DEFAULT (datetime('now', '+24 hours'))
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        content TEXT,
        file_path TEXT,
        file_type TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS lan_hosts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        game_name TEXT,
        ip_address TEXT,
        port INTEGER,
        description TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    
    # ساخت ادمین پیش‌فرض
    c.execute("SELECT * FROM users WHERE username = 'admin'")
    if not c.fetchone():
        c.execute('''INSERT INTO users (username, password, full_name, bio, role) 
                     VALUES (?, ?, ?, ?, ?)''',
                  ('admin', 'admin123', 'مدیر سیستم', 'مدیر ارشد Volexturn', 'admin'))
        conn.commit()
        print("[✅] ادمین پیش‌فرض ساخته شد: admin / admin123")
    
    # پاک کردن استوری‌های منقضی شده
    c.execute("DELETE FROM stories WHERE expires_at < datetime('now')")
    conn.commit()
    conn.close()

init_db()

# مدیریت آنلاین بودن کاربران
online_users = set()
socket_to_user = {}

def get_file_type(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg']: return 'image'
    if ext in ['.mp4', '.mkv', '.mov', '.webm', '.avi', '.flv']: return 'video'
    if ext in ['.mp3', '.wav', '.ogg', '.m4a', '.flac']: return 'audio'
    return 'file'

# ========== مسیرهای API ==========

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api')
def api_terminal():
    """ترمینال مدیریت API سرور"""
    html = '''
    <!DOCTYPE html>
    <html dir="rtl" lang="fa">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>API Terminal - Volexturn</title>
        <style>
            * { margin:0; padding:0; box-sizing:border-box; font-family: 'Courier New', monospace; }
            body { background:#0a0e17; color:#00ff41; height:100vh; display:flex; flex-direction:column; }
            .header { background:#111827; padding:12px 20px; border-bottom:1px solid #1f2937; display:flex; justify-content:space-between; align-items:center; }
            .header h1 { font-size:18px; color:#00ff41; }
            .header span { color:#6b7280; font-size:12px; }
            .container { flex:1; display:flex; overflow:hidden; }
            .sidebar { width:250px; background:#111827; border-left:1px solid #1f2937; overflow-y:auto; padding:10px; }
            .sidebar h3 { color:#6b7280; font-size:12px; margin:10px 0 6px; }
            .endpoint { padding:8px 12px; margin:2px 0; border-radius:4px; cursor:pointer; color:#9ca3af; font-size:13px; transition:0.2s; }
            .endpoint:hover { background:#1f2937; color:#00ff41; }
            .endpoint.get { border-right:3px solid #22c55e; }
            .endpoint.post { border-right:3px solid #eab308; }
            .endpoint.delete { border-right:3px solid #ef4444; }
            .endpoint.active { background:#1f2937; color:#00ff41; }
            .main { flex:1; display:flex; flex-direction:column; background:#0a0e17; }
            .url-bar { padding:10px 16px; background:#111827; border-bottom:1px solid #1f2937; display:flex; gap:10px; }
            .url-bar select, .url-bar input { background:#0a0e17; border:1px solid #1f2937; color:#00ff41; padding:6px 12px; border-radius:4px; font-size:13px; }
            .url-bar input { flex:1; }
            .url-bar button { background:#00ff41; color:#0a0e17; border:none; padding:6px 20px; border-radius:4px; cursor:pointer; font-weight:bold; }
            .url-bar button:hover { opacity:0.8; }
            .response-area { flex:1; padding:16px; overflow-y:auto; }
            .response-area pre { white-space:pre-wrap; word-break:break-all; font-size:13px; line-height:1.6; }
            .status-line { padding:8px 16px; background:#111827; border-top:1px solid #1f2937; display:flex; justify-content:space-between; color:#6b7280; font-size:12px; }
            .status-line .success { color:#22c55e; }
            .status-line .error { color:#ef4444; }
            .input-area { padding:10px 16px; background:#111827; border-top:1px solid #1f2937; display:flex; gap:10px; }
            .input-area textarea { flex:1; background:#0a0e17; border:1px solid #1f2937; color:#00ff41; padding:8px; border-radius:4px; resize:none; height:60px; font-size:13px; }
            ::-webkit-scrollbar { width:6px; }
            ::-webkit-scrollbar-track { background:#0a0e17; }
            ::-webkit-scrollbar-thumb { background:#1f2937; border-radius:3px; }
            .blink { animation: blink 1s infinite; }
            @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0} }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>⚡ API Terminal <span class="blink">●</span></h1>
            <span>Volexturn v2.0 | ${new Date().toLocaleString('fa-IR')}</span>
        </div>
        <div class="container">
            <div class="sidebar" id="sidebar">
                <h3>📂 ENDPOINTS</h3>
                <div class="endpoint get" data-method="GET" data-url="/api/admin/stats">GET /api/admin/stats</div>
                <div class="endpoint get" data-method="GET" data-url="/users">GET /users</div>
                <div class="endpoint get" data-method="GET" data-url="/stories">GET /stories</div>
                <div class="endpoint get" data-method="GET" data-url="/posts">GET /posts</div>
                <div class="endpoint get" data-method="GET" data-url="/lan_hosts">GET /lan_hosts</div>
                <div class="endpoint post" data-method="POST" data-url="/create_story">POST /create_story</div>
                <div class="endpoint post" data-method="POST" data-url="/create_post">POST /create_post</div>
                <div class="endpoint post" data-method="POST" data-url="/create_lan_host">POST /create_lan_host</div>
                <div class="endpoint delete" data-method="DELETE" data-url="/api/admin/clear_all_messages">DELETE /api/admin/clear_all_messages</div>
                <h3>📊 ADMIN</h3>
                <div class="endpoint get" data-method="GET" data-url="/api/admin/users">GET /api/admin/users</div>
                <div class="endpoint delete" data-method="DELETE" data-url="/api/admin/delete_user/1">DELETE /api/admin/delete_user/{id}</div>
                <div class="endpoint post" data-method="POST" data-url="/api/admin/promote_user/1">POST /api/admin/promote_user/{id}</div>
            </div>
            <div class="main">
                <div class="url-bar">
                    <select id="methodSelect">
                        <option value="GET">GET</option>
                        <option value="POST">POST</option>
                        <option value="DELETE">DELETE</option>
                        <option value="PUT">PUT</option>
                    </select>
                    <input type="text" id="urlInput" value="/api/admin/stats">
                    <button onclick="sendRequest()">▶ اجرا</button>
                </div>
                <div class="input-area" id="bodyArea" style="display:none;">
                    <textarea id="bodyInput" placeholder="JSON Body..."></textarea>
                </div>
                <div class="response-area" id="responseArea">
                    <pre style="color:#6b7280;">// برای اجرا دکمه ▶ اجرا را بزنید</pre>
                </div>
                <div class="status-line">
                    <span id="statusText">● آماده</span>
                    <span id="timeText"></span>
                </div>
            </div>
        </div>
        <script>
            const endpoints = document.querySelectorAll('.endpoint');
            endpoints.forEach(el => {
                el.onclick = function() {
                    endpoints.forEach(e => e.classList.remove('active'));
                    this.classList.add('active');
                    document.getElementById('methodSelect').value = this.dataset.method;
                    document.getElementById('urlInput').value = this.dataset.url;
                    if (this.dataset.method === 'POST' || this.dataset.method === 'PUT') {
                        document.getElementById('bodyArea').style.display = 'flex';
                    } else {
                        document.getElementById('bodyArea').style.display = 'none';
                    }
                };
            });
            
            document.getElementById('methodSelect').onchange = function() {
                if (this.value === 'POST' || this.value === 'PUT') {
                    document.getElementById('bodyArea').style.display = 'flex';
                } else {
                    document.getElementById('bodyArea').style.display = 'none';
                }
            };

            async function sendRequest() {
                const method = document.getElementById('methodSelect').value;
                const url = document.getElementById('urlInput').value;
                const body = document.getElementById('bodyInput').value;
                const status = document.getElementById('statusText');
                const time = document.getElementById('timeText');
                const responseArea = document.getElementById('responseArea');
                
                status.innerHTML = '⏳ در حال ارسال...';
                const start = Date.now();
                
                try {
                    const options = { method };
                    if (method === 'POST' || method === 'PUT') {
                        options.headers = { 'Content-Type': 'application/json' };
                        if (body.trim()) options.body = body;
                    }
                    
                    const res = await fetch(url, options);
                    const end = Date.now();
                    const data = await res.json();
                    
                    status.innerHTML = res.ok ? '✅ موفق' : '❌ خطا';
                    status.style.color = res.ok ? '#22c55e' : '#ef4444';
                    time.textContent = `${end - start}ms | ${res.status} ${res.statusText}`;
                    
                    responseArea.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
                } catch(e) {
                    status.innerHTML = '❌ خطا در اتصال';
                    status.style.color = '#ef4444';
                    responseArea.innerHTML = `<pre style="color:#ef4444;">${e.message}</pre>`;
                }
            }
            
            // اجرا با Enter
            document.getElementById('urlInput').onkeypress = function(e) {
                if (e.key === 'Enter') sendRequest();
            };
        </script>
    </body>
    </html>
    '''
    return render_template_string(html)

@app.route('/files/<category>/<filename>')
def serve_file(category, filename):
    if category in FOLDERS:
        return send_from_directory(os.path.join(UPLOAD_FOLDER, category), filename)
    return jsonify({'message': 'Category invalid'}), 400

@app.route('/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password))
    user = c.fetchone()
    conn.close()
    
    if user:
        u_dict = dict(user)
        u_dict['is_online'] = u_dict['id'] in online_users
        return jsonify({'success': True, 'user': u_dict})
    return jsonify({'success': False, 'message': 'نام کاربری یا رمز عبور اشتباه است'})

@app.route('/register', methods=['POST'])
def register():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({'success': False, 'message': 'اطلاعات پر نشده است'})
    
    if len(username) < 3:
        return jsonify({'success': False, 'message': 'نام کاربری حداقل ۳ کاراکتر باشد'})
    if len(password) < 4:
        return jsonify({'success': False, 'message': 'رمز عبور حداقل ۴ کاراکتر باشد'})
        
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('INSERT INTO users (username, password, full_name, bio, avatar, role) VALUES (?, ?, ?, ?, ?, ?)',
                  (username, password, username, 'کاربر جدید Volexturn', '', 'user'))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'ثبت‌نام انجام شد! اکنون وارد شوید.'})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'success': False, 'message': 'این نام کاربری قبلاً استفاده شده است'})

@app.route('/users', methods=['GET'])
def get_users():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, username, full_name, bio, avatar, role FROM users')
    users = [dict(row) for row in c.fetchall()]
    conn.close()
    for u in users:
        u['is_online'] = u['id'] in online_users
    return jsonify(users)

@app.route('/messages/<int:u1>/<int:u2>', methods=['GET'])
def get_messages(u1, u2):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT * FROM messages WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?) ORDER BY id ASC''', (u1, u2, u2, u1))
    msgs = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(msgs)

@app.route('/send_message', methods=['POST'])
def send_message():
    sender_id = request.form.get('sender_id')
    receiver_id = request.form.get('receiver_id')
    content = request.form.get('content', '')
    
    file_path, file_type, file_name = None, None, None
    
    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename:
            file_name = secure_filename(file.filename)
            timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S_')
            file_path = timestamp + file_name
            file.save(os.path.join(UPLOAD_FOLDER, 'chat', file_path))
            file_type = get_file_type(file_name)

    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO messages (sender_id, receiver_id, content, file_path, file_type, file_name) VALUES (?, ?, ?, ?, ?, ?)''',
              (sender_id, receiver_id, content, file_path, file_type, file_name))
    msg_id = c.lastrowid
    conn.commit()
    
    c.execute('SELECT * FROM messages WHERE id = ?', (msg_id,))
    msg = dict(c.fetchone())
    conn.close()

    socketio.emit('new_message', msg)
    return jsonify({'success': True, 'message': msg})

@app.route('/stories', methods=['GET'])
def get_stories():
    """دریافت استوری‌های معتبر (غیرمنقضی)"""
    conn = get_db()
    c = conn.cursor()
    # فقط استوری‌هایی که منقضی نشده‌اند
    c.execute('''SELECT stories.*, users.full_name, users.avatar 
                 FROM stories 
                 JOIN users ON stories.user_id = users.id 
                 WHERE stories.expires_at > datetime('now')
                 ORDER BY stories.id DESC''')
    stories = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(stories)

@app.route('/create_story', methods=['POST'])
def create_story():
    """ایجاد استوری جدید با تاریخ انقضای ۲۴ ساعت"""
    user_id = request.form.get('user_id')
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'فایلی ارسال نشده است'})
    
    file = request.files['file']
    if file and file.filename:
        file_name = secure_filename(file.filename)
        timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S_')
        file_path = timestamp + file_name
        file.save(os.path.join(UPLOAD_FOLDER, 'stories', file_path))
        file_type = get_file_type(file_name)
        
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO stories (user_id, file_path, file_type, expires_at) 
                     VALUES (?, ?, ?, datetime('now', '+24 hours'))''', 
                  (user_id, file_path, file_type))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'استوری با موفقیت قرار گرفت'})
    return jsonify({'success': False, 'message': 'خطا در آپلود استوری'})

@app.route('/posts', methods=['GET'])
def get_posts():
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT posts.*, users.full_name, users.avatar FROM posts JOIN users ON posts.user_id = users.id ORDER BY posts.id DESC''')
    posts = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(posts)

@app.route('/create_post', methods=['POST'])
def create_post():
    user_id = request.form.get('user_id')
    content = request.form.get('content', '')
    
    file_path, file_type = None, None
    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename:
            file_name = secure_filename(file.filename)
            timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S_')
            file_path = timestamp + file_name
            file.save(os.path.join(UPLOAD_FOLDER, 'posts', file_path))
            file_type = get_file_type(file_name)

    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO posts (user_id, content, file_path, file_type) VALUES (?, ?, ?, ?)', (user_id, content, file_path, file_type))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'پست با موفقیت منتشر شد'})

@app.route('/lan_hosts', methods=['GET'])
def get_lan_hosts():
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT lan_hosts.*, users.full_name FROM lan_hosts JOIN users ON lan_hosts.user_id = users.id ORDER BY lan_hosts.id DESC''')
    hosts = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(hosts)

@app.route('/create_lan_host', methods=['POST'])
def create_lan_host():
    data = request.json or {}
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO lan_hosts (user_id, game_name, ip_address, port, description) VALUES (?, ?, ?, ?, ?)''',
              (data.get('user_id'), data.get('game_name'), data.get('ip_address'), data.get('port'), data.get('description')))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/delete_lan_host/<int:host_id>', methods=['DELETE'])
def delete_lan_host(host_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM lan_hosts WHERE id = ?', (host_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/update_profile', methods=['POST'])
def update_profile():
    user_id = request.form.get('user_id')
    full_name = request.form.get('full_name')
    bio = request.form.get('bio')
    
    conn = get_db()
    c = conn.cursor()
    
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename:
            file_name = secure_filename(file.filename)
            timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S_')
            avatar_path = timestamp + file_name
            file.save(os.path.join(UPLOAD_FOLDER, 'profiles', avatar_path))
            c.execute('UPDATE users SET full_name = ?, bio = ?, avatar = ? WHERE id = ?', (full_name, bio, avatar_path, user_id))
    else:
        c.execute('UPDATE users SET full_name = ?, bio = ? WHERE id = ?', (full_name, bio, user_id))
        
    conn.commit()
    c.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    updated_user = dict(c.fetchone())
    conn.close()
    
    return jsonify({'success': True, 'user': updated_user})

# ========== API های ادمین ==========

@app.route('/api/admin/stats', methods=['GET'])
def admin_stats():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    total_users = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM messages')
    total_messages = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM posts')
    total_posts = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM lan_hosts')
    active_lan = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM stories WHERE expires_at > datetime("now")')
    active_stories = c.fetchone()[0]
    conn.close()
    
    return jsonify({
        'status': 'فعال و آنلاین ⚡',
        'active_sockets': len(online_users),
        'total_users': total_users,
        'total_messages': total_messages,
        'total_posts': total_posts,
        'active_lan_hosts': active_lan,
        'active_stories': active_stories,
        'max_file_size_mb': 50,
        'image_compression': 'فعال',
        'server_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'python_version': sys.version.split()[0]
    })

@app.route('/api/admin/users', methods=['GET'])
def admin_get_users():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, username, full_name, bio, avatar, role, created_at FROM users ORDER BY id DESC')
    users = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(users)

@app.route('/api/admin/delete_user/<int:user_id>', methods=['DELETE'])
def admin_delete_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM users WHERE id = ? AND username != "admin"', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'کاربر با موفقیت حذف شد'})

@app.route('/api/admin/promote_user/<int:user_id>', methods=['POST'])
def admin_promote_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE users SET role = "admin" WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'کاربر به ادمین ارتقا یافت'})

@app.route('/api/admin/demote_user/<int:user_id>', methods=['POST'])
def admin_demote_user(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE users SET role = "user" WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'ادمین به کاربر عادی تبدیل شد'})

@app.route('/api/admin/delete_post/<int:post_id>', methods=['DELETE'])
def admin_delete_post(post_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM posts WHERE id = ?', (post_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'پست با موفقیت حذف شد'})

@app.route('/api/admin/delete_story/<int:story_id>', methods=['DELETE'])
def admin_delete_story(story_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM stories WHERE id = ?', (story_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'استوری با موفقیت حذف شد'})

@app.route('/api/admin/delete_message/<int:msg_id>', methods=['DELETE'])
def admin_delete_message(msg_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM messages WHERE id = ?', (msg_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'پیام با موفقیت حذف شد'})

@app.route('/api/admin/clear_all_messages', methods=['DELETE'])
def admin_clear_all_messages():
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM messages')
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'همه پیام‌ها پاک شدند'})

@app.route('/api/admin/system_info', methods=['GET'])
def system_info():
    """اطلاعات سیستم سرور"""
    return jsonify({
        'platform': sys.platform,
        'python_version': sys.version,
        'cwd': os.getcwd(),
        'uploads_folder': UPLOAD_FOLDER,
        'database': DB_FILE,
        'online_users': len(online_users)
    })

# ========== Socket.IO رویدادها ==========

@socketio.on('connect')
def handle_connect():
    pass

@socketio.on('join')
def handle_join(data):
    user_id = data.get('user_id')
    if user_id:
        online_users.add(int(user_id))
        socket_to_user[request.sid] = int(user_id)
        emit('user_status', {}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    user_id = socket_to_user.pop(request.sid, None)
    if user_id and user_id in online_users:
        online_users.remove(user_id)
        emit('user_status', {}, broadcast=True)

@socketio.on('join_voice')
def handle_join_voice(data):
    room = data.get('room', 'global_voice')
    join_room(room)

@socketio.on('leave_voice')
def handle_leave_voice(data):
    room = data.get('room', 'global_voice')
    leave_room(room)

@socketio.on('voice_signal')
def handle_voice_signal(data):
    room = data.get('room', 'global_voice')
    emit('voice_signal', data, to=room, include_self=False)

if __name__ == '__main__':
    def get_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except: return '127.0.0.1'
        
    ip = get_ip()
    port = 5000
    print("="*60)
    print(f"🚀 Volexturn Super-App Server Running!")
    print(f"🏠 Local Access:   http://localhost:{port}")
    print(f"🌐 Network Access: http://{ip}:{port}")
    print(f"📡 API Terminal:   http://localhost:{port}/api")
    print(f"👑 Admin: admin / admin123")
    print("="*60)
    
    socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
