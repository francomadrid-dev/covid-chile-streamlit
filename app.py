# app.py — Calidad del Aire (Open-Meteo, sin API key)
import requests
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(page_title="Calidad del Aire Chile • Open-Meteo", layout="wide")

# Ciudades chilenas comunes (lat, lon)
CITIES = {
    "Santiago": (-33.45, -70.66),
    "Valparaíso": (-33.047, -71.612),
    "Concepción": (-36.827, -73.050),
    "La Serena": (-29.904, -71.249),
    "Antofagasta": (-23.650, -70.400),
    "Temuco": (-38.739, -72.598),
    "Puerto Montt": (-41.471, -72.936),
}

PARAMS = {
    "pm2_5": "µg/m³",
    "pm10": "µg/m³",
    "ozone": "µg/m³",     # Open-Meteo entrega O3 en µg/m³
    "nitrogen_dioxide": "µg/m³",
    "sulphur_dioxide": "µg/m³",
    "carbon_monoxide": "µg/m³",
}

API = "https://air-quality-api.open-meteo.com/v1/air-quality"

def fetch_hourly(lat, lon, param_list, start, end):
    """Descarga serie HORARIA y devuelve dataframe con columnas por parámetro."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(param_list),
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "timezone": "auto",
    }
    r = requests.get(API, params=params, timeout=30)
    r.raise_for_status()
    j = r.json()
    if "hourly" not in j or "time" not in j["hourly"]:
        return pd.DataFrame()
    df = pd.DataFrame(j["hourly"])
    df["time"] = pd.to_datetime(df["time"])
    df = df.rename(columns={"time": "FechaHora"})
    return df

def hourly_to_daily(df_hourly):
    """Agrega a promedio DIARIO."""
    if df_hourly.empty:
        return pd.DataFrame()
    df = df_hourly.copy()
    df["Fecha"] = df["FechaHora"].dt.date
    # promedios diarios para todas las columnas numéricas
    num_cols = df.select_dtypes("number").columns
    d = df.groupby("Fecha")[num_cols].mean().reset_index()
    d["Fecha"] = pd.to_datetime(d["Fecha"])
    return d.sort_values("Fecha")

def main():
    st.title("Calidad del Aire • Chile (Open-Meteo)")
    st.caption("Fuente: Open-Meteo Air Quality API (PM2.5, PM10, O₃, NO₂, SO₂, CO) — se agrega a promedio diario en la app.")

    col1, col2, col3 = st.columns([1,1,2])
    with col1:
        city = st.selectbox("Ciudad", list(CITIES.keys()), index=0)
        lat, lon = CITIES[city]
    with col2:
        hoy = datetime.utcnow().date()
        start = st.date_input("Desde", hoy - timedelta(days=30))
        end = st.date_input("Hasta", hoy)
        if start > end:
            st.error("La fecha 'Desde' no puede ser mayor que 'Hasta'.")
            st.stop()
    with col3:
        pnames = list(PARAMS.keys())
        sel_params = st.multiselect("Parámetros", pnames, default=["pm2_5","pm10"])
        st.info("Tip: selecciona 1–3 para un gráfico más claro.")

    if not sel_params:
        st.warning("Selecciona al menos un parámetro.")
        st.stop()

    with st.spinner("Descargando serie horaria..."):
        df_hourly = fetch_hourly(lat, lon, sel_params, pd.to_datetime(start), pd.to_datetime(end))

    if df_hourly.empty:
        st.error("No se obtuvieron datos para ese rango. Prueba otra ciudad o fechas.")
        st.stop()

    df_daily = hourly_to_daily(df_hourly)

    # KPIs (si hay columnas seleccionadas)
    kcols = st.columns(min(3, len(sel_params)))
    for i, p in enumerate(sel_params[:3]):
        ultimo = df_daily[p].dropna().iloc[-1] if not df_daily[p].dropna().empty else float("nan")
        prom7 = df_daily[p].tail(7).mean()
        kcols[i].metric(f"{p} (últ. día)", f"{ultimo:.1f} {PARAMS[p]}", f"7d: {prom7:.1f}")

    # Gráfico
    fig, ax = plt.subplots(figsize=(10,5))
    for p in sel_params:
        ax.plot(df_daily["Fecha"], df_daily[p], label=p)
    ax.set_title(f"{city}: promedio diario de calidad del aire")
    ax.set_xlabel("Fecha")
    ax.set_ylabel("Concentración")
    ax.legend(loc="upper left", fontsize=8)
    plt.xticks(rotation=45)
    st.pyplot(fig, clear_figure=True)

    st.subheader("Datos diarios")
    st.dataframe(df_daily[["Fecha"]+sel_params], use_container_width=True)

    csv = df_daily[["Fecha"]+sel_params].to_csv(index=False).encode("utf-8")
    st.download_button("Descargar CSV", data=csv, file_name=f"aire_{city}_{start}_{end}.csv", mime="text/csv")

    st.markdown("---")
    st.markdown("**Notas:**")
    st.markdown("- Fuente: Open-Meteo Air Quality (sin API key).")
    st.markdown("- La API entrega datos **horarios**; aquí se agregan a **promedio diario**.")
    st.markdown("- Parámetros disponibles: PM2.5, PM10, ozone, nitrogen_dioxide, sulphur_dioxide, carbon_monoxide.")

if __name__ == "__main__":
    main()
