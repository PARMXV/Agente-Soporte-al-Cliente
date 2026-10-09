# 🤖 Agente de Soporte con Python y Gemini AI

Agente de Inteligencia Artificial desarrollado en Python que procesa automáticamente las quejas y sugerencias registradas en **Google Forms** (almacenadas en **Google Sheets**), clasifica el tipo de incidente y analiza el sentimiento del cliente utilizando la API oficial de **Gemini AI** (`gemini-2.5-flash`).

---

## 🚀 Requisitos

- Python 3.9 o superior
- Una cuenta de Google con acceso a Google Forms y Google Sheets
- API Key de Google AI Studio (Gemini)

---

## 🛠️ Instalación

1. Clona el repositorio:
   ```bash
   git clone https://github.com/TU_USUARIO/mi_agente_soporte.git
   cd mi_agente_soporte
   ```

2. Instala las librerías necesarias:
   ```bash
   pip install gspread google-auth google-genai schedule
   ```

---

## 🔑 Configuración de Credenciales

1. **Gemini API Key**:
   - Obtén tu clave gratuita en [Google AI Studio](https://aistudio.google.com/app/api-keys).
   - Abre `agente_soporte.py` y asigna tu API Key a `GEMINI_API_KEY`, o establece la variable de entorno:
     ```bash
     export GEMINI_API_KEY="tu_api_key_aqui"
     ```

2. **Google OAuth 2.0 (`client_secrets.json`)**:
   - Crea un proyecto en [Google Cloud Console](https://console.cloud.google.com).
   - Habilita las APIs: **Google Sheets API** y **Google Drive API**.
   - En **Credenciales**, crea un **ID de cliente de OAuth 2.0** (Aplicación de escritorio).
   - Descarga el archivo JSON de credenciales, renómbralo a `client_secrets.json` y colócalo en la carpeta raíz del proyecto.

---

## 🏃 Ejecución

Para iniciar el agente en segundo plano:

```bash
python agente_soporte.py
```

El script procesará automáticamente los registros no leídos y volverá a comprobar la hoja cada 15 minutos.

---

## 🧪 Pruebas Locales

Puedes realizar una prueba local del modelo de IA sin necesidad de conectar Google Sheets:

```bash
python test_agente.py "TU_GEMINI_API_KEY"
```
