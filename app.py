"""Alterseinkünfte Simulation – Hauptdatei."""

import streamlit as st

st.set_page_config(
    page_title="Alterseinkünfte Simulation",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

from engine import Profil, berechne_rente, berechne_haushalt
from session_io import save_session, load_session, list_saves
from tabs import dashboard, simulation, auszahlung, steuern, vorsorge, haushalt


# ── Sidebar-Hilfsfunktion je Person ──────────────────────────────────────────

def _profil_inputs(label: str, pfx: str, geb_default: int) -> Profil:
    """Rendert Eingaben für eine Person und gibt ein Profil zurück."""
    st.sidebar.markdown(f"**{label}**")

    geburtsjahr = st.sidebar.number_input(
        "Geburtsjahr", 1945, 1995, st.session_state.get(f"{pfx}_geb", geb_default),
        step=1, key=f"{pfx}_geb",
    )
    renteneintritt_alter = st.sidebar.slider(
        "Renteneintrittsalter", 60, 70,
        st.session_state.get(f"{pfx}_re_alter", 67),
        key=f"{pfx}_re_alter",
        help="Regelaltersgrenze 2025: 67 Jahre.",
    )

    st.sidebar.markdown("*Gesetzliche Rente (BFA / DRV)*")
    aktuelle_punkte = st.sidebar.number_input(
        "Aktuelle Rentenpunkte", 0.0, 80.0,
        st.session_state.get(f"{pfx}_punkte", 25.0 if pfx == "p1" else 15.0),
        step=0.5, key=f"{pfx}_punkte",
        help="Entgeltpunkte lt. letzter Renteninformation der DRV.",
    )
    punkte_pro_jahr = st.sidebar.number_input(
        "Rentenpunkte pro Jahr (Ø)", 0.0, 3.0,
        st.session_state.get(f"{pfx}_ppj", 1.2),
        step=0.05, key=f"{pfx}_ppj",
        help="1,0 = Durchschnittsverdienst (~45.358 € brutto in 2024).",
    )
    rentenanpassung = st.sidebar.slider(
        "Rentenanpassung p.a. (%)", 0.0, 5.0,
        st.session_state.get(f"{pfx}_ren_anp", 2.0),
        step=0.1, key=f"{pfx}_ren_anp",
    ) / 100

    st.sidebar.markdown("*Sparkapital*")
    sparkapital = st.sidebar.number_input(
        "Sparkapital heute (€)", 0.0, 5_000_000.0,
        st.session_state.get(f"{pfx}_spkap", 50_000.0),
        step=1_000.0, key=f"{pfx}_spkap",
    )
    sparrate = st.sidebar.number_input(
        "Monatliche Sparrate (€)", 0.0, 10_000.0,
        st.session_state.get(f"{pfx}_sprate", 500.0),
        step=50.0, key=f"{pfx}_sprate",
    )
    rendite = st.sidebar.slider(
        "Rendite p.a. (%)", 0.0, 12.0,
        st.session_state.get(f"{pfx}_rendite", 5.0),
        step=0.5, key=f"{pfx}_rendite",
    ) / 100
    zusatz = st.sidebar.number_input(
        "Zusatzrente bAV/Riester/Rürup (€/Mon.)", 0.0, 5_000.0,
        st.session_state.get(f"{pfx}_zusatz", 200.0),
        step=50.0, key=f"{pfx}_zusatz",
        help="Monatliche Auszahlung aus Zusatzvorsorge (falls nicht im Vorsorge-Tab erfasst).",
    )

    st.sidebar.markdown("*Krankenversicherung in der Rente*")
    kv_idx = 0 if st.session_state.get(f"{pfx}_kv", "GKV") == "GKV" else 1
    kv_wahl = st.sidebar.radio(
        "Versicherungsart", ["Gesetzlich (GKV)", "Privat (PKV)"],
        index=kv_idx, horizontal=True, key=f"{pfx}_kv_radio",
    )
    pkv_beitrag = 0.0
    gkv_zusatz = 0.017
    kinder = True
    if kv_wahl.startswith("Privat"):
        pkv_beitrag = st.sidebar.number_input(
            "PKV-Beitrag (€/Mon.)", 200.0, 3_000.0,
            st.session_state.get(f"{pfx}_pkv", 600.0),
            step=10.0, key=f"{pfx}_pkv",
        )
    else:
        gkv_zusatz = st.sidebar.slider(
            "GKV Zusatzbeitrag (%)", 0.5, 4.0,
            st.session_state.get(f"{pfx}_gkv_zus", 1.7),
            step=0.1, key=f"{pfx}_gkv_zus",
        ) / 100
        kinder = st.sidebar.checkbox(
            "Hat Kinder", value=st.session_state.get(f"{pfx}_kinder", True),
            key=f"{pfx}_kinder",
        )

    return Profil(
        geburtsjahr=geburtsjahr,
        renteneintritt_alter=renteneintritt_alter,
        aktuelle_punkte=aktuelle_punkte,
        punkte_pro_jahr=punkte_pro_jahr,
        zusatz_monatlich=zusatz,
        sparkapital=sparkapital,
        sparrate=sparrate,
        rendite_pa=rendite,
        rentenanpassung_pa=rentenanpassung,
        krankenversicherung="PKV" if kv_wahl.startswith("Privat") else "GKV",
        pkv_beitrag=pkv_beitrag,
        gkv_zusatzbeitrag=gkv_zusatz,
        kinder=kinder,
    )


# ── Hauptsidebar ──────────────────────────────────────────────────────────────

def _sidebar():
    st.sidebar.title("🏦 Alterseinkünfte")
    st.sidebar.caption("Simulation | Keine Anlageberatung")

    # ── Laden (ganz oben für schnellen Zugriff) ───────────────────────────────
    saves = list_saves()
    if saves:
        with st.sidebar.expander("📂 Gespeicherte Profile", expanded=False):
            namen = [n for n, _ in saves]
            auswahl = st.selectbox("Profil wählen", namen, key="load_select")
            if st.button("📥 Laden", key="load_btn"):
                pfad = dict(saves)[auswahl]
                data = load_session(pfad)
                p1 = data["profil1"]
                # Profil 1 in session state schreiben
                for k, v in [
                    ("p1_geb", p1.geburtsjahr), ("p1_re_alter", p1.renteneintritt_alter),
                    ("p1_punkte", p1.aktuelle_punkte), ("p1_ppj", p1.punkte_pro_jahr),
                    ("p1_ren_anp", p1.rentenanpassung_pa * 100),
                    ("p1_spkap", p1.sparkapital), ("p1_sprate", p1.sparrate),
                    ("p1_rendite", p1.rendite_pa * 100), ("p1_zusatz", p1.zusatz_monatlich),
                    ("p1_pkv", p1.pkv_beitrag), ("p1_gkv_zus", p1.gkv_zusatzbeitrag * 100),
                    ("p1_kinder", p1.kinder), ("p1_kv", p1.krankenversicherung),
                ]:
                    st.session_state[k] = v
                if data.get("profil2"):
                    p2 = data["profil2"]
                    st.session_state["hat_partner"] = True
                    for k, v in [
                        ("p2_geb", p2.geburtsjahr), ("p2_re_alter", p2.renteneintritt_alter),
                        ("p2_punkte", p2.aktuelle_punkte), ("p2_ppj", p2.punkte_pro_jahr),
                        ("p2_ren_anp", p2.rentenanpassung_pa * 100),
                        ("p2_spkap", p2.sparkapital), ("p2_sprate", p2.sparrate),
                        ("p2_rendite", p2.rendite_pa * 100), ("p2_zusatz", p2.zusatz_monatlich),
                        ("p2_pkv", p2.pkv_beitrag), ("p2_gkv_zus", p2.gkv_zusatzbeitrag * 100),
                        ("p2_kinder", p2.kinder), ("p2_kv", p2.krankenversicherung),
                    ]:
                        st.session_state[k] = v
                else:
                    st.session_state["hat_partner"] = False
                st.session_state["veranlagung"] = data.get("veranlagung", "Getrennt")
                st.session_state["vp_produkte"] = data.get("produkte", [])
                st.rerun()

    st.sidebar.markdown("---")

    # ── Person 1 ──────────────────────────────────────────────────────────────
    with st.sidebar.expander("👤 Person 1", expanded=True):
        profil1 = _profil_inputs("Person 1", "p1", geb_default=1970)

    # ── Ehepartner ────────────────────────────────────────────────────────────
    hat_partner = st.sidebar.checkbox(
        "👥 Ehepartner / Partnerin hinzufügen",
        value=st.session_state.get("hat_partner", False),
        key="hat_partner",
    )
    profil2 = None
    veranlagung = "Getrennt"
    if hat_partner:
        with st.sidebar.expander("👤 Person 2", expanded=True):
            profil2 = _profil_inputs("Person 2", "p2", geb_default=1972)
        veranlagung = st.sidebar.radio(
            "Steuerliche Veranlagung in der Rente",
            ["Zusammenveranlagung (Splitting)", "Getrennte Veranlagung"],
            index=0 if st.session_state.get("veranlagung", "Zusammen") == "Zusammen" else 1,
            key="veranlagung_radio",
            help="Splitting: Einkommen wird halbiert, Steuer berechnet und verdoppelt → "
                 "Vorteil bei ungleichen Einkommen.",
        )
        veranlagung = "Zusammen" if "Splitting" in veranlagung else "Getrennt"
        st.session_state["veranlagung"] = veranlagung

    st.sidebar.markdown("---")

    # ── Speichern ─────────────────────────────────────────────────────────────
    with st.sidebar.expander("💾 Profil speichern", expanded=False):
        save_name = st.text_input("Name der Sicherung", value="MeinProfil", key="save_name")
        if st.button("💾 Jetzt speichern", key="save_btn"):
            pfad = save_session(
                name=save_name,
                profil1=profil1,
                profil2=profil2,
                veranlagung=veranlagung,
                produkte=st.session_state.get("vp_produkte", []),
            )
            st.success(f"Gespeichert: {pfad}")

    return profil1, profil2, veranlagung


# ── App ───────────────────────────────────────────────────────────────────────

profil1, profil2, veranlagung = _sidebar()
ergebnis1 = berechne_rente(profil1)
ergebnis2 = berechne_rente(profil2) if profil2 else None
haushalt_daten = berechne_haushalt(ergebnis1, ergebnis2, veranlagung)

tab_labels = ["📊 Dashboard", "🔮 Simulation", "🏦 Vorsorge-Bausteine",
              "💰 Kapital vs. Rente", "🧾 Steuern & KV"]
if profil2:
    tab_labels.insert(1, "👥 Haushalt")

tabs = st.tabs(tab_labels)

idx = 0
T: dict = {}
T["Dashboard"] = tabs[idx]; idx += 1
if profil2:
    T["Haushalt"] = tabs[idx]; idx += 1
T["Simulation"] = tabs[idx]; idx += 1
T["Vorsorge"]   = tabs[idx]; idx += 1
T["Auszahlung"] = tabs[idx]; idx += 1
T["Steuern"]    = tabs[idx]; idx += 1

dashboard.render(T, profil1, ergebnis1)
if profil2:
    haushalt.render(T, profil1, profil2, ergebnis1, ergebnis2, veranlagung, haushalt_daten)
simulation.render(T, profil1, ergebnis1)
vorsorge.render(T, profil1, ergebnis1, profil2=profil2)
auszahlung.render(T, profil1, ergebnis1)
steuern.render(T, profil1, ergebnis1)
