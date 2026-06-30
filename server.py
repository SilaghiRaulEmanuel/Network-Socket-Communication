#!/usr/bin/env python3
import socket, threading, json, time, os
from pathlib import Path

# ---------------------------------------------------------------
# CONFIGURARE SERVER
# ---------------------------------------------------------------
TCP_HOST = '0.0.0.0'
TCP_PORT = 9009
UDP_HOST = '0.0.0.0'
UDP_PORT = 9010

QUESTION_TIMEOUT = 10
MIN_PLAYERS_TO_START = 2
QUESTIONS_FILE = 'questions.json'

# ---------------------------------------------------------------
# STARE GLOBALĂ
# ---------------------------------------------------------------
clients_lock = threading.Lock()
clients = {}  # conn -> {'name':..., 'addr':(...)}

scores_lock = threading.Lock()
scores = {}  # name -> puncte

answers_lock = threading.Lock()
answers = {}  # name -> answer

buzz_lock = threading.Lock()
buzzed_player = None  # primul care a buzz-uit la întrebarea curentă

current_qid = None

stop_event = threading.Event()
restart_event = threading.Event()
players_cond = threading.Condition()

# ---------------------------------------------------------------
# ÎNCĂRCARE ÎNTREBĂRI
# ---------------------------------------------------------------
script_dir = Path(__file__).parent
qfile = script_dir / QUESTIONS_FILE
if not qfile.exists():
    print(f"Nu am găsit {QUESTIONS_FILE}")
    raise SystemExit(1)

with open(qfile, 'r', encoding='utf-8') as f:
    QUESTIONS = json.load(f)

# ---------------------------------------------------------------
def safe_print(*a, **k):
    print(*a, **k)

# ---------------------------------------------------------------
# UDP LISTENER PENTRU BUZZ
# ---------------------------------------------------------------
def udp_listener():
    global buzzed_player
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((UDP_HOST, UDP_PORT))
    except Exception as e:
        safe_print(f"[UDP] Bind error: {e}")
        return
    s.settimeout(1.0)
    safe_print(f"[UDP] Listening on {UDP_HOST}:{UDP_PORT}")

    while not stop_event.is_set():
        try:
            data, addr = s.recvfrom(4096)
            text = data.decode('utf-8', errors='ignore').strip()
            if text.startswith('BUZZ:'):
                name = text.split(':', 1)[1]
                with buzz_lock:
                    if buzzed_player is None:
                        buzzed_player = name  # setăm instant jucătorul care a buzz-uit
                        safe_print(f"[UDP] BUZZ from {name} ({addr})")
                        # trimite confirmare direct și info celorlalți
                        with clients_lock:
                            for conn, info in clients.items():
                                try:
                                    if info['name'] == name:
                                        conn.sendall((json.dumps({'type':'BUZZ_GRANTED','name':name})+"\n").encode())
                                    else:
                                        conn.sendall((json.dumps({'type':'INFO','msg':f'BUZZ de la {name}!'}))+"\n".encode())
                                except: pass
        except socket.timeout:
            continue
        except Exception as e:
            safe_print(f"[UDP] Error: {e}")
            continue
    try: s.close()
    except: pass
    safe_print("[UDP] Listener stopped")

# ---------------------------------------------------------------
# BROADCAST TCP
# ---------------------------------------------------------------
def broadcast(obj):
    to_remove = []
    with clients_lock:
        for conn in list(clients.keys()):
            try:
                conn.sendall((json.dumps(obj, ensure_ascii=False)+"\n").encode('utf-8'))
            except:
                to_remove.append(conn)
        for c in to_remove:
            try: c.close()
            except: pass
            clients.pop(c, None)

