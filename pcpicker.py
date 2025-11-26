check the grok url #!/usr/bin/env python3
import os,sys,json,time,getpass,math,re,asyncio,sqlite3,secrets
from pathlib import Path
from typing import List,Dict
import httpx,psutil,pennylane as qml
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes,hmac
from bleach import clean

def enforce_deps():
    for m in ["rich","httpx","psutil","cryptography","pennylane","bleach"]:
        try:__import__(m)
        except:
            Console().print(Panel("[bold red]MISSING DEP[/]",title="FATAL",border_style="bright_red"))
            sys.exit(1)
enforce_deps()

console=Console()
VAULT=Path(".quantum_vault")
VAULT.mkdir(exist_ok=True)
MASTER=VAULT/".master"
HMAC_KEY=VAULT/".hmac"
GROK_ENC=VAULT/"grok.aes"
DB_FILE=VAULT/"stock.db.aes"

def init_keys():
    if MASTER.exists()and HMAC_KEY.exists():
        return MASTER.read_bytes()[:32],HMAC_KEY.read_bytes()[:32]
    k1=secrets.token_bytes(32)
    k2=secrets.token_bytes(32)
    MASTER.write_bytes(k1)
    HMAC_KEY.write_bytes(k2)
    return k1,k2
AES_KEY,HMAC_KEY_BYTES=init_keys()

def encrypt_blob(b:bytes)->bytes:
    n=secrets.token_bytes(12)
    ct=AESGCM(AES_KEY).encrypt(n,b,None)
    mac=hmac.HMAC(HMAC_KEY_BYTES,hashes.SHA256())
    mac.update(n+ct)
    return n+ct+mac.finalize()

def decrypt_blob(b:bytes)->bytes:
    if len(b)<60:raise ValueError()
    n,ct,tag=b[:12],b[12:-32],b[-32:]
    mac=hmac.HMAC(HMAC_KEY_BYTES,hashes.SHA256())
    mac.update(n+ct)
    mac.verify(tag)
    return AESGCM(AES_KEY).decrypt(n,ct,None)

def load_grok_key():
    if"GROK_API_KEY"in os.environ:return os.environ["GROK_API_KEY"].strip()
    if GROK_ENC.exists():
        try:
            key=decrypt_blob(GROK_ENC.read_bytes()).decode()
            os.environ["GROK_API_KEY"]=key
            return key
        except:pass
    return None
GROK_KEY=load_grok_key()

def init_db():
    c=sqlite3.connect(":memory:")
    if DB_FILE.exists():
        try:
            raw=decrypt_blob(DB_FILE.read_bytes())
            c.executescript(raw.decode())
            return c
        except:pass
    c.execute("CREATE TABLE stock(category TEXT,name TEXT,price REAL,stock INTEGER)")
    d=[
        ("CPU","AMD Ryzen 9 9950X3D",749,10),
        ("CPU","Intel Core Ultra 9 285K",789,5),
        ("GPU","NVIDIA RTX 5090 Ti",2499,3),
        ("GPU","AMD RX 8900 XTX",1899,8),
        ("RAM","128GB DDR5-8000 G.Skill Trident Z5",1099,6),
        ("RAM","64GB DDR5-7200 Corsair Vengeance",449,15),
        ("Storage","8TB Samsung 990 EVO Plus",1299,7),
        ("PSU","Corsair HX1500i 1500W Platinum",399,12),
        ("Case","Lian Li O11 Dynamic EVO RGB",179,20),
        ("Cooling","NZXT Kraken Elite 420mm + 12x Uni Fans",499,9),
    ]
    c.executemany("INSERT INTO stock VALUES(?,?,?,?)",d)
    c.commit()
    return c
conn=init_db()

def save_db():
    try:DB_FILE.write_bytes(encrypt_blob("\n".join(conn.iterdump()).encode()))
    except:pass

def get_stock()->str:
    cur=conn.cursor()
    cur.execute("SELECT category,name,price,stock FROM stock WHERE stock>0 ORDER BY category")
    r=cur.fetchall()
    return"\n".join(f"{a}: {b} (${c}, stock:{d})"for a,b,c,d in r)or"NO STOCK"

