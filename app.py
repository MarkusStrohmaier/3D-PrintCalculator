import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from fpdf import FPDF
from datetime import datetime

# --- DATENBANK SETUP ---
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    projects = relationship("Project", back_populates="user")

class Material(Base):
    __tablename__ = 'materials'
    id = Column(Integer, primary_key=True); name = Column(String, unique=True); price_per_kg = Column(Float)

class Printer(Base):
    __tablename__ = 'printers'
    id = Column(Integer, primary_key=True); name = Column(String, unique=True); cost_per_hour = Column(Float)

class Project(Base):
    __tablename__ = 'projects'
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(String, default=datetime.now().strftime("%d. %B %Y"))
    user = relationship("User", back_populates="projects")
    items = relationship("ProjectItem", back_populates="project", cascade="all, delete-orphan")

class ProjectItem(Base):
    __tablename__ = 'items'
    id = Column(Integer, primary_key=True); project_id = Column(Integer, ForeignKey('projects.id'))
    item_type = Column(String); name = Column(String); weight = Column(Float); cost = Column(Float); details = Column(String)
    project = relationship("Project", back_populates="items")

engine = create_engine('sqlite:///projekte.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine); db = Session()

# --- PDF DESIGN ---
def create_styled_pdf(project):
    pdf = FPDF()
    pdf.add_page(); pdf.set_margins(20, 20, 20)
    accent_color = (26, 64, 102) 
    pdf.set_font("Arial", 'B', 38); pdf.set_text_color(*accent_color); pdf.cell(0, 20, "MaxlDruck", ln=True)
    pdf.set_font("Arial", '', 12); pdf.set_text_color(50, 50, 50); pdf.cell(0, 10, "MATERIALPREISLISTE / KALKULATION", ln=True)
    pdf.set_font("Arial", size=10); pdf.set_y(20)
    pdf.cell(0, 5, f"PROJEKT-NR: {project.id + 1000}", ln=True, align='R')
    pdf.cell(0, 5, f"{datetime.now().strftime('%d. %B %Y').upper()}", ln=True, align='R')
    pdf.set_draw_color(*accent_color); pdf.set_line_width(1.5); pdf.line(20, 55, 190, 55)
    pdf.set_y(65); pdf.set_font("Arial", 'B', 11); pdf.set_text_color(0, 0, 0)
    u_name = project.user.name if project.user else "Kein User"
    pdf.cell(0, 10, f"PROJEKT: {project.name.upper()} | KUNDE: {u_name}", ln=True); pdf.ln(5)
    pdf.set_fill_color(*accent_color); pdf.set_text_color(255, 255, 255); pdf.set_font("Arial", 'B', 10)
    pdf.cell(90, 10, " BESCHREIBUNG", fill=True); pdf.cell(25, 10, "ANZAHL", fill=True, align='C')
    pdf.cell(25, 10, "PREIS", fill=True, align='R'); pdf.cell(30, 10, "SUMME ", fill=True, align='R', ln=True)
    pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", size=10); pdf.set_draw_color(200, 200, 200)
    total_sum = 0
    for item in project.items:
        pdf.cell(90, 12, f" {item.name}", border='B')
        anz_str = item.details.split(" ")[0] if "Stk" in item.details else "1"
        pdf.cell(25, 12, anz_str, border='B', align='C')
        pdf.cell(25, 12, f"{item.cost:.2f} EUR", border='B', align='R')
        pdf.cell(30, 12, f"{item.cost:.2f} EUR", border='B', align='R', ln=True)
        total_sum += item.cost
    pdf.ln(15); pdf.set_font("Arial", 'B', 14); pdf.set_text_color(*accent_color); pdf.cell(130, 10, "GESAMTSUMME", align='R')
    pdf.set_font("Arial", 'B', 20); pdf.set_text_color(0, 0, 0); pdf.cell(40, 10, f"{total_sum:.2f} EUR", align='R', ln=True)
    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- UI LOGIK ---
st.set_page_config(page_title="MaxlDruck Pro", layout="wide")

if 'current_items' not in st.session_state: st.session_state.current_items = []
if 'edit_idx' not in st.session_state: st.session_state.edit_idx = None
if 'p_name' not in st.session_state: st.session_state.p_name = ""
if 'editing_project_id' not in st.session_state: st.session_state.editing_project_id = None

# Sidebar
with st.sidebar:
    st.header("⚙️ Stammdaten")
    with st.expander("Filament & Drucker"):
        m_n = st.text_input("Material"); m_p = st.number_input("€/kg", value=25.0)
        if st.button("Mat speichern"): db.merge(Material(name=m_n, price_per_kg=m_p)); db.commit(); st.rerun()
        st.divider()
        pr_n = st.text_input("Drucker"); pr_p = st.number_input("€/h", value=0.40)
        if st.button("Drucker speichern"): db.merge(Printer(name=pr_n, cost_per_hour=pr_p)); db.commit(); st.rerun()

# --- TABS ---
tab_calc, tab_users, tab_stats = st.tabs(["🖨️ Kalkulator", "👥 Benutzerverwaltung", "📊 Statistiken"])

# --- TAB 1: KALKULATOR ---
with tab_calc:
    st.title("📦 MaxlDruck Kalkulator")
    col_form, col_list = st.columns([1, 1])

    with col_form:
        st.subheader("📝 Eingabe")
        is_item_edit = st.session_state.edit_idx is not None
        edit_val = st.session_state.current_items[st.session_state.edit_idx] if is_item_edit else {}

        with st.container(border=True):
            st.session_state.p_name = st.text_input("Projekt Name", value=st.session_state.p_name)
            
            # User Auswahl
            users = db.query(User).all()
            user_list = {u.name: u.id for u in users}
            selected_user_name = st.selectbox("Zuteilen zu Benutzer", list(user_list.keys())) if user_list else st.warning("Lege erst einen Benutzer an!")
            
            st.divider()
            i_type = st.radio("Typ", ["Druckteil", "Zubehör"], index=0 if not is_item_edit or edit_val['Typ'] == "Druck" else 1, horizontal=True)
            i_name = st.text_input("Bezeichnung", value=edit_val.get('Name', ""))

            if i_type == "Druckteil":
                m_db = {m.name: m.price_per_kg for m in db.query(Material).all()}
                p_db = {p.name: p.cost_per_hour for p in db.query(Printer).all()}
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
                        st.session_state.edit_idx = None; st.rerun()

            else:
                i_pr = st.number_input("Preis/Stk", min_value=0.0)
                i_q = st.number_input("Anzahl", min_value=1, value=1)
                if st.button("Übernehmen" if is_item_edit else "Hinzufügen"):
                    item = {"Typ": "Zubehör", "Name": i_name, "Gewicht (g)": 0, "Kosten (€)": round(i_pr * i_q, 2), "Details": f"{i_q} Stk"}
                    if is_item_edit: st.session_state.current_items[st.session_state.edit_idx] = item
                    else: st.session_state.current_items.append(item)
                    st.session_state.edit_idx = None; st.rerun()

    with col_list:
        st.subheader("🛒 Aktuelle Liste")
        for idx, itm in enumerate(st.session_state.current_items):
            with st.container(border=True):
                cols = st.columns([4, 1, 1])
                cols[0].write(f"**{itm['Name']}** ({itm['Details']}) - {itm['Kosten (€)']} EUR")
                if cols[1].button("✏️", key=f"ei_{idx}"): st.session_state.edit_idx = idx; st.rerun()
                if cols[2].button("🗑️", key=f"di_{idx}"): st.session_state.current_items.pop(idx); st.rerun()
        
        if st.session_state.current_items and user_list:
            if st.button("💾 PROJEKT FINAL SPEICHERN", use_container_width=True, type="primary"):
                if st.session_state.editing_project_id:
                    old = db.query(Project).filter(Project.id == st.session_state.editing_project_id).first()
                    if old: db.delete(old)
                new_p = Project(name=st.session_state.p_name, user_id=user_list[selected_user_name])
                for i in st.session_state.current_items:
                    new_p.items.append(ProjectItem(item_type=i['Typ'], name=i['Name'], weight=i['Gewicht (g)'], cost=i['Kosten (€)'], details=i['Details']))
                db.add(new_p); db.commit()
                st.session_state.current_items = []; st.session_state.p_name = ""; st.session_state.editing_project_id = None; st.rerun()

    st.divider()
    st.header("📂 Archiv")
    for proj in db.query(Project).order_by(Project.id.desc()).all():
        with st.expander(f"📦 {proj.name.upper()} ({proj.user.name if proj.user else '?'}) - {sum(i.cost for i in proj.items):.2f} EUR"):
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("✏️ Laden", key=f"lp_{proj.id}"):
                    st.session_state.editing_project_id = proj.id
                    st.session_state.p_name = proj.name
                    st.session_state.current_items = [{"Typ": i.item_type, "Name": i.name, "Gewicht (g)": i.weight, "Kosten (€)": i.cost, "Details": i.details} for i in proj.items]
                    st.rerun()
            with c2: st.download_button("📄 PDF", data=create_styled_pdf(proj), file_name=f"{proj.name}.pdf", key=f"pdf_{proj.id}")
            with c3:
                if st.button("🗑️ Löschen", key=f"dp_{proj.id}"): db.delete(proj); db.commit(); st.rerun()

# --- TAB 2: BENUTZERVERWALTUNG ---
with tab_users:
    st.header("👥 Benutzer verwalten")
    with st.form("new_user_form"):
        u_name = st.text_input("Benutzername / Kunde")
        if st.form_submit_button("Benutzer anlegen"):
            if u_name:
                db.add(User(name=u_name)); db.commit(); st.rerun()
    
    st.subheader("Bestehende Benutzer")
    for u in db.query(User).all():
        col_u1, col_u2 = st.columns([4, 1])
        col_u1.write(f"👤 {u.name}")
        if col_u2.button("Löschen", key=f"del_u_{u.id}"):
            db.delete(u); db.commit(); st.rerun()

# --- TAB 3: STATISTIKEN ---
with tab_stats:
    st.header("📊 Gesamt-Statistik")
    all_projects = db.query(Project).all()
    
    if all_projects:
        total_val = sum(sum(i.cost for i in p.items) for p in all_projects)
        total_items = sum(len(p.items) for p in all_projects)
        
        stat1, stat2, stat3 = st.columns(3)
        stat1.metric("Gesamtumsatz", f"{total_val:.2f} €")
        stat2.metric("Projekte gesamt", len(all_projects))
        stat3.metric("Posten gesamt", total_items)
        
        st.divider()
        st.subheader("👤 Statistik pro Benutzer")
        for u in db.query(User).all():
            user_projects = [p for p in all_projects if p.user_id == u.id]
            user_sum = sum(sum(i.cost for i in p.items) for p in user_projects)
            with st.container(border=True):
                st.write(f"**Benutzer: {u.name}**")
                st.write(f"Anzahl Projekte: {len(user_projects)}")
                st.write(f"Umsatz: {user_sum:.2f} €")
    else:
        st.info("Noch keine Daten vorhanden.")