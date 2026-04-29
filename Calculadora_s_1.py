import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import math
import random
import base64
from streamlit_gsheets import GSheetsConnection

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="SW Calculator", layout="centered")

# --- CONSTANTES ---
URL_SHEET = "https://docs.google.com/spreadsheets/d/1phPfVZrXO3reP4xoeltILvOIRmNMqhS4aQz4-601_Pk/edit?usp=sharing"
START_NORMAL, END_NORMAL = time(9, 30), time(18, 30)
START_FRI, END_FRI = time(9, 0), time(15, 30)
LUNCH_START, LUNCH_END = time(13, 30), time(14, 30)

reco_reco = [
    "RWwgZXF1aWxpYnJpbyBlbiBsYSBjYXJnYSBkZSB0cmFiYWpvIGVzIGxhIGJhc2UgZGUgdW4gZXF1aXBvIHNvc3RlbmlibGUu",
    "UGxhbmlmaWNhciBiaWVuIGhveSBldml0YSBjcmlzaXMgbWHDsWFuYS4=",
    "QXNpZ25hciBjb24gY3JpdGVyaW8gcG90ZW5jaWEgZWwgdGFsZW50byBkZWwgZXF1aXBvLg=="
]

def calculo_feriados(txt_base64):
    return base64.b64decode(txt_base64).decode('utf-8')