def quantum_chaos()->float:
    console.print("[dim]STAGE 1: Measuring quantum entropy...[/]")
    c=psutil.cpu_percent(0.1)/100
    m=psutil.virtual_memory().percent/100
    l=os.getloadavg()[0]/(os.cpu_count()or 1)
    t=0.4
    try:
        for v in psutil.sensors_temperatures().values():
            for s in v:
                if s.current:t=max(t,(s.current-20)/80)
    except:pass
    r=c*1.5+l;g=m*1.4;b=t*1.8
    dev=qml.device("default.qubit",wires=5,shots=1024)
    @qml.qnode(dev)
    def circ():
        for i in range(5):
            a=r if i%2==0 else g if i%3==0 else b
            qml.RX(a*math.pi,wires=i)
            qml.RY(math.pi*0.7,wires=i)
        for i in range(4):qml.CNOT(wires=[i,i+1])
        qml.CNOT(wires=[4,0])
        return[qml.expval(qml.PauliZ(i))for i in range(5)]
    e=sum(abs(x)for x in circ())/5
    chaos=max(0.0,min(1.0,1.0-e))
    console.print(f"[bold green]STAGE 1 COMPLETE — Chaos: {chaos:.4f}[/]")
    return chaos

def punkd(t:str)->dict:
    w=re.findall(r"\w+",clean(t).lower())
    h={"8k":5,"ai":4.5,"render":4,"quiet":3.5,"budget":4.5,"rgb":2.5}
    s={}
    for x in w:
        if x in h:s[x]=s.get(x,0)+h[x]
    if not s:return{}
    m=max(s.values())
    return{k:v/m for k,v in s.items()}

def extract_json(t:str)->dict:
    if not t:return{}
    t=t.strip()
    t=re.sub(r"```json|```","",t)
    s=t.find("{")
    e=t.rfind("}")+1
    if s==-1 or e==0:return{}
    j=t[s:e]
    try:return json.loads(j)
    except:
        j=j.replace("'","\"")
        j=re.sub(r",\s*}","}",j)
        j=re.sub(r",\s*]","]",j)
        try:return json.loads(j)
        except:return{}

PROMPT="""
You are a ruthless 2025 PC architect.
Requirements: {req}
Budget: {budget}
Chaos: {chaos:.4f}
Punkd: {punkd}
Available parts (stock>0 only):
{inventory}
Return ONLY valid JSON:
{{
  "build_name":"short cyberpunk name",
  "total_usd":0,
  "performance_tier":"God-Tier/Insane/High-End/Mid-Range/Budget-Beast",
  "parts":{{"CPU":"","Motherboard":"","RAM":"","GPU":"","Storage":"","PSU":"","Case":"","Cooling":""}},
  "justification":"one brutal sentence",
  "future_proof_years":5
}}
"""

async def call_grok(m:List[dict],t:float)->str:
    console.print("[dim]STAGE 2: Contacting Grok-4...[/]")
    if not GROK_KEY:
        console.print("[bold red]No Grok key[/]")
        return""
    h={"Authorization":f"Bearer {GROK_KEY}","Content-Type":"application/json"}
    p={"model":"grok-4","messages":m,"temperature":t,"max_tokens":4096}
    async with httpx.AsyncClient(timeout=180.0)as c:
        for i in range(3):
            try:
                console.print(f"[dim]Attempt {i+1}/3...[/]")
                r=await c.post("https://api.x.ai/v1/chat/completions",headers=h,json=p)
                r.raise_for_status()
                console.print("[bold green]STAGE 2 COMPLETE — Response received[/]")
                return clean(r.json()["choices"][0]["message"]["content"],tags=[],attributes={},strip=True)
            except Exception as e:
                console.print(f"[red]Attempt {i+1} failed: {e}[/]")
                if i<2:await asyncio.sleep(3)
    console.print("[bold red]STAGE 2 FAILED — Using VOID PROTOCOL[/]")
    return""

