# ============================================
# server.py - سرور بهینه شده برای اتصال به فایل HTML مجزا
# ============================================

import os
import json
import datetime
import hashlib
import secrets
import socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from threading import Lock

PORT = 5555
UPLOAD_FOLDER = 'videos'
USERS_FILE = 'users.json'
MSG_FILE = 'messages.json'
HTML_FILE = 'index.html' # نام فایل HTML جدید

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
file_lock = Lock()

# ساخت فایل‌های اولیه
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'w') as f: json.dump({}, f)

with open(USERS_FILE, 'r') as f: users = json.load(f)

if 'admin' not in users:
    users['admin'] = {
        'password': hashlib.sha256('admin77'.encode()).hexdigest(),
        'role': 'admin'
    }
    with open(USERS_FILE, 'w') as f: json.dump(users, f, indent=2)
    print("[OK] Admin created")

if not os.path.exists(MSG_FILE):
    with open(MSG_FILE, 'w') as f: json.dump([], f)

class Security:
    sessions = {}
    
    @staticmethod
    def register(username, password):
        with file_lock:
            with open(USERS_FILE, 'r') as f: users = json.load(f)
            if username in users: return False, "این نام کاربری موجود است"
            if len(username) < 3: return False, "نام کاربری حداقل ۳ کاراکتر باشد"
            if len(password) < 4: return False, "رمز عبور حداقل ۴ کاراکتر باشد"
            if username == 'admin': return False, "نام کاربری غیرمجاز است"
            
            users[username] = {'password': hashlib.sha256(password.encode()).hexdigest(), 'role': 'user'}
            with open(USERS_FILE, 'w') as f: json.dump(users, f, indent=2)
            return True, "ثبت نام موفقیت‌آمیز بود"
    
    @staticmethod
    def login(username, password):
        with open(USERS_FILE, 'r') as f: users = json.load(f)
        if username not in users: return False, "کاربر یافت نشد"
        if users[username]['password'] != hashlib.sha256(password.encode()).hexdigest():
            return False, "رمز عبور اشتباه است"
        token = secrets.token_hex(16)
        Security.sessions[token] = username
        return True, token
    
    @staticmethod
    def get_user(token): return Security.sessions.get(token)
    
    @staticmethod
    def logout(token):
        if token in Security.sessions:
            del Security.sessions[token]
            return True
        return False
    
    @staticmethod
    def is_admin(username):
        with open(USERS_FILE, 'r') as f:
            return json.load(f).get(username, {}).get('role', 'user') == 'admin'

    @staticmethod
    def get_all_users():
        with open(USERS_FILE, 'r') as f: return json.load(f)

