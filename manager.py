import os
import re
import sys
import time
import json
import uuid
import hmac
import secrets
import socket
import logging
import subprocess
import threading
import webbrowser
import tkinter as tk
import psutil
import flask.cli
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask import Flask, render_template, request, session, redirect, url_for, jsonify, Response, send_file

if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

# --- MANAGER CONFIGURATION ---
MANAGER_CONFIG_FILE = 'manager_config.json'
DEFAULT_CONFIG = {
    'admin_user': 'admin',
    'admin_pass': 'admin',
    'instance_name': '',
    'hide_instance_on_login': False,
    'manager_port': 8000,
    'language': 'en',
    'monitor_cpu_ram': False,
    'instances': {}
}

def is_password_hashed(pw):
    return isinstance(pw, str) and (pw.startswith('scrypt:') or pw.startswith('pbkdf2:'))

def load_config():
    if not os.path.exists(MANAGER_CONFIG_FILE):
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        save_config(cfg)
        return cfg
    try:
        with open(MANAGER_CONFIG_FILE, 'r') as f:
            cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = json.loads(json.dumps(v))
            return cfg
    except:
        return json.loads(json.dumps(DEFAULT_CONFIG))

def save_config(cfg):
    with open(MANAGER_CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=4)

START_TIME = time.time()
CONFIG = load_config()
PROCESSES = {}  # RAM storage of sub-processes { instance_id: proc }

# --- INTERNAL LOGS ---
INTERNAL_LOGS = []

def add_internal_log(event, level="INFO"):
    try:
        ip = request.remote_addr if request else "SYSTEM"
    except:
        ip = "SYSTEM"
    log_entry = {
        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "ip": ip,
        "event": event,
        "level": level
    }
    INTERNAL_LOGS.append(log_entry)
    if len(INTERNAL_LOGS) > 1000:
        INTERNAL_LOGS.pop(0)
    current_time = datetime.now().strftime("%d/%m/%Y - %H:%M")
    print(f"[{current_time}] [{level}] {event}")

def translate_log_event_fr(evt):
    fr_dict_py = {
        "Manager started.": "Manager démarré.",
        "Manager settings updated.": "Paramètres du Manager mis à jour.",
        "Manager restart requested.": "Redémarrage du Manager demandé.",
        "Factory reset requested.": "Réinitialisation d'usine demandée.",
        "Logs cleared by user.": "Journaux effacés par l'utilisateur.",
        "Configuration imported.": "Configuration importée."
    }
    if evt in fr_dict_py:
        return fr_dict_py[evt]
    fr_regex_py = [
        (r"3 failed login attempts from IP (.+)", r"3 tentatives de connexion échouées depuis l'IP \1"),
        (r"Successful login from IP (.+)\.", r"Connexion réussie depuis l'IP \1."),
        (r"Failed login attempt from IP (.+)", r"Tentative de connexion échouée depuis l'IP \1"),
        (r"HTTP Port changed from (\d+) to (\d+)\. Manager restart requested\.", r"Port HTTP modifié de \1 vers \2. Redémarrage du Manager demandé."),
        (r"Instance '(.+)' started automatically\.", r"Instance '\1' démarrée automatiquement."),
        (r"Instance '(.+)' added\.", r"Instance '\1' ajoutée."),
        (r"Instance '(.+)' updated\.", r"Instance '\1' mise à jour."),
        (r"Instance '(.+)' removed\.", r"Instance '\1' retirée."),
        (r"Instance '(.+)' started\.", r"Instance '\1' démarrée."),
        (r"Instance '(.+)' stopped\.", r"Instance '\1' arrêtée."),
        (r"Failed to start instance '(.+)': (.+)", r"Échec du démarrage de l'instance '\1' : \2"),
        (r"Autostart enabled for '(.+)'\.", r"Démarrage automatique activé pour '\1'."),
        (r"Autostart disabled for '(.+)'\.", r"Démarrage automatique désactivé pour '\1'.")
    ]
    for rx, rep in fr_regex_py:
        new_evt = re.sub(rx, rep, evt)
        if new_evt != evt:
            return new_evt
    return evt

def is_proc_running(proc):
    if not proc: return False
    if hasattr(proc, 'poll'): return proc.poll() is None
    if hasattr(proc, 'is_running'):
        try: return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
        except: return False
    return False

def kill_proc_tree(proc):
    """Cleanly terminates the instance process as well as all its child sub-processes (ffmpeg, ffprobe)."""
    if not proc:
        return
    try:
        pid = proc.pid
        parent = psutil.Process(pid) if isinstance(proc, subprocess.Popen) else proc
        children = []
        try:
            children = parent.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        for ch in children:
            try:
                ch.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            parent.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        if isinstance(proc, subprocess.Popen):
            try:
                proc.wait(timeout=1)
            except Exception:
                pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