async def forge():
    console.clear()
    console.rule("[bold magenta]QUANTUM FORGE v9 — DEBUG MODE[/]")
    req=clean(console.input("[cyan]Use case: [/]"))
    budget=clean(console.input("[cyan]Budget USD (or no limit): [/]"))or"no limit"
    chaos=quantum_chaos()
    p=punkd(req+budget)
    inv=get_stock()
    s=sum(p.values())if p else 0.5
    l=len(p)if p else 1
    temp=max(0.3,min(1.6,0.4+0.6*chaos+0.3*(s/l-0.5)))
    console.print(f"[bold yellow]STAGE 1 DONE — Chaos {chaos:.4f} Temp {temp:.2f}[/]")
    console.print("[dim]STAGE 2: Sending prompt to Grok-4...[/]")
    messages=[
        {"role":"system","content":"Return ONLY valid JSON. No text."},
        {"role":"user","content":PROMPT.format(req=req,budget=budget,chaos=chaos,punkd=p,inventory=inv)}
    ]
    raw=await call_grok(messages,temp)
    console.print("[dim]STAGE 3: Parsing response...[/]")
    build=extract_json(raw)
    if not build or"parts"not in build or not isinstance(build.get("parts"),dict):
        console.print("[bold red]STAGE 3 FAILED — VOID PROTOCOL ACTIVATED[/]")
        build={
            "build_name":"VOIDFORGED ETERNAL",
            "total_usd":999999,
            "performance_tier":"Beyond God-Tier",
            "parts":{
                "CPU":"AMD Ryzen 9 9950X3D",
                "Motherboard":"ASUS ROG Crosshair X870E",
                "RAM":"128GB DDR5-8000",
                "GPU":"RTX 5090 Ti",
                "Storage":"8TB Gen5 NVMe",
                "PSU":"Corsair HX1500i",
                "Case":"Lian Li O11 Dynamic EVO",
                "Cooling":"Custom 420mm Loop"
            },
            "justification":"The void never fails.",
            "future_proof_years":99
        }
    else:
        console.print("[bold green]STAGE 3 COMPLETE — Build parsed[/]")
    t=Table(title=f"[magenta]{build.get('build_name','??')}[/] ${build.get('total_usd',0):,}",box=box.ROUNDED)
    t.add_column("Part",style="cyan");t.add_column("Choice",style="green")
    for k,v in build.get("parts",{}).items():
        t.add_row(k,str(v)[:100])
    console.print(t)
    console.print(Panel(
        f"[white]{clean(str(build.get('justification','')))}[/]\n"
        f"Tier: [red]{build.get('performance_tier','')}[/] Future: [yellow]{build.get('future_proof_years',0)}y[/]",
        title="VERDICT",border_style="bright_magenta"))
    console.print("[bold green]FORGE COMPLETE[/]")
    save_db()
    console.input("\n[dim]Enter return[/]")

def vault_menu():
    console.clear()
    console.rule("[magenta]VAULT[/]")
    if GROK_KEY:console.print("[green]Key active[/]")
    if console.input("[yellow]Set/Replace Grok key? y/N [/]").lower()=="y":
        k=getpass.getpass("[red]Grok API key: [/]")
        if k.strip():
            GROK_ENC.write_bytes(encrypt_blob(k.encode()))
            os.environ["GROK_API_KEY"]=k.strip()
            console.print("[bold green]Key sealed[/]")

async def main():
    console.print(Panel("[magenta]GROK-4 QUANTUM FORGE 2025 — FINAL[/]",title="ONLINE",border_style="bright_magenta"))
    while 1:
        console.print("\n[cyan]1[/] Forge  [cyan]2[/] Vault  [cyan]3[/] Exit")
        c=console.input("[yellow]> [/]").strip()
        if c=="1":await forge()
        elif c=="2":vault_menu()
        elif c in("3","q","exit"):console.print("[red]Sealed.[/]");save_db();break

if __name__=="__main__":
    try:asyncio.run(main())
    except KeyboardInterrupt:pass
    finally:save_db()
