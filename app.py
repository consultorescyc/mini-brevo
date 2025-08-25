import os
import smtplib
import sqlite3
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from contextlib import contextmanager
from datetime import datetime

import pandas as pd
import streamlit as st

# -------------- Config ----------------
st.set_page_config(page_title="Mini-Brevo (Local Demo)", page_icon="📧", layout="wide")

DB_PATH = os.path.join(os.path.dirname(__file__), "mini_brevo.db")

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
FROM_EMAIL = os.getenv("FROM_EMAIL", SMTP_USER or "demo@example.com")
FROM_NAME = os.getenv("FROM_NAME", "Mini-Brevo Demo")

# -------------- DB Helpers ------------

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT UNIQUE,
                tags TEXT,
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT,
                body TEXT,
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER,
                contact_id INTEGER,
                email TEXT,
                status TEXT,
                error TEXT,
                sent_at TEXT
            )
        """)
        conn.commit()

def insert_contact(name, email, tags):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO contacts(name, email, tags, created_at) VALUES (?,?,?,?)",
            (name.strip(), email.strip().lower(), tags.strip(), datetime.utcnow().isoformat())
        )
        conn.commit()

def bulk_import_contacts(df: pd.DataFrame):
    count = 0
    for _, row in df.iterrows():
        name = str(row.get("name", "")).strip()
        email = str(row.get("email", "")).strip().lower()
        tags = str(row.get("tags", "")).strip()
        if email:
            try:
                insert_contact(name, email, tags)
                count += 1
            except Exception:
                pass
    return count

def insert_campaign(subject, body):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO campaigns(subject, body, created_at) VALUES (?,?,?)",
            (subject.strip(), body, datetime.utcnow().isoformat())
        )
        conn.commit()

def log_send(campaign_id, contact_id, email, status, error=""):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sends(campaign_id, contact_id, email, status, error, sent_at) VALUES (?,?,?,?,?,?)",
            (campaign_id, contact_id, email, status, error, datetime.utcnow().isoformat())
        )
        conn.commit()

# -------------- Email Sender ----------
def send_email_smtp(to_email: str, subject: str, body_html: str):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and FROM_EMAIL):
        return True, "SIMULATED"
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
        msg["To"] = to_email

        part_html = MIMEText(body_html, "html", "utf-8")
        msg.attach(part_html)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(FROM_EMAIL, [to_email], msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)

# -------------- UI --------------------
def page_contacts():
    import re

    def is_valid_email(s: str) -> bool:
        return re.match(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", s or "") is not None

    st.header("👥 Contactos")

    # -------------------------------
    # 1) Agregar contacto individual
    # -------------------------------
    with st.expander("➕ Agregar contacto individual", expanded=True):
        with st.form("add_contact_form"):
            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                name = st.text_input("Nombre")
            with col2:
                email = st.text_input("Email *")
            with col3:
                tags = st.text_input("Etiquetas (opcional, separadas por coma)")

            submitted = st.form_submit_button("Guardar")
            if submitted:
                if not email:
                    st.error("El email es obligatorio.")
                elif not is_valid_email(email):
                    st.error("Formato de email no válido.")
                else:
                    insert_contact(name, email, tags)
                    st.success(f"Contacto '{email}' guardado (o ya existía).")
                    with get_conn() as conn:
                        st.session_state["contacts_df"] = pd.read_sql_query(
                            "SELECT * FROM contacts ORDER BY id DESC", conn
                        )
                    st.rerun()

    st.divider()

    # -------------------------------
    # 2) Importar contactos CSV o TXT
    # -------------------------------
    st.subheader("📤 Importar desde CSV o TXT")
    st.caption("""