def get_pid_by_port(port):
    """Find the PID of the process that is listening on the instance's network port."""
    if not port or str(port) == "N/A": return None
    try:
        p_num = int(port)
        for conn in psutil.net_connections(kind='tcp'):
            if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.port == p_num:
                if conn.pid: return conn.pid
    except: pass
    if sys.platform == 'win32':
        try:
            out = subprocess.check_output('netstat -ano -p tcp', shell=True).decode('utf-8', errors='ignore')
            for line in out.splitlines():
                parts = line.strip().split()
                if len(parts) >= 5 and parts[0].upper() == 'TCP' and parts[3].upper() == 'LISTENING':
                    if parts[1].endswith(f":{port}"):
                        return int(parts[4])
        except: pass
    return None

def sync_running_processes():
    """Scans the system to attach to instances that were started before the Manager."""
    global PROCESSES
    # 1. Cleaning up dead processes
    for inst_id in list(PROCESSES.keys()):
        if not is_proc_running(PROCESSES[inst_id]):
            del PROCESSES[inst_id]

    # 2. Robust detection (TCP listening port + standardized command line)
    for inst_id, info in CONFIG['instances'].items():
        if inst_id in PROCESSES and is_proc_running(PROCESSES[inst_id]):
            continue

        inst_path = info.get('path', '')
        norm_target_path = os.path.normcase(os.path.realpath(inst_path)) if inst_path else ''

        # Method A: Listening port resolved via RAM cache with the active language
        port_val = get_cached_instance_config(inst_path, CONFIG.get('language', 'en'))[0]
        pid_port = get_pid_by_port(port_val)
        if pid_port and psutil.pid_exists(pid_port):
            try:
                proc_found = psutil.Process(pid_port)
                if is_proc_running(proc_found):
                    PROCESSES[inst_id] = proc_found
                    continue
            except: pass

        # Method B: Command line (cmdline) and CWD
        if not norm_target_path: continue
        for p in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmd = p.info.get('cmdline') or []
                if not cmd: continue
                cmd_full = " ".join(cmd).lower()
                if 'app.py' in cmd_full:
                    matched = False
                    for arg in cmd:
                        try:
                            if norm_target_path in os.path.normcase(os.path.realpath(arg)):
                                matched = True; break
                        except: pass
                    if not matched:
                        try:
                            if os.path.normcase(os.path.realpath(p.cwd())) == norm_target_path:
                                matched = True
                        except: pass
                    if matched and is_proc_running(p):
                        PROCESSES[inst_id] = p
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

# --- RAM CACHE FOR INSTANCE CONFIGURATIONS ---
CONFIG_CACHE = {}

def get_cached_instance_config(path, lang):
    """Caches the configuration in RAM and only re-reads it from the disk if the file has been modified."""
    conf_path = os.path.join(path, 'config.json')
    default_details = {
        'output_device': 'Non configuré' if lang == 'fr' else 'Not configured',
        'output_gain': 0.0,
        'loss_thresh': -45.0,
        'loss_time': 10,
        'unreach_time': 5,
        'rec_thresh': -35.0,
        'rec_time': 5,
        'selection_mode': 'auto',
        'uecp_any_enabled': False,
        'smtp_enabled': False,
        'sources': [{'name': f'Source {i+1}', 'alert_silent': False, 'alert_unreachable': False} for i in range(3)]
    }
    if not os.path.exists(conf_path):
        return "N/A", default_details

    try:
        mtime = os.path.getmtime(conf_path)
        cached = CONFIG_CACHE.get(conf_path)
        # If the file has not been modified on the disk, it is returned instantly from RAM.
        if cached and cached.get('mtime') == mtime and cached.get('lang') == lang:
            return cached['port'], cached['details']

        with open(conf_path, 'r') as f:
            inst_cfg = json.load(f)

        port = inst_cfg.get('server', {}).get('port', 8090)
        audio_cfg = inst_cfg.get('audio', {})
        out_dev = audio_cfg.get('output_device')
        s_cfg = inst_cfg.get('settings', {})

        try:
            raw_gain = audio_cfg.get('output_gain_db')
            if raw_gain is None:
                raw_gain = audio_cfg.get('out_gain', 0.0)
            out_gain_val = float(raw_gain)
        except (ValueError, TypeError):
            out_gain_val = 0.0
        
        details = {
            'output_device': str(out_dev) if out_dev else ('Par défaut' if lang == 'fr' else 'Default'),
            'output_gain': out_gain_val,
            'loss_thresh': s_cfg.get('loss_threshold_db', -45.0),
            'loss_time': s_cfg.get('loss_timeout_sec', 10),
            'unreach_time': s_cfg.get('unreachable_timeout_sec', 5),
            'rec_thresh': s_cfg.get('recovery_threshold_db', -35.0),
            'rec_time': s_cfg.get('recovery_timeout_sec', 5),
            'selection_mode': str(s_cfg.get('selection_mode', 'auto')),
            'uecp_any_enabled': any(bool(s.get('uecp_enabled', False)) for s in inst_cfg.get('sources', [])[:3]),
            'smtp_enabled': inst_cfg.get('smtp', {}).get('enabled', False),
            'sources': [{'name': f'Source {i+1}', 'alert_silent': False, 'alert_unreachable': False} for i in range(3)]
        }
        src_list = inst_cfg.get('sources', [])
        for i in range(min(3, len(src_list))):
            details['sources'][i] = {
                'name': src_list[i].get('name', f'Source {i+1}'),
                'alert_silent': src_list[i].get('alert_silent', False),
                'alert_unreachable': src_list[i].get('alert_unreachable', False)
            }

        CONFIG_CACHE[conf_path] = {'mtime': mtime, 'lang': lang, 'port': port, 'details': details}
        return port, details
    except:
        return "N/A", default_details