# ---------------------------------------------------------------
# CLIENT THREAD TCP
# ---------------------------------------------------------------
def client_thread(conn, addr):
    name = None
    try:
        conn.sendall((json.dumps({'type': 'WELCOME','msg':'Trimite numele tau'})+"\n").encode())
        data = conn.recv(4096)
        if not data:
            conn.close()
            return
        try: obj = json.loads(data.decode('utf-8', errors='ignore'))
        except: conn.close(); return

        name = obj.get('name','Anonim')

        with clients_lock:
            clients[conn] = {'name': name, 'addr': addr}
            safe_print(f"[TCP] {name} connected from {addr} ({len(clients)} clients)")

        conn.sendall((json.dumps({'type':'INFO','msg':'Asteapta jocul...'})+"\n").encode())
        with players_cond:
            players_cond.notify_all()

        buffer = ""
        conn.settimeout(1.0)

        while not stop_event.is_set():
            try:
                data = conn.recv(4096)
                if not data: break
                buffer += data.decode('utf-8', errors='ignore')
                while "\n" in buffer:
                    line, buffer = buffer.split("\n",1)
                    if not line.strip(): continue
                    try: obj = json.loads(line)
                    except: continue

                    t = obj.get('type')
                    global current_qid, buzzed_player

                    if t=='RESTART':
                        safe_print(f"[TCP] RESTART requested by {name}")
                        restart_event.set()
                    elif t=='STOP':
                        safe_print(f"[TCP] STOP requested by {name}")
                        broadcast({'type':'INFO','msg':'Server se oprește la cerere.'})
                        stop_event.set()
                        with players_cond:
                            players_cond.notify_all()
                    elif t=='ANSWER':
                        qid = obj.get('id')
                        ans = obj.get('answer')
                        with answers_lock, buzz_lock:
                            # acceptăm răspunsul dacă e jucătorul care a buzz-uit
                            if qid == current_qid and name == buzzed_player and name not in answers:
                                answers[name] = ans
            except socket.timeout:
                continue
            except: break
    except Exception as e:
        safe_print(f"[TCP] Exception: {e}")
    finally:
        with clients_lock:
            if conn in clients:
                safe_print(f"[TCP] {clients[conn]['name']} disconnected")
                del clients[conn]
        try: conn.close()
        except: pass
        with players_cond:
            players_cond.notify_all()

# ---------------------------------------------------------------
# START TCP SERVER
# ---------------------------------------------------------------
def start_tcp_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((TCP_HOST, TCP_PORT))
    s.listen(32)
    safe_print(f"[TCP] Listening on {TCP_HOST}:{TCP_PORT}")

    def accept_loop():
        while not stop_event.is_set():
            try:
                conn, addr = s.accept()
                threading.Thread(target=client_thread, args=(conn, addr), daemon=True).start()
            except:
                break
        try: s.close()
        except: pass

    threading.Thread(target=accept_loop, daemon=True).start()

# ---------------------------------------------------------------
# GAME LOOP
# ---------------------------------------------------------------
def game_loop():
    global current_qid, answers, buzzed_player
    threading.Thread(target=udp_listener, daemon=True).start()

    while not stop_event.is_set():
        with players_cond:
            while len(clients)<MIN_PLAYERS_TO_START and not stop_event.is_set():
                broadcast({'type':'INFO', 'msg':f'Așteptăm cel puțin {MIN_PLAYERS_TO_START} jucători...'})
                players_cond.wait(timeout=1.0)
        if stop_event.is_set(): break

        with scores_lock:
            scores.clear()
            for info in clients.values():
                scores.setdefault(info['name'],0)

        restart_event.clear()
        broadcast({'type':'INFO','msg':'Începem jocul!'})
        safe_print("Game started")

        for q in QUESTIONS:
            if stop_event.is_set() or restart_event.is_set(): break

            with answers_lock, buzz_lock:
                current_qid = q['id']
                answers.clear()
                buzzed_player = None

            broadcast({'type':'QUESTION','id':q['id'],'text':q['question'],'choices':q['choices']})
            safe_print(f"Broadcast question {q['id']} - {q['question']}")

            waited = 0.0
            interval = 0.1
            while waited < QUESTION_TIMEOUT and not restart_event.is_set() and not stop_event.is_set():
                time.sleep(interval)
                waited += interval

            with answers_lock, scores_lock:
                correct = q.get('answer')
                for name, ans in answers.items():
                    if ans == correct:
                        scores[name] += 10
                        broadcast({'type':'INFO','msg':f'{name} a raspuns corect! +10'})
                    else:
                        broadcast({'type':'INFO','msg':f'{name} a raspuns gresit. (fara penalizare)'})

                for info in clients.values():
                    if info['name'] not in answers:
                        broadcast({'type':'INFO','msg':f"{info['name']} nu a raspuns. (fara penalizare)"})

                broadcast({'type':'SCORES','scores':scores})
            time.sleep(0.5)

        broadcast({'type':'INFO','msg':'Sfârșitul jocului!'})
        safe_print("Match finished")

        while not restart_event.is_set() and not stop_event.is_set():
            time.sleep(1)

        if restart_event.is_set():
            restart_event.clear()
            with scores_lock, answers_lock:
                scores.clear()
                answers.clear()
                current_qid = None
            broadcast({'type':'INFO','msg':'Runda s-a repornit!'})

    safe_print("Server shutting down")
    broadcast({'type':'INFO','msg':'Server se oprește acum.'})
    with clients_lock:
        for c in list(clients.keys()):
            try: c.close()
            except: pass
        clients.clear()
    time.sleep(0.2)
    os._exit(0)

# ---------------------------------------------------------------
if __name__=='__main__':
    safe_print("Server starting...")
    start_tcp_server()
    try:
        game_loop()
    except KeyboardInterrupt:
        safe_print("KeyboardInterrupt - stopping")
        stop_event.set()
        time.sleep(0.2)
        os._exit(0)
