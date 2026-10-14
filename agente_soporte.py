import json
import os
import sys
import time
import schedule
import gspread
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# ==========================================
# SECCIÓN DE CONFIGURACIÓN (Fase 1)
# ==========================================
# Cargar variables de entorno desde el archivo .env si existe
load_dotenv()

# Nombre del archivo OAuth descargado en la Fase 2 (Práctica 1)
ARCHIVO_CREDENCIALES = "client_secrets.json"

# Scopes requeridos para Google Sheets y Drive
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Nombre de la hoja de cálculo creada en la Fase 1
NOMBRE_HOJA = "Respuestas de quejas (base de datos)."

# API Key de Gemini obtenida de las variables de entorno
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "TU_API_KEY_AQUI")

# Cada cuántos minutos el agente revisará si hay nuevas quejas (para modo bucle local)
INTERVALO_MINUTOS = 1

# Índices numéricos de las columnas en Google Sheets (1-indexed)
COL_CLASIFICACION = 4  # Columna D: Clasificación IA
COL_SENTIMIENTO = 5    # Columna E: Sentimiento IA
COL_EJECUTADO = 6      # Columna F: Agente Ejecutado ('SI')

# Variable global para el cliente de Gemini
client = None


# ==========================================
# FUNCIÓN: Conectar con Google Sheets (Paso 1.2)
# ==========================================
def conectar_sheets():
    """
    Autentica con Google Sheets.
    Si existe la variable de entorno GOOGLE_TOKEN_JSON (ej. en GitHub Actions),
    se autentica sin navegador usando el token guardado.
    Si no existe la variable, usa autenticación OAuth con navegador (modo local).
    """
    try:
        google_token_json = os.getenv("GOOGLE_TOKEN_JSON")

        if google_token_json:
            print("[INFO] Autenticando mediante GOOGLE_TOKEN_JSON (Modo sin navegador / Nube)...")
            token_data = json.loads(google_token_json)
            creds = Credentials.from_authorized_user_info(token_data, scopes=SCOPES)
            creds.refresh(Request())
            gc = gspread.authorize(creds)

            # Intentar abrir la hoja por nombre exacto o variantes
            try:
                sh = gc.open(NOMBRE_HOJA)
                return sh.sheet1
            except Exception:
                pass

            try:
                sh = gc.open("Respuestas de Quejas (Base de Datos)")
                return sh.sheet1
            except Exception:
                pass

            # Si falla el nombre exacto, buscar hojas en Google Drive
            todas_las_hojas = gc.openall()
            for hoja in todas_las_hojas:
                titulo_lower = hoja.title.lower()
                if "quejas" in titulo_lower or "respuestas" in titulo_lower:
                    print(f"[INFO] Conectado a la hoja encontrada: '{hoja.title}'")
                    return hoja.sheet1

            if todas_las_hojas:
                print(f"[INFO] Se usará la primera hoja disponible: '{todas_las_hojas[0].title}'")
                return todas_las_hojas[0].sheet1

            print("[ERROR] No se encontró ninguna hoja de cálculo disponible.")
            return None

        else:
            # Modo local: Autenticación OAuth 2.0 mediante navegador y client_secrets.json
            print("[INFO] Autenticando localmente con client_secrets.json (OAuth)...")
            gc = gspread.oauth(credentials_filename=ARCHIVO_CREDENCIALES)

            # 1. Intentar abrir por nombre exacto
            try:
                sh = gc.open(NOMBRE_HOJA)
                return sh.sheet1
            except Exception:
                pass

            try:
                sh = gc.open("Respuestas de Quejas (Base de Datos)")
                return sh.sheet1
            except Exception:
                pass

            # 2. Si falla por nombre exacto, buscar hojas en Google Drive
            todas_las_hojas = gc.openall()
            if not todas_las_hojas:
                print("[ERROR] No se encontró ninguna hoja de cálculo en tu cuenta de Google Drive.")
                return None

            nombre_buscado_lower = NOMBRE_HOJA.lower()
            for hoja in todas_las_hojas:
                titulo = hoja.title
                titulo_lower = titulo.lower()
                if (titulo_lower == nombre_buscado_lower or
                    "quejas" in titulo_lower or
                    "respuestas" in titulo_lower):
                    print(f"[INFO] Conectado a la hoja encontrada: '{titulo}'")
                    return hoja.sheet1

            # Si no coincide ninguna palabra clave, usar la primera hoja encontrada y avisar
            hoja_encontrada = todas_las_hojas[0]
            print(f"[INFO] No se encontró la hoja con el nombre exacto '{NOMBRE_HOJA}'.")
            print(f"[INFO] Se usará la hoja disponible: '{hoja_encontrada.title}'")
            return hoja_encontrada.sheet1

    except Exception as e:
        print(f"[ERROR] No se pudo conectar con Google Sheets: {e}")
        return None


