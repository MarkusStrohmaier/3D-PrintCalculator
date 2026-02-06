import os
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from fpdf import FPDF
from datetime import datetime
from passlib.hash import pbkdf2_sha256

# --- Directories ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(BASE_DIR, "user_dbs")
os.makedirs(USERS_DIR, exist_ok=True)

# --- DATABASE BASES ---
AuthBase = declarative_base()
GlobalBase = declarative_base()
ProjectBase = declarative_base()

# --- AUTH MODEL (central DB) ---
class User(AuthBase):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)

# --- GLOBAL STAMMDATEN (shared DB for materials/printers) ---
class Material(GlobalBase):
    __tablename__ = 'materials'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    price_per_kg = Column(Float)

class Printer(GlobalBase):
    __tablename__ = 'printers'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True)
    cost_per_hour = Column(Float)

# --- USER-PROJECT MODELS (each user gets their own DB file) ---
class Project(ProjectBase):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    customer_name = Column(String, nullable=True)
    work_hours = Column(Float, default=0.0)
    work_rate = Column(Float, default=0.0)
    failed_filament_g = Column(Float, default=0.0)
    failed_material = Column(String, nullable=True)
    created_at = Column(String, default=datetime.now().strftime("%d. %B %Y"))
    items = relationship("ProjectItem", back_populates="project", cascade="all, delete-orphan")

class ProjectItem(ProjectBase):
    __tablename__ = 'items'
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey('projects.id'))
    item_type = Column(String)
    name = Column(String)
    weight = Column(Float)
    cost = Column(Float)
    details = Column(String)
    project = relationship("Project", back_populates="items")

# --- ENGINES + SESSIONS ---
auth_engine = create_engine('sqlite:///auth.db')
global_engine = create_engine('sqlite:///global.db')
AuthBase.metadata.create_all(auth_engine)
GlobalBase.metadata.create_all(global_engine)
AuthSession = sessionmaker(bind=auth_engine)
auth_db = AuthSession()
GlobalSession = sessionmaker(bind=global_engine)
global_db = GlobalSession()

# --- PASSWORD HELPERS (use PBKDF2 to avoid bcrypt 72-byte limit) ---
def hash_pw(pw: str) -> str:
    return pbkdf2_sha256.hash(pw)

def verify_pw(pw: str, hashval: str) -> bool:
    return pbkdf2_sha256.verify(pw, hashval)

def get_user_engine(username: str):
    # sqlite file per user
    safe_name = ''.join(c for c in username if c.isalnum() or c in ('_', '-')).lower()
    path = os.path.join(USERS_DIR, f'user_{safe_name}.db')
    return create_engine(f'sqlite:///{path}'), path

def ensure_user_db(username: str):
    engine, path = get_user_engine(username)
    # Create tables if they don't exist
    ProjectBase.metadata.create_all(engine)
    # If the projects table exists but is missing the `customer_name` column,
    # add it via ALTER TABLE (SQLite supports ADD COLUMN).
    try:
        with engine.connect() as conn:
            infos = conn.execute(text("PRAGMA table_info(projects);")).fetchall()
            cols = [row[1] for row in infos] if infos else []
            if infos:
                if 'customer_name' not in cols:
                    conn.execute(text("ALTER TABLE projects ADD COLUMN customer_name TEXT;"))
                if 'work_hours' not in cols:
                    conn.execute(text("ALTER TABLE projects ADD COLUMN work_hours REAL DEFAULT 0.0;"))
                if 'work_rate' not in cols:
                    conn.execute(text("ALTER TABLE projects ADD COLUMN work_rate REAL DEFAULT 0.0;"))
                if 'failed_filament_g' not in cols:
                    conn.execute(text("ALTER TABLE projects ADD COLUMN failed_filament_g REAL DEFAULT 0.0;"))
                if 'failed_material' not in cols:
                    conn.execute(text("ALTER TABLE projects ADD COLUMN failed_material TEXT;"))
    except Exception:
        # If anything goes wrong we silently continue; reading uses getattr so missing
        # attribute won't crash.
        pass
    return engine

