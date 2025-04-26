import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from fredapi import Fred
from streamlit.components.v1 import html

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="DCA Portfolio Dashboard", layout="wide")

# --- CONSTANTES ---
etfs = {
    'S&P500': 'SPY',
    'NASDAQ100': 'QQQ',
    'CAC40': 'CAC.PA',
    'EURO STOXX50': 'FEZ',
    'EURO STOXX600 TECH': 'EXV3.DE',
    'NIKKEI 225': '^N225',
    'WORLD': 'VT',
    'EMERGING': 'EEM'
}
timeframes = {
    'Hebdo': 5,
    'Mensuel': 21,
    'Trimestriel': 63,
    'Annuel': 252,
    '5 ans': 1260
}
macro_series = {
    'CAPE10': 'CAPE',
    'Fed Funds Rate': 'FEDFUNDS',
    'CPI YoY': 'CPIAUCSL',
    'ECY': 'DGS10'
}

# --- FONCTIONS DE RÉCUPÉRATION DES DONNÉES ---
@st.cache_data(show_spinner=False)
def fetch_etf_prices(symbols, days=5*365):
    """Télécharge les cours ajustés des ETF sur la période spécifiée."""
    end = datetime.today()
    start = end - timedelta(days=days)
    df = pd.DataFrame()
    for name, ticker in symbols.items():
        data = yf.download(ticker, start=start, end=end, progress=False)
        df[name] = data.get('Adj Close', data.get('Close', pd.NA))
    return df

@st.cache_data(show_spinner=False)
def fetch_macro_data(series_dict, days=5*365):
    """Récupère les séries macro via l'API FRED avec fallback si clé manquante."""
    key = st.secrets.get('FRED_API_KEY', '')
    if not key:
        return pd.DataFrame(columns=series_dict.keys())
    fred = Fred(api_key=key)
    end = datetime.today()
    start = end - timedelta(days=days)
    df = pd.DataFrame()
    for label, code in series_dict.items():
        try:
            df[label] = fred.get_series(code, start, end)
        except Exception:
            df[label] = pd.NA
    return df

# --- UTILITAIRES ---
def pct_change(series):
    """Calcul du % de variation jour à jour."""
    if len(series) < 2:
        return 0.0
    return float((series.iloc[-1] / series.iloc[-2] - 1) * 100)

def compute_green_counts(df):
    """Compte pour chaque ETF le nombre de périodes où le dernier cours < moyenne de la fenêtre."""
    counts = {}
    for name in df.columns:
        series = df[name]
        count = 0
        for window in timeframes.values():
            if len(series) >= window and series.iloc[-1] < series.iloc[-window:].mean():
                count += 1
        counts[name] = count
    return counts

# --- INTERFACE ---
st.title("Dashboard DCA ETF")

# Rafraîchir les données
if st.sidebar.button("🔄 Rafraîchir les données"):
    st.cache_data.clear()

# Chargement des données
tab1, tab2 = st.tabs(["Données ETF", "Données Macro"])  # pour garder la structure si besoin
with st.spinner("Chargement des données…"):
    price_df = fetch_etf_prices(etfs)
    macro_df = fetch_macro_data(macro_series)

# Calcul des indicateurs
deltas = {n: pct_change(s) for n, s in price_df.items()}
green_counts = compute_green_counts(price_df)

# Sidebar - Paramètres de rééquilibrage
st.sidebar.header("Paramètres de rééquilibrage")
threshold = st.sidebar.slider(
    "Seuil de déviation (%)", 5, 30, 15, 5,
    help="Écart max entre part réelle et cible avant alerte de rééquilibrage."
)

# Sidebar - Allocation dynamique
st.sidebar.header("Allocation dynamique (%)")
total_green = sum(green_counts.values()) or 1
for name, count in green_counts.items():
    alloc = (count / total_green) * 50
    arrow = "▲" if count > 0 else ""
    color_arrow = "#28a745" if count > 0 else "#888"
    st.sidebar.markdown(
        f"**{name}**: {alloc:.1f}% <span style='color:{color_arrow}'>{arrow}{count}</span>",
        unsafe_allow_html=True
    )

