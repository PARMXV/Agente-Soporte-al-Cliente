import json
import os
import time
import schedule
import gspread
from google import genai
from google.genai import types

# ==========================================
# SECCIÓN DE CONFIGURACIÓN (Paso 4.3)
# ==========================================
# Nombre del archivo OAuth descargado en la Fase 2
ARCHIVO_CREDENCIALES = "client_secrets.json"

# Nombre exacto de la hoja de cálculo creada en la Fase 1
NOMBRE_HOJA = "Respuestas de Quejas (Base de Datos)"

# API Key de Gemini obtenida en la Fase 3
# Se puede configurar directamente aquí o mediante la variable de entorno GEMINI_API_KEY
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "TU_API_KEY_AQUI")

# Cada cuántos minutos el agente revisará si hay nuevas quejas
INTERVALO_MINUTOS = 15

# Índices numéricos de las columnas en Google Sheets (1-indexed)
COL_CLASIFICACION = 4  # Columna D: Clasificación IA
COL_SENTIMIENTO = 5    # Columna E: Sentimiento IA
COL_EJECUTADO = 6      # Columna F: Agente Ejecutado ('SI')

# Variable global para el cliente de Gemini
client = None


# ==========================================
# FUNCIÓN: Conectar con Google Sheets (Paso 4.4)
# ==========================================
def conectar_sheets():
    """
    Autentica el script con Google usando OAuth 2.0 a través de gspread,
    abre la hoja de cálculo por su nombre y retorna la primera pestaña (sheet1).
    """
    try:
        # Autenticación OAuth 2.0 utilizando el archivo client_secrets.json
        gc = gspread.oauth(credentials_filename=ARCHIVO_CREDENCIALES)
        
        # 1. Intentar abrir por nombre exacto
        try:
            sh = gc.open(NOMBRE_HOJA)
            return sh.sheet1
        except Exception:
            pass

        # 2. Si falla por nombre exacto, buscar hojas en Google Drive
        todas_las_hojas = gc.openall()
        if not todas_las_hojas:
            print("[ERROR] No se encontró ninguna hoja de cálculo en tu cuenta de Google Drive.")
            print("Asegúrate de haber creado la hoja desde Google Forms en tu cuenta parm15022012@gmail.com.")
            return None

        # Intentar coincidencia sin importar mayúsculas/minúsculas o palabras clave
        nombre_buscado_lower = NOMBRE_HOJA.lower()
        for hoja in todas_las_hojas:
            titulo = hoja.title
            titulo_lower = titulo.lower()
            if titulo_lower == nombre_buscado_lower or "quejas" in titulo_lower or "respuestas" in titulo_lower:
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
# FUNCIÓN: Agente Principal (Paso 4.6)
# ==========================================
def ejecutar_agente():
    """
    Orquesta el ciclo completo del agente:
    1. Conectar a Google Sheets.
    2. Leer todas las filas y omitir los encabezados.
    3. Filtrar las filas cuya columna F esté vacía (no contenga 'SI').
    4. Enviar el comentario de cada fila a analizar_con_gemini().
    5. Escribir clasificación en col D, sentimiento en col E, y 'SI' en col F.
    6. Manejo de errores para continuar con la siguiente fila si algo falla.
    """
    print("\n--------------------------------------------------")
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Iniciando ciclo del agente...")
    
    hoja = conectar_sheets()
    if not hoja:
        print("[ERROR] Imposible continuar sin conexión a Google Sheets.")
        return

    try:
        filas = hoja.get_all_values()
    except Exception as e:
        print(f"[ERROR] Error al leer los datos de la hoja: {e}")
        return

    # Verificar que existan datos más allá de los encabezados (fila 1)
    if len(filas) <= 1:
        print("[INFO] La hoja no contiene registros de respuestas por analizar.")
        return

    nuevas_filas_procesadas = 0

    # Recorrer las filas a partir de la fila 2 (índice 2 en 1-based gspread update)
    for idx_fila, fila in enumerate(filas[1:], start=2):
        # Columna F (índice 5 en la lista de python 0-indexed)
        estado_ejecutado = fila[5] if len(fila) > 5 else ""

        # Si ya contiene "SI", significa que la fila ya fue procesada antes
        if estado_ejecutado.strip().upper() == "SI":
            continue

        nombre_cliente = fila[1] if len(fila) > 1 and fila[1] else "Cliente Anónimo"
        comentario = fila[2] if len(fila) > 2 else ""

        if not comentario.strip():
            print(f"[OMITIDO] Fila {idx_fila} - Cliente: '{nombre_cliente}' (Comentario vacío)")
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

    print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Ciclo completado. Filas procesadas: {nuevas_filas_procesadas}")
    print("--------------------------------------------------")


# ==========================================
# PUNTO DE ENTRADA DEL SCRIPT (Paso 4.7)
# ==========================================
if __name__ == "__main__":
    print("==================================================")
    print("      AGENTE DE SOPORTE CON PYTHON Y GEMINI       ")
    print("==================================================")

    # 1. Validar la API Key
    if not GEMINI_API_KEY or GEMINI_API_KEY == "TU_API_KEY_AQUI":
        print("\n[ERROR CRÍTICO] GEMINI_API_KEY no configurada.")
        print("Por favor, abre 'agente_soporte.py' y asigna tu API Key en GEMINI_API_KEY,")
        print("o establece la variable de entorno 'GEMINI_API_KEY'.")
        exit(1)

    # 2. Validar el archivo de credenciales de Google
    if not os.path.exists(ARCHIVO_CREDENCIALES):
        print(f"\n[ERROR CRÍTICO] Archivo de credenciales '{ARCHIVO_CREDENCIALES}' no encontrado.")
        print("Asegúrate de copiar el archivo JSON de OAuth 2.0 descargado de Google Cloud Console")
        print(f"a esta misma carpeta y renombrarlo exactamente a '{ARCHIVO_CREDENCIALES}'.")
        exit(1)

    # 3. Inicializar el cliente de Gemini AI
    try:
        print("[CONFIGURACIÓN] Inicializando cliente de Gemini AI...")
        client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"[ERROR CRÍTICO] No se pudo inicializar el cliente de Gemini: {e}")
        exit(1)

    # 4. Ejecutar inmediatamente al arrancar
    ejecutar_agente()

    # 5. Programar ejecuciones automáticas cada INTERVALO_MINUTOS
    schedule.every(INTERVALO_MINUTOS).minutes.do(ejecutar_agente)
    print(f"\n[AGENTE ACTIVO] Revisando la hoja de cálculo cada {INTERVALO_MINUTOS} minutos.")
    print("Presiona Ctrl+C para detener el agente.\n")

    # 6. Mantener el script en ejecución continua (bucle infinito cada 30 segundos)
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n[AGENTE DETENIDO] El usuario ha detenido la ejecución.")
