import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
from fredapi import Fred

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Dashboard DCA ETF", layout="wide", initial_sidebar_state="expanded")

# --- CONSTANTES ---
etfs = {
    'S&P500': 'SPY',
    'NASDAQ100': 'QQQ',
    'CAC40': '^FCHI',
    'EURO STOXX50': 'FEZ',
    'EURO STOXX600 TECH': 'EXV3.DE',
    'NIKKEI 225': '^N225',
    'WORLD': 'VT',
    'EMERGING': 'EEM'
}
timeframes = {
    'Hebdo': 7,
    'Mensuel': 30,
    'Trimestriel': 90,
    'Annuel': 365,
    '5 ans': 365 * 5
}
macro_series = {
    'CAPE10': 'CAPE',
    'Fed Funds Rate': 'FEDFUNDS',
    'CPI YoY': 'CPIAUCSL',
    'ECY': 'DGS10'
}

# --- CHARGEMENT DES DONNÉES ---
@st.cache_data
def load_prices():
    end = datetime.today()
    start = end - timedelta(days=365*6)
    df = pd.DataFrame()
    for name, ticker in etfs.items():
        try:
            data = yf.download(ticker, start=start, end=end, progress=False)
            series = data['Adj Close'] if 'Adj Close' in data.columns else data['Close']
            df[name] = series
        except:
            df[name] = pd.Series(dtype=float)
    return df

@st.cache_data
def load_macro():
    api_key = st.secrets.get('FRED_API_KEY', '')
    if not api_key:
        return pd.DataFrame()
    fred = Fred(api_key=api_key)
    end = datetime.today()
    start = end - timedelta(days=365*6)
    df = pd.DataFrame()
    for label, code in macro_series.items():
        try:
            df[label] = fred.get_series(code, start, end)
        except:
            df[label] = pd.Series(dtype=float)
    return df

# --- FONCTIONS UTILES ---
def pct_change(s):
    return float((s.iloc[-1] / s.iloc[-2] - 1) * 100) if len(s) > 1 else 0.0

def score_and_style(diff, threshold):
    """
    Renvoie (poids, flèche, couleur) selon la déviation.
    Vert (diff<0): +1, ↑, green
    Orange (|diff|<threshold): +0.5, ↗, orange
    Rouge: -1, ↓, crimson
    """
    if diff < 0:
        return 1, '↑', 'green'
    elif abs(diff) < threshold/100:
        return 0.5, '↗', 'orange'
    else:
        return -1, '↓', 'crimson'

# --- SIDEBAR ---
st.sidebar.header("Paramètres de rééquilibrage")
if st.sidebar.button("🔄 Rafraîchir"):
    st.cache_data.clear()

# Slider et arbitrage
threshold = st.sidebar.slider("Seuil déviation (%)", 5, 30, 15, 5)
arb = st.sidebar.multiselect("Seuils arbitrage > (%)", [5, 10, 15], [5, 10, 15])

# VIX 3 mois
try:
    vix = yf.download('^VIX', period='3mo', progress=False)['Adj Close']
    fig_vix = px.line(vix, height=100)
    fig_vix.update_layout(margin=dict(l=0,r=0,t=0,b=0), showlegend=False)
    st.sidebar.subheader("VIX (3 mois)")
    st.sidebar.plotly_chart(fig_vix, use_container_width=True)
    st.sidebar.metric("VIX actuel", f"{vix.iloc[-1]:.2f}", delta=f"{vix.iloc[-1]-vix.iloc[-2]:+.2f}")
except:
    st.sidebar.write("VIX non disponible")

# Allocation dynamique (calcul unique)
st.sidebar.header("Allocation dynamique (%)")
prices_temp = load_prices()
surp_scores = {}
for name in etfs:
    scores = []
    s = prices_temp[name].dropna()
    if len(s):
        for w in timeframes.values():
            if len(s) >= w:
                diff = (s.iloc[-1] - s.tail(w).mean()) / s.tail(w).mean()
                weight, _, _ = score_and_style(diff, threshold)
                scores.append(weight)
    surp_scores[name] = sum(scores)