# --- PDF DESIGN ---
def create_styled_pdf(project, username=None):
    pdf = FPDF()
    pdf.add_page(); pdf.set_margins(20, 20, 20)
    def safe(txt):
        if txt is None:
            return ""
        if not isinstance(txt, str):
            txt = str(txt)
        # replace common problematic symbols (euro) and ensure latin-1 encodability
        txt = txt.replace('€', 'EUR')
        return txt.encode('latin-1', 'replace').decode('latin-1')
    accent_color = (26, 64, 102)
    pdf.set_font("Arial", 'B', 38); pdf.set_text_color(*accent_color); pdf.cell(0, 20, safe("MaxlDruck"), ln=True)
    pdf.set_font("Arial", '', 12); pdf.set_text_color(50, 50, 50); pdf.cell(0, 10, safe("MATERIALPREISLISTE / KALKULATION"), ln=True)
    pdf.set_font("Arial", size=10); pdf.set_y(20)
    pdf.cell(0, 5, safe(f"PROJEKT-NR: {project.id + 1000}"), ln=True, align='R')
    pdf.cell(0, 5, safe(f"{datetime.now().strftime('%d. %B %Y').upper()}"), ln=True, align='R')
    pdf.set_draw_color(*accent_color); pdf.set_line_width(1.5); pdf.line(20, 55, 190, 55)
    pdf.set_y(65); pdf.set_font("Arial", 'B', 11); pdf.set_text_color(0, 0, 0)
    # prefer project.customer_name if available
    u_name = (getattr(project, 'customer_name', None) or username) or "Kein User"
    pdf.cell(0, 10, safe(f"PROJEKT: {project.name.upper()} | KUNDE: {u_name}"), ln=True); pdf.ln(5)
    pdf.set_fill_color(*accent_color); pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", 'B', 10)
    pdf.cell(90, 10, safe(" BESCHREIBUNG"), fill=True); pdf.cell(25, 10, safe("ANZAHL"), fill=True, align='C')
    pdf.cell(25, 10, safe("PREIS"), fill=True, align='R'); pdf.cell(30, 10, safe("SUMME "), fill=True, align='R', ln=True)
    pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", size=10); pdf.set_draw_color(200, 200, 200)
    total_sum = 0
    for item in project.items:
        pdf.cell(90, 12, safe(f" {item.name}"), border='B')
        anz_str = item.details.split(" ")[0] if item.details and "Stk" in item.details else "1"
        pdf.cell(25, 12, safe(anz_str), border='B', align='C')
        pdf.cell(25, 12, safe(f"{item.cost:.2f} EUR"), border='B', align='R')
        pdf.cell(30, 12, safe(f"{item.cost:.2f} EUR"), border='B', align='R', ln=True)
        total_sum += item.cost
    # Optional: Arbeitsstunden und Fehldruck als separate Zeilen (werden NICHT zur Gesamtsumme addiert)
    pdf.ln(8)
    pdf.set_font("Arial", size=10); pdf.set_text_color(0, 0, 0)
    # Arbeitsstunden
    wh = float(getattr(project, 'work_hours', 0.0) or 0.0)
    wr = float(getattr(project, 'work_rate', 0.0) or 0.0)
    if wh and wr:
        work_cost = wh * wr
        pdf.cell(115, 8, safe(f"Arbeitsstunden: {wh:.2f} h @ {wr:.2f} EUR/h"), border='B')
        pdf.cell(40, 8, safe(f"{work_cost:.2f} EUR"), border='B', align='R', ln=True)
        pdf.set_font("Arial", size=8); pdf.cell(0, 5, safe("(Nicht in Gesamtsumme enthalten)"), ln=True)
        pdf.set_font("Arial", size=10)

    # Fehldruck Filament
    ff_g = float(getattr(project, 'failed_filament_g', 0.0) or 0.0)
    ff_mat = getattr(project, 'failed_material', None)
    if ff_g and ff_mat:
        # find material price
        mat = global_db.query(Material).filter(Material.name == ff_mat).first()
        if mat and mat.price_per_kg:
            ff_cost = (mat.price_per_kg / 1000.0) * ff_g
            pdf.cell(115, 8, safe(f"Fehldruckfilament: {ff_g:.0f} g ({ff_mat})"), border='B')
            pdf.cell(40, 8, safe(f"{ff_cost:.2f} EUR"), border='B', align='R', ln=True)
            pdf.set_font("Arial", size=8); pdf.cell(0, 5, safe("(Nicht in Gesamtsumme enthalten)"), ln=True)
            pdf.set_font("Arial", size=10)

    pdf.ln(7); pdf.set_font("Arial", 'B', 14); pdf.set_text_color(*accent_color); pdf.cell(130, 10, safe("GESAMTSUMME"), align='R')
    pdf.set_font("Arial", 'B', 20); pdf.set_text_color(0, 0, 0); pdf.cell(40, 10, safe(f"{total_sum:.2f} EUR"), align='R', ln=True)
    return pdf.output(dest='S').encode('latin-1', 'replace')