# Sidebar - VIX
try:
    vix = yf.download('^VIX', period='2d', progress=False)['Adj Close']
    st.sidebar.metric("VIX", f"{vix.iloc[-1]:.2f}", f"{vix.iloc[-1] - vix.iloc[-2]:+.2f}")
except Exception:
    st.sidebar.write("VIX non disponible")

# Sidebar - Seuils arbitrage
st.sidebar.header("Seuils arbitrage")
thresholds = st.sidebar.multiselect(
    "Choisir seuils (%)", [5, 10, 15, 20, 25], default=[5, 10, 15],
    help="Alerte si écart de performance entre indices > seuil."
)

# --- AFFICHAGE PRINCIPAL ---
cols = st.columns(2)
for idx, (name, series) in enumerate(price_df.items()):
    # Calcul des variations et style
    delta = deltas[name]
    perf_color = "green" if delta >= 0 else "crimson"
    # Valeur du jour
    last_price = series.iloc[-1] if len(series) else None
    price_str = f"{last_price:.2f} USD" if last_price is not None else "N/A"
    # Compte de périodes vertes
    gc = green_counts[name]
    border_color = "#28a745" if gc >= 4 else "#ffc107" if gc >= 2 else "#dc3545"

    # Préparation du graphique HTML
    fig = px.line(series, height=120)
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), xaxis_showgrid=False, yaxis_showgrid=False)
    fig_html = fig.to_html(include_plotlyjs=False, full_html=False)

    # Badges DCA
    badges_list = []
    for lbl, w in timeframes.items():
        if len(series) >= w:
            avg = series.iloc[-w:].mean()
            bg = "green" if series.iloc[-1] < avg else "crimson"
            title = f"Moyenne {lbl}: {avg:.2f}"
        else:
            bg = "crimson"
            title = ""
        badges_list.append(
            f"<span title='{title}' style='background:{bg};color:white;"
            "padding:3px 6px;border-radius:4px;margin-right:4px;font-size:12px'>{lbl}</span>"
        )
    badges_html = "".join(badges_list)

    # Indicateurs macro en deux colonnes
    items = []
    for lbl in macro_series:
        if lbl in macro_df and not macro_df[lbl].dropna().empty:
            val = macro_df[lbl].dropna().iloc[-1]
            items.append(f"<li>{lbl}: {val:.2f}</li>")
        else:
            items.append(f"<li>{lbl}: N/A</li>")
    half = len(items) // 2 + len(items) % 2
    left, right = ''.join(items[:half]), ''.join(items[half:])

    # Construction du fragment HTML complet
    card_html = f"""
    <div style='border:3px solid {border_color};border-radius:12px;padding:16px;margin:10px;"
    f"background-color:white;max-height:380px;overflow:auto;'>
      <h4 style='margin:4px 0'>{name}: {price_str} "
      f"<span style='color:{perf_color}'>{delta:+.2f}%</span></h4>
      {fig_html}
      <div style='margin-top:8px;display:flex;gap:4px;'>{badges_html}</div>
      <div style='text-align:right;font-size:13px;margin-top:6px;'>"
      f"Surpondération: <span style='color:#1f77b4'>{'🔵' * gc}</span></div>
      <div style='display:flex;gap:20px;margin-top:8px;font-size:12px;'>
        <ul style='margin:0;padding-left:16px'>{left}</ul>
        <ul style='margin:0;padding-left:16px'>{right}</ul>
      </div>
    </div>
    """
    with cols[idx % 2]:
        html(card_html, height=420)

    # Alertes d'arbitrage entre indices (après chaque paire)
    if idx % 2 == 1 and thresholds:
        for t in sorted(thresholds, reverse=True):
            pairs = [(i, j, abs(deltas[i] - deltas[j])) for i in deltas for j in deltas if i < j and abs(deltas[i] - deltas[j]) > t]
            if pairs:
                st.warning(f"Écart > {t}% détecté :")
                for i, j, d in pairs:
                    st.write(f"- {i} vs {j}: {d:.1f}%")

# --- MESSAGE ERREUR FRED EN BAS ---
if not st.secrets.get('FRED_API_KEY'):
    st.warning(
        "🔑 Clé FRED_API_KEY manquante : configurez-la dans les Secrets de Streamlit Cloud pour activer les indicateurs macro."
    )
