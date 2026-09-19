import streamlit as st
import pandas as pd
import re
import PyPDF2
import io

st.set_page_config(page_title="Procesador GNSS | ConPlanos", layout="wide", page_icon="🛰️")

# --- FUNCIONES DE EXTRACCIÓN PDF ---
def extraer_datos_pdf(archivo_pdf):
    lector = PyPDF2.PdfReader(archivo_pdf)
    texto = ""
    for pagina in lector.pages:
        texto += pagina.extract_text() + "\n"

    def obtener_ultimo_flotante(patron, txt):
        match = re.search(patron, txt, re.IGNORECASE)
        if match:
            # Encuentra números con comas y decimales (ej. 210,204.5425)
            numeros = re.findall(r'\b\d{1,3}(?:,\d{3})*\.\d+\b', match.group(0))
            if numeros:
                return float(numeros[-1].replace(',', ''))
        return None

    # Coordenadas (Extrae la última coincidencia de la línea, que corresponde al Móvil)
    easting = obtener_ultimo_flotante(r'Coordenada X:.*', texto)
    northing = obtener_ultimo_flotante(r'Coordenada Y:.*', texto)
    h_orto = obtener_ultimo_flotante(r'Altura Ortom\.:.*', texto)
    h_elip = obtener_ultimo_flotante(r'Altura Elip WGS84:.*', texto)

    # Resumen de Calidad
    distancia = obtener_ultimo_flotante(r'Dist\. Geom\.:.*', texto)
    cq2d = obtener_ultimo_flotante(r'CQ 2D:.*', texto)
    cq3d = obtener_ultimo_flotante(r'CQ 3D:.*', texto)

    match_duracion = re.search(r'Duración:\s*([\d:]+)', texto)
    duracion = match_duracion.group(1) if match_duracion else "Desconocido"

    match_fecha = re.search(r'Hora Inicio - Hora Fin:\s*([\d/]+\s[\d:]+)', texto)
    fecha = match_fecha.group(1) if match_fecha else "Desconocida"

    fijo = "✅ FIJO" if "Fijo (Fase)" in texto or "Solucionado PP" in texto else "❌ NO FIJO"
    
    # Extraer antena móvil
    match_antena = re.search(r'Móvil\s*-\s*(.+)', texto)
    antena = match_antena.group(1).strip() if match_antena else "CHC / TRIMBLE (Ver reporte)"

    return {
        'e': easting, 'n': northing, 'h_orto': h_orto, 'h_elip': h_elip,
        'dist': distancia, 'duracion': duracion, 'cq2d': cq2d, 'cq3d': cq3d,
        'fecha': fecha, 'fijo': fijo, 'antena': antena
    }

# --- INTERFAZ ---
st.title("🛰️ Procesador y Corrector GNSS | ConPlanos")
st.markdown("Sube tu CSV nativo de campo y, opcionalmente, el reporte de Leica Infinity en PDF para extraer las coordenadas automáticamente.")

col_archivos1, col_archivos2 = st.columns(2)
with col_archivos1:
    csv_file = st.file_uploader("1. Subir Levantamiento (CSV Nativo)", type=["csv"])
with col_archivos2:
    pdf_file = st.file_uploader("2. Subir Informe de Procesamiento (PDF Leica)", type=["pdf"])

# Variables de estado para los inputs manuales
if 'e_val' not in st.session_state:
    st.session_state.e_val = 0.0
    st.session_state.n_val = 0.0
    st.session_state.h_val = 0.0
    st.session_state.pdf_procesado = None

df_csv = None
if csv_file:
    try:
        df_csv = pd.read_csv(csv_file, encoding='utf-8')
    except UnicodeDecodeError:
        csv_file.seek(0)
        df_csv = pd.read_csv(csv_file, encoding='latin1')
        
    col_nom = next((c for c in df_csv.columns if c.strip().lower() == 'nombre'), df_csv.columns[0])
    col_e = next((c for c in df_csv.columns if c.strip().lower() == 'e'), 'e')
    col_n = next((c for c in df_csv.columns if c.strip().lower() == 'n'), 'n')
    col_h = next((c for c in df_csv.columns if c.strip().lower() == 'h'), 'h')
    
    h_original_csv = float(df_csv.loc[0, col_h])

    # Si se subió un PDF y no se ha procesado aún en esta sesión
    if pdf_file and st.session_state.pdf_procesado != pdf_file.name:
        datos_pdf = extraer_datos_pdf(pdf_file)
        
        st.session_state.e_val = datos_pdf['e'] if datos_pdf['e'] else 0.0
        st.session_state.n_val = datos_pdf['n'] if datos_pdf['n'] else 0.0
        
        # Validación inteligente de Altura (Geoide EGM08 vs Elipsoide)
        h_orto = datos_pdf['h_orto']
        h_elip = datos_pdf['h_elip']
        
        d_orto = abs(h_orto - h_original_csv) if h_orto else float('inf')
        d_elip = abs(h_elip - h_original_csv) if h_elip else float('inf')
        
        if d_orto < d_elip:
            st.session_state.h_val = h_orto
            st.session_state.tipo_h = ("Ortométrica", d_orto, h_elip, d_elip)
        else:
            st.session_state.h_val = h_elip
            st.session_state.tipo_h = ("Elipsoidal", d_elip, h_orto, d_orto)
            
        st.session_state.pdf_resumen = datos_pdf
        st.session_state.pdf_procesado = pdf_file.name