# ==========================================
# FUNCIÓN: Analizar con Gemini (Paso 4.5)
# ==========================================
def analizar_con_gemini(comentario):
    """
    Envía la queja/comentario a la API de Gemini (gemini-2.5-flash) para que la clasifique
    (Ventas, Soporte Técnico, Logística) y detecte el sentimiento (Positivo, Negativo, Neutro).
    Retorna un diccionario Python con las claves 'clasificacion' y 'sentimiento'.
    """
    system_instruction = (
        "Eres un analista de soporte al cliente. Tu única tarea es devolver una "
        "respuesta en formato JSON estricto, sin texto adicional ni explicaciones."
    )

    prompt_usuario = (
        "Clasifica el siguiente comentario recibido en una de tres categorías: "
        "'Ventas', 'Soporte Técnico' o 'Logística'. "
        "Detecta también el sentimiento: 'Positivo', 'Negativo' o 'Neutro'.\n\n"
        f"Comentario: \"{comentario}\"\n\n"
        "Responde en formato JSON estricto con la siguiente estructura:\n"
        "{\n"
        '  "clasificacion": "Ventas" | "Soporte Técnico" | "Logística",\n'
        '  "sentimiento": "Positivo" | "Negativo" | "Neutro"\n'
        "}"
    )

    # Reintentos en caso de límite de cuota (429 RESOURCE_EXHAUSTED)
    max_reintentos = 3
    for intento in range(max_reintentos):
        try:
            # Llamada a la API de Gemini utilizando gemini-2.5-flash y GenerateContentConfig
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt_usuario,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json"
                )
            )

            texto_respuesta = response.text.strip()

            # Limpiar bloques de código Markdown (```json o ```) si Gemini los agrega
            if texto_respuesta.startswith("```"):
                lines = texto_respuesta.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                texto_respuesta = "\n".join(lines).strip()

            # Convertir texto JSON a diccionario Python
            resultado = json.loads(texto_respuesta)
            return resultado

        except Exception as e:
            if "429" in str(e) and intento < max_reintentos - 1:
                espera = 15 * (intento + 1)
                print(f"[AVISO] Límite de cuota alcanzado (429). Esperando {espera} segundos antes de reintentar...")
                time.sleep(espera)
            else:
                print(f"[ERROR] Error durante el análisis con Gemini: {e}")
                return None
    return None


