
import io
import requests
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st

st.set_page_config(page_title="COVID-19 Chile - Dataviz", page_icon="🦠", layout="wide")

DATA_URL = "https://raw.githubusercontent.com/MinCiencia/Datos-COVID19/master/output/producto3/CasosTotalesCumulativos.csv"

@st.cache_data(ttl=60*60)
def load_data():
    # Descarga y carga en memoria sin depender del disco
    resp = requests.get(DATA_URL, timeout=30)
    resp.raise_for_status()
    raw = io.BytesIO(resp.content)
    df = pd.read_csv(raw)
    # Limpieza básica
    if "Codigo comuna" in df.columns:
        df = df.drop(columns=["Codigo comuna"])
    # Convertir a formato largo
    df = df.melt(id_vars=["Region", "Comuna"], var_name="Fecha", value_name="Casos")
    # Manejo de fechas y numéricos
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce")
    df = df.dropna(subset=["Fecha"])
    df["Casos"] = pd.to_numeric(df["Casos"], errors="coerce").fillna(0).astype(int)
    # Orden
    df = df.sort_values(["Region", "Comuna", "Fecha"]).reset_index(drop=True)
    return df

def compute_daily(df_filtrado):
    # Calcula casos diarios a partir de acumulados
    dfd = df_filtrado.copy()
    dfd["Nuevos"] = dfd.groupby(["Region", "Comuna"])["Casos"].diff().fillna(0).clip(lower=0).astype(int)
    return dfd

def kpi_block(df_filtrado):
    latest = df_filtrado["Fecha"].max()
    last_val = int(df_filtrado.loc[df_filtrado["Fecha"] == latest, "Casos"].sum())
    # crecimiento últimos 7 días (si existen)
    seven_days_before = latest - pd.Timedelta(days=7)
    prev = int(df_filtrado[df_filtrado["Fecha"] <= seven_days_before].groupby("Comuna")["Casos"].last().sum() if not df_filtrado[df_filtrado["Fecha"] <= seven_days_before].empty else 0)
    delta = last_val - prev
    # número de comunas seleccionadas
    n_comunas = df_filtrado["Comuna"].nunique()
    c1, c2, c3 = st.columns(3)
    c1.metric("Casos acumulados", f"{last_val:,}".replace(",", "."), delta=f"{delta:+,}".replace(",", "."))
    c2.metric("Comunas seleccionadas", f"{n_comunas}")
    c3.metric("Última fecha", latest.strftime("%Y-%m-%d"))

def main():
    st.title("📊 COVID-19 en Chile por Comuna")
    st.caption("Fuente: Ministerio de Ciencia (Repositorio COVID-19). App educativa para análisis y visualización.")

    with st.spinner("Descargando y preparando datos..."):
        df = load_data()

    # --- Sidebar de filtros
    st.sidebar.header("Filtros")
    regiones = sorted(df["Region"].dropna().unique().tolist())
    region_sel = st.sidebar.multiselect("Región", regiones, default=[])

    df_reg = df[df["Region"].isin(region_sel)] if region_sel else df.copy()
    comunas = sorted(df_reg["Comuna"].dropna().unique().tolist())
    comuna_sel = st.sidebar.multiselect("Comuna", comunas, default=comunas[:1] if comunas else [])

    # Rango de fechas
    if not df_reg.empty:
        min_date = df_reg["Fecha"].min()
        max_date = df_reg["Fecha"].max()
    else:
        min_date = pd.Timestamp("2020-03-01")
        max_date = pd.Timestamp.today().normalize()
    fecha_ini, fecha_fin = st.sidebar.date_input("Rango de fechas", (min_date.date(), max_date.date()))

    # Subset final
    mask = (df_reg["Comuna"].isin(comuna_sel)) & (df_reg["Fecha"].between(pd.to_datetime(fecha_ini), pd.to_datetime(fecha_fin)))
    df_view = df_reg[mask].copy()

    if df_view.empty:
        st.warning("No hay datos para los filtros seleccionados. Ajusta Región/Comuna/Fechas.")
        return

    # KPIs
    kpi_block(df_view)

    # Tabs
    tab1, tab2, tab3 = st.tabs(["Evolución acumulada", "Casos diarios", "Top comunas (por región)"])

    with tab1:
        st.subheader("Serie temporal - Casos acumulados")
        fig1, ax1 = plt.subplots()
        for comuna, dfg in df_view.groupby("Comuna"):
            ax1.plot(dfg["Fecha"], dfg["Casos"], marker="o", linewidth=1, label=str(comuna))
        ax1.set_xlabel("Fecha")
        ax1.set_ylabel("Casos acumulados")
        ax1.set_title("Evolución de casos acumulados")
        ax1.tick_params(axis="x", rotation=45)
        ax1.legend(loc="best", fontsize=8)
        st.pyplot(fig1, clear_figure=True)

        st.download_button(
            "Descargar datos filtrados (CSV)",
            data=df_view.to_csv(index=False).encode("utf-8"),
            file_name="covid_chile_filtrado.csv",
            mime="text/csv",
        )

        st.dataframe(df_view.tail(20))

    with tab2:
        st.subheader("Serie temporal - Casos diarios (derivado)")
        dfd = compute_daily(df_view)
        fig2, ax2 = plt.subplots()
        for comuna, dfg in dfd.groupby("Comuna"):
            ax2.plot(dfg["Fecha"], dfg["Nuevos"], marker="o", linewidth=1, label=str(comuna))
        ax2.set_xlabel("Fecha")
        ax2.set_ylabel("Casos nuevos")
        ax2.set_title("Evolución de casos diarios")
        ax2.tick_params(axis="x", rotation=45)
        ax2.legend(loc="best", fontsize=8)
        st.pyplot(fig2, clear_figure=True)
        st.dataframe(dfd.tail(20))

    with tab3:
        st.subheader("Top 10 comunas por casos (dentro de las regiones seleccionadas)")
        latest = df_view["Fecha"].max()
        df_latest = df_view[df_view["Fecha"] == latest].copy()
        top = (df_latest.groupby(["Region", "Comuna"], as_index=False)["Casos"]
               .sum()
               .sort_values("Casos", ascending=False)
               .head(10))
        st.dataframe(top)

    # Pie de página
    st.markdown("---")
    st.markdown("**Notas:**")
    st.markdown("- Los casos diarios se calculan como diferencia de acumulados entre fechas consecutivas por comuna.")
    st.markdown("- Fuente de datos: Repositorio COVID-19 MinCiencia (GitHub).")
    st.markdown(f"- Endpoint utilizado: `{DATA_URL}`")

if __name__ == "__main__":
    main()
