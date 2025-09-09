# app.py — Calidad del Aire Chile (OpenAQ v2, sin API key)
import io, time, os
import requests
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(page_title="Calidad del Aire Chile (OpenAQ v2)", layout="wide")

API_V2 = "https://api.openaq.org/v2"

PARAMETERS = [
    {"name": "pm25", "units": "µg/m³"},
    {"name": "pm10", "units": "µg/m³"},
    {"name": "o3",   "units": "ppm"},
    {"name": "no2",  "units": "ppm"},
    {"name": "so2",  "units": "ppm"},
    {"name": "co",   "units": "ppm"},
]

def _get(url, params=None, timeout=30, retries=3):
    last = None
    for _ in range(retries):
        try:
            r = requests.get(url, params=params or {}, timeout=timeout)
            if r.status_code >= 400:
                st.error(f"Error {r.status_code} en {url}\n\nParams={params}\n\n{r.text[:300]}")
                r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(1.2)
    raise RuntimeError(f"Falla GET {url}: {last}")

@st.cache_data(ttl=3600)
def list_locations_v2(country="CL", parameter="pm25", limit=2000):
    """
    Devuelve estaciones de OpenAQ v2 para un país y parámetro.
    """
    url = f"{API_V2}/locations"
    data = _get(url, params={
        "country": country,
        "parameter": parameter,
        "limit": limit,
        "order_by": "location",
        "sort": "asc",
    })
    rows = []
    for loc in data.get("results", []):
        coords = loc.get("coordinates") or {}
        rows.append({
            "location_id": loc.get("id"),
            "name": loc.get("name"),
            "city": loc.get("city"),
            "provider": loc.get("provider"),
            "lat": coords.get("latitude"),
            "lon": coords.get("longitude"),
        })
    return pd.DataFrame(rows)

@st.cache_data(ttl=1800)
def fetch_measurements_daily_v2(location_id, parameter, date_from, date_to):
    """
    Descarga mediciones v2 y agrega promedio diario.
    """
    url = f"{API_V2}/measurements"
    # pedimos bastante por si acaso; v2 pagina, pero para 30–60 días suele bastar
    data = _get(url, params={
        "location_id": location_id,
        "parameter": parameter,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "limit": 10000,
        "order_by": "datetime",
        "sort": "asc",
    })
    rs = data.get("results", [])
    if not rs:
        return pd.DataFrame(columns=["Fecha", "valor"])
    df = pd.DataFrame([{
        "Fecha": pd.to_datetime(r["date"]["utc"]),
        "valor": r.get("value")
    } for r in rs])
    # Pasamos a zona naïve y agregamos por día (promedio)
    df["Fecha"] = df["Fecha"].dt.tz_convert(None)
    d = df.groupby(df["Fecha"].dt.date)["valor"].mean().reset_index()
    d["Fecha"] = pd.to_datetime(d["Fecha"])
    return d.sort_values("Fecha")

def main():
    st.title("Calidad del Aire • Chile (OpenAQ v2)")
    st.caption("Datos desde OpenAQ v2 (no requiere API key). Parámetros: PM2.5, PM10, O₃, NO₂, SO₂, CO.")

    # Controles
    col1, col2, col3 = st.columns([1,1,2])
    with col1:
        pname = st.selectbox("Parámetro", [p["name"] for p in PARAMETERS], index=0)
        pinfo = next(p for p in PARAMETERS if p["name"] == pname)
    with col2:
        hoy = datetime.utcnow().date()
        fecha_ini = st.date_input("Desde", hoy - timedelta(days=30))
        fecha_fin = st.date_input("Hasta", hoy)
        if fecha_ini > fecha_fin:
            st.error("La fecha 'Desde' no puede ser mayor que 'Hasta'.")
            st.stop()
    with col3:
        st.info("Tip: selecciona 1–3 estaciones para un gráfico más claro.")

    # Estaciones
    with st.spinner("Cargando estaciones..."):
        df_loc = list_locations_v2("CL", pname)
    if df_loc.empty:
        st.warning("No se encontraron estaciones en Chile para ese parámetro.")
        st.stop()

    df_loc["etiqueta"] = df_loc.apply(
        lambda r: f"{r['name']} — {r['city'] or 's/n'} (id {r['location_id']})", axis=1
    )
    sel = st.multiselect("Estaciones disponibles", options=df_loc["etiqueta"].tolist(),
                         default=df_loc["etiqueta"].tolist()[:2])

    if not sel:
        st.warning("Selecciona al menos una estación.")
        st.stop()

    # Series por estación
    all_series = []
    with st.spinner("Descargando mediciones y agregando diario..."):
        for etiqueta in sel:
            loc_id = int(etiqueta.split("id")[-1].strip(") ").strip())
            dfd = fetch_measurements_daily_v2(loc_id, pname, pd.to_datetime(fecha_ini), pd.to_datetime(fecha_fin))
            if not dfd.empty:
                dfd = dfd.rename(columns={"valor": etiqueta})
                all_series.append(dfd)

    if not all_series:
        st.error("No hay datos en el rango seleccionado para las estaciones escogidas.")
        st.stop()

    df_final = all_series[0]
    for extra in all_series[1:]:
        df_final = df_final.merge(extra, on="Fecha", how="outer")
    df_final = df_final.sort_values("Fecha")

    # KPIs simples
    k1, k2, k3 = st.columns(3)
    ultimo = df_final.dropna().iloc[-1, 1:].mean()
    prom_7 = df_final.tail(7).dropna().iloc[:,1:].mean().mean()
    prom_30 = df_final.tail(30).dropna().iloc[:,1:].mean().mean()
    k1.metric(f"Último día ({pname})", f"{ultimo:.2f} {pinfo['units']}")
    k2.metric("Promedio 7 días", f"{prom_7:.2f} {pinfo['units']}")
    k3.metric("Promedio 30 días", f"{prom_30:.2f} {pinfo['units']}")

    # Gráfico
    fig, ax = plt.subplots(figsize=(10,5))
    for col in df_final.columns[1:]:
        ax.plot(df_final["Fecha"], df_final[col], label=col)
    ax.set_title(f"Serie diaria {pname.upper()} – Chile (OpenAQ v2)")
    ax.set_xlabel("Fecha")
    ax.set_ylabel(f"{pname} ({pinfo['units']})")
    ax.legend(loc="upper left", fontsize=8)
    plt.xticks(rotation=45)
    st.pyplot(fig, clear_figure=True)

    st.subheader("Datos (promedio diario por estación seleccionada)")
    st.dataframe(df_final, use_container_width=True)

    csv = df_final.to_csv(index=False).encode("utf-8")
    st.download_button("Descargar CSV", data=csv, file_name="calidad_aire_chile_diario.csv", mime="text/csv")

    st.markdown("---")
    st.markdown("**Fuente:** OpenAQ v2 — /locations y /measurements. Agregación diaria calculada en la app.")
    st.caption("Si luego quieres volver a v3 con tu API key, lo cambiamos sin problema.")

if __name__ == "__main__":
    main()