def format_eur(v: float) -> str:
    try:
        return f"{float(v):.2f} €"
    except Exception:
        return "0.00 €"

# --- UI LOGIK ---
st.set_page_config(page_title="MaxlDruck Pro", layout="wide")

if 'current_items' not in st.session_state: st.session_state.current_items = []
if 'edit_idx' not in st.session_state: st.session_state.edit_idx = None
if 'p_name' not in st.session_state: st.session_state.p_name = ""
if 'editing_project_id' not in st.session_state: st.session_state.editing_project_id = None
if 'username' not in st.session_state: st.session_state.username = None
if '_rerun_req' not in st.session_state: st.session_state['_rerun_req'] = False
if 'customer_name' not in st.session_state: st.session_state.customer_name = ""
if 'work_hours' not in st.session_state: st.session_state.work_hours = 0.0
if 'work_rate' not in st.session_state: st.session_state.work_rate = 0.0
if 'failed_filament_g' not in st.session_state: st.session_state.failed_filament_g = 0.0
if 'failed_material' not in st.session_state: st.session_state.failed_material = ""

def do_rerun():
    try:
        # try the built-in rerun (may not exist in some Streamlit builds)
        if hasattr(st, 'experimental_rerun'):
            st.experimental_rerun()
            return
        if hasattr(st, 'rerun'):
            st.rerun()
            return
    except Exception:
        pass
    # fallback: toggle a session flag and stop to trigger a rerun
    st.session_state['_rerun_req'] = not st.session_state.get('_rerun_req', False)
    st.stop()

# --- SIDEBAR: AUTH + Stammdaten ---
with st.sidebar:
    st.header("🔐 Anmeldung / Benutzer")
    if not st.session_state.username:
        u = st.text_input("Benutzername", key='login_user')
        pw = st.text_input("Passwort", type='password', key='login_pw')
        col1, col2 = st.columns(2)
        if col1.button("Anmelden"):
            if u and pw:
                found = auth_db.query(User).filter(User.name == u).first()
                if found and verify_pw(pw, found.password_hash):
                    st.session_state.username = found.name
                    ensure_user_db(found.name)
                    do_rerun()
                else:
                    st.error("Anmeldung fehlgeschlagen.")
        if col2.button("Registrieren"):
            if u and pw:
                exists = auth_db.query(User).filter(User.name == u).first()
                if exists:
                    st.warning("Benutzer existiert bereits.")
                else:
                    h = hash_pw(pw)
                    auth_db.add(User(name=u, password_hash=h)); auth_db.commit()
                    ensure_user_db(u)
                    st.session_state.username = u
                    st.success("Benutzer angelegt und angemeldet.")
                    do_rerun()
    else:
        st.write(f"Angemeldet als: **{st.session_state.username}**")
        if st.button("Abmelden"):
            st.session_state.username = None
            do_rerun()

    st.divider(); st.header("⚙️ Stammdaten")
    with st.expander("Filament & Drucker"):
        m_n = st.text_input("Material"); m_p = st.number_input("€/kg", value=25.0)
        if st.button("Mat speichern"): global_db.merge(Material(name=m_n, price_per_kg=m_p)); global_db.commit(); do_rerun()
        st.divider()
        pr_n = st.text_input("Drucker"); pr_p = st.number_input("€/h", value=0.40)
        if st.button("Drucker speichern"): global_db.merge(Printer(name=pr_n, cost_per_hour=pr_p)); global_db.commit(); do_rerun()

