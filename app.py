"""Altereinkünfte Simulation – Hauptdatei."""

import streamlit as st

st.set_page_config(
    page_title="Altereinkünfte Simulation",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

from engine import Profil, berechne_rente
from tabs import dashboard, simulation, auszahlung, steuern


def _sidebar() -> Profil:
    st.sidebar.title("🏦 Altereinkünfte")
    st.sidebar.caption("Simulation | Keine Anlageberatung")
    st.sidebar.markdown("---")

    st.sidebar.subheader("Persönliche Daten")
    geburtsjahr = st.sidebar.number_input(
        "Geburtsjahr", min_value=1945, max_value=1995, value=1970, step=1
    )
    renteneintritt_alter = st.sidebar.slider(
        "Renteneintrittsalter", min_value=60, max_value=70, value=67,
        help="Regelaltersgrenze 2025: 67 Jahre. Frühestens ab 63 (mit Abschlägen)."
    )

    st.sidebar.subheader("Gesetzliche Rente (BFA / DRV)")
    aktuelle_punkte = st.sidebar.number_input(
        "Aktuelle Rentenpunkte (laut Renteninformation)",
        min_value=0.0, max_value=80.0, value=25.0, step=0.5,
        help="Entgeltpunkte lt. letzter Rentenauskunft der Deutschen Rentenversicherung."
    )
    punkte_pro_jahr = st.sidebar.number_input(
        "Rentenpunkte pro Jahr (Ø)",
        min_value=0.0, max_value=3.0, value=1.2, step=0.05,
        help="1,0 Punkt = Durchschnittsverdienst (ca. 45.358 € brutto in 2024). "
             "Gut verdienende erreichen 1,5–2,0 Punkte/Jahr."
    )
    rentenanpassung = st.sidebar.slider(
        "Rentenanpassung p.a. (%)", min_value=0.0, max_value=5.0, value=2.0, step=0.1,
        help="Historischer Durchschnitt ~2 %. Pessimistisch: 1 %, Optimistisch: 3 %."
    ) / 100

    st.sidebar.subheader("Zusätzliche Altersvorsorge")
    zusatz_monatlich = st.sidebar.number_input(
        "Monatliche Zusatzrente (bAV / Riester / Rürup, €)",
        min_value=0.0, max_value=5_000.0, value=200.0, step=50.0,
        help="Erwartete monatliche Auszahlung aus betrieblicher oder privater Altersvorsorge."
    )
    sparkapital = st.sidebar.number_input(
        "Vorhandenes Sparkapital heute (€)",
        min_value=0.0, max_value=5_000_000.0, value=50_000.0, step=1_000.0,
        help="Depot, ETF-Sparplan, Tagesgeld etc. – aktueller Wert."
    )
    sparrate = st.sidebar.number_input(
        "Monatliche Sparrate bis Rente (€)",
        min_value=0.0, max_value=10_000.0, value=500.0, step=50.0,
        help="Monatlicher Betrag, der ab heute bis Renteneintritt angelegt wird."
    )
    rendite = st.sidebar.slider(
        "Rendite auf Sparkapital p.a. (%)", min_value=0.0, max_value=12.0, value=5.0, step=0.5,
        help="Langfristige Rendite eines global diversifizierten ETF-Portfolios: historisch ~7–8 % nominal."
    ) / 100

    st.sidebar.subheader("Krankenversicherung in der Rente")
    kv_wahl = st.sidebar.radio(
        "Versicherungsart",
        ["Gesetzlich (GKV)", "Privat (PKV)"],
        horizontal=True,
    )
    pkv_beitrag = 0.0
    gkv_zusatz = 0.017
    kinder = True
    if kv_wahl.startswith("Privat"):
        pkv_beitrag = st.sidebar.number_input(
            "PKV-Beitrag im Rentenalter (€/Monat)",
            min_value=200.0, max_value=3_000.0, value=600.0, step=10.0,
            help="PKV-Beiträge steigen mit zunehmendem Alter und Leistungsnutzung erheblich."
        )
    else:
        gkv_zusatz = st.sidebar.slider(
            "GKV Zusatzbeitrag (%)", min_value=0.5, max_value=4.0, value=1.7, step=0.1,
            help="Kassenindividueller Zusatzbeitrag (Durchschnitt 2024: ca. 1,7 %)."
        ) / 100
        kinder = st.sidebar.checkbox(
            "Hat Kinder (niedrigerer PV-Beitrag)", value=True,
            help="Kinderlose zahlen 0,6 % höheren Pflegeversicherungsbeitrag."
        )

    return Profil(
        geburtsjahr=geburtsjahr,
        renteneintritt_alter=renteneintritt_alter,
        aktuelle_punkte=aktuelle_punkte,
        punkte_pro_jahr=punkte_pro_jahr,
        zusatz_monatlich=zusatz_monatlich,
        sparkapital=sparkapital,
        sparrate=sparrate,
        rendite_pa=rendite,
        rentenanpassung_pa=rentenanpassung,
        krankenversicherung="PKV" if kv_wahl.startswith("Privat") else "GKV",
        pkv_beitrag=pkv_beitrag,
        gkv_zusatzbeitrag=gkv_zusatz,
        kinder=kinder,
    )


profil = _sidebar()
ergebnis = berechne_rente(profil)

tabs = st.tabs(["📊 Dashboard", "🔮 Simulation", "💰 Kapital vs. Rente", "🧾 Steuern & KV"])
T = {
    "Dashboard":  tabs[0],
    "Simulation": tabs[1],
    "Auszahlung": tabs[2],
    "Steuern":    tabs[3],
}

dashboard.render(T, profil, ergebnis)
simulation.render(T, profil, ergebnis)
auszahlung.render(T, profil, ergebnis)
steuern.render(T, profil, ergebnis)