# ==========================================
# FUNCIÓN: Agente Principal (Paso 1.3)
# ==========================================
def ejecutar_agente():
    """
    Orquesta el ciclo completo del agente:
    1. Conectar a Google Sheets.
    2. Leer todas las filas y omitir los encabezados.
    3. Filtrar las filas cuya columna F esté vacía (no contenga 'SI').
    4. Enviar el comentario de cada fila a analizar_con_gemini().
    5. Escribir clasificación en col D, sentimiento en col E, y 'SI' en col F.
    6. Retorna True si completó el ciclo con éxito, False si hubo error de conexión.
    """
    print("\n--------------------------------------------------")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Iniciando ciclo del agente...")

    hoja = conectar_sheets()
    if not hoja:
        print("[ERROR] Imposible continuar sin conexión a Google Sheets.")
        return False

    try:
        filas = hoja.get_all_values()
    except Exception as e:
        print(f"[ERROR] Error al leer los datos de la hoja: {e}")
        return False

    # Verificar que existan datos más allá de los encabezados (fila 1)
    if len(filas) <= 1:
        print("[INFO] La hoja no contiene registros de respuestas por analizar.")
        return True

    nuevas_filas_procesadas = 0

    # Recorrer las filas a partir de la fila 2 (índice 2 en 1-based gspread update)
    for idx_fila, fila in enumerate(filas[1:], start=2):
        # Columna F (índice 5 en la lista de python 0-indexed)
        estado_ejecutado = fila[5] if len(fila) > 5 else ""

        # Si ya contiene "SI", significa que la fila ya fue procesada antes
        if estado_ejecutado.strip().upper() == "SI":
            continue

        nombre_cliente = fila[1] if len(fila) > 1 and fila[1] else "Cliente Anónimo"

        # Extraer comentario de la columna C (índice 2) o columna B (índice 1)
        comentario = ""
        if len(fila) > 2 and fila[2].strip():
            comentario = fila[2].strip()
        elif len(fila) > 1 and fila[1].strip() and len(fila[1].strip()) > 15:
            comentario = fila[1].strip()

        if not comentario:
            print(f"[OMITIDO] Fila {idx_fila} - Cliente: '{nombre_cliente}' (Sin comentario detectable)")
            continue

        print(f"\n[PROCESANDO NUEVA QUEJA] Fila {idx_fila} - Cliente: {nombre_cliente}")
        print(f"   Comentario: \"{comentario}\"")

        # Analizar comentario con Gemini AI
        analisis = analizar_con_gemini(comentario)

        if analisis and "clasificacion" in analisis and "sentimiento" in analisis:
            clasificacion = analisis["clasificacion"]
            sentimiento = analisis["sentimiento"]

            print(f"   -> Clasificación IA: {clasificacion}")
            print(f"   -> Sentimiento IA:   {sentimiento}")

            try:
                # Escribir en la columna D (Clasificación IA)
                hoja.update_cell(idx_fila, COL_CLASIFICACION, clasificacion)
                # Escribir en la columna E (Sentimiento IA)
                hoja.update_cell(idx_fila, COL_SENTIMIENTO, sentimiento)
                # Escribir 'SI' en la columna F (Agente Ejecutado)
                hoja.update_cell(idx_fila, COL_EJECUTADO, "SI")

                print(f"   [ÉXITO] Resultados guardados en Google Sheets (Fila {idx_fila}).")
                nuevas_filas_procesadas += 1
            except Exception as e:
                print(f"   [ERROR] No se pudieron guardar los resultados en la fila {idx_fila}: {e}")
        else:
            print(f"   [ERROR] No se obtuvo un JSON válido de Gemini para la fila {idx_fila}. Se omitirá por ahora.")

        # Pausa ligera entre filas para respetar los límites de la API gratuita
        time.sleep(2)

    print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Ciclo completado. Filas procesadas en este turno: {nuevas_filas_procesadas}")
    print("--------------------------------------------------")
    return True


# ==========================================
# PUNTO DE ENTRADA DEL SCRIPT (Paso 1.3 y 1.4)
# ==========================================
if __name__ == "__main__":
    print("==================================================")
    print("      AGENTE DE SOPORTE CON PYTHON Y GEMINI       ")
    print("==================================================")

    # 1. Validar la API Key
    if not GEMINI_API_KEY or GEMINI_API_KEY == "TU_API_KEY_AQUI":
        print("\n[ERROR CRÍTICO] GEMINI_API_KEY no configurada.")
        print("Por favor, configura la variable GEMINI_API_KEY en tu archivo .env")
        print("o como variable de entorno del sistema.")
        sys.exit(1)

    # 2. Validar el archivo de credenciales de Google (solo si no existe GOOGLE_TOKEN_JSON)
    if not os.getenv("GOOGLE_TOKEN_JSON"):
        if not os.path.exists(ARCHIVO_CREDENCIALES):
            print(f"\n[ERROR CRÍTICO] Archivo de credenciales '{ARCHIVO_CREDENCIALES}' no encontrado.")
            print("Asegúrate de tener client_secrets.json en esta carpeta para ejecución local")
            print("o de definir la variable GOOGLE_TOKEN_JSON para ejecución en la nube.")
            sys.exit(1)

    # 3. Inicializar el cliente de Gemini AI
    try:
        print("[CONFIGURACIÓN] Inicializando cliente de Gemini AI...")
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"[ERROR CRÍTICO] No se pudo inicializar el cliente de Gemini: {e}")
        sys.exit(1)

    # 4. Modo 'Una Vez' para GitHub Actions (--una-vez)
    if "--una-vez" in sys.argv:
        print("[MODO] Ejecutando en modo una sola vez (--una-vez)...")
        exito = ejecutar_agente()
        sys.exit(0 if exito else 1)

    # 5. Modo continuo para ejecución local con bucle schedule
    ejecutar_agente()

    schedule.every(INTERVALO_MINUTOS).minutes.do(ejecutar_agente)
    print(f"\n[AGENTE ACTIVO] Revisando la hoja de cálculo CADA {INTERVALO_MINUTOS} MINUTO(S).")
    print("Presiona Ctrl+C para detener el agente.\n")

    try:
        while True:
            schedule.run_pending()
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n[AGENTE DETENIDO] El usuario ha detenido la ejecución.")