# --- TABS ---
tab_calc, tab_users, tab_stats = st.tabs(["🖨️ Kalkulator", "👥 Benutzerverwaltung", "📊 Statistiken"])

# --- TAB 1: KALKULATOR ---
with tab_calc:
    st.title("📦 MaxlDruck Kalkulator")
    if not st.session_state.username:
        st.info("Bitte anmelden, um Projekte zu verwalten.")
    else:
        username = st.session_state.username
        user_engine = ensure_user_db(username)
        UserSession = sessionmaker(bind=user_engine)
        user_db = UserSession()

        col_form, col_list = st.columns([1, 1])

        with col_form:
            st.subheader("📝 Eingabe")
            is_item_edit = st.session_state.edit_idx is not None
            edit_val = st.session_state.current_items[st.session_state.edit_idx] if is_item_edit else {}

            with st.container(border=True):
                st.session_state.p_name = st.text_input("Projekt Name", value=st.session_state.p_name)
                st.session_state.customer_name = st.text_input("Kundenname", value=st.session_state.customer_name)

                # Zusatzfelder: Arbeitsstunden und Fehldruck
                cols_add = st.columns([1, 1, 1, 1])
                cols_add[0].write("**Arbeitsstunden (h)**")
                st.session_state.work_hours = cols_add[0].number_input("", min_value=0.0, value=float(st.session_state.work_hours), key='in_work_hours')
                cols_add[1].write("**Stundensatz (€/h)**")
                st.session_state.work_rate = cols_add[1].number_input("", min_value=0.0, value=float(st.session_state.work_rate), key='in_work_rate')
                cols_add[2].write("**Fehldruck Filament (g)**")
                st.session_state.failed_filament_g = cols_add[2].number_input("", min_value=0.0, value=float(st.session_state.failed_filament_g), key='in_failed_g')
                # Material Auswahl für Fehldruck (optional)
                m_names = [""] + [m.name for m in global_db.query(Material).all()]
                st.session_state.failed_material = cols_add[3].selectbox("Material (Fehldruck)", m_names, index=(m_names.index(st.session_state.failed_material) if st.session_state.failed_material in m_names else 0), key='in_failed_mat')

                st.divider()
                i_type = st.radio("Typ", ["Druckteil", "Zubehör"], index=0 if not is_item_edit or edit_val.get('Typ') == "Druck" else 1, horizontal=True)
                i_name = st.text_input("Bezeichnung", value=edit_val.get('Name', ""))

                if i_type == "Druckteil":
                    m_db = {m.name: m.price_per_kg for m in global_db.query(Material).all()}
                    p_db = {p.name: p.cost_per_hour for p in global_db.query(Printer).all()}
                    if m_db and p_db:
                        c1, c2 = st.columns(2)
                        sel_m = c1.selectbox("Material", list(m_db.keys()))
                        sel_p = c2.selectbox("Drucker", list(p_db.keys()))
                        i_w = st.number_input("Gewicht (g)", min_value=0.0, value=float(edit_val.get('Gewicht (g)', 0.0)))
                        i_t = st.number_input("Zeit (h)", min_value=0.0)
                        if st.button("Übernehmen" if is_item_edit else "Hinzufügen"):
                            cost = (m_db[sel_m]/1000 * i_w) + (p_db[sel_p] * i_t)
                            item = {"Typ": "Druck", "Name": i_name, "Gewicht (g)": i_w, "Kosten (€)": round(cost, 2), "Details": f"{sel_m}"}
                            if is_item_edit: st.session_state.current_items[st.session_state.edit_idx] = item
                            else: st.session_state.current_items.append(item)
                            st.session_state.edit_idx = None; do_rerun()

                else:
                    i_pr = st.number_input("Preis/Stk", min_value=0.0)
                    i_q = st.number_input("Anzahl", min_value=1, value=1)
                    if st.button("Übernehmen" if is_item_edit else "Hinzufügen"):
                        item = {"Typ": "Zubehör", "Name": i_name, "Gewicht (g)": 0, "Kosten (€)": round(i_pr * i_q, 2), "Details": f"{i_q} Stk"}
                        if is_item_edit: st.session_state.current_items[st.session_state.edit_idx] = item
                        else: st.session_state.current_items.append(item)
                        st.session_state.edit_idx = None; do_rerun()

        with col_list:
            st.subheader("🛒 Aktuelle Liste")
            # Show items as a tidy table
            if st.session_state.current_items:
                df = pd.DataFrame([{"Bezeichnung": it["Name"], "Details": it.get("Details", ""), "Kosten": it.get("Kosten (€)", 0.0)} for it in st.session_state.current_items])
                df["Kosten"] = df["Kosten"].map(lambda x: format_eur(x))
                st.table(df)

                # action buttons below table for edit/delete
                for idx, itm in enumerate(st.session_state.current_items):
                    r1, r2 = st.columns([6,1])
                    r1.write(f"**{itm['Name']}** — {itm.get('Details','')}")
                    if r2.button("✏️", key=f"ei_{idx}"):
                        st.session_state.edit_idx = idx; do_rerun()
                    if r2.button("🗑️", key=f"di_{idx}"):
                        st.session_state.current_items.pop(idx); do_rerun()

                if st.button("💾 PROJEKT FINAL SPEICHERN", use_container_width=True, type="primary"):
                    if st.session_state.editing_project_id:
                        old = user_db.query(Project).filter(Project.id == st.session_state.editing_project_id).first()
                        if old:
                            user_db.delete(old)
                    new_p = Project(name=st.session_state.p_name, customer_name=st.session_state.customer_name,
                                    work_hours=float(st.session_state.work_hours), work_rate=float(st.session_state.work_rate),
                                    failed_filament_g=float(st.session_state.failed_filament_g), failed_material=st.session_state.failed_material or None)
                    for i in st.session_state.current_items:
                        new_p.items.append(ProjectItem(item_type=i['Typ'], name=i['Name'], weight=i['Gewicht (g)'], cost=i['Kosten (€)'], details=i['Details']))
                    user_db.add(new_p); user_db.commit()
                    st.session_state.current_items = []; st.session_state.p_name = ""; st.session_state.editing_project_id = None; do_rerun()

                # Nice summary panel
                subtotal = sum(i.get("Kosten (€)", 0.0) for i in st.session_state.current_items)
                wh = float(st.session_state.work_hours or 0.0)
                wr = float(st.session_state.work_rate or 0.0)
                work_cost = wh * wr if (wh and wr) else 0.0
                ff_g = float(st.session_state.failed_filament_g or 0.0)
                ff_cost = 0.0
                if ff_g and st.session_state.failed_material:
                    mat = global_db.query(Material).filter(Material.name == st.session_state.failed_material).first()
                    if mat and mat.price_per_kg:
                        ff_cost = (mat.price_per_kg / 1000.0) * ff_g
                s1, s2, s3 = st.columns(3)
                s1.metric("Zwischensumme", format_eur(subtotal))
                s2.metric("Arbeitskosten (optional)", format_eur(work_cost))
                s3.metric("Fehldruck (optional)", format_eur(ff_cost))

            st.divider()
            st.header("📂 Archiv")
            for proj in user_db.query(Project).order_by(Project.id.desc()).all():
                with st.expander(f"📦 {proj.name.upper()} - {sum(i.cost for i in proj.items):.2f} EUR"):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        if st.button("✏️ Laden", key=f"lp_{proj.id}"):
                            st.session_state.editing_project_id = proj.id
                            st.session_state.p_name = proj.name
                            st.session_state.customer_name = getattr(proj, 'customer_name', "") or ""
                            st.session_state.work_hours = float(getattr(proj, 'work_hours', 0.0) or 0.0)
                            st.session_state.work_rate = float(getattr(proj, 'work_rate', 0.0) or 0.0)
                            st.session_state.failed_filament_g = float(getattr(proj, 'failed_filament_g', 0.0) or 0.0)
                            st.session_state.failed_material = getattr(proj, 'failed_material', "") or ""
                            st.session_state.current_items = [{"Typ": i.item_type, "Name": i.name, "Gewicht (g)": i.weight, "Kosten (€)": i.cost, "Details": i.details} for i in proj.items]
                            do_rerun()
                    with c2: st.download_button("📄 PDF", data=create_styled_pdf(proj, username), file_name=f"{proj.name}.pdf", key=f"pdf_{proj.id}")
                    with c3:
                        if st.button("🗑️ Löschen", key=f"dp_{proj.id}"): user_db.delete(proj); user_db.commit(); do_rerun()

