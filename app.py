# app.py — Calidad del Aire Chile (OpenAQ)
import os, io, time
import requests
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(page_title="Calidad del Aire Chile (OpenAQ)", layout="wide")

# ===== Configuración =====
API_BASE = "https://api.openaq.org/v3"
API_KEY = st.secrets.get("OPENAQ_API_KEY", os.environ.get("OPENAQ_API_KEY", ""))
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}
st.sidebar.info(f"API key cargada: {bool(API_KEY)} — largo: {len(API_KEY)}")
PARAMETERS = [
    {"name": "pm25", "id": 2, "units": "µg/m³"},
    {"name": "pm10", "id": 1, "units": "µg/m³"},
    {"name": "o3",   "id": 10, "units": "ppm"},
    {"name": "no2",  "id": 7,  "units": "ppm"},
    {"name": "so2",  "id": 9,  "units": "ppm"},
    {"name": "co",   "id": 8,  "units": "ppm"},
]

def need_key():
    if not API_KEY:
        st.error("Falta la API key de OpenAQ. Ve a Manage app → Secrets y agrega:\n\nOPENAQ_API_KEY = \"TU_API_KEY\"")
        st.stop()

def _get(url, params=None, timeout=30, retries=3):
    need_key()
    last = None
    for _ in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, params=params or {}, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            time.sleep(1.2)
    raise RuntimeError(f"Falla GET {url}: {last}")

@st.cache_data(ttl=3600)
def list_locations(country_code="CL", parameter_id=2, limit=2000):
    url = f"{API_BASE}/locations"
    data = _get(url, params={"country": country_code, "limit": limit})
    rows = []
    for loc in data.get("results", []):
        coords = loc.get("coordinates") or {}
        sensors = [s for s in loc.get("sensors", []) if s.get("parameter", {}).get("id") == parameter_id]
        rows.append({
            "location_id": loc["id"],
            "name": loc.get("name"),
            "locality": loc.get("locality"),
            "provider": (loc.get("provider") or {}).get("name"),
            "owner": (loc.get("owner") or {}).get("name"),
            "lat": coords.get("latitude"),
            "lon": coords.get("longitude"),
            "timezone": loc.get("timezone"),
            "sensors": sensors,
        })
    return pd.DataFrame(rows)

@st.cache_data(ttl=3600)
def sensors_by_location(location_id):
    url = f"{API_BASE}/locations/{location_id}/sensors"
    data = _get(url)
    return pd.DataFrame(data.get("results", []))

@st.cache_data(ttl=1800)
def fetch_days(sensor_id, date_from, date_to):
    url = f"{API_BASE}/sensors/{sensor_id}/days"
    params = {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "limit": 10000}
    data = _get(url, params=params)
    rows = []
    for r in data.get("results", []):
        dt = r["period"]["datetimeFrom"]["utc"]
        rows.append({"date_utc": dt, "value": r["value"]})
    d = pd.DataFrame(rows)
    if not d.empty:
        d["Fecha"] = pd.to_datetime(d["date_utc"]).dt.tz_convert(None)
        d = d.drop(columns=["date_utc"]).sort_values("Fecha")
    return d

def main():
    st.title("Calidad del Aire • Chile (OpenAQ)")
    st.caption("Fuentes: OpenAQ v3 (incluye datos de SINCA y otras redes).")

    # Controles
    col1, col2, col3 = st.columns([1,1,2])
    with col1:
        pname = st.selectbox("Parámetro", [p["name"] for p in PARAMETERS], index=0)
        pinfo = next(p for p in PARAMETERS if p["name"] == pname)
    with col2:
        hoy = datetime.utcnow().date()
        fecha_ini = st.date_input("Desde", hoy - timedelta(days=60))
        fecha_fin = st.date_input("Hasta", hoy)
        if fecha_ini > fecha_fin:
            st.error("La fecha 'Desde' no puede ser mayor que 'Hasta'.")
            st.stop()
    with col3:
        st.info("Tip: selecciona 1–3 estaciones para un gráfico más claro.")

    # Estaciones
    with st.spinner("Cargando estaciones..."):
        df_loc = list_locations("CL", pinfo["id"])
    if df_loc.empty:
        st.warning("No se encontraron estaciones para ese parámetro en Chile.")
        st.stop()

    df_loc["etiqueta"] = df_loc.apply(
        lambda r: f"{r['name']} – {r['locality'] or 's/n'} (id {r['location_id']})", axis=1
    )
    default_sel = df_loc["etiqueta"].tolist()[:2]
    sel = st.multiselect("Estaciones disponibles", options=df_loc["etiqueta"].tolist(), default=default_sel)

    if not sel:
        st.warning("Selecciona al menos una estación.")
        st.stop()

    # Serie diaria por estación (promedio de sensores del mismo parámetro)
    all_series = []
    with st.spinner("Descargando series diarias..."):
        for etiqueta in sel:
            loc_id = int(etiqueta.split("id")[-1].strip(") ").strip())
            df_sens = sensors_by_location(loc_id)
            df_sens = df_sens[df_sens["parameter"].apply(lambda x: x.get("id") == pinfo["id"])]

            series_loc = []
            for _, s in df_sens.iterrows():
                sid = int(s["id"])
                dfd = fetch_days(sid, pd.to_datetime(fecha_ini), pd.to_datetime(fecha_fin))
                if not dfd.empty:
                    dfd = dfd.rename(columns={"value": f"sensor_{sid}"}).set_index("Fecha")
                    series_loc.append(dfd)

            if series_loc:
                merged = pd.concat(series_loc, axis=1).mean(axis=1).to_frame(name=etiqueta)
                merged.reset_index(inplace=True)
                all_series.append(merged)

    if not all_series:
        st.error("No hay datos diarios en el rango seleccionado para las estaciones escogidas.")
        st.stop()

    df_final = all_series[0]
    for extra in all_series[1:]:
        df_final = df_final.merge(extra, on="Fecha", how="outer")
    df_final = df_final.sort_values("Fecha")

    # KPIs
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
    ax.set_title(f"Serie diaria {pname.upper()} – Chile (OpenAQ)")
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
    st.markdown("**Fuente:** OpenAQ v3 (incluye redes como SINCA).")
    st.markdown("Docs: Locations / Sensors / Measurements Days.")
    st.caption("Recuerda configurar tu API key en Secrets como OPENAQ_API_KEY.")

if __name__ == "__main__":
    main()