PROC_STATS_CACHE = {}

def get_instance_process_stats(proc):
    """Calculate the actual CPU (%) and RAM (MB) usage of the `app.py` process and all its children (ffmpeg, etc.)."""
    if not is_proc_running(proc):
        return None
    try:
        base_p = psutil.Process(proc.pid) if isinstance(proc, subprocess.Popen) else proc
        main_key = (base_p.pid, base_p.create_time())
        main_p = PROC_STATS_CACHE.get(main_key)
        if not main_p:
            base_p.cpu_percent(interval=None)
            PROC_STATS_CACHE[main_key] = base_p
            main_p = base_p

        procs = [main_p]
        try:
            for child in main_p.children(recursive=True):
                ckey = (child.pid, child.create_time())
                cproc = PROC_STATS_CACHE.get(ckey)
                if not cproc:
                    child.cpu_percent(interval=None)
                    PROC_STATS_CACHE[ckey] = child
                    cproc = child
                procs.append(cproc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        total_cpu = 0.0
        total_ram_bytes = 0
        for p in procs:
            try:
                total_cpu += p.cpu_percent(interval=None)
                total_ram_bytes += p.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        if len(PROC_STATS_CACHE) > 200:
            for k in list(PROC_STATS_CACHE.keys()):
                if not is_proc_running(PROC_STATS_CACHE[k]):
                    del PROC_STATS_CACHE[k]

        cpu_count = psutil.cpu_count() or 1
        total_mem = psutil.virtual_memory().total or 1
        return {
            'cpu': min(100.0, round(total_cpu / cpu_count, 1)),
            'ram_pct': min(100.0, round((total_ram_bytes / total_mem) * 100.0, 1))
        }
    except Exception:
        return None

# --- FLASK APPLICATION ---
flask.cli.show_server_banner = lambda *args, **kwargs: None
logging.getLogger('werkzeug').setLevel(logging.ERROR)
app = Flask(__name__)
app.secret_key = os.urandom(32)
app.config['SESSION_COOKIE_NAME'] = 'wb_manager_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

LOGIN_ATTEMPTS = {}

def get_restarting_page(message, redirect_url="'/'"):
    lang = CONFIG.get('language', 'en')
    title = "Redémarrage du système" if lang == 'fr' else "System Restart"
    sub_txt = "Vous allez être automatiquement redirigé vers la page de connexion dans 5 secondes." if lang == 'fr' else "You will be automatically redirected to the login page in 5 seconds."
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title} - WB-Streamer Manager</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; text-align: center; padding-top: 100px; background: #eef2f5; color: #333; height: 100vh; margin: 0; }}
            .card {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); display: inline-block; min-width: 400px; }}
            h2 {{ color: #3c8dbc; margin-top: 0; font-weight: bold; font-size: 1.5rem; }}
            .loader {{ border: 4px solid #f3f3f3; border-top: 4px solid #3c8dbc; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="loader"></div>
            <h2>{message}</h2>
            <p>{sub_txt}</p>
        </div>
        <script>
            setTimeout(function() {{ window.location.href = {redirect_url}; }}, 5000);
        </script>
    </body>
    </html>
    """

def login_required(f):
    def wrap(*args, **kwargs):
        if not session.get('logged_in'):
            return jsonify({'status': 'error', 'message': 'You do not have the necessary permissions to access this resource - Please log in and try again / Vous ne disposez pas des autorisations nécessaires pour accéder à cette ressource - Veuillez vous connecter puis recommencez'}), 403
        if request.method == 'POST':
            token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
            sess_token = session.get('csrf_token', '')
            if not token or not sess_token or not hmac.compare_digest(str(token), str(sess_token)):
                return jsonify({'status': 'error', 'message': 'Jeton de sécurité CSRF invalide'}), 403
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

@app.route('/')
def index():
    login_error = request.args.get('error') == '1'
    login_lockout = request.args.get('error') == 'lockout'
    lang = CONFIG.get('language', 'en')
    logged_in = bool(session.get('logged_in'))
    hide_name = CONFIG.get('hide_instance_on_login', False)
    safe_cfg = {
        'admin_user': CONFIG['admin_user'],
        'instance_name': '' if (not logged_in and hide_name) else CONFIG.get('instance_name', ''),
        'hide_instance_on_login': hide_name,
        'manager_port': CONFIG['manager_port'],
        'monitor_cpu_ram': CONFIG.get('monitor_cpu_ram', False),
        'local_ip': get_local_ip(),
        'start_time': int(START_TIME)
    }
    if not logged_in:
        return render_template('manager_dashboard.html', login_needed=True, login_error=login_error, login_lockout=login_lockout, lang=lang, cfg=safe_cfg, csrf_token='')
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return render_template('manager_dashboard.html', login_needed=False, lang=lang, cfg=safe_cfg, csrf_token=session['csrf_token'])

@app.route('/login', methods=['POST'])
def login():
    ip = request.remote_addr
    now = time.time()

    if ip in LOGIN_ATTEMPTS:
        LOGIN_ATTEMPTS[ip] = [t for t in LOGIN_ATTEMPTS[ip] if now - t < 90]

    if len(LOGIN_ATTEMPTS.get(ip, [])) >= 3:
        add_internal_log(f"3 failed login attempts from IP {ip}", "AUTH")
        return redirect(url_for('index', error='lockout'))

    username = request.form.get('username', '')
    password = request.form.get('password', '')
    user_ok = hmac.compare_digest(username, CONFIG['admin_user'])
    stored_pw = CONFIG.get('admin_pass', '')
    if is_password_hashed(stored_pw):
        pass_ok = check_password_hash(stored_pw, password)
        if user_ok and pass_ok:
            CONFIG['admin_pass'] = password
            save_config(CONFIG)
    else:
        pass_ok = hmac.compare_digest(password, stored_pw)

    if user_ok and pass_ok:
        if ip in LOGIN_ATTEMPTS:
            del LOGIN_ATTEMPTS[ip]
        session.clear()
        session['logged_in'] = True
        session['csrf_token'] = secrets.token_hex(32)
        add_internal_log(f"Successful login from IP {ip}.", "AUTH")
        return redirect(url_for('index'))

    if ip not in LOGIN_ATTEMPTS:
        LOGIN_ATTEMPTS[ip] = []
    LOGIN_ATTEMPTS[ip].append(now)
    add_internal_log(f"Failed login attempt from IP {ip}", "AUTH")
    return redirect(url_for('index', error='1'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- MANAGER API ---
@app.route('/api/instances', methods=['GET'])
@login_required
def get_instances():
    sync_running_processes()
    instances_data = []
    lang = CONFIG.get('language', 'en')
    monitor_sys = CONFIG.get('monitor_cpu_ram', False)
    
    for inst_id, inst_info in CONFIG['instances'].items():
        path = inst_info['path']
        proc = PROCESSES.get(inst_id)
        is_running = is_proc_running(proc)
        
        # Immediate retrieval from RAM without disk access
        port, inst_details = get_cached_instance_config(path, lang)
        sys_stats = get_instance_process_stats(proc) if (monitor_sys and is_running) else None
                
        instances_data.append({
            'id': inst_id,
            'name': inst_info['name'],
            'path': path,
            'port': port,
            'running': is_running,
            'autostart': inst_info.get('autostart', False),
            'monitor_cpu_ram': monitor_sys,
            'sys_stats': sys_stats,
            'details': inst_details
        })
    
    instances_data.sort(key=lambda x: x['name'].lower())
    return jsonify(instances_data)

@app.route('/api/instances/fetch_name', methods=['POST'])
@login_required
def fetch_name():
    path = request.form.get('path', '').strip()
    conf_path = os.path.join(path, 'config.json')
    if os.path.exists(conf_path):
        try:
            with open(conf_path, 'r') as f:
                name = json.load(f).get('server', {}).get('instance_name', '')
                if name:
                    return jsonify({'status': 'ok', 'name': name})
        except:
            pass
    lang = CONFIG.get('language', 'en')
    return jsonify({'status': 'error', 'message': 'Introuvable' if lang == 'fr' else 'Not found'})

@app.route('/api/instances/add', methods=['POST'])
@login_required
def add_instance():
    name = request.form.get('name', '').strip()
    path = request.form.get('path', '').strip()
    lang = CONFIG.get('language', 'en')
    
    if not name or not path:
        return jsonify({'status': 'error', 'message': 'Champs requis.' if lang == 'fr' else 'Fields required.'})
    
    if not os.path.exists(path) or not os.path.isdir(path):
        return jsonify({'status': 'error', 'message': 'Chemin introuvable.' if lang == 'fr' else 'Path not found.'})
        
    app_py_path = os.path.join(path, 'app.py')
    if not os.path.exists(app_py_path):
        return jsonify({'status': 'error', 'message': 'app.py introuvable.' if lang == 'fr' else 'app.py not found.'})

    norm_new_path = os.path.normcase(os.path.realpath(path))
    new_port = get_cached_instance_config(path, lang)[0]
    for existing_info in CONFIG['instances'].values():
        ex_path = existing_info.get('path', '')
        if ex_path and os.path.normcase(os.path.realpath(ex_path)) == norm_new_path:
            return jsonify({'status': 'error', 'message': 'Cette instance (même dossier) a déjà été ajoutée.' if lang == 'fr' else 'This instance (same folder) has already been added.'})
        if new_port != "N/A":
            ex_port = get_cached_instance_config(ex_path, lang)[0]
            if ex_port != "N/A" and str(ex_port) == str(new_port):
                return jsonify({'status': 'error', 'message': f"Le port {new_port} est déjà utilisé par l'instance '{existing_info.get('name')}'." if lang == 'fr' else f"Port {new_port} is already used by instance '{existing_info.get('name')}'."})
        
    inst_id = str(uuid.uuid4())
    CONFIG['instances'][inst_id] = {
        'name': name,
        'path': path,
        'autostart': (request.form.get('autostart') == 'true')
    }
    save_config(CONFIG)
    add_internal_log(f"Instance '{name}' added.", "INFO")
    
    return jsonify({'status': 'ok'})

@app.route('/api/instances/<inst_id>/edit', methods=['POST'])
@login_required
def edit_instance(inst_id):
    lang = CONFIG.get('language', 'en')
    if inst_id not in CONFIG['instances']:
        return jsonify({'status': 'error', 'message': 'Instance introuvable.' if lang == 'fr' else 'Instance not found.'})

    name = request.form.get('name', '').strip()
    path = request.form.get('path', '').strip()
    autostart = (request.form.get('autostart') == 'true')

    if not name or not path:
        return jsonify({'status': 'error', 'message': 'Champs requis.' if lang == 'fr' else 'Fields required.'})

    if not os.path.exists(path) or not os.path.isdir(path):
        return jsonify({'status': 'error', 'message': 'Chemin introuvable.' if lang == 'fr' else 'Path not found.'})

    app_py_path = os.path.join(path, 'app.py')
    if not os.path.exists(app_py_path):
        return jsonify({'status': 'error', 'message': 'app.py introuvable.' if lang == 'fr' else 'app.py not found.'})

    old_path = CONFIG['instances'][inst_id].get('path', '')
    norm_old_path = os.path.normcase(os.path.realpath(old_path)) if old_path else ''
    norm_new_path = os.path.normcase(os.path.realpath(path))

    if norm_new_path != norm_old_path and is_proc_running(PROCESSES.get(inst_id)):
        return jsonify({'status': 'error', 'message': "Veuillez arrêter l'instance avant de modifier le chemin de son dossier." if lang == 'fr' else "Please stop the instance before changing its folder path."})

    new_port = get_cached_instance_config(path, lang)[0]
    for existing_id, existing_info in CONFIG['instances'].items():
        if existing_id == inst_id:
            continue
        ex_path = existing_info.get('path', '')
        if ex_path and os.path.normcase(os.path.realpath(ex_path)) == norm_new_path:
            return jsonify({'status': 'error', 'message': 'Cette instance (même dossier) est déjà déclarée.' if lang == 'fr' else 'This instance (same folder) is already declared.'})
        if new_port != "N/A":
            ex_port = get_cached_instance_config(ex_path, lang)[0]
            if ex_port != "N/A" and str(ex_port) == str(new_port):
                return jsonify({'status': 'error', 'message': f"Le port {new_port} est déjà utilisé par l'instance '{existing_info.get('name')}'." if lang == 'fr' else f"Port {new_port} is already used by instance '{existing_info.get('name')}'."})

    CONFIG['instances'][inst_id]['name'] = name
    CONFIG['instances'][inst_id]['path'] = path
    CONFIG['instances'][inst_id]['autostart'] = autostart
    save_config(CONFIG)
    add_internal_log(f"Instance '{name}' updated.", "INFO")
    return jsonify({'status': 'ok'})

@app.route('/api/instances/<inst_id>/autostart', methods=['POST'])
@login_required
def toggle_autostart(inst_id):
    if inst_id in CONFIG['instances']:
        val = (request.form.get('autostart') == 'true')
        CONFIG['instances'][inst_id]['autostart'] = val
        save_config(CONFIG)
        add_internal_log(f"Autostart {'enabled' if val else 'disabled'} for '{CONFIG['instances'][inst_id]['name']}'.", "INFO")
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error'})

@app.route('/api/instances/<inst_id>/delete', methods=['POST'])
@login_required
def delete_instance(inst_id):
    if inst_id in CONFIG['instances']:
        inst_name = CONFIG['instances'][inst_id]['name']
        proc = PROCESSES.get(inst_id)
        if is_proc_running(proc):
            kill_proc_tree(proc)
            if inst_id in PROCESSES:
                del PROCESSES[inst_id]
            
        del CONFIG['instances'][inst_id]
        save_config(CONFIG)
        add_internal_log(f"Instance '{inst_name}' removed.", "INFO")
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error', 'message': 'Instance introuvable.'})

@app.route('/api/instances/<inst_id>/start', methods=['POST'])
@login_required
def start_instance(inst_id):
    sync_running_processes()
    inst_info = CONFIG['instances'].get(inst_id)
    if not inst_info:
        return jsonify({'status': 'error', 'message': 'Instance introuvable.'})
        
    proc = PROCESSES.get(inst_id)
    if is_proc_running(proc):
        lang = CONFIG.get('language', 'en')
        return jsonify({'status': 'error', 'message': 'Déjà en cours' if lang == 'fr' else 'Already running'})
        
    path = inst_info['path']
    app_py_path = os.path.join(path, 'app.py')
    
    try:
        popen_kwargs = {
            'cwd': path,
            'stdin': subprocess.DEVNULL,
            'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL,
            'close_fds': True
        }
        if sys.platform == 'win32':
            popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            popen_kwargs['start_new_session'] = True

        PROCESSES[inst_id] = subprocess.Popen([sys.executable, app_py_path], **popen_kwargs)
        add_internal_log(f"Instance '{inst_info['name']}' started.", "SYSTEM")
        return jsonify({'status': 'ok'})
    except Exception as e:
        add_internal_log(f"Failed to start instance '{inst_info['name']}': {e}", "ERROR")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/instances/<inst_id>/stop', methods=['POST'])
@login_required
def stop_instance(inst_id):
    proc = PROCESSES.get(inst_id)
    inst_name = CONFIG['instances'].get(inst_id, {}).get('name', inst_id)
    if is_proc_running(proc):
        kill_proc_tree(proc)
        if inst_id in PROCESSES:
            del PROCESSES[inst_id]
        add_internal_log(f"Instance '{inst_name}' stopped.", "SYSTEM")
        return jsonify({'status': 'ok'})
    return jsonify({'status': 'error', 'message': 'L\'instance n\'est pas en cours d\'exécution.'})

@app.route('/api/manager/config', methods=['GET'])
@login_required
def get_manager_config():
    pw = CONFIG.get('admin_pass', '')
    return jsonify({
        'admin_pass': '' if is_password_hashed(pw) else pw
    })

@app.route('/api/manager/settings', methods=['POST'])
@login_required
def manager_settings():
    new_user = request.form.get('admin_user', '').strip()
    new_pass = request.form.get('admin_pass', '')
    new_lang = request.form.get('language', 'en')
    if new_user:
        CONFIG['admin_user'] = new_user
    if new_pass:
        CONFIG['admin_pass'] = new_pass
    if new_lang in ('en', 'fr'):
        CONFIG['language'] = new_lang
    CONFIG['instance_name'] = request.form.get('instance_name', '').strip()
    CONFIG['hide_instance_on_login'] = (request.form.get('hide_instance_on_login') == 'on')
    CONFIG['monitor_cpu_ram'] = (request.form.get('monitor_cpu_ram') == 'on')
    old_port = CONFIG['manager_port']
    try:
        new_port = int(request.form.get('manager_port', 8000))
        if not (1 <= new_port <= 65535):
            new_port = old_port
    except ValueError:
        new_port = old_port
    CONFIG['manager_port'] = new_port
    save_config(CONFIG)
    
    if old_port != new_port:
        add_internal_log(f"HTTP Port changed from {old_port} to {new_port}. Manager restart requested.", "SYSTEM")
        def restart():
            time.sleep(1)
            subprocess.Popen([sys.executable] + sys.argv)
            os._exit(0)
        threading.Thread(target=restart).start()
        msg = "Port HTTP modifié. Redémarrage du Manager en cours... Veuillez patienter." if CONFIG.get('language', 'en') == 'fr' else "HTTP Port modified. The Manager is restarting... Please wait."
        redirect_js = f"window.location.protocol + '//' + window.location.hostname + ':{new_port}/'"
        return get_restarting_page(msg, redirect_js)
    add_internal_log("Manager settings updated.", "INFO")
    return redirect(url_for('index'))

@app.route('/api/manager/restart', methods=['POST'])
@login_required
def manager_restart():
    add_internal_log("Manager restart requested.", "SYSTEM")
    def restart():
        time.sleep(1)
        subprocess.Popen([sys.executable] + sys.argv)
        os._exit(0)
    threading.Thread(target=restart).start()
    return jsonify({'status': 'ok'})

@app.route('/api/manager/reset', methods=['POST'])
@login_required
def manager_reset():
    global CONFIG
    CONFIG = json.loads(json.dumps(DEFAULT_CONFIG))
    save_config(CONFIG)
    add_internal_log("Factory reset requested.", "SYSTEM")
    def restart():
        time.sleep(1)
        subprocess.Popen([sys.executable] + sys.argv)
        os._exit(0)
    threading.Thread(target=restart).start()
    return jsonify({'status': 'ok'})

@app.route('/api/logs')
@login_required
def api_logs():
    try: page = int(request.args.get('page', 1))
    except: page = 1
    log_filter = request.args.get('filter', 'ALL')
    per_page = 50
    filtered_logs = [log for log in reversed(INTERNAL_LOGS) if log_filter == "ALL" or log['level'] == log_filter]
    total_logs = len(filtered_logs)
    total_pages = max(1, (total_logs + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    return jsonify({
        'logs': filtered_logs[start:start + per_page],
        'total': total_logs,
        'page': page,
        'total_pages': total_pages
    })

@app.route('/logs_export')
@login_required
def logs_export():
    lang = CONFIG.get('language', 'en')
    date_str = datetime.now().strftime('%d-%m-%Y')
    filename = f"WB-Manager_Logs_{date_str}.txt"
    def generate():
        if lang == 'fr':
            yield "Horodatage | Type | Événement\n"
            yield "--------------------------\n"
            for log in INTERNAL_LOGS:
                yield f"{log['timestamp']} | {log['level']} | {translate_log_event_fr(log['event'])}\n"
        else:
            yield "Timestamp | Type | Event\n"
            yield "--------------------------\n"
            for log in INTERNAL_LOGS:
                yield f"{log['timestamp']} | {log['level']} | {log['event']}\n"
    return Response(generate(), mimetype="text/plain", headers={"Content-Disposition": f"attachment;filename={filename}"})

@app.route('/api/logs/clear', methods=['POST'])
@login_required
def clear_logs():
    INTERNAL_LOGS.clear()
    add_internal_log("Logs cleared by user.", "SYSTEM")
    return jsonify({'status': 'ok'})

@app.route('/sys_export')
@login_required
def sys_export():
    save_config(CONFIG)
    return send_file(MANAGER_CONFIG_FILE, as_attachment=True, download_name='manager_config.json')

@app.route('/sys_import', methods=['POST'])
@login_required
def sys_import():
    lang = CONFIG.get('language', 'en')
    if 'config_file' not in request.files:
        return "Aucun fichier" if lang == 'fr' else "No file", 400
    file = request.files['config_file']
    if not file or file.filename == '':
        return "Nom de fichier manquant" if lang == 'fr' else "No filename", 400
    try:
        parsed = json.loads(file.read().decode('utf-8'))
        if not isinstance(parsed, dict) or 'instances' not in parsed:
            return "Format de fichier invalide" if lang == 'fr' else "Invalid configuration file", 400
        for k, v in DEFAULT_CONFIG.items():
            if k not in parsed:
                parsed[k] = json.loads(json.dumps(v))
        try:
            new_port = int(parsed.get('manager_port', CONFIG.get('manager_port', 8000)))
            if not (1 <= new_port <= 65535):
                new_port = CONFIG.get('manager_port', 8000)
        except (ValueError, TypeError):
            new_port = CONFIG.get('manager_port', 8000)
        parsed['manager_port'] = new_port
        save_config(parsed)
        add_internal_log("Configuration imported.", "SYSTEM")
        def restart_thread():
            time.sleep(1)
            subprocess.Popen([sys.executable] + sys.argv)
            os._exit(0)
        threading.Thread(target=restart_thread).start()
        msg = "Fichier de configuration importé avec succès. Redémarrage du Manager..." if lang == 'fr' else "The configuration file has been imported successfully. Restarting the Manager..."
        redirect_js = f"window.location.protocol + '//' + window.location.hostname + ':{new_port}/'" if new_port != CONFIG.get('manager_port', 8000) else "'/'"
        return get_restarting_page(msg, redirect_js)
    except Exception:
        return "Erreur de lecture du fichier JSON" if lang == 'fr' else "Error parsing JSON configuration file", 400

# --- HOST INTERFACE (TKINTER) ---
def start_gui():
    root = tk.Tk()
    root.title("WB-Streamer Manager")
    try:
        icon_path = os.path.join('static', 'favicon.ico')
        if os.path.exists(icon_path):
            root.iconbitmap(icon_path)
    except:
        pass
    root.resizable(False, False)
    
    win_w, win_h = 520, 225
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    root.geometry(f"{win_w}x{win_h}+{(screen_w - win_w) // 2}+{(screen_h - win_h) // 2}")
    root.configure(bg="#eef2f5")
    
    port = CONFIG['manager_port']
    lbl_title = tk.Label(root, text="", fg="#198754", bg="#eef2f5", font=("Segoe UI", 13, "bold"))
    lbl_title.pack(pady=(20, 5))
    lbl_sub = tk.Label(root, text="", fg="#555", bg="#eef2f5", font=("Segoe UI", 10))
    lbl_sub.pack(pady=(0, 12))
    
    btn = tk.Button(root, text="", 
                    bg="#3c8dbc", fg="white", activebackground="#337ab7", activeforeground="white", 
                    font=("Segoe UI", 9, "bold"), relief=tk.FLAT, cursor="hand2", 
                    command=lambda: webbrowser.open(f"http://localhost:{port}"))
    btn.pack(fill=tk.X, padx=40, ipadx=10, ipady=6)

    lbl_instances = tk.Label(root, text="", fg="#555", bg="#eef2f5", font=("Segoe UI", 10, "bold"))
    lbl_instances.pack(pady=(14, 4))
    lbl_ip = tk.Label(root, text="", fg="#555", bg="#eef2f5", font=("Segoe UI", 11))
    lbl_ip.pack(pady=(0, 0))

    def update_gui_lang():
        cur_lang = CONFIG.get('language', 'en')
        local_ip = get_local_ip()
        inst_ids = list(CONFIG.get('instances', {}).keys())
        total_inst = len(inst_ids)
        active_inst = sum(1 for iid in inst_ids if is_proc_running(PROCESSES.get(iid)))
        if cur_lang == 'fr':
            lbl_title.config(text=f"MANAGER ACTIF - INTERFACE DISPONIBLE SUR LE PORT {port}")
            lbl_sub.config(text="Veuillez garder cette fenêtre ouverte, sinon la surveillance sera interrompue !")
            btn.config(text="CLIQUEZ ICI POUR ACCÉDER À L'INTERFACE\n(Identifiants par défaut : admin/admin)")
            lbl_instances.config(text=f"Instances actuellement actives : {active_inst}/{total_inst}")
            lbl_ip.config(text=f"IP : {local_ip}")
        else:
            lbl_title.config(text=f"MANAGER ACTIVE - INTERFACE AVAILABLE ON PORT {port}")
            lbl_sub.config(text="Please keep this window open, otherwise the monitoring will be interrupted!")
            btn.config(text="CLICK HERE TO ACCESS THE INTERFACE\n(Default credentials: admin/admin)")
            lbl_instances.config(text=f"Currently active instances: {active_inst}/{total_inst}")
            lbl_ip.config(text=f"IP: {local_ip}")
        root.after(1000, update_gui_lang)

    update_gui_lang()
    
    from tkinter import messagebox
    def on_closing():
        cur_lang = CONFIG.get('language', 'en')
        if cur_lang == 'fr':
            title = "Demande de confirmation"
            msg = "Êtes-vous sûr de vouloir arrêter WB-Streamer Manager ?\n\nATTENTION : La fermeture de cette fenêtre occasionnera l'arrêt de l'interface web du superviseur."
        else:
            title = "Closure Confirmation"
            msg = "Are you sure you want to stop WB-Streamer Manager?\n\nWARNING: Closing this window will cause the supervisor's web interface to shut down."

        if messagebox.askyesno(title, msg):
            # Launched instances remain active independently, even if the Manager is closed.
            root.destroy()
            os._exit(0)
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == '__main__':
    add_internal_log("Manager started.", "SYSTEM")
    # Automatic startup of configured instances (detached from the Manager)
    sync_running_processes()
    for inst_id, info in CONFIG['instances'].items():
        if info.get('autostart', False) and not is_proc_running(PROCESSES.get(inst_id)):
            try:
                popen_kwargs = {
                    'cwd': info['path'],
                    'stdin': subprocess.DEVNULL,
                    'stdout': subprocess.DEVNULL,
                    'stderr': subprocess.DEVNULL,
                    'close_fds': True
                }
                if sys.platform == 'win32':
                    popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                else:
                    popen_kwargs['start_new_session'] = True
                PROCESSES[inst_id] = subprocess.Popen([sys.executable, os.path.join(info['path'], 'app.py')], **popen_kwargs)
                add_internal_log(f"Instance '{info['name']}' started automatically.", "SYSTEM")
            except: pass

    # Starts the Flask server in a separate thread
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=CONFIG['manager_port'], debug=False, use_reloader=False), daemon=True).start()
    print(f"--- MANAGER READY ON PORT {CONFIG['manager_port']} ---")
    start_gui()