# --- MOSTRAR RESUMEN DEL PDF Y ADVERTENCIAS ---
if pdf_file and 'pdf_resumen' in st.session_state:
    res = st.session_state.pdf_resumen
    st.markdown("### 📄 Resumen del Procesamiento Leica")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Solución", res['fijo'])
    c2.metric("Precisión (CQ 2D / 3D)", f"{res['cq2d']}m / {res['cq3d']}m")
    c3.metric("Línea Base (Dist. a ERP)", f"{res['dist']} m")
    c4.metric("Tiempo de Lectura", res['duracion'])
    
    st.write(f"**Fecha y Hora:** {res['fecha']} | **Antena/Equipo usado:** {res['antena']}")
    
    # Alerta del Geoide / Altura
    if 'tipo_h' in st.session_state and df_csv is not None:
        tipo_select, delta_select, h_otra, delta_otra = st.session_state.tipo_h
        
        st.info(f"📏 **Análisis de Altura:** El CSV original tiene una cota de **{h_original_csv:.4f}m**. El sistema seleccionó automáticamente la **Altura {tipo_select}** del PDF con una diferencia de ajuste de **{delta_select:.4f}m**.")
        
        if delta_select > 40:
            st.error(f"🚨 **ADVERTENCIA DE DESFASE EXCESIVO:** La diferencia de altura es mayor a 40m ({delta_select:.2f}m). Verifica si el colector en campo usó un modelo geoidal distinto al del procesamiento en oficina. (Posible desfase EGM08 vs Elipsoide WGS84).")

st.markdown("---")
st.markdown("### 🎯 Coordenadas de Corrección")
st.write("Verifica o introduce manualmente las coordenadas procesadas. (Si subiste el PDF, ya están llenas).")

col_input1, col_input2, col_input3 = st.columns(3)
with col_input1: e_ingresado = st.number_input("Este (E)", value=st.session_state.e_val, format="%.4f", step=0.0001)
with col_input2: n_ingresado = st.number_input("Norte (N)", value=st.session_state.n_val, format="%.4f", step=0.0001)
with col_input3: h_ingresado = st.number_input("Cota (Z)", value=st.session_state.h_val, format="%.4f", step=0.0001)

# --- PROCESAMIENTO FINAL ---
if st.button("⚡ Aplicar Corrección y Generar CSV", type="primary") and df_csv is not None:
    e_base_orig = float(df_csv.loc[0, col_e])
    n_base_orig = float(df_csv.loc[0, col_n])
    h_base_orig = float(df_csv.loc[0, col_h])
    
    dE = e_ingresado - e_base_orig
    dN = n_ingresado - n_base_orig
    dH = h_ingresado - h_base_orig
    
    df_proc = df_csv.copy()
    df_proc[col_e] = (df_proc[col_e] + dE).round(4)
    df_proc[col_n] = (df_proc[col_n] + dN).round(4)
    df_proc[col_h] = (df_proc[col_h] + dH).round(4)
    
    # Ajuste de observación a 65
    col_obs = next((c for c in df_proc.columns if 'observaci' in c.lower()), None)
    if col_obs:
        df_proc.loc[1:, col_obs] = 65

    st.success(f"✅ Deltas aplicados correctamente: dE = {dE:+.4f} m | dN = {dN:+.4f} m | dZ = {dH:+.4f} m")

    # Archivos para descargar
    nombre_csv = csv_file.name
    if re.search(r'NATIV[OA]', nombre_csv, re.IGNORECASE):
        name_corr = re.sub(r'NATIV[OA]', 'CORREGIDA', nombre_csv, flags=re.IGNORECASE)
        name_pol = re.sub(r'NATIV[OA]', 'POLIGONO', nombre_csv, flags=re.IGNORECASE)
    else:
        name_corr = f"{nombre_csv.replace('.csv', '')}_CORREGIDA.csv"
        name_pol = f"{nombre_csv.replace('.csv', '')}_POLIGONO.csv"

    csv_out_corr = df_proc.to_csv(index=False).encode('utf-8')
    cols_pol_target = ['nombre', 'e', 'n', 'h', 'código', 'codigo']
    cols_presentes = [c for c in df_proc.columns if c.strip().lower() in cols_pol_target]
    csv_out_pol = df_proc[cols_presentes].to_csv(index=False).encode('utf-8')
    
    st.markdown("### 📥 Descargas Listas")
    b1, b2 = st.columns(2)
    with b1: st.download_button("Descargar CSV Completo (CORREGIDA)", data=csv_out_corr, file_name=name_corr, mime="text/csv")
    with b2: st.download_button("Descargar CSV Reducido (POLIGONO)", data=csv_out_pol, file_name=name_pol, mime="text/csv")
elif st.button("⚡ Aplicar Corrección y Generar CSV") and df_csv is None:
    st.error("Sube primero el archivo CSV Nativo para poder procesarlo.")