def redondear_a_media_hora(dt):
    minutos = dt.minute
    if minutos < 15: return dt.replace(minute=0, second=0, microsecond=0)
    elif minutos < 45: return dt.replace(minute=30, second=0, microsecond=0)
    else: return (dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

@st.cache_data
def cargar_datos():
    conn = st.connection("gsheets", type=GSheetsConnection)
    df = conn.read(spreadsheet=URL_SHEET, worksheet="1594771444")
    
    feriados = {
        'CL': pd.to_datetime(df.iloc[:, 0].dropna(), dayfirst=True).dt.date.tolist(),
        'MX': pd.to_datetime(df.iloc[:, 2].dropna(), dayfirst=True).dt.date.tolist(),
        'AR': pd.to_datetime(df.iloc[:, 1].dropna(), dayfirst=True).dt.date.tolist()
    }
    
    df_staff = df.iloc[:, [17, 19, 20, 21]].copy()
    df_staff.columns = ['Nombre', 'Rol', 'Pais', 'Estatus']
    df_activo = df_staff[df_staff['Estatus'].astype(str).str.upper() == 'YES'].dropna(subset=['Nombre'])
    
    df_idiomas = df.iloc[:, [4, 5, 6, 7, 8, 9]].copy()
    df_idiomas.columns = ['Nombre', 'H_Ini', 'H_Fin', 'Dias', 'F_Ini', 'F_Fin']
    df_idiomas = df_idiomas.dropna(subset=['Nombre', 'Dias'])

    placeholder = "Seleccione un colaborador"
    lista_sw = [placeholder] + sorted(df_activo[df_activo['Rol'].astype(str).str.upper() == 'SW']['Nombre'].tolist())
    lista_qa = [placeholder] + sorted(df_activo[df_activo['Rol'].astype(str).str.upper() == 'QA']['Nombre'].tolist())
    
    return lista_sw, lista_qa, feriados, df_activo, df_idiomas

def normalizar_hora(t):
    if isinstance(t, time): return t
    if isinstance(t, datetime): return t.time()
    if isinstance(t, str):
        try: return datetime.strptime(t, "%H:%M:%S").time()
        except: return datetime.strptime(t, "%H:%M").time()
    return t

def obtener_clase_hoy(fecha_dt, nombre, df_idiomas):
    if not nombre or nombre == "Seleccione un colaborador": return None, None
    clases = df_idiomas[df_idiomas['Nombre'] == nombre]
    dias_map = {"lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2, "jueves": 3, "viernes": 4}
    
    for _, clase in clases.iterrows():
        f_ini = pd.to_datetime(clase['F_Ini']).date()
        f_fin = pd.to_datetime(clase['F_Fin']).date()
        if f_ini <= fecha_dt.date() <= f_fin:
            if any(d for d, n in dias_map.items() if d in str(clase['Dias']).lower() and n == fecha_dt.weekday()):
                return normalizar_hora(clase['H_Ini']), normalizar_hora(clase['H_Fin'])
    return None, None

def calcular_entrega(fecha_inicio, horas_objetivo, lista_feriados, nombre_sw, nombre_qa, df_idiomas, es_segunda_mitad):
    fecha_actual = fecha_inicio
    horas_restantes = float(horas_objetivo)
    feriado_det, clase_sw_det, clase_qa_det = False, False, False

    while horas_restantes > 0:
        # 1. Fin de semana y Feriados
        if fecha_actual.weekday() >= 5 or fecha_actual.date() in lista_feriados:
            if fecha_actual.date() in lista_feriados: feriado_det = True
            fecha_actual = (fecha_actual + timedelta(days=1)).replace(hour=9, minute=30, second=0)
            continue

        # 2. Definir jornada
        es_viernes = fecha_actual.weekday() == 4
        es_verano = 1 <= fecha_actual.month <= 9
        h_ini_lab, h_fin_lab = (START_FRI, END_FRI) if (es_viernes and es_verano) else (START_NORMAL, END_NORMAL)
        
        inicio_j = datetime.combine(fecha_actual.date(), h_ini_lab)
        fin_j = datetime.combine(fecha_actual.date(), h_fin_lab)
        
        if fecha_actual < inicio_j: fecha_actual = inicio_j
        if fecha_actual >= fin_j:
            fecha_actual = (fecha_actual + timedelta(days=1)).replace(hour=9, minute=30, second=0)
            continue

        # 3. Almuerzo
        alm_ini = datetime.combine(fecha_actual.date(), LUNCH_START)
        alm_fin = datetime.combine(fecha_actual.date(), LUNCH_END)
        if alm_ini <= fecha_actual < alm_fin:
            fecha_actual = alm_fin
            continue

        # 4. Clases SW (Siempre) y QA (Solo si es >= 50% del proyecto)
        hitos_clases = []
        
        # Clase SW
        sw_h_ini, sw_h_fin = obtener_clase_hoy(fecha_actual, nombre_sw, df_idiomas)
        if sw_h_ini:
            c_ini_sw = datetime.combine(fecha_actual.date(), sw_h_ini)
            c_fin_sw = datetime.combine(fecha_actual.date(), sw_h_fin)
            if c_ini_sw <= fecha_actual < c_fin_sw:
                clase_sw_det = True
                fecha_actual = c_fin_sw
                continue
            elif fecha_actual < c_ini_sw: hitos_clases.append(c_ini_sw)

        # Clase QA (Solo aplica si estamos en la segunda mitad del tiempo del proyecto)
        if es_segunda_mitad:
            qa_h_ini, qa_h_fin = obtener_clase_hoy(fecha_actual, nombre_qa, df_idiomas)
            if qa_h_ini:
                c_ini_qa = datetime.combine(fecha_actual.date(), qa_h_ini)
                c_fin_qa = datetime.combine(fecha_actual.date(), qa_h_fin)
                if c_ini_qa <= fecha_actual < c_fin_qa:
                    clase_qa_det = True
                    fecha_actual = c_fin_qa
                    continue
                elif fecha_actual < c_ini_qa: hitos_clases.append(c_ini_qa)

        # 5. Próximo Hito
        hitos_posibles = [fin_j]
        if fecha_actual < alm_ini: hitos_posibles.append(alm_ini)
        hitos_posibles.extend(hitos_clases)
        
        prox_hito = min(hitos_posibles)
        disponible = (prox_hito - fecha_actual).total_seconds() / 3600

        if horas_restantes <= disponible:
            res = fecha_actual + timedelta(hours=horas_restantes)
            return redondear_a_media_hora(res), feriado_det, clase_sw_det, clase_qa_det
        else:
            horas_restantes -= disponible
            fecha_actual = prox_hito
            
    return redondear_a_media_hora(fecha_actual), feriado_det, clase_sw_det, clase_qa_det

# --- INTERFAZ ---
st.title("🗓️ SW Calculator IIS - Latam🧮")

try:
    lista_sw, lista_qa, todos_feriados, df_staff, df_idiomas = cargar_datos()

    col_a, col_b = st.columns(2)
    with col_a: nombre_dev = st.selectbox("Seleccionar SW", lista_sw)
    with col_b: nombre_qa = st.selectbox("Seleccionar QA", lista_qa)

    c1, c2, c3 = st.columns([2, 1, 1])
    f_inicio = c1.date_input("Fecha Inicio", datetime.now(), format="DD/MM/YYYY")
    h_inicio = c2.time_input("Hora Inicio", time(9, 30), step=1800)
    horas_totales = c3.number_input("Horas Proyecto", min_value=1, value=8)

    if st.button("🚀 Generar Cronograma", use_container_width=True):
        if nombre_dev != "Seleccione un colaborador":
            pais = df_staff[df_staff['Nombre'] == nombre_dev]['Pais'].values[0]
            dt_inicio = datetime.combine(f_inicio, h_inicio)
            
            # Hitos: Feedback(25%), Materiales(50%), Dummy(75%), 1st Link(100%)
            hitos_dict = {"Feedback": 0.25, "Materiales": 0.50, "Dummy": 0.75, "1st Link": 1.00}
            
            fechas_finales, f_fnd, sw_c_fnd, qa_c_fnd = [], False, False, False

            for h, p in hitos_dict.items():
                # Regla: QA solo cuenta desde el 50% en adelante
                es_2da_mitad = (p >= 0.50)
                
                # Cálculo de horas para este hito
                h_obj = min(horas_totales * p, 8.0) if h == "Feedback" else horas_totales * p
                
                res, f, c_sw, c_qa = calcular_entrega(
                    dt_inicio, h_obj, todos_feriados.get(pais, []), 
                    nombre_dev, nombre_qa, df_idiomas, es_2da_mitad
                )
                
                fechas_finales.append(res.strftime("%d-%m-%Y %H:%M"))
                if f: f_fnd = True
                if c_sw: sw_c_fnd = True
                if c_qa: qa_c_fnd = True

            # Mostrar Advertencias
            if f_fnd: st.warning(f"📌 Feriado detectado en {pais}. Tiempos ajustados.")
            if sw_c_fnd: st.info(f"📚 Clase de idiomas del SW ({nombre_dev}) detectada y ajustada.")
            if qa_c_fnd: st.info(f"🔍 Clase de idiomas del QA ({nombre_qa}) detectada y ajustada (Solo >50% del proyecto).")

            st.table(pd.DataFrame([fechas_finales], columns=hitos_dict.keys()))
            st.text_area("Copia rápida:", value="\n".join(fechas_finales))

    st.markdown("---")
    if st.button("v1.4 - IIS Latam SW Team", type="secondary"):
        st.info(calculo_feriados(random.choice(reco_reco)))

except Exception as e:
    st.error(f"Error crítico: {e}")