# Normalisation et affichage
total = sum(abs(v) for v in surp_scores.values()) or 1
for name, score in surp_scores.items():
    alloc = score / total * 50
    st.sidebar.markdown(
        f"**{name}:** {alloc:.1f}% <span style='color:blue'>({score:.1f})</span>",
        unsafe_allow_html=True
    )

# --- CHARGEMENT PRINCIPAL ---
prices = load_prices()
macro_df = load_macro()
deltas = {n: pct_change(prices[n].dropna()) for n in etfs}

# --- AFFICHAGE PRINCIPAL ---
st.title("Dashboard DCA ETF")
cols = st.columns(2)

for idx, name in enumerate(etfs):
    series = prices[name].dropna()
    if series.empty:
        continue

    last = series.iloc[-1]
    delta = deltas[name]
    perf_color = "green" if delta >= 0 else "crimson"
    border = "#28a745" if surp_scores[name] > 0 else "#dc3545"

    # Période via session_state
    key = f"win_{name}"
    if key not in st.session_state:
        st.session_state[key] = "Annuel"
    period_days = timeframes[st.session_state[key]]
    df_plot = series.tail(period_days)

    # Graphique
    fig = px.line(df_plot, height=300)
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), showlegend=False,
                      xaxis_title="Date", yaxis_title="Valeur")

    # Indicateurs macro
    macro_items = []
    for lbl in macro_series:
        if lbl in macro_df and not macro_df[lbl].dropna().empty:
            val = macro_df[lbl].dropna().iloc[-1]
            macro_items.append(f"<li>{lbl}: {val:.2f}</li>")
        else:
            macro_items.append(f"<li>{lbl}: N/A</li>")
    half = len(macro_items)//2 + len(macro_items)%2
    macro_html = (
        "<div style='display:flex;gap:40px;font-size:12px;'>"
        f"<ul style='margin:0;padding-left:16px'>{''.join(macro_items[:half])}</ul>"
        f"<ul style='margin:0;padding-left:16px'>{''.join(macro_items[half:])}</ul>"
        "</div>"
    )

    with cols[idx % 2]:
        st.markdown(f"<div style='border:2px solid {border};border-radius:6px; padding:12px;margin:6px;'>", unsafe_allow_html=True)
        st.markdown(
            f"<h4>{name}: {last:.2f} <span style='color:{perf_color}'>{delta:+.2f}%</span></h4>",
            unsafe_allow_html=True
        )
        st.plotly_chart(fig, use_container_width=True)

        # Badges tri-couleurs
        badge_cols = st.columns(len(timeframes))
        for j, (lbl, w) in enumerate(timeframes.items()):
            arrow = ''
            if len(series) >= w:
                diff = (last - series.tail(w).mean()) / series.tail(w).mean()
                _, arrow, bg = score_and_style(diff, threshold)
            else:
                arrow, bg = '↓', 'crimson'
            if badge_cols[j].button(lbl, key=f"{name}_{lbl}"):
                st.session_state[key] = lbl
            badge_cols[j].markdown(
                f"<span title='Moyenne {lbl}: {series.tail(w).mean():.2f if len(series)>=w else 'N/A'}' "
                f"style='background:{bg};color:white;padding:4px 8px;border-radius:4px;font-size:12px;'>"
                f"{lbl} {arrow}</span>", unsafe_allow_html=True)

        # Surpondération et macro
        st.markdown(f"<div style='text-align:right;color:#1f77b4;'>Surpondération: {surp_scores[name]:.1f}</div>", unsafe_allow_html=True)
        st.markdown(macro_html, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Alertes d'arbitrage
        if idx % 2 == 1 and arb:
            for thr in arb:
                pairs = [(a, b, abs(deltas[a] - deltas[b])) for a in deltas for b in deltas if a < b and abs(deltas[a] - deltas[b]) > thr]
                if pairs:
                    st.warning(f"Écart > {thr}% : {pairs}")

# Avertissement clé FRED
if macro_df.empty:
    st.warning("🔑 Clé FRED_API_KEY manquante pour indicateurs macro.")
