#!/usr/bin/env python3
import socket, threading, json, tkinter as tk
from tkinter import messagebox
import sys
import socket  # pentru UDP
 # pentru UDP

SERVER_HOST = '127.0.0.1'
TCP_PORT = 9009
UDP_PORT = 9010
send_lock = threading.Lock()

class TriviaClient:
    def __init__(self, name):
        self.name = name
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.gui = None
        self.alive = True

    def connect(self, host=None, port=None):
        host = host or SERVER_HOST
        port = port or TCP_PORT
        self.tcp.connect((host, port))
        self.safe_send({'name': self.name})
        threading.Thread(target=self.tcp_recv_loop, daemon=True).start()

    def safe_send(self, obj):
        try:
            with send_lock:
                self.tcp.sendall((json.dumps(obj, ensure_ascii=False)+"\n").encode('utf-8'))
        except:
            pass

    def tcp_recv_loop(self):
        buffer = ""
        while self.alive:
            try:
                data = self.tcp.recv(4096)
                if not data: break
                buffer += data.decode('utf-8', errors='ignore')
                while "\n" in buffer:
                    line, buffer = buffer.split("\n",1)
                    if not line.strip(): continue
                    try: obj = json.loads(line)
                    except: continue
                    self.handle_msg(obj)
            except:
                break
        if self.gui: self.gui.root.after(0,self.gui.log,"Disconnected from server")
        try: self.tcp.close()
        except: pass

    def handle_msg(self,obj):
        t = obj.get('type')
        if t in ('WELCOME','INFO'):
            if self.gui: self.gui.root.after(0,self.gui.log,obj.get('msg',''))
        elif t=='QUESTION':
            if self.gui: self.gui.root.after(0,self.gui.show_question,obj)
        elif t=='SCORES':
            if self.gui: self.gui.root.after(0,self.gui.update_scores,obj.get('scores',{}))

    def send_answer(self,qid,answer):
        self.safe_send({'type':'ANSWER','id':qid,'answer':answer})

    def restart(self):
        self.safe_send({'type':'RESTART'})

    def stop_server(self):
        self.safe_send({'type':'STOP'})

    def buzz(self):
        try:
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST,1)
            payload = f'BUZZ:{self.name}'.encode('utf-8')
            u.sendto(payload,( '<broadcast>', UDP_PORT))
            u.close()
        except Exception as e:
            if self.gui: self.gui.root.after(0,self.gui.log,f"Buzz failed: {e}")

class TriviaGUI:
    def __init__(self,root,client):
        self.client=client
        self.root=root
        self.current_qid=None
        self.current_choices=[]

        top_frame = tk.Frame(root)
        top_frame.pack(padx=10,pady=10)

        self.question_var = tk.StringVar()
        self.question_label = tk.Label(top_frame,textvariable=self.question_var,wraplength=500,font=('Arial',14))
        self.question_label.pack(pady=(0,10))

        self.buttons=[]
        for i in range(4):
            b=tk.Button(top_frame,text=f'Choice {i+1}',width=60,command=lambda idx=i:self.on_choice(idx))
            b.pack(pady=2)
            self.buttons.append(b)

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=6)
        self.restart_btn=tk.Button(btn_frame,text='Restart joc',bg='orange',command=self.on_restart)
        self.restart_btn.pack(side='left', padx=6)
        self.stop_btn=tk.Button(btn_frame,text='Stop Server',bg='red',command=self.on_stop)
        self.stop_btn.pack(side='left', padx=6)
        self.buzz_btn=tk.Button(btn_frame,text='BUZZ',bg='green',command=self.on_buzz)
        self.buzz_btn.pack(side='left', padx=6)

        self.logbox = tk.Text(root,height=10,width=80)
        self.logbox.pack(padx=10,pady=6)
        self.scores_label = tk.Label(root,text='Scores: -',font=('Arial',12,'bold'))
        self.scores_label.pack(pady=(0,10))

    def log(self,txt):
        self.logbox.insert('end',f'{txt}\n')
        self.logbox.see('end')

    def show_question(self,obj):
        self.current_qid=obj.get('id')
        self.question_var.set(obj.get('text',''))
        choices=obj.get('choices',[])
        self.current_choices=choices
        for i,b in enumerate(self.buttons):
            if i<len(choices): b.config(text=choices[i],state='normal')
            else: b.config(text='-',state='disabled')

    def on_choice(self,idx):
        if idx<len(self.current_choices):
            answer=self.current_choices[idx]
            self.client.send_answer(self.current_qid,answer)
            self.log(f'Trimis: {answer}')
            for b in self.buttons: b.config(state='disabled')

    def update_scores(self,scores):
        s=', '.join([f'{k}:{v}' for k,v in scores.items()])
        self.scores_label.config(text='Scores: '+s)

    def on_restart(self):
        self.client.restart()
        self.log("Ai cerut restart joc")

    def on_stop(self):
        if messagebox.askyesno("Confirm","Oprești serverul? Toți jucătorii vor fi deconectați."):
            self.client.stop_server()
            self.log("Ai cerut oprirea serverului")

    def on_buzz(self):
        self.client.buzz()
        self.log("BUZZ trimis!")

if __name__=='__main__':
    if len(sys.argv)>1: name=sys.argv[1]
    else:
        try: name=input("Nume jucator: ").strip() or "Anonim"
        except: name="Anonim"

    root=tk.Tk()
    root.title('Trivia Client')
    root.geometry("600x500")

    client=TriviaClient(name)
    gui=TriviaGUI(root,client)
    client.gui=gui

    try: client.connect()
    except Exception as e:
        tk.messagebox.showerror("Eroare",f"Conectare esuata: {e}")
        raise SystemExit(1)

    def on_close():
        try: client.alive=False; client.tcp.close()
        except: pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW",on_close)
    root.mainloop()