class Handler(SimpleHTTPRequestHandler):
    def get_token(self):
        try:
            cookie = self.headers.get('Cookie', '')
            for item in cookie.split(';'):
                if 'session=' in item: return item.split('session=')[1].strip()
        except: pass
        return None
    
    def get_current_user(self): return Security.get_user(self.get_token())
    
    def is_admin(self):
        user = self.get_current_user()
        return Security.is_admin(user) if user else False
    
    def json_response(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json;charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    # خواندن فایل HTML مشترک برای تمام مسیرهای ظاهری (SPA)
    def serve_html(self):
        try:
            with open(HTML_FILE, 'r', encoding='utf-8') as f: content = f.read()
            self.send_response(200)
            self.send_header('Content-type', 'text/html;charset=utf-8')
            self.end_headers()
            self.wfile.write(content.encode())
        except Exception as e:
            self.send_error(500, f"HTML file not found! Create {HTML_FILE} in the same folder.")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ['/', '/login', '/admin']: self.serve_html()
        elif path == '/api/videos': self.get_videos()
        elif path == '/api/messages': self.get_messages()
        elif path == '/api/session': self.check_session()
        elif path == '/api/users': self.get_users()
        elif path == '/api/logout': self.handle_logout()
        elif path.startswith('/videos/'): self.serve_video()
        else: super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/register': self.handle_register()
        elif path == '/api/login': self.handle_login()
        elif path == '/api/upload': self.handle_upload()
        elif path == '/api/send_message': self.handle_send_message()
        elif path == '/api/delete_user': self.handle_delete_user()
        else: self.send_error(404)

    def serve_video(self):
        filename = os.path.basename(self.path)
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        if not os.path.exists(filepath):
            self.send_error(404)
            return
        
        file_size = os.path.getsize(filepath)
        range_header = self.headers.get('Range', None)
        
        if range_header:
            try:
                range_value = range_header.replace('bytes=', '').split('-')
                start = int(range_value[0])
                end = int(range_value[1]) if range_value[1] else file_size - 1
                
                self.send_response(206)
                self.send_header('Content-type', 'video/mp4')
                self.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
                self.send_header('Content-Length', str(end - start + 1))
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()
                
                with open(filepath, 'rb') as f:
                    f.seek(start)
                    self.wfile.write(f.read(end - start + 1))
            except: self.send_error(500)
        else:
            self.send_response(200)
            self.send_header('Content-type', 'video/mp4')
            self.send_header('Content-Length', str(file_size))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            with open(filepath, 'rb') as f: self.wfile.write(f.read())

    def get_videos(self):
        videos = [{'name': f, 'size': os.stat(os.path.join(UPLOAD_FOLDER, f)).st_size, 'url': f'/videos/{f}'} 
                  for f in os.listdir(UPLOAD_FOLDER) if f.endswith(('.mp4', '.avi', '.mkv', '.webm'))]
        self.json_response(videos)

    def get_messages(self):
        with open(MSG_FILE, 'r', encoding='utf-8') as f: self.json_response(json.load(f))

    def check_session(self):
        user = self.get_current_user()
        if user: self.json_response({'authenticated': True, 'username': user, 'is_admin': Security.is_admin(user)})
        else: self.json_response({'authenticated': False})

    def get_users(self):
        if not self.is_admin(): return self.json_response({'success': False}, 403)
        users = [{'username': u, 'role': d.get('role')} for u, d in Security.get_all_users().items()]
        self.json_response({'users': users})

    def handle_register(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])).decode())
        success, msg = Security.register(data.get('username', ''), data.get('password', ''))
        self.json_response({'success': success, 'message': msg}, 200 if success else 400)

    def handle_login(self):
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])).decode())
        success, res = Security.login(data.get('username', ''), data.get('password', ''))
        if success: self.json_response({'success': True, 'token': res})
        else: self.json_response({'success': False, 'message': res}, 401)

    def handle_logout(self):
        Security.logout(self.get_token())
        self.json_response({'success': True})

    def handle_upload(self):
        if not self.get_current_user(): return self.json_response({'success': False}, 401)
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            boundary = self.headers['Content-Type'].split('boundary=')[1].encode()
            parts = post_data.split(boundary)
            
            for part in parts:
                if b'filename=' in part:
                    lines = part.split(b'\r\n')
                    filename = None
                    for line in lines:
                        if b'filename=' in line:
                            filename = line.decode().split('filename="')[1].split('"')[0]
                            break
                    if filename:
                        file_start = part.find(b'\r\n\r\n') + 4
                        file_content = part[file_start:-2]
                        path = os.path.join(UPLOAD_FOLDER, filename)
                        with open(path, 'wb') as out: out.write(file_content)
                        return self.json_response({'success': True, 'message': 'آپلود شد'})
        except Exception as e: return self.json_response({'success': False, 'message': str(e)}, 500)

    def handle_send_message(self):
        user = self.get_current_user()
        if not user: return self.json_response({'success': False}, 401)
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])).decode())
        text = data.get('text', '').strip()
        if text:
            with file_lock:
                with open(MSG_FILE, 'r', encoding='utf-8') as f: msgs = json.load(f)
                msgs.append({'user': user, 'text': text, 'time': datetime.datetime.now().isoformat()})
                with open(MSG_FILE, 'w', encoding='utf-8') as f: json.dump(msgs[-100:], f, ensure_ascii=False)
        self.json_response({'success': True})

    def handle_delete_user(self):
        if not self.is_admin(): return
        data = json.loads(self.rfile.read(int(self.headers['Content-Length'])).decode())
        user = data.get('username', '')
        if user != 'admin':
            with file_lock:
                with open(USERS_FILE, 'r') as f: users = json.load(f)
                if user in users: del users[user]
                with open(USERS_FILE, 'w') as f: json.dump(users, f, indent=2)
        self.json_response({'success': True})

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except: return '127.0.0.1'

if __name__ == '__main__':
    ip = get_ip()
    print("="*50)
    print(f" SERVER RUNNING SUCCESSFULLY")
    print(f" Network URL: http://{ip}:{PORT}")
    print("="*50)
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()