- **CSV**: columnas `email`, `name`, `tags` (obligatorio `email`).
- **TXT**: dos opciones:
  1) `email;name;tags` (separados por `;`) — `name` y `tags` pueden ir vacíos.
  2) Solo correos, separados por salto de línea, coma, espacio o `;`.
    """)

    file = st.file_uploader("Subir CSV o TXT", type=["csv", "txt"])
    if file:
        df = None
        skipped = 0

        if file.name.endswith(".csv"):
            df = pd.read_csv(file)
            # Normalizar nombres de columnas esperadas
            cols_lower = {c.lower(): c for c in df.columns}
            # Mapear si vienen en mayúsculas/otras variantes
            email_col = cols_lower.get("email")
            name_col = cols_lower.get("name")
            tags_col = cols_lower.get("tags")
            # Crear columnas faltantes
            if email_col is None:
                st.error("El CSV debe incluir una columna 'email'.")
                return
            if name_col is None:
                df["name"] = ""
                name_col = "name"
            if tags_col is None:
                df["tags"] = ""
                tags_col = "tags"
            # Dejar columnas con nombres estándar
            df = df.rename(columns={email_col: "email", name_col: "name", tags_col: "tags"})

            # Validar emails y limpiar
            df["email"] = df["email"].astype(str).str.strip().str.lower()
            mask_valid = df["email"].apply(is_valid_email)
            skipped = int((~mask_valid).sum())
            df = df[mask_valid].copy()

        elif file.name.endswith(".txt"):
            text = file.read().decode("utf-8")
            rows = []

            # Procesar línea por línea
            for ln in [l.strip() for l in text.splitlines() if l.strip()]:
                if ";" in ln:
                    # Formato estructurado: email;name;tags
                    partes = [p.strip() for p in ln.split(";")]
                    email = (partes[0] if len(partes) >= 1 else "").lower()
                    name  = (partes[1] if len(partes) >= 2 else "")
                    tags_ = ";".join(partes[2:]) if len(partes) >= 3 else ""
                    rows.append({"email": email, "name": name, "tags": tags_})
                else:
                    # Formato libre: correos separados por coma/espacio/;
                    tokens = re.split(r"[,\s;]+", ln)
                    for tok in [t.strip().lower() for t in tokens if t.strip()]:
                        rows.append({"email": tok, "name": "", "tags": ""})

            df = pd.DataFrame(rows)
            if not df.empty:
                df["email"] = df["email"].astype(str).str.strip().str.lower()
                mask_valid = df["email"].apply(is_valid_email)
                skipped = int((~mask_valid).sum())
                df = df[mask_valid].copy()

            # Quitar duplicados por email conservando el primero
            if not df.empty:
                df = df.drop_duplicates(subset=["email"], keep="first")

        # Mostrar y permitir importar
        if df is not None and not df.empty:
            st.dataframe(df.head(50), use_container_width=True)
            if skipped > 0:
                st.warning(f"Se omitieron {skipped} filas por email inválido.")
            if st.button("Importar contactos"):
                count = bulk_import_contacts(df)
                st.success(f"Importados {count} contactos.")
                with get_conn() as conn:
                    st.session_state["contacts_df"] = pd.read_sql_query(
                        "SELECT * FROM contacts ORDER BY id DESC", conn
                    )
                st.rerun()
        else:
            st.info("No se detectaron contactos válidos en el archivo.")

    st.divider()

    # -------------------------------
    # 3) Listado de contactos (editar + eliminar)
    # -------------------------------
    with get_conn() as conn:
        df_contacts = pd.read_sql_query("SELECT * FROM contacts ORDER BY id DESC", conn)
    st.session_state["contacts_df"] = df_contacts

    st.subheader(f"📋 Listado de contactos ({len(df_contacts)})")

    # --- Edición en tabla ---
    st.caption("Puedes editar Email / Nombre / Etiquetas y luego guardar los cambios.")
    edited_df = st.data_editor(
        df_contacts[["id", "email", "name", "tags"]],
        hide_index=True,
        column_config={
            "id": st.column_config.Column("ID", disabled=True),
            "email": st.column_config.Column("Email"),
            "name": st.column_config.Column("Nombre"),
            "tags": st.column_config.Column("Etiquetas"),
        },
        num_rows="fixed",  # no permitir agregar filas desde el editor
        key="contacts_editor"
    )

    if st.button("💾 Guardar cambios"):
        updates = 0
        errors = []
        with get_conn() as conn:
            cur = conn.cursor()
            # comparar por ID y actualizar sólo lo que cambió
            original = df_contacts.set_index("id")
            for _, row in edited_df.iterrows():
                rid = int(row["id"])
                new_email = str(row["email"]).strip().lower()
                new_name  = str(row["name"]).strip()
                new_tags  = str(row["tags"]).strip()
                # Validar email
                if not is_valid_email(new_email):
                    errors.append(f"ID {rid}: email inválido '{new_email}'")
                    continue
                # Ver si cambió algo
                if (original.at[rid, "email"] != new_email or
                    original.at[rid, "name"]  != new_name  or
                    original.at[rid, "tags"]  != new_tags):
                    try:
                        cur.execute(
                            "UPDATE contacts SET email=?, name=?, tags=? WHERE id=?",
                            (new_email, new_name, new_tags, rid)
                        )
                        updates += 1
                    except Exception as e:
                        errors.append(f"ID {rid}: {e}")
            conn.commit()
        if updates:
            st.success(f"✅ {updates} contacto(s) actualizado(s).")
        if errors:
            st.error("⚠️ Errores:\n- " + "\n- ".join(errors))
        st.rerun()

    st.divider()

    # --- Eliminar: por ID ---
    st.subheader("🗑️ Eliminar contactos")
    colA, colB = st.columns([2, 1])
    with colA:
        delete_id = st.text_input("ID del contacto a eliminar", placeholder="Ej: 12")
    with colB:
        if st.button("Eliminar por ID"):
            if delete_id.isdigit():
                with get_conn() as conn:
                    conn.execute("DELETE FROM contacts WHERE id=?", (int(delete_id),))
                    conn.commit()
                st.success(f"Contacto con ID {delete_id} eliminado.")
                st.rerun()
            else:
                st.warning("Ingresa un ID numérico válido.")

    # --- Eliminar: botón por fila (con buscador) ---
    st.caption("También puedes eliminar por fila. Usa el buscador para filtrar.")
    q = st.text_input("🔎 Buscar por email o nombre", "")
    df_del = df_contacts.copy()
    if q.strip():
        ql = q.strip().lower()
        df_del = df_del[
            df_del["email"].str.lower().str.contains(ql) |
            df_del["name"].fillna("").str.lower().str.contains(ql)
        ]

    for _, row in df_del.iterrows():
        c1, c2, c3, c4, c5 = st.columns([3, 3, 3, 1, 1])
        c1.write(row["name"] or "—")
        c2.write(row["email"])
        c3.write(row["tags"] or "—")
        c4.write(f"ID: {row['id']}")
        if c5.button("🗑️", key=f"del_row_{row['id']}"):
            with get_conn() as conn:
                conn.execute("DELETE FROM contacts WHERE id=?", (row["id"],))
                conn.commit()
            st.success(f"Contacto {row['email']} eliminado.")
            st.rerun()



def page_campaigns():
    st.header("📝 Campañas (borradores)")
    with st.form("new_campaign_form"):
        subject = st.text_input("Asunto *")
        body = st.text_area(
            "Contenido (HTML o texto) *", height=200,
            value="<h2>Hola {{name}}</h2><p>Este es un mensaje de prueba.</p>"
        )
        submitted = st.form_submit_button("Crear campaña")
        if submitted:
            if subject and body:
                insert_campaign(subject, body)
                st.success("Campaña creada.")
            else:
                st.error("Asunto y contenido son obligatorios.")

    st.divider()
    with get_conn() as conn:
        df_campaigns = pd.read_sql_query("SELECT * FROM campaigns ORDER BY id DESC", conn)
    st.session_state["campaigns_df"] = df_campaigns
    st.subheader(f"📚 Borradores ({len(df_campaigns)})")
    st.dataframe(df_campaigns, use_container_width=True)


def page_send():
    st.header("🚀 Enviar campaña")
    df_campaigns = st.session_state.get("campaigns_df")
    df_contacts = st.session_state.get("contacts_df")

    if df_campaigns is None or df_contacts is None:
        st.warning("Debes crear al menos una campaña y agregar contactos.")
        return

    if df_campaigns.empty or df_contacts.empty:
        st.warning("Debes crear al menos una campaña y agregar contactos.")
        return

    campaign = st.selectbox(
        "Selecciona campaña",
        df_campaigns.itertuples(),
        format_func=lambda r: f"[{r.id}] {r.subject}"
    )

    recipients = st.multiselect(
        "Destinatarios",
        options=df_contacts.itertuples(),
        default=list(df_contacts.itertuples()),
        format_func=lambda r: f"{r.email} ({r.name})" if r.name else r.email
    )

    test_email = st.text_input("Enviar prueba a (opcional)")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Enviar PRUEBA"):
            if test_email:
                body = campaign.body.replace("{{name}}", "Prueba")
                ok, err = send_email_smtp(test_email, campaign.subject, body)
                status = "SENT" if ok else "ERROR"
                log_send(campaign.id, None, test_email, status, err)
                with get_conn() as conn:
                    st.session_state["sends_df"] = pd.read_sql_query(
                        "SELECT s.id, s.sent_at, s.status, s.error, s.email, c.subject "
                        "FROM sends s LEFT JOIN campaigns c ON s.campaign_id = c.id "
                        "ORDER BY s.id DESC LIMIT 500", conn
                    )
                if ok:
                    st.success("Prueba enviada (o simulada).")
                else:
                    st.error(f"Error: {err}")
            else:
                st.info("Escribe un email para la prueba.")

    with col2:
        if st.button("Enviar a TODOS los seleccionados"):
            sent_ok = 0
            for r in recipients:
                personalized = campaign.body.replace("{{name}}", r.name or "")
                ok, err = send_email_smtp(r.email, campaign.subject, personalized)
                status = "SENT" if ok else "ERROR"
                log_send(campaign.id, r.id, r.email, status, err)
                if ok: sent_ok += 1
            with get_conn() as conn:
                st.session_state["sends_df"] = pd.read_sql_query(
                    "SELECT s.id, s.sent_at, s.status, s.error, s.email, c.subject "
                    "FROM sends s LEFT JOIN campaigns c ON s.campaign_id = c.id "
                    "ORDER BY s.id DESC LIMIT 500", conn
                )
            st.success(f"Proceso finalizado. Enviados OK: {sent_ok}/{len(recipients)} (simulados).")


def main():
    init_db()

    if "contacts_df" not in st.session_state:
        with get_conn() as conn:
            st.session_state["contacts_df"] = pd.read_sql_query(
                "SELECT * FROM contacts ORDER BY id DESC", conn
            )

    if "campaigns_df" not in st.session_state:
        with get_conn() as conn:
            st.session_state["campaigns_df"] = pd.read_sql_query(
                "SELECT * FROM campaigns ORDER BY id DESC", conn
            )

    if "sends_df" not in st.session_state:
        with get_conn() as conn:
            st.session_state["sends_df"] = pd.read_sql_query(
                "SELECT s.id, s.sent_at, s.status, s.error, s.email, c.subject "
                "FROM sends s LEFT JOIN campaigns c ON s.campaign_id = c.id "
                "ORDER BY s.id DESC LIMIT 500", conn
            )

    st.sidebar.title("Mini-Brevo (Local Demo)")
    page = st.sidebar.radio("Menú", ["Contactos", "Campañas", "Enviar", "Logs"])

    if page == "Contactos":
        page_contacts()
    elif page == "Campañas":
        page_campaigns()
    elif page == "Enviar":
        page_send()
    else:
        st.header("📈 Historial de envíos")
        df = st.session_state.get("sends_df")
        st.dataframe(df, use_container_width=True)
        st.caption("Nota: En modo demo, los envíos se simulan si no configuras SMTP.")

    with st.sidebar.expander("ℹ️ Ayuda"):
        st.markdown("""
**Mini-Brevo (Local Demo)**  
- Agrega contactos, crea campañas y envía (o simula) correos.  
- Personalización básica: usa `{{name}}` en el cuerpo para reemplazar el nombre.  
- Para envíos reales, configura variables de entorno SMTP.
        """)

if __name__ == "__main__":
    main()
