#!/usr/bin/env python3
"""
MindWriter GUI  —  Tkinter desktop app styled to match the web UI.
Run:  python3 mindwriter_gui.py   [--api http://localhost:9000]
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import urllib.request, urllib.error, urllib.parse
import json, threading, argparse, sys, os, subprocess, time

# ── Palette ────────────────────────────────────────────────────────────────
BG=    "#0c0c0f"; SURF=  "#121218"; SURF2= "#18181f"; BORDER="#222230"
ACCENT="#b8f050"; BLUE=  "#50c8f0"; MUTED= "#50506a"; TEXT=  "#d8d8e8"
DIM=   "#8888a0"; DANGER="#f05858"

_m=sys.platform=="darwin"; _w=sys.platform=="win32"
MONO=("Menlo",10) if _m else ("Consolas",10) if _w else ("DejaVu Sans Mono",10)
SANS=("Helvetica Neue",10) if _m else ("Segoe UI",10) if _w else ("DejaVu Sans",10)
MONO9=(MONO[0],9); SANS9=(SANS[0],9)

# ── API client ─────────────────────────────────────────────────────────────
class API:
    def __init__(self, base="http://localhost:8000"):
        self.base=base.rstrip("/"); self.key=""
    def _req(self,method,path,data=None,timeout=15):
        url=self.base+path
        body=json.dumps(data).encode() if data is not None else None
        h={}
        if self.key: h["X-API-Key"]=self.key
        if body: h["Content-Type"]="application/json"
        req=urllib.request.Request(url,data=body,headers=h,method=method)
        with urllib.request.urlopen(req,timeout=timeout) as r:
            return json.loads(r.read().decode())
    def get(self,p,t=15):   return self._req("GET",p,timeout=t)
    def post(self,p,d=None): return self._req("POST",p,data=d)
    def put(self,p,d=None):  return self._req("PUT",p,data=d)
    def delete(self,p):      return self._req("DELETE",p)
    def health(self):
        try:   self._req("GET","/health",timeout=3); return True
        except: return False
    def fetch_key(self):
        try:   return self._req("GET","/api/auth/key",timeout=3).get("api_key","")
        except: return ""
    def upload_file(self,url_path,filepath,extra=None):
        boundary="MWB888"; fname=os.path.basename(filepath)
        with open(filepath,"rb") as fh: fd=fh.read()
        parts=[]
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                       f"filename=\"{fname}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
                       ).encode()+fd+b"\r\n")
        for k,v in (extra or {}).items():
            parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode())
        parts.append(f"--{boundary}--\r\n".encode())
        body=b"".join(parts)
        req=urllib.request.Request(self.base+url_path,data=body,method="POST")
        req.add_header("Content-Type",f"multipart/form-data; boundary={boundary}")
        if self.key: req.add_header("X-API-Key",self.key)
        with urllib.request.urlopen(req,timeout=60) as r:
            return json.loads(r.read().decode())

api=API()
app=None
_api_process=None

# ── API Server Startup ─────────────────────────────────────────────────────
def start_api_server():
    """Start the Flask API server in a subprocess."""
    global _api_process
    try:
        env=os.environ.copy()
        env['MINDWRITER_GUI_STARTED']='1'
        _api_process=subprocess.Popen(
            [sys.executable,os.path.join(os.path.dirname(__file__),'mindwriter_api.py')],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env
        )
        print(f"✓ API server started (PID: {_api_process.pid})")
        time.sleep(2)
    except Exception as e:
        print(f"✗ Failed to start API server: {e}")

def stop_api_server():
    """Stop the API server process."""
    global _api_process
    if _api_process:
        try:
            _api_process.terminate()
            _api_process.wait(timeout=3)
            print("✓ API server stopped")
        except subprocess.TimeoutExpired:
            _api_process.kill()
            print("✓ API server killed")
        except Exception as e:
            print(f"✗ Error stopping API: {e}")

def async_run(fn,*args,ok=None,err=None):
    def _w():
        try:
            r=fn(*args)
            if ok: app.after(0,lambda:ok(r))
        except Exception as exc:
            if err: app.after(0,lambda:err(exc))
    threading.Thread(target=_w,daemon=True).start()

# ── Primitive helpers ──────────────────────────────────────────────────────
def frm(p,bg=BG,**kw):  return tk.Frame(p,bg=bg,**kw)
def lbl(p,t="",fg=TEXT,bg=BG,font=None,**kw):
    return tk.Label(p,text=t,fg=fg,bg=bg,font=font or SANS,**kw)
def hsep(p): return tk.Frame(p,bg=BORDER,height=1)
def vsep(p): return tk.Frame(p,bg=BORDER,width=1)

def entry(p,textvariable=None,show=None,font=None,**kw):
    kw2=dict(bg=SURF2,fg=TEXT,insertbackground=ACCENT,relief="flat",
             font=font or SANS,highlightthickness=1,
             highlightbackground=BORDER,highlightcolor=ACCENT,
             selectbackground=BLUE)
    if textvariable: kw2["textvariable"]=textvariable
    if show: kw2["show"]=show
    kw2.update(kw)
    return tk.Entry(p,**kw2)

def btn_accent(p,t,cmd,**kw):
    return tk.Button(p,text=t,command=cmd,bg=ACCENT,fg=BG,
                     activebackground=ACCENT,activeforeground=BG,
                     relief="flat",cursor="hand2",
                     font=(SANS[0],SANS[1],"bold"),
                     padx=12,pady=5,highlightthickness=0,**kw)

def btn_ghost(p,t,cmd,**kw):
    return tk.Button(p,text=t,command=cmd,bg=SURF2,fg=BG,
                     activebackground=SURF2,activeforeground=BG,
                     relief="flat",cursor="hand2",font=SANS,
                     padx=10,pady=4,highlightthickness=1,
                     highlightbackground=BORDER,highlightcolor=ACCENT,**kw)

def btn_danger(p,t,cmd,**kw):
    return tk.Button(p,text=t,command=cmd,bg=SURF2,fg=BG,
                     activebackground=SURF2,activeforeground=BG,
                     relief="flat",cursor="hand2",font=SANS,
                     padx=10,pady=4,highlightthickness=1,
                     highlightbackground=DANGER,highlightcolor=DANGER,**kw)

def scrolled_text(p,bg=BG,fg=DIM,font=None,**kw):
    f=frm(p,bg=bg)
    sb=tk.Scrollbar(f,orient="vertical",bg=BORDER,troughcolor=BG,
                    activebackground=MUTED,relief="flat",width=6,highlightthickness=0)
    t=tk.Text(f,yscrollcommand=sb.set,bg=bg,fg=fg,insertbackground=ACCENT,
              relief="flat",font=font or MONO,wrap="word",borderwidth=0,
              highlightthickness=0,selectbackground=BLUE,spacing3=3,
              padx=24,pady=4,**kw)
    sb.config(command=t.yview); t.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
    return f,t

# ── Canvas note list (styled like .note-row) ───────────────────────────────
class NoteList(tk.Canvas):
    RH=62
    def __init__(self,p,on_sel=None,on_edit=None,on_del=None):
        super().__init__(p,bg=SURF,highlightthickness=0,relief="flat",bd=0)
        self._on_sel=on_sel; self._on_edit=on_edit; self._on_del=on_del
        self._notes=[]; self._sel=-1; self._hover=-1; self._off=0
        self.bind("<Configure>",self._draw)
        self.bind("<ButtonRelease-1>",self._click)
        self.bind("<Motion>",self._motion)
        self.bind("<Leave>",self._leave)
        self.bind("<Enter>",lambda e:self.focus_set())
        self.bind("<MouseWheel>",self._wheel)
        self.bind("<Button-4>",lambda e:self._scroll(-1))
        self.bind("<Button-5>",lambda e:self._scroll(1))
    def attach_vsb(self,sb):
        sb.config(command=self._vsb_cmd); self._vsb=sb
    def _update_vsb(self):
        h=self.winfo_height(); tot=len(self._notes)*self.RH
        if tot<=0: tot=1
        self._vsb.set(self._off/tot,min(1,(self._off+h)/tot))
    def _vsb_cmd(self,*a):
        if a[0]=="moveto": self._off=int(float(a[1])*max(1,len(self._notes)*self.RH))
        elif a[0]=="scroll": self._off+=int(a[1])*self.RH*(1 if a[2]=="units" else 5)
        self._clamp(); self._draw()
    def _wheel(self,e): self._scroll(-1 if (e.delta>0 or e.num==4) else 1)
    def _scroll(self,d): self._off+=d*self.RH; self._clamp(); self._draw(); self._update_vsb()
    def _clamp(self):
        h=self.winfo_height(); tot=len(self._notes)*self.RH
        self._off=max(0,min(self._off,max(0,tot-h)))
    def set_notes(self,notes,sel_id=None):
        self._notes=notes; self._sel=next((i for i,n in enumerate(notes) if n["id"]==sel_id),-1); self._draw(); self._update_vsb()
    def select_id(self,nid):
        self._sel=next((i for i,n in enumerate(self._notes) if n["id"]==nid),-1); self._draw()
    def _row_at(self,y): i=(y+self._off)//self.RH; return i if 0<=i<len(self._notes) else -1
    def _click(self,e):
        i=self._row_at(e.y)
        if i<0: return
        w=self.winfo_width()
        if e.x>w-34:
            if self._on_del: self._on_del(self._notes[i])
        elif e.x>w-70:
            if self._on_edit: self._on_edit(self._notes[i])
        else:
            self._sel=i; self._draw()
            if self._on_sel: self._on_sel(self._notes[i])
    def _motion(self,e):
        i=self._row_at(e.y)
        if i!=self._hover: self._hover=i; self._draw()
    def _leave(self,e):
        self._hover=-1; self._draw()
    def _draw(self,_=None):
        self.delete("all"); w=self.winfo_width(); h=self.winfo_height()
        if not w: return
        for i,n in enumerate(self._notes):
            y0=i*self.RH-self._off; y1=y0+self.RH
            if y1<0 or y0>h: continue
            sel=i==self._sel; hov=i==self._hover
            self.create_rectangle(0,y0,w,y1,fill=SURF2 if (sel or hov) else SURF,outline="")
            if sel: self.create_rectangle(0,y0,2,y1,fill=ACCENT,outline="")
            self.create_line(0,y1-1,w,y1-1,fill=BORDER)
            x=14 if not sel else 16
            self.create_text(x,y0+14,text=f"#{n['id']}",anchor="w",fill=MUTED,font=MONO9)
            title=(n.get("title") or n["filename"]).title()
            self.create_text(x,y0+31,text=title[:44],anchor="w",
                             fill=ACCENT if sel else TEXT,
                             font=(SANS[0],SANS[1],"bold"))
            parts=[p for p in [n.get("author",""),
                                n.get("modified","")[:10] if n.get("modified") else "",
                                n.get("priority","")] if p]
            if parts: self.create_text(x,y0+47,text="  ".join(parts)[:52],anchor="w",fill=MUTED,font=SANS9)
            if sel or hov:
                self.create_rectangle(w-68,y0+19,w-38,y0+43,fill=SURF,outline=BORDER)
                self.create_text(w-53,y0+31,text="✎",fill=MUTED,font=SANS9)
                self.create_rectangle(w-34,y0+19,w-4,y0+43,fill=SURF,outline=BORDER)
                self.create_text(w-19,y0+31,text="✕",fill=MUTED,font=SANS9)
        self.configure(scrollregion=(0,0,w,len(self._notes)*self.RH))
        self._update_vsb()

# ── Canvas dataset list ────────────────────────────────────────────────────
class DSList(tk.Canvas):
    RH=54
    def __init__(self,p,on_sel=None):
        super().__init__(p,bg=SURF,highlightthickness=0,relief="flat",bd=0)
        self._on_sel=on_sel; self._ds=[]; self._sel=-1; self._hover=-1; self._off=0
        self.bind("<Configure>",self._draw)
        self.bind("<ButtonRelease-1>",self._click)
        self.bind("<Motion>",self._motion)
        self.bind("<Leave>",self._leave)
        self.bind("<Enter>",lambda e:self.focus_set())
        self.bind("<MouseWheel>",self._wheel)
        self.bind("<Button-4>",lambda e:self._scroll(-1))
        self.bind("<Button-5>",lambda e:self._scroll(1))
    def _wheel(self,e): self._scroll(-1 if (e.delta>0 or e.num==4) else 1)
    def _scroll(self,d): self._off+=d*self.RH; self._clamp(); self._draw()
    def _clamp(self):
        h=self.winfo_height(); tot=len(self._ds)*self.RH
        self._off=max(0,min(self._off,max(0,tot-h)))
    def set_ds(self,ds,sel_id=None):
        self._ds=ds; self._sel=next((i for i,d in enumerate(ds) if d["id"]==sel_id),-1); self._draw()
    def _row_at(self,y): i=(y+self._off)//self.RH; return i if 0<=i<len(self._ds) else -1
    def _click(self,e):
        i=self._row_at(e.y)
        if i<0: return
        self._sel=i; self._draw()
        if self._on_sel: self._on_sel(self._ds[i])
    def _motion(self,e):
        i=self._row_at(e.y)
        if i!=self._hover: self._hover=i; self._draw()
    def _leave(self,e): self._hover=-1; self._draw()
    def _draw(self,_=None):
        self.delete("all"); w=self.winfo_width(); h=self.winfo_height()
        if not w: return
        for i,d in enumerate(self._ds):
            y0=i*self.RH-self._off; y1=y0+self.RH
            if y1<0 or y0>h: continue
            sel=i==self._sel; hov=i==self._hover
            self.create_rectangle(0,y0,w,y1,fill=SURF2 if (sel or hov) else SURF,outline="")
            if sel: self.create_rectangle(0,y0,2,y1,fill=BLUE,outline="")
            self.create_line(0,y1-1,w,y1-1,fill=BORDER)
            title=(d.get("title") or d["filename"]).title()
            self.create_text(14,y0+17,text=title[:38],anchor="w",
                             fill=BLUE if sel else TEXT,font=(SANS[0],SANS[1],"bold"))
            fmt=d.get("format",""); rows=f"{d['rows']} rows" if d.get("rows") else ""
            self.create_text(14,y0+36,text=f"{fmt}  {rows}".strip(),anchor="w",fill=MUTED,font=MONO9)
        self.configure(scrollregion=(0,0,w,len(self._ds)*self.RH))

# ── Main window ────────────────────────────────────────────────────────────
class MindWriter(tk.Tk):
    def __init__(self,url):
        super().__init__()
        api.base=url; self.title("MindWriter")
        self.geometry("1140x720"); self.minsize(860,540); self.configure(bg=BG)
        self._active=None; self._build(); self._autoconnect()

    def _build(self):
        self._build_header()
        self._banner=frm(self,bg="#1a0e0e",highlightthickness=1,highlightbackground="#3e2020")
        lbl(self._banner,"⚠  API not reachable — start: python3 mindwriter_api.py",
            bg="#1a0e0e",fg="#d88888",font=SANS9).pack(padx=14,pady=8)
        shell=frm(self); shell.pack(fill="both",expand=True)
        self._panels={}
        for name,cls in [("notes",NotesPanel),("search",SearchPanel),
                          ("stats",StatsPanel),("datasets",DatasetsPanel)]:
            p=cls(shell,self); p.place(relx=0,rely=0,relwidth=1,relheight=1)
            self._panels[name]=p
        self._switch("notes")

    def _build_header(self):
        hdr=frm(self,bg=SURF,height=46); hdr.pack(fill="x"); hdr.pack_propagate(False)
        hsep(hdr).pack(side="bottom",fill="x")
        lbl(hdr,"✦ mindwriter",fg=ACCENT,bg=SURF,
            font=(MONO[0],MONO[1],"bold")).pack(side="left",padx=(18,6))
        self._nav={}
        nf=frm(hdr,bg=SURF); nf.pack(side="left",padx=2)
        for nm in ("Notes","Search","Stats","Datasets"):
            b=tk.Button(nf,text=nm,bg=SURF,fg=MUTED,activebackground=SURF2,
                        activeforeground=TEXT,relief="flat",cursor="hand2",
                        font=SANS9,padx=10,pady=5,highlightthickness=0,
                        command=lambda n=nm.lower():self._switch(n))
            b.pack(side="left",padx=1); self._nav[nm.lower()]=b
        right=frm(hdr,bg=SURF); right.pack(side="right",padx=14)
        self._dot=tk.Canvas(right,width=9,height=9,bg=SURF,highlightthickness=0)
        self._dot.pack(side="right",padx=(6,0))
        self._oval=self._dot.create_oval(1,1,8,8,fill=MUTED,outline="")
        lbl(right,"Key",fg=MUTED,bg=SURF,font=SANS9).pack(side="right",padx=(8,0))
        self._kv=tk.StringVar()
        ke=entry(right,textvariable=self._kv,show="•",font=(MONO[0],9),width=13)
        ke.pack(side="right",padx=(4,0)); ke.bind("<Return>",lambda e:self._reconnect())
        lbl(right,"API",fg=MUTED,bg=SURF,font=SANS9).pack(side="right",padx=(8,0))
        self._uv=tk.StringVar(value=api.base)
        ue=entry(right,textvariable=self._uv,font=(MONO[0],9),width=22)
        ue.pack(side="right",padx=(4,0)); ue.bind("<Return>",lambda e:self._reconnect())

    def _switch(self,name):
        for n,b in self._nav.items():
            if n==name:
                b.config(fg=ACCENT,bg="#1d211c")
            else:
                b.config(fg=MUTED,bg=SURF)
        if self._active: self._panels[self._active].lower()
        self._panels[name].lift(); self._panels[name].on_show(); self._active=name

    def _autoconnect(self):
        def _t():
            key=api.fetch_key()
            if key: api.key=key; self.after(0,lambda:self._kv.set(key))
            ok=api.health(); self.after(0,lambda:self._setdot(ok))
            if ok: self.after(0,self._panels["notes"].load)
        threading.Thread(target=_t,daemon=True).start()

    def _reconnect(self):
        api.base=self._uv.get().rstrip("/"); api.key=self._kv.get().strip()
        self._setdot(None)
        def _t():
            if not api.key:
                key=api.fetch_key()
                if key: api.key=key; self.after(0,lambda:self._kv.set(key))
            ok=api.health(); self.after(0,lambda:self._setdot(ok))
            if ok: self.after(0,self._panels["notes"].load)
        threading.Thread(target=_t,daemon=True).start()

    def _setdot(self,ok):
        c=MUTED if ok is None else (ACCENT if ok else DANGER)
        self._dot.itemconfig(self._oval,fill=c)
        if ok is False: self._banner.pack(fill="x",padx=10,pady=(6,0))
        else: self._banner.pack_forget()

# ── Notes Panel ─────────────────────────────────────────────────────────────
class NotesPanel(tk.Frame):
    def __init__(self,p,app_ref):
        super().__init__(p,bg=BG)
        self._app=app_ref; self._notes=[]; self._active=None; self._mode="empty"
        self._build()

    def _build(self):
        aside=frm(self,bg=SURF,width=270); aside.pack(side="left",fill="y"); aside.pack_propagate(False)
        vsep(aside).pack(side="right",fill="y")
        head=frm(aside,bg=SURF); head.pack(fill="x",padx=10,pady=10)
        br=frm(head,bg=SURF); br.pack(fill="x",pady=(0,6))
        btn_ghost(br,"+ New Note",self._new).pack(side="left",fill="x",expand=True)
        frm(br,bg=SURF,width=6).pack(side="left")
        btn_ghost(br,"⬆ Upload",self._upload).pack(side="left",fill="x",expand=True)
        self._ftag=entry(head,width=30); self._ftag.pack(fill="x",pady=2)
        self._ftag.insert(0,"Filter by tag…"); self._ftag.config(fg=MUTED)
        self._ftag.bind("<FocusIn>", lambda e:(self._ftag.delete(0,"end"),self._ftag.config(fg=TEXT)) if self._ftag.get()=="Filter by tag…" else None)
        self._ftag.bind("<FocusOut>",lambda e:(self._ftag.insert(0,"Filter by tag…"),self._ftag.config(fg=MUTED)) if not self._ftag.get() else None)
        self._ftag.bind("<Return>",lambda e:self.load())
        self._fauth=entry(head,width=30); self._fauth.pack(fill="x",pady=2)
        self._fauth.insert(0,"Filter by author…"); self._fauth.config(fg=MUTED)
        self._fauth.bind("<FocusIn>", lambda e:(self._fauth.delete(0,"end"),self._fauth.config(fg=TEXT)) if self._fauth.get()=="Filter by author…" else None)
        self._fauth.bind("<FocusOut>",lambda e:(self._fauth.insert(0,"Filter by author…"),self._fauth.config(fg=MUTED)) if not self._fauth.get() else None)
        self._fauth.bind("<Return>",lambda e:self.load())
        sr=frm(head,bg=SURF); sr.pack(fill="x",pady=(4,0))
        lbl(sr,"Sort:",fg=MUTED,bg=SURF,font=SANS9).pack(side="left")
        self._sort=tk.StringVar(value="id")
        for v,t in [("id","Index"),("title","Title"),("modified","Modified")]:
            tk.Radiobutton(sr,text=t,variable=self._sort,value=v,bg=SURF,fg=MUTED,
                           selectcolor=SURF,activebackground=SURF,activeforeground=ACCENT,
                           font=SANS9,command=self.load).pack(side="left",padx=3)
        hsep(aside).pack(fill="x")
        lw=frm(aside,bg=SURF); lw.pack(fill="both",expand=True)
        vsb=tk.Scrollbar(lw,orient="vertical",bg=BORDER,troughcolor=BG,
                         activebackground=MUTED,relief="flat",width=6,highlightthickness=0)
        self._nl=NoteList(lw,on_sel=self._on_sel,on_edit=self._open_edit,on_del=self._confirm_del)
        self._nl.pack(side="left",fill="both",expand=True); vsb.pack(side="right",fill="y")
        self._nl.attach_vsb(vsb)
        right=frm(self); right.pack(side="left",fill="both",expand=True)
        self._emp=frm(right); self._emp.place(relx=0,rely=0,relwidth=1,relheight=1)
        lbl(self._emp,"◎",fg=MUTED,font=(MONO[0],28)).pack(pady=(160,6))
        lbl(self._emp,"Select a note or create a new one",fg=MUTED,font=SANS9).pack()
        self._reader=frm(right); self._build_reader()
        self._editor=frm(right); self._build_editor()
        self._show("empty")

    def _build_reader(self):
        hdr=frm(self._reader); hdr.pack(fill="x",padx=28,pady=(24,4))
        self._rt=lbl(hdr,fg=TEXT,font=(SANS[0],16,"bold"),anchor="w",wraplength=500,justify="left")
        self._rt.pack(side="left",fill="x",expand=True)
        br=frm(hdr); br.pack(side="right")
        btn_ghost(br,"✎ Edit",self._open_edit_active).pack(side="left",padx=(0,6))
        btn_danger(br,"✕ Delete",self._confirm_del_active).pack(side="left")
        self._rm=lbl(self._reader,fg=DIM,font=SANS9,anchor="w",justify="left")
        self._rm.pack(fill="x",padx=28,pady=(0,2))
        self._rtags=frm(self._reader); self._rtags.pack(fill="x",padx=28,pady=(0,6))
        hsep(self._reader).pack(fill="x",padx=28,pady=(0,4))
        bw,self._rb=scrolled_text(self._reader,fg="#b8b8cc",font=MONO)
        self._rb.config(state="disabled",padx=28); bw.pack(fill="both",expand=True,pady=(0,20))

    def _build_editor(self):
        self._etl=lbl(self._editor,fg=ACCENT,font=(MONO[0],MONO[1],"bold"),anchor="w")
        self._etl.pack(fill="x",padx=28,pady=(22,8))
        def fl(t): lbl(self._editor,t,fg=BLUE,font=(MONO[0],9),anchor="w").pack(fill="x",padx=28)
        fl("TITLE *"); self._et=entry(self._editor); self._et.pack(fill="x",padx=28,pady=(2,8),ipady=4)
        fl("AUTHOR"); self._ea=entry(self._editor); self._ea.pack(fill="x",padx=28,pady=(2,8),ipady=4)
        r2=frm(self._editor); r2.pack(fill="x",padx=28,pady=(0,8))
        for attr,lb in [("_ep","PRIORITY"),("_etg","TAGS")]:
            s=frm(r2); s.pack(side="left",fill="x",expand=True,padx=(0,8) if attr=="_ep" else 0)
            lbl(s,lb,fg=BLUE,font=(MONO[0],9),anchor="w").pack(fill="x")
            e=entry(s); e.pack(fill="x",pady=(2,0),ipady=4); setattr(self,attr,e)
        fl("BODY")
        bw,self._ebody=scrolled_text(self._editor,bg=SURF2,fg=TEXT,font=MONO)
        self._ebody.config(highlightthickness=1,highlightbackground=BORDER,highlightcolor=ACCENT)
        bw.pack(fill="both",expand=True,padx=28,pady=(2,0))
        act=frm(self._editor); act.pack(fill="x",padx=28,pady=10)
        self._esb=btn_accent(act,"Save Note",self._save); self._esb.pack(side="left",padx=(0,8))
        btn_ghost(act,"Cancel",self._cancel).pack(side="left")
        self._emsg=lbl(act,fg=ACCENT,font=SANS9); self._emsg.pack(side="left",padx=12)

    def _show(self,w):
        self._mode=w
        for f in (self._emp,self._reader,self._editor): f.place_forget()
        if w=="empty":  self._emp.place(relx=0,rely=0,relwidth=1,relheight=1)
        elif w=="view": self._reader.place(relx=0,rely=0,relwidth=1,relheight=1)
        else:           self._editor.place(relx=0,rely=0,relwidth=1,relheight=1)

    def on_show(self):
        if not self._notes: self.load()

    def load(self):
        tag=self._ftag.get(); auth=self._fauth.get()
        if tag=="Filter by tag…": tag=""
        if auth=="Filter by author…": auth=""
        qs=f"?sort={self._sort.get()}"
        if tag:  qs+=f"&tag={urllib.parse.quote(tag)}"
        if auth: qs+=f"&author={urllib.parse.quote(auth)}"
        async_run(lambda:api.get(f"/api/notes{qs}"),ok=self._done_load,err=lambda e:None)

    def _done_load(self,d):
        self._notes=d.get("notes",[])
        self._nl.set_notes(self._notes,sel_id=self._active["id"] if self._active else None)

    def _on_sel(self,n):
        async_run(lambda:api.get(f"/api/notes/{n['id']}"),ok=self._show_note,err=lambda e:None)

    def _show_note(self,n):
        self._active=n; self._nl.select_id(n["id"])
        self._rt.config(text=(n.get("title") or n["filename"]).title())
        p=[]; 
        if n.get("author"):   p.append(f"author  {n['author']}")
        if n.get("created"):  p.append(f"created  {n['created'][:10]}")
        if n.get("modified"): p.append(f"modified  {n['modified'][:10]}")
        if n.get("priority"): p.append(f"priority  {n['priority']}")
        self._rm.config(text="    ".join(p))
        for w in self._rtags.winfo_children(): w.destroy()
        for tag in n.get("tags",[]):
            tk.Label(self._rtags,text=tag,bg="#1a2a10",fg=ACCENT,
                     font=(MONO[0],9),padx=6,pady=2,relief="flat",
                     highlightthickness=1,highlightbackground="#2a3e18").pack(side="left",padx=(0,4))
        self._rb.config(state="normal"); self._rb.delete("1.0","end")
        self._rb.insert("1.0",n.get("body","") or "(empty)"); self._rb.config(state="disabled")
        self._show("view")

    def _new(self):
        self._active=None; self._etl.config(text="+ New Note")
        self._esb.config(text="Save Note"); self._clr(); self._show("edit"); self._et.focus()

    def _open_edit(self,n):
        async_run(lambda:api.get(f"/api/notes/{n['id']}"),ok=self._fill_edit,err=lambda e:None)

    def _open_edit_active(self):
        if self._active: self._open_edit(self._active)

    def _fill_edit(self,n):
        self._active=n; self._etl.config(text="✎ Edit Note")
        self._esb.config(text="Update Note"); self._clr()
        self._et.insert(0,n.get("title","")); self._ea.insert(0,n.get("author",""))
        self._ep.insert(0,n.get("priority","")); self._etg.insert(0,", ".join(n.get("tags",[])))
        self._ebody.insert("1.0",n.get("body","")); self._emsg.config(text="")
        self._show("create"); self._et.focus()

    def _clr(self):
        for w in (self._et,self._ea,self._ep,self._etg): w.delete(0,"end")
        self._ebody.delete("1.0","end"); self._emsg.config(text="")

    def _save(self):
        title=self._et.get().strip()
        if not title: self._emsg.config(text="Title is required.",fg=DANGER); return
        data={"title":title,"body":self._ebody.get("1.0","end-1c"),
              "author":self._ea.get().strip(),"priority":self._ep.get().strip(),
              "tags":self._etg.get().strip()}
        self._esb.config(state="disabled",text="Saving…")
        if not self._active:
            async_run(lambda:api.post("/api/notes",data),ok=self._after_save,err=self._save_err)
        else:
            nid=self._active["id"]
            async_run(lambda:api.put(f"/api/notes/{nid}",data),ok=self._after_save,err=self._save_err)

    def _after_save(self,r):
        self._esb.config(state="normal"); self._emsg.config(text="Saved!",fg=ACCENT)
        self.load()
        nid=r.get("id") or (self._active["id"] if self._active else None)
        if nid:
            self.after(300,lambda:async_run(lambda:api.get(f"/api/notes/{nid}"),
                                             ok=self._show_note,err=lambda e:None))

    def _save_err(self,exc):
        self._esb.config(state="normal"); self._emsg.config(text=str(exc)[:70],fg=DANGER)

    def _cancel(self):
        if self._active: self._show_note(self._active)
        else: self._show("empty")

    def _confirm_del(self,n):
        if not messagebox.askyesno("Delete Note",
            f"Delete \"{n.get('title') or n['filename']}\"?\nThis cannot be undone."): return
        async_run(lambda:api.delete(f"/api/notes/{n['id']}"),
                  ok=lambda _:(self._show("empty") if (self._active and self._active.get("id")==n["id"]) else None,
                                setattr(self,"_active",None) if (self._active and self._active.get("id")==n["id"]) else None,
                                self.load()),
                  err=lambda e:messagebox.showerror("Error",str(e)))

    def _confirm_del_active(self):
        if self._active: self._confirm_del(self._active)

    def _upload(self):
        path=filedialog.askopenfilename(title="Upload Note",
            filetypes=[("Note files","*.md *.txt *.note"),("All","*.*")])
        if not path: return
        ow=messagebox.askyesno("Overwrite?","Replace existing note if filename already exists?")
        async_run(lambda:api.upload_file("/api/notes/upload",path,{"overwrite":"true" if ow else "false"}),
                  ok=lambda d:(self.load(),messagebox.showinfo("Uploaded",f"Uploaded: {d.get('filename','')}")),
                  err=lambda e:messagebox.showerror("Upload failed",str(e)))

# ── Search Panel ─────────────────────────────────────────────────────────────
class SearchPanel(tk.Frame):
    def __init__(self,p,app_ref):
        super().__init__(p,bg=BG); self._app=app_ref; self._build()
    def _build(self):
        bar=frm(self); bar.pack(fill="x",padx=24,pady=20)
        self._qv=tk.StringVar()
        e=entry(bar,textvariable=self._qv); e.pack(side="left",fill="x",expand=True,ipady=5,padx=(0,8))
        e.bind("<Return>",lambda ev:self._search())
        btn_accent(bar,"Search",self._search).pack(side="left")
        hsep(self).pack(fill="x")
        rw,self._res=scrolled_text(self); self._res.config(state="disabled",padx=24); rw.pack(fill="both",expand=True)
        for tag,fg2,fn in [("title",TEXT,(SANS[0],SANS[1],"bold")),("id",MUTED,MONO9),
                            ("kw",ACCENT,MONO9),("snip",DIM,MONO9),("div",BORDER,SANS9)]:
            self._res.tag_config(tag,foreground=fg2,font=fn)
    def on_show(self): pass
    def _search(self):
        q=self._qv.get().strip()
        if not q: return
        kws=[k.strip() for k in q.split() if k.strip()]
        qs="&".join(f"q={urllib.parse.quote(k)}" for k in kws)
        async_run(lambda:api.get(f"/api/notes/search?{qs}"),ok=self._render,err=lambda e:self._err(str(e)))
    def _render(self,d):
        self._res.config(state="normal"); self._res.delete("1.0","end")
        notes=d.get("notes",[])
        if not notes: self._res.insert("end","\n  No results found.","id")
        for n in notes:
            self._res.insert("end",f"\n#{n['id']}  ","id")
            self._res.insert("end",(n.get("title") or n["filename"]).title()+"\n","title")
            self._res.insert("end","  matched: "+"  ".join(n.get("matched_keywords",[]))+"\n","kw")
            for kw,info in n.get("match_report",{}).items():
                for s in info.get("snippets",[])[:1]:
                    self._res.insert("end",f"  …{s.strip()}…\n","snip")
            self._res.insert("end","  "+"─"*56+"\n","div")
        self._res.config(state="disabled")
    def _err(self,msg):
        self._res.config(state="normal"); self._res.delete("1.0","end")
        self._res.insert("end",f"Error: {msg}","id"); self._res.config(state="disabled")

# ── Stats Panel ───────────────────────────────────────────────────────────────
class StatsPanel(tk.Frame):
    def __init__(self,p,app_ref):
        super().__init__(p,bg=BG); self._app=app_ref; self._loaded=False; self._build()
    def _build(self):
        hdr=frm(self); hdr.pack(fill="x",padx=24,pady=(18,0))
        lbl(hdr,"Stats",fg=TEXT,font=(SANS[0],14,"bold")).pack(side="left")
        btn_ghost(hdr,"↻ Refresh",self._load).pack(side="left",padx=12)
        hsep(self).pack(fill="x",pady=(10,0))
        outer=frm(self); outer.pack(fill="both",expand=True)
        vsb=tk.Scrollbar(outer,orient="vertical",bg=BORDER,troughcolor=BG,
                         activebackground=MUTED,relief="flat",width=6,highlightthickness=0)
        self._cv=tk.Canvas(outer,bg=BG,highlightthickness=0,yscrollcommand=vsb.set)
        vsb.config(command=self._cv.yview); vsb.pack(side="right",fill="y"); self._cv.pack(side="left",fill="both",expand=True)
        self._inn=frm(self._cv); self._win=self._cv.create_window((0,0),window=self._inn,anchor="nw")
        self._inn.bind("<Configure>",lambda e:self._cv.configure(scrollregion=self._cv.bbox("all")))
        self._cv.bind("<Configure>",lambda e:self._cv.itemconfig(self._win,width=e.width))
        self._cv.bind("<Enter>",lambda e:self._cv.focus_set())
        self._cv.bind("<MouseWheel>",lambda e:self._cv.yview_scroll(-1 if e.delta>0 else 1,"units"))
        self._st=lbl(self._inn,"Switch to this tab to load stats.",fg=MUTED,font=SANS9); self._st.pack(pady=40)
    def on_show(self):
        if not self._loaded: self._load()
    def _load(self):
        self._st.config(text="Loading…")
        async_run(lambda:api.get("/api/stats"),ok=self._render,err=lambda e:self._st.config(text=f"Error: {e}"))
    def _render(self,s):
        for w in self._inn.winfo_children(): w.destroy()
        co=frm(self._inn); co.pack(fill="x",padx=20,pady=(16,20))
        for val,lb in [(str(s.get("total_notes",0)),"total notes"),
                       (f"{s.get('total_words',0):,}","total words"),
                       (f"{s.get('avg_words',0):,}","avg words/note"),
                       (str(s.get("no_title",0)),"missing title"),
                       (str(s.get("no_author",0)),"missing author"),
                       (str(s.get("no_tags",0)),"missing tags")]:
            c=tk.Frame(co,bg=SURF,highlightthickness=1,highlightbackground=BORDER)
            c.pack(side="left",fill="x",expand=True,padx=4)
            lbl(c,val,bg=SURF,fg=ACCENT,font=(SANS[0],20,"bold")).pack(pady=(14,2))
            lbl(c,lb,bg=SURF,fg=MUTED,font=SANS9).pack(pady=(0,14))
        for title,key in [("By Author","by_author"),("By Priority","by_priority"),("By Tag","by_tag")]:
            data=s.get(key,{})
            if not data: continue
            sec=frm(self._inn); sec.pack(fill="x",padx=24,pady=(0,20))
            lbl(sec,title,fg=BLUE,font=(MONO[0],9),anchor="w").pack(fill="x")
            hsep(sec).pack(fill="x",pady=(4,10))
            top=sorted(data.items(),key=lambda x:x[1],reverse=True)[:10]
            mx=max(v for _,v in top) if top else 1
            for name,count in top:
                row=frm(sec); row.pack(fill="x",pady=2)
                lbl(row,name[:22],fg=TEXT,font=SANS9,width=18,anchor="w").pack(side="left")
                lbl(row,str(count),fg=MUTED,font=(MONO[0],9),width=5,anchor="e").pack(side="left",padx=(0,8))
                tr=tk.Canvas(row,height=5,bg=BORDER,highlightthickness=0); tr.pack(side="left",fill="x",expand=True)
                fp=count/mx
                def draw(cv=tr,p=fp):
                    w=cv.winfo_width()
                    if w>4: cv.create_rectangle(0,0,int(w*p),5,fill=ACCENT,outline="")
                    else: cv.after(50,draw)
                tr.after(80,draw)
        self._loaded=True

# ── Datasets Panel ────────────────────────────────────────────────────────────
class DatasetsPanel(tk.Frame):
    def __init__(self,p,app_ref):
        super().__init__(p,bg=BG); self._app=app_ref
        self._ds=[]; self._active=None; self._page=1; self._pages=1; self._pp=100; self._q=""
        self._build()
    def _build(self):
        aside=frm(self,bg=SURF,width=280); aside.pack(side="left",fill="y"); aside.pack_propagate(False)
        vsep(aside).pack(side="right",fill="y")
        head=frm(aside,bg=SURF); head.pack(fill="x",padx=10,pady=10)
        btn_ghost(head,"↻ Refresh",self._load).pack(fill="x")
        hsep(aside).pack(fill="x")
        self._dsl=DSList(aside,on_sel=self._on_sel); self._dsl.pack(fill="both",expand=True)
        right=frm(self); right.pack(side="left",fill="both",expand=True)
        self._emp=frm(right); self._emp.place(relx=0,rely=0,relwidth=1,relheight=1)
        lbl(self._emp,"◎",fg=MUTED,font=(MONO[0],28)).pack(pady=(140,6))
        lbl(self._emp,"Select a dataset from the list",fg=MUTED,font=SANS9).pack()
        self._det=frm(right); self._build_det()
    def _build_det(self):
        hdr=frm(self._det); hdr.pack(fill="x",padx=24,pady=(20,4))
        self._dtitle=lbl(hdr,fg=TEXT,font=(SANS[0],14,"bold"),anchor="w")
        self._dtitle.pack(side="left",fill="x",expand=True)
        self._dfmt=tk.Label(hdr,text="",bg="#141428",fg=BLUE,font=(MONO[0],9,"bold"),
                             padx=7,pady=3,relief="flat",highlightthickness=1,highlightbackground=BORDER)
        self._dfmt.pack(side="right")
        self._dmeta=lbl(self._det,fg=MUTED,font=SANS9,anchor="w"); self._dmeta.pack(fill="x",padx=24,pady=(0,4))
        hsep(self._det).pack(fill="x",padx=24,pady=(0,8))
        sb=frm(self._det); sb.pack(fill="x",padx=24,pady=(0,8))
        self._qv=tk.StringVar()
        e=entry(sb,textvariable=self._qv,font=MONO); e.pack(side="left",fill="x",expand=True,ipady=4,padx=(0,6))
        e.bind("<Return>",lambda ev:self._search())
        btn_accent(sb,"Search",self._search).pack(side="left",padx=(0,6))
        btn_ghost(sb,"Clear",self._clear).pack(side="left")
        self._tw=frm(self._det); self._tw.pack(fill="both",expand=True,padx=24)
        pg=frm(self._det); pg.pack(fill="x",padx=24,pady=8)
        self._pf=btn_ghost(pg,"«",lambda:self._go(1)); self._pf.pack(side="left",padx=2)
        self._pp_btn=btn_ghost(pg,"‹",lambda:self._go(self._page-1)); self._pp_btn.pack(side="left",padx=2)
        self._pi=lbl(pg,"",fg=MUTED,font=(MONO[0],9)); self._pi.pack(side="left",padx=8)
        self._pn=btn_ghost(pg,"›",lambda:self._go(self._page+1)); self._pn.pack(side="left",padx=2)
        self._pl=btn_ghost(pg,"»",lambda:self._go(self._pages)); self._pl.pack(side="left",padx=2)
    def on_show(self):
        if not self._ds: self._load()
    def _load(self):
        async_run(lambda:api.get("/api/datasets"),ok=self._done_load,err=lambda e:None)
    def _done_load(self,d):
        self._ds=d.get("datasets",[])
        self._dsl.set_ds(self._ds,sel_id=self._active["id"] if self._active else None)
    def _on_sel(self,ds):
        self._active=ds; self._page=1; self._q=""; self._qv.set("")
        self._dtitle.config(text=(ds.get("title") or ds["filename"]).title())
        self._dfmt.config(text=ds.get("format",""))
        p=[]
        if ds.get("rows"):     p.append(f"{ds['rows']} rows × {ds.get('columns','?')} columns")
        if ds.get("author"):   p.append(f"author: {ds['author']}")
        if ds.get("imported"): p.append(f"imported: {ds['imported']}")
        self._dmeta.config(text="   ".join(p))
        self._emp.place_forget(); self._det.place(relx=0,rely=0,relwidth=1,relheight=1)
        self._load_data()
    def _load_data(self):
        ds=self._active; pg=self._page; q=self._q
        qs=f"?page={pg}&per_page={self._pp}"
        if q: qs+=f"&q={urllib.parse.quote(q)}"
        async_run(lambda:api.get(f"/api/datasets/{ds['id']}/data{qs}"),
                  ok=self._render_table,err=lambda e:self._tmsg(str(e)))
    def _render_table(self,d):
        for w in self._tw.winfo_children(): w.destroy()
        cols=d.get("columns",[]); rows=d.get("rows",[])
        self._page=d.get("page",1); self._pages=d.get("pages",1); total=d.get("total",0)
        if not cols: self._tmsg("No data."); return
        style=ttk.Style(); style.theme_use("default")
        style.configure("MW.Treeview",background=SURF,foreground=TEXT,fieldbackground=SURF,
                        rowheight=22,borderwidth=0,font=(MONO[0],9))
        style.configure("MW.Treeview.Heading",background=SURF2,foreground=BLUE,
                        relief="flat",font=(MONO[0],9,"bold"))
        style.map("MW.Treeview",background=[("selected",SURF2)],foreground=[("selected",ACCENT)])
        vsb=tk.Scrollbar(self._tw,orient="vertical",bg=BORDER,troughcolor=BG,
                         activebackground=MUTED,relief="flat",width=6,highlightthickness=0)
        hsb=tk.Scrollbar(self._tw,orient="horizontal",bg=BORDER,troughcolor=BG,
                         relief="flat",width=6,highlightthickness=0)
        tree=ttk.Treeview(self._tw,columns=cols,show="headings",style="MW.Treeview",
                           yscrollcommand=vsb.set,xscrollcommand=hsb.set)
        vsb.config(command=tree.yview); hsb.config(command=tree.xview)
        cw=max(80,min(200,900//max(len(cols),1)))
        for c in cols:
            tree.heading(c,text=c); tree.column(c,width=cw,minwidth=40,stretch=True)
        for row in rows:
            tree.insert("","end",values=[str(v) if v is not None else "" for v in row])
        vsb.pack(side="right",fill="y"); hsb.pack(side="bottom",fill="x"); tree.pack(fill="both",expand=True)
        s=(self._page-1)*self._pp+1; e2=min(self._page*self._pp,total)
        self._pi.config(text=f"rows {s}–{e2} of {total:,}  ·  page {self._page}/{self._pages}")
        self._pf.config(state="normal" if self._page>1 else "disabled")
        self._pp_btn.config(state="normal" if self._page>1 else "disabled")
        self._pn.config(state="normal" if self._page<self._pages else "disabled")
        self._pl.config(state="normal" if self._page<self._pages else "disabled")
    def _tmsg(self,msg):
        for w in self._tw.winfo_children(): w.destroy()
        lbl(self._tw,msg,fg=MUTED,font=SANS9).pack(pady=20)
    def _go(self,page):
        if page<1 or page>self._pages: return
        self._page=page; self._load_data()
    def _search(self): self._q=self._qv.get().strip(); self._page=1; self._load_data()
    def _clear(self): self._q=""; self._qv.set(""); self._page=1; self._load_data()

# ── Entry point ────────────────────────────────────────────────────────────
def main():
    parser=argparse.ArgumentParser(description="MindWriter Desktop GUI")
    parser.add_argument("--api",default="http://localhost:8000")
    parser.add_argument("--no-server",action="store_true",help="Don't start the API server")
    args=parser.parse_args()
    
    if not args.no_server:
        start_api_server()
    
    global app
    app=MindWriter(args.api)
    
    def on_closing():
        if not args.no_server:
            stop_api_server()
        app.destroy()
    
    app.protocol("WM_DELETE_WINDOW",on_closing)
    app.mainloop()

if __name__=="__main__":
    main()