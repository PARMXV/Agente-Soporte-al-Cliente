"""
Script de prueba local para validar el análisis con Gemini AI de las quejas descritas en el PDF.
Ejecutar con: python test_agente.py [TU_GEMINI_API_KEY]
"""

import sys
import os
import json
from agente_soporte import analizar_con_gemini
from google import genai

# Datos de prueba exactos especificados en el PDF (Pasos 1.3 y 5.2)
CASOS_PRUEBA = [
    {
        "nombre": "Cliente de Prueba (Paso 1.3)",
        "comentario": "Mi pedido llegó tarde y la caja estaba rota. Muy mal servicio.",
        "esperado": "Logística / Negativo"
    },
    {
        "nombre": "Ana (Paso 5.2)",
        "comentario": "No entiendo cómo funciona la nueva app, el botón de ayuda no sirve.",
        "esperado": "Soporte Técnico / Negativo"
    },
    {
        "nombre": "Carlos (Paso 5.2)",
        "comentario": "Me atendió un vendedor llamado Juan y fue increíble, ¡resolvió todo! 10/10.",
        "esperado": "Ventas / Positivo"
    },
    {
        "nombre": "María (Paso 5.2)",
        "comentario": "Mi paquete lleva 2 semanas sin llegar y nadie me da información.",
        "esperado": "Logística / Negativo"
    }
]

def probar_analisis(api_key):
    import agente_soporte
    agente_soporte.client = genai.Client(api_key=api_key)

    print("==================================================")
    print("   PRUEBA LOCAL DE ANÁLISIS DE QUEJAS CON GEMINI  ")
    print("==================================================\n")

    for i, caso in enumerate(CASOS_PRUEBA, 1):
        print(f"--- Caso de Prueba #{i}: {caso['nombre']} ---")
        print(f"Comentario: \"{caso['comentario']}\"")
        print(f"Esperado:   {caso['esperado']}")
        
        res = analizar_con_gemini(caso["comentario"])
        
        if res:
            print(f"Obtenido:   {res.get('clasificacion')} / {res.get('sentimiento')}")
            print(f"JSON Raw:   {json.dumps(res, ensure_ascii=False)}")
        else:
            print("Obtenido:   [ERROR AL ANALIZAR]")
        print()
        import time
        time.sleep(2)

if __name__ == "__main__":
    api_key = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Uso: python test_agente.py <TU_GEMINI_API_KEY>")
        print("O exporta la variable de entorno GEMINI_API_KEY")
        sys.exit(1)
    
    probar_analisis(api_key)
