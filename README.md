# Mini-Brevo (Demo) – Streamlit

Prototipo educativo para gestionar contactos, crear campañas y enviar correos (o simularlos) sin usar HTML, construido con **Python + Streamlit**.

## Requisitos
- Python 3.10+
- pip

## Instalación local
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Envío real de emails (opcional)
Crea un archivo `.env` con tus credenciales SMTP (copiando desde `.env.example`).  
Si no configuras `.env`, la app **simula** envíos y aún registra logs.

## Despliegue rápido
- **Streamlit Cloud**: conecta este repo y listo.
