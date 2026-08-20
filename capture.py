"""Boot Brata, log in as admin, screenshot every view. Resumable (skips existing PNGs)."""
import os, time, json, subprocess, urllib.request, sys

SHOTS = "/home/claude/shots"
os.makedirs(SHOTS, exist_ok=True)
PORT = 8077
BASE = f"http://127.0.0.1:{PORT}"

# (group, key, label) — full nav, admin sees all
VIEWS = [
    ("Overview","home","Home"),
    ("Overview","methodology","Methodology"),
    ("Overview","dashboards","Dashboards"),
    ("Overview","learnings","Learnings"),
    ("Overview","dashboard","Snapshot"),
    ("Assess","assess","BRO Chat"),
    ("Assess","proassess","ProAssess"),
    ("Assess","assessments","Assessments"),
    ("Assess","engagements","Engagements"),
    ("Assess","vendors","Supplier Register"),
    ("Assess","artefacts","Certifications"),
    ("Assess","fdd","Financial DD"),
    ("Assess","reputation","Reputation"),
    ("Assess","oss","Open Source (SBOM)"),
    ("Assess","review","Review Queue"),
    ("Monitor & Manage","vendor360","Supplier 360"),
    ("Monitor & Manage","documents","Documents"),
    ("Monitor & Manage","performance","Performance"),
    ("Monitor & Manage","slamgmt","SLA Management"),
    ("Monitor & Manage","perfissues","Performance Issues"),
    ("Monitor & Manage","findings","Findings"),
    ("Monitor & Manage","issues","Issues Log"),
    ("Monitor & Manage","incidents","Supplier Incidents"),
    ("Monitor & Manage","remediation","Remediation Plans"),
    ("Monitor & Manage","fourthparties","4th Party Register"),
    ("Monitor & Manage","contracts","Contracts"),
    ("Monitor & Manage","exit","Exit Planning"),
    ("Monitor & Manage","notifications","Notifications"),
    ("Monitor & Manage","schedules","Schedules"),
    ("Monitor & Manage","connections","Connections"),
    ("Analyse","pestle","PESTLE Intelligence"),
    ("Analyse","intel","Intelligence"),
    ("Analyse","advanced","Overview"),
    ("Analyse","integrity","Data Integrity"),
    ("Analyse","entitygraph","Entity Graph"),
    ("Analyse","exposure","BU Exposure"),
    ("Analyse","geopolitical","Geopolitical"),
    ("Analyse","criticality","Critical Supplier Modelling"),
    ("Analyse","scenario","Scenario Simulator"),
    ("Analyse","stressradar","Stress Radar"),
    ("Understand","copilot","Ask Anything"),
    ("Understand","management","Management"),
    ("Understand","globalreg","Global Regulations"),
    ("Understand","boardpack","Board / Regulator Pack"),
    ("Understand","reports","Reports"),
    ("Understand","aireports","AI Reports"),
    ("Understand","evidence","Evidence on Demand"),
    ("Understand","lifecycle","Lifecycle"),
    ("Understand","governance","Governance"),
    ("Understand","audit","Audit Trail"),
    ("Documentation","sop","SOP"),
    ("Documentation","techdetails","Technical Details"),
    ("Documentation","versions","Version Control"),
    ("Admin Tools","guideddemo","Guided Demo"),
    ("Admin Tools","admin","Admin"),
    ("Admin Tools","usermgmt","User Management"),
    ("Admin Tools","adminchange","Admin Change"),
    ("Admin Tools","aicontrol","AI Control"),
    ("Admin Tools","config","Configuration"),
    ("Admin Tools","settings","Settings"),
    ("Admin Tools","language","Translation workbench"),
    ("Admin Tools","feedback","Feedback"),
]

def wait_up(timeout=40):
    t0=time.time()
    while time.time()-t0 < timeout:
        try:
            urllib.request.urlopen(BASE+"/", timeout=2); return True
        except Exception: time.sleep(1)
    return False

env=dict(os.environ, BRO_DB_URL="sqlite:///bro_demo.db")
srv=subprocess.Popen([sys.executable,"-m","uvicorn","app.bro_app:app",
                      "--host","127.0.0.1","--port",str(PORT)],
                     cwd="/home/claude/brate", env=env,
                     stdout=open("/tmp/cap_srv.log","w"), stderr=subprocess.STDOUT)
try:
    if not wait_up(): print("SERVER FAILED"); print(open("/tmp/cap_srv.log").read()[-2000:]); sys.exit(1)
    # login -> token
    body=json.dumps({"username":"admin","password":"admin"}).encode()
    req=urllib.request.Request(BASE+"/api/v1/login", data=body, headers={"Content-Type":"application/json"})
    tok=json.loads(urllib.request.urlopen(req, timeout=10).read())["token"]
    print("token OK")

    from playwright.sync_api import sync_playwright
    done=0; skipped=0; failed=[]
    with sync_playwright() as p:
        b=p.chromium.launch()
        pg=b.new_page(viewport={"width":1440,"height":900}, device_scale_factor=1.5)
        pg.goto(BASE+"/", wait_until="domcontentloaded")
        pg.evaluate("t=>sessionStorage.setItem('bro_tok',t)", tok)
        pg.goto(BASE+"/", wait_until="domcontentloaded")
        # wait for app shell to show
        pg.wait_for_selector("#app:not(.hidden)", timeout=15000)
        pg.wait_for_timeout(1200)
        for grp,key,label in VIEWS:
            out=f"{SHOTS}/{key}.png"
            if os.path.exists(out) and os.path.getsize(out)>2000:
                skipped+=1; continue
            try:
                pg.evaluate("k=>window.go(k)", key)
                try: pg.wait_for_load_state("networkidle", timeout=4000)
                except Exception: pass
                pg.wait_for_timeout(900)
                pg.screenshot(path=out, full_page=True)
                done+=1; print(f"[{done+skipped}/{len(VIEWS)}] {key}")
            except Exception as e:
                failed.append((key,str(e)[:120])); print(f"FAIL {key}: {e}")
        # extra: a concrete Supplier 360 deep-link
        try:
            if not os.path.exists(f"{SHOTS}/vendor360_detail.png"):
                pg.evaluate("()=>{ if(window.openV360) window.openV360('VEN-000001'); }")
                pg.wait_for_timeout(1500); pg.screenshot(path=f"{SHOTS}/vendor360_detail.png", full_page=True)
                print("extra: vendor360_detail")
        except Exception as e: print("v360 detail skip:", e)
        b.close()
    print(f"DONE captured={done} skipped={skipped} failed={len(failed)}")
    if failed: print("FAILED:", failed)
finally:
    srv.terminate()
    try: srv.wait(timeout=5)
    except Exception: srv.kill()