# --- TAB 2: BENUTZERVERWALTUNG ---
with tab_users:
    st.header("👥 Benutzer verwalten")
    with st.form("new_user_form"):
        u_name = st.text_input("Benutzername / Kunde")
        u_pw = st.text_input("Passwort", type='password')
        if st.form_submit_button("Benutzer anlegen"):
            if u_name and u_pw:
                exists = auth_db.query(User).filter(User.name == u_name).first()
                if exists:
                    st.warning("Benutzer existiert bereits.")
                else:
                    h = hash_pw(u_pw)
                    auth_db.add(User(name=u_name, password_hash=h)); auth_db.commit(); ensure_user_db(u_name)
                    st.session_state.username = u_name
                    st.success("Benutzer angelegt und angemeldet.")
                    do_rerun()

    st.subheader("Bestehende Benutzer")
    for u in auth_db.query(User).all():
        col_u1, col_u2 = st.columns([4, 1])
        col_u1.write(f"👤 {u.name}")
        if col_u2.button("Löschen", key=f"del_u_{u.id}"):
            # delete auth entry and remove user DB file
            auth_db.delete(u); auth_db.commit()
            _, path = get_user_engine(u.name)
            try:
                os.remove(path)
            except Exception:
                pass
            do_rerun()

# --- TAB 3: STATISTIKEN ---
with tab_stats:
    st.header("📊 Gesamt-Statistik")
    # global stats across all user DBs
    total_val = 0.0
    total_projects = 0
    total_items = 0
    for fname in os.listdir(USERS_DIR):
        if fname.endswith('.db'):
            fpath = os.path.join(USERS_DIR, fname)
            eng = create_engine(f'sqlite:///{fpath}')
            S = sessionmaker(bind=eng)();
            try:
                projs = S.query(Project).all()
            except Exception:
                projs = []
            for p in projs:
                total_projects += 1
                total_items += len(p.items)
                total_val += sum(i.cost for i in p.items)

    if total_projects:
        stat1, stat2, stat3 = st.columns(3)
        stat1.metric("Gesamtumsatz", f"{total_val:.2f} €")
        stat2.metric("Projekte gesamt", total_projects)
        stat3.metric("Posten gesamt", total_items)
    else:
        st.info("Noch keine Daten vorhanden.")
