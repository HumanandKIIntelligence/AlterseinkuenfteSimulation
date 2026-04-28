"""Hypothek-Tab – Tilgungsplan, Restschuldverlauf und Restschuld-Behandlung."""

import math

import plotly.graph_objects as go
import streamlit as st

from engine import AKTUELLES_JAHR


def _de(v: float, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _default_hyp_daten() -> dict:
    return {
        "aktiv": False,
        "startjahr": AKTUELLES_JAHR,
        "endjahr": AKTUELLES_JAHR + 20,
        "betrag": 300_000.0,
        "jaehrl_rate": 15_000.0,
        "zins_pa": 0.035,
        "sondertilgungen": [],
        # Restschuld-Behandlung
        "restschuld_behandlung": "keine",   # "keine", "kapitalanlage", "ratenkredit"
        "anschluss_zins_pa": 0.04,
        "anschluss_laufzeit": 10,
        # Laufende Raten in Simulation berücksichtigen
        "raten_in_simulation": False,
    }


def _validate_hyp(startjahr: int, endjahr: int, betrag: float, jaehrl_rate: float) -> list[str]:
    """Gibt Liste von Fehlermeldungen zurück (leer = gültig)."""
    errors = []
    if endjahr <= startjahr:
        errors.append(f"Endjahr ({endjahr}) muss nach dem Startjahr ({startjahr}) liegen.")
    if betrag <= 0:
        errors.append("Darlehensbetrag muss > 0 € sein.")
    if jaehrl_rate <= 0:
        errors.append("Jährliche Rate muss > 0 € sein.")
    if jaehrl_rate > betrag:
        errors.append(
            f"Jahresrate ({_de(jaehrl_rate)} €) überschreitet den Darlehensbetrag "
            f"({_de(betrag)} €) – bitte prüfen."
        )
    return errors


def _annuitaet_rate(kapital: float, zins_pa: float, laufzeit_jahre: int) -> float:
    """Jährliche Annuitätsrate für einen Kredit."""
    if laufzeit_jahre <= 0 or kapital <= 0:
        return 0.0
    if zins_pa <= 0.0:
        return kapital / laufzeit_jahre
    r = zins_pa
    return kapital * r * (1 + r) ** laufzeit_jahre / ((1 + r) ** laufzeit_jahre - 1)


def get_hyp_schedule() -> list[dict]:
    """Tilgungsplan als Liste von Dicts. Leer wenn nicht konfiguriert."""
    d = st.session_state.get("hyp_daten", {})
    if not d.get("aktiv", False):
        return []

    restschuld = float(d.get("betrag", 0.0))
    jaehrl_rate = float(d.get("jaehrl_rate", 0.0))
    zins_pa = float(d.get("zins_pa", 0.0))
    startjahr = int(d.get("startjahr", AKTUELLES_JAHR))
    endjahr = int(d.get("endjahr", AKTUELLES_JAHR + 20))
    sondertilgungen_raw = d.get("sondertilgungen", [])
    sondertilgungen = {int(s["jahr"]): float(s["betrag"]) for s in sondertilgungen_raw}

    schedule = []
    for jahr in range(startjahr, endjahr + 1):
        if restschuld <= 0.0:
            break
        restschuld_anfang = restschuld
        zinsen = restschuld_anfang * zins_pa
        tilgung = max(0.0, jaehrl_rate - zinsen)
        sondertilgung = sondertilgungen.get(jahr, 0.0)
        jahresausgabe = min(jaehrl_rate + sondertilgung, restschuld_anfang + zinsen)
        restschuld_neu = max(0.0, restschuld_anfang - tilgung - sondertilgung)
        schedule.append({
            "Jahr": jahr,
            "Restschuld_Anfang": restschuld_anfang,
            "Zinsen": zinsen,
            "Tilgung": tilgung,
            "Sondertilgung": sondertilgung,
            "Jahresausgabe": jahresausgabe,
            "Restschuld_Ende": restschuld_neu,
        })
        restschuld = restschuld_neu

    return schedule


def get_restschuld_end() -> float:
    """Gibt Restschuld am Endjahr zurück (0 wenn vollständig getilgt)."""
    schedule = get_hyp_schedule()
    if not schedule:
        return 0.0
    return schedule[-1]["Restschuld_Ende"]


def get_anschluss_schedule() -> list[dict]:
    """Anschlusskredit-Tilgungsplan als Liste von Dicts. Leer wenn nicht konfiguriert.

    Startet im Endjahr der Primärhypothek (= Jahr der letzten Rate). Jedes Dict
    enthält "Jahr" und "Jahresausgabe" (Annuität Anschlusskredit).
    """
    d = st.session_state.get("hyp_daten", {})
    if not d.get("aktiv", False) or d.get("restschuld_behandlung", "keine") != "ratenkredit":
        return []
    restschuld = get_restschuld_end()
    if restschuld <= 0.0:
        return []
    endjahr  = int(d.get("endjahr", AKTUELLES_JAHR + 20))
    zins     = float(d.get("anschluss_zins_pa", 0.04))
    laufzeit = int(d.get("anschluss_laufzeit", 10))
    if laufzeit <= 0:
        return []
    rate = _annuitaet_rate(restschuld, zins, laufzeit)
    return [{"Jahr": endjahr + i, "Jahresausgabe": rate} for i in range(laufzeit)]


def get_ausgaben_plan() -> dict[int, float]:
    """
    Gibt {Jahr: Jahresausgabe} für die Simulation zurück.

    - raten_in_simulation=True: laufende Jahresraten aus dem Tilgungsplan
    - "kapitalanlage": Einmaltilgung im Endjahr (aus Pool, fehlend aus Netto)
    - "ratenkredit":   Jahresraten ab Endjahr+1 über anschluss_laufzeit Jahre
    """
    d = st.session_state.get("hyp_daten", {})
    if not d.get("aktiv", False):
        return {}

    plan: dict[int, float] = {}

    # Laufende Hypothekraten in der Simulation
    if d.get("raten_in_simulation", False):
        for row in get_hyp_schedule():
            plan[row["Jahr"]] = plan.get(row["Jahr"], 0.0) + row["Jahresausgabe"]

    # Restschuld-Behandlung am Ende
    behandlung = d.get("restschuld_behandlung", "keine")
    restschuld = get_restschuld_end()
    if restschuld > 0.0 and behandlung != "keine":
        endjahr = int(d.get("endjahr", AKTUELLES_JAHR + 20))
        if behandlung == "kapitalanlage":
            plan[endjahr] = plan.get(endjahr, 0.0) + restschuld
        elif behandlung == "ratenkredit":
            zins = float(d.get("anschluss_zins_pa", 0.04))
            laufzeit = int(d.get("anschluss_laufzeit", 10))
            rate = _annuitaet_rate(restschuld, zins, laufzeit)
            for i in range(laufzeit):
                plan[endjahr + 1 + i] = plan.get(endjahr + 1 + i, 0.0) + rate

    return plan


def get_hyp_info() -> dict | None:
    """Gibt Hypothek-Metadaten zurück (None wenn nicht konfiguriert/inaktiv)."""
    d = st.session_state.get("hyp_daten", {})
    if not d.get("aktiv", False):
        return None
    return {
        "startjahr":        int(d.get("startjahr", AKTUELLES_JAHR)),
        "endjahr":          int(d.get("endjahr", AKTUELLES_JAHR + 20)),
        "betrag":           float(d.get("betrag", 0.0)),
        "jaehrl_rate":      float(d.get("jaehrl_rate", 0.0)),
        "zins_pa":          float(d.get("zins_pa", 0.035)),
        "restschuld_end":   get_restschuld_end(),
        "anschluss_zins_pa":  float(d.get("anschluss_zins_pa", 0.04)),
        "anschluss_laufzeit": int(d.get("anschluss_laufzeit", 10)),
    }


def get_ausgaben_plan_optimierung(
    markt_zins_pa: float,
    anschluss_laufzeit: int,
    als_einmaltilgung: bool = False,
) -> dict[int, float]:
    """
    Ausgaben-Plan für Entnahme-Optimierung:
    - Laufende Jahresraten aus dem Tilgungsplan (bestehender Nominalzins)
    - Restschuld-Behandlung nach Endjahr:
        als_einmaltilgung=True  → Einmalbetrag im Endjahr (aus Vorsorgevertrag)
        als_einmaltilgung=False → Ratenkredit mit markt_zins_pa über anschluss_laufzeit
    """
    d = st.session_state.get("hyp_daten", {})
    if not d.get("aktiv", False):
        return {}

    plan: dict[int, float] = {}

    for row in get_hyp_schedule():
        plan[row["Jahr"]] = plan.get(row["Jahr"], 0.0) + row["Jahresausgabe"]

    restschuld = get_restschuld_end()
    if restschuld > 0.0:
        endjahr = int(d.get("endjahr", AKTUELLES_JAHR + 20))
        if als_einmaltilgung:
            plan[endjahr] = plan.get(endjahr, 0.0) + restschuld
        elif anschluss_laufzeit > 0:
            rate = _annuitaet_rate(restschuld, markt_zins_pa, anschluss_laufzeit)
            for i in range(anschluss_laufzeit):
                plan[endjahr + 1 + i] = plan.get(endjahr + 1 + i, 0.0) + rate

    return plan


def _restschuld_vergleich_ui(restschuld: float, endjahr: int, d: dict, _rc: int) -> None:
    """Zeigt Vergleich Kapitalanlage vs. Ratenkredit, inkl. Mindest-Netto-Check."""
    st.subheader("⚖️ Restschuld-Behandlung")
    st.caption(f"Verbleibende Restschuld zum Endjahr {endjahr}: **{_de(restschuld)} €**")

    behandlung = st.radio(
        "Wie soll die Restschuld behandelt werden?",
        ["keine", "kapitalanlage", "ratenkredit"],
        format_func=lambda x: {
            "keine": "⬜ Keine gesonderte Planung",
            "kapitalanlage": "💰 Einmaltilgung aus Kapitalanlage (im Endjahr)",
            "ratenkredit": "🏦 Anschlussfinanzierung / Ratenkredit (nach Endjahr)",
        }[x],
        index=["keine", "kapitalanlage", "ratenkredit"].index(
            d.get("restschuld_behandlung", "keine")
        ),
        key=f"rc{_rc}_hyp_behandlung",
    )
    st.session_state["hyp_daten"]["restschuld_behandlung"] = behandlung

    # Anschluss-Parameter (nur bei Ratenkredit sichtbar)
    anschluss_zins = float(d.get("anschluss_zins_pa", 0.04))
    anschluss_laufzeit = int(d.get("anschluss_laufzeit", 10))

    if behandlung == "ratenkredit":
        rc1, rc2 = st.columns(2)
        with rc1:
            anschluss_zins_pct = st.number_input(
                "Zinssatz Anschlussfinanzierung (%)", 0.0, 20.0,
                value=anschluss_zins * 100, step=0.05, format="%.2f",
                key=f"rc{_rc}_hyp_anschl_zins",
            )
            anschluss_zins = anschluss_zins_pct / 100.0
            st.session_state["hyp_daten"]["anschluss_zins_pa"] = anschluss_zins
        with rc2:
            anschluss_laufzeit = st.number_input(
                "Laufzeit Ratenkredit (Jahre)", 1, 30,
                value=anschluss_laufzeit, step=1,
                key=f"rc{_rc}_hyp_anschl_lz",
            )
            st.session_state["hyp_daten"]["anschluss_laufzeit"] = int(anschluss_laufzeit)

    # ── Vergleichsrechnung ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**Kostenvergleich**")

    # Ratenkredit-Kennzahlen
    rate_j = _annuitaet_rate(restschuld, anschluss_zins, anschluss_laufzeit)
    zinslast_ratenkredit = rate_j * anschluss_laufzeit - restschuld

    col_ka, col_rk = st.columns(2)

    with col_ka:
        st.markdown("**💰 Kapitalanlage-Tilgung**")
        st.metric("Einmalige Belastung", f"{_de(restschuld)} €")
        st.metric("Laufende Mehrbelastung", "0 €/Jahr")
        st.caption(
            "Der Kapitalanlage-Pool wird um die Restschuld reduziert. "
            "Fehlbetrag (wenn Pool < Restschuld) verringert das verfügbare Netto im Endjahr."
        )

    with col_rk:
        st.markdown("**🏦 Ratenkredit**")
        st.metric("Jahresrate", f"{_de(rate_j)} €/Jahr")
        st.metric("Gesamtzinslast", f"{_de(zinslast_ratenkredit)} €")
        st.caption(
            f"Laufzeit: {anschluss_laufzeit} Jahre ab {endjahr + 1}. "
            "Die Jahresrate reduziert das verfügbare Netto in jedem Jahr der Laufzeit."
        )

    # Mindest-Netto Eingabe für Empfehlung
    st.markdown("---")
    st.markdown("**🎯 Empfehlung unter Liquiditätsvorgabe**")
    mindest_netto = st.number_input(
        "Mindest-Haushaltsnetto (€/Monat)",
        min_value=0, max_value=20_000,
        value=int(st.session_state.get(f"rc{_rc}_hyp_mindest_netto", 2000)),
        step=100,
        key=f"rc{_rc}_hyp_mindest_netto",
        help="Wie viel Netto monatlich mindestens verfügbar sein soll (Eingabe dient nur dem Vergleich hier)",
    )

    mindest_jahres = mindest_netto * 12

    # Heuristischer Vergleich ohne engine-Aufruf
    # Kapitalanlage: kritisches Jahr = Endjahr (Pool-Entnahme)
    ka_kritisch = restschuld  # Einmalbelastung

    # Ratenkredit: jährliche Mehrbelastung
    rk_jahresbelastung = rate_j

    st.info(
        f"**Anschluss-Ratenkredit** belastet das Netto mit **{_de(rate_j)} €/Jahr** "
        f"({_de(rate_j / 12, 0)} €/Monat) über {anschluss_laufzeit} Jahre. "
        f"Das verfügbare Netto muss in dieser Zeit um mind. {_de(rate_j)} €/Jahr über "
        f"dem Zielwert ({_de(mindest_jahres)} €/Jahr) liegen, "
        f"damit das Mindest-Netto erreicht wird.\n\n"
        f"**Kapitalanlage** reduziert den Anlagestock einmalig um {_de(ka_kritisch)} €. "
        f"Laufendes Netto bleibt unverändert – sofern der Pool ausreicht.",
        icon="ℹ️",
    )

    if rate_j / 12 > mindest_netto * 0.3:
        st.warning(
            f"⚠️ Die monatliche Ratenkredit-Rate ({_de(rate_j / 12, 0)} €) übersteigt 30 % "
            f"des angestrebten Mindest-Nettos ({mindest_netto} €/Monat). "
            "Kapitalanlage-Tilgung empfohlen, sofern der Pool ausreicht."
        )
    elif zinslast_ratenkredit < restschuld * 0.15:
        st.success(
            f"✅ Die Gesamtzinslast des Ratenkredits ({_de(zinslast_ratenkredit)} €) ist gering "
            "(< 15 % der Restschuld). Der Ratenkredit schont die Kapitalanlage und ist hier sinnvoll."
        )
    else:
        st.info(
            "Beide Optionen sind plausibel. Der vollständige Vergleich "
            "(inkl. Steuerwirkung und Pool-Rendite) erscheint im Tab "
            "**💡 Entnahme-Optimierung** im Jahresverlauf."
        )


def render(T: dict, _rc: int) -> None:
    with T["Hypothek"]:
        st.header("🏠 Hypothek")

        if "hyp_daten" not in st.session_state:
            st.session_state["hyp_daten"] = _default_hyp_daten()

        d = st.session_state["hyp_daten"]

        if not d.get("aktiv", False):
            # ── Erfassungsformular ─────────────────────────────────────────────
            st.info("Noch keine Hypothek erfasst. Daten eingeben und speichern.")
            with st.form(f"rc{_rc}_hyp_form"):
                st.subheader("Hypothek erfassen")
                fa, fb = st.columns(2)
                with fa:
                    startjahr = st.number_input(
                        "Startjahr", AKTUELLES_JAHR - 30, AKTUELLES_JAHR + 30,
                        value=int(d.get("startjahr", AKTUELLES_JAHR)), step=1,
                        key=f"rc{_rc}_hyp_startjahr_f",
                    )
                    betrag = st.number_input(
                        "Darlehensbetrag (€)", 0.0, 10_000_000.0,
                        value=float(d.get("betrag", 300_000.0)),
                        step=5_000.0, key=f"rc{_rc}_hyp_betrag_f",
                    )
                    zins_pct = st.number_input(
                        "Nominalzins p.a. (%)", 0.0, 20.0,
                        value=float(d.get("zins_pa", 0.035)) * 100,
                        step=0.05, format="%.2f", key=f"rc{_rc}_hyp_zins_f",
                    )
                with fb:
                    endjahr = st.number_input(
                        "Endjahr (Planungshorizont)", AKTUELLES_JAHR, AKTUELLES_JAHR + 50,
                        value=int(d.get("endjahr", AKTUELLES_JAHR + 20)), step=1,
                        key=f"rc{_rc}_hyp_endjahr_f",
                    )
                    jaehrl_rate = st.number_input(
                        "Jährl. Annuitätsrate (€/Jahr)", 0.0, 1_000_000.0,
                        value=float(d.get("jaehrl_rate", 15_000.0)),
                        step=500.0, key=f"rc{_rc}_hyp_rate_f",
                    )
                raten_in_sim = st.checkbox(
                    "Laufende Raten in Entnahme-Simulation berücksichtigen",
                    value=bool(d.get("raten_in_simulation", False)),
                    key=f"rc{_rc}_hyp_raten_in_sim_f",
                    help="Wenn aktiviert, werden die jährlichen Hypothekraten als Ausgaben "
                         "in der Entnahme-Optimierung abgezogen.",
                )
                submitted = st.form_submit_button("💾 Hypothek speichern", use_container_width=True)
                if submitted:
                    _errs = _validate_hyp(int(startjahr), int(endjahr), float(betrag), float(jaehrl_rate))
                    if _errs:
                        for _e in _errs:
                            st.error(_e)
                    else:
                        st.session_state["hyp_daten"] = {
                            **_default_hyp_daten(),
                            "aktiv": True,
                            "startjahr": int(startjahr),
                            "endjahr": int(endjahr),
                            "betrag": float(betrag),
                            "jaehrl_rate": float(jaehrl_rate),
                            "zins_pa": float(zins_pct) / 100.0,
                            "sondertilgungen": d.get("sondertilgungen", []),
                            "raten_in_simulation": bool(raten_in_sim),
                        }
                        st.rerun()
            return

        # ── Hypothek aktiv: Anzeige ────────────────────────────────────────────
        schedule = get_hyp_schedule()
        endjahr = int(d.get("endjahr", AKTUELLES_JAHR + 20))

        # Kennzahlen
        gesamtzinsen = sum(r["Zinsen"] for r in schedule)
        gesamtausgaben = sum(r["Jahresausgabe"] for r in schedule)
        restschuld_end = schedule[-1]["Restschuld_Ende"] if schedule else float(d.get("betrag", 0))

        tilgungsdauer = "nach Endjahr"
        for r in schedule:
            if r["Restschuld_Ende"] <= 0.0:
                tilgungsdauer = str(r["Jahr"])
                break

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Darlehensbetrag", f"{_de(d['betrag'])} €")
        m2.metric("Restschuld am Endjahr", f"{_de(restschuld_end)} €",
                  delta=f"{_de(restschuld_end - d['betrag'])} €" if restschuld_end > 0 else None,
                  delta_color="inverse")
        m3.metric("Gesamtzinsen", f"{_de(gesamtzinsen)} €")
        m4.metric("Tilgungsdauer", tilgungsdauer)

        if restschuld_end > 0.0:
            st.warning(
                f"Am Ende des Planungszeitraums ({endjahr}) verbleibt eine Restschuld von "
                f"**{_de(restschuld_end)} €**. Siehe Abschnitt Restschuld-Behandlung unten."
            )

        st.divider()

        # ── Restschuld-Verlauf ─────────────────────────────────────────────────
        st.subheader("Restschuldverlauf")
        if schedule:
            _jahre = [r["Jahr"] for r in schedule]
            _rs_end = [r["Restschuld_Ende"] for r in schedule]
            _zinsen = [r["Zinsen"] for r in schedule]
            _tilgung = [r["Tilgung"] + r["Sondertilgung"] for r in schedule]

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                name="Restschuld", x=_jahre, y=_rs_end,
                mode="lines+markers", line=dict(color="#EF5350", width=2),
                hovertemplate="%{x}: %{y:,.0f} €<extra>Restschuld</extra>",
            ))
            fig.add_trace(go.Bar(
                name="Zinsen", x=_jahre, y=_zinsen,
                marker_color="#FFA726", opacity=0.7,
                hovertemplate="%{x}: %{y:,.0f} €<extra>Zinsen</extra>",
                yaxis="y2",
            ))
            fig.add_trace(go.Bar(
                name="Tilgung (inkl. Sonder)", x=_jahre, y=_tilgung,
                marker_color="#66BB6A", opacity=0.7,
                hovertemplate="%{x}: %{y:,.0f} €<extra>Tilgung</extra>",
                yaxis="y2",
            ))
            fig.update_layout(
                template="plotly_white", height=360,
                barmode="stack",
                xaxis=dict(title="Jahr", dtick=2),
                yaxis=dict(title="Restschuld (€)", tickformat=",.0f"),
                yaxis2=dict(title="Jahresbetrag (€)", overlaying="y", side="right",
                            tickformat=",.0f", showgrid=False),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=10, r=10, t=40, b=10),
                separators=",.",
            )
            st.plotly_chart(fig, use_container_width=True)

        # ── Tilgungsplan (Expander) ────────────────────────────────────────────
        with st.expander("📋 Tilgungsplan anzeigen"):
            if schedule:
                import pandas as pd
                _df = pd.DataFrame(schedule)
                _df_fmt = pd.DataFrame({
                    "Jahr": _df["Jahr"].astype(str),
                    "Restschuld Anfang (€)": _df["Restschuld_Anfang"].map(lambda v: _de(v)),
                    "Zinsen (€)": _df["Zinsen"].map(lambda v: _de(v)),
                    "Tilgung (€)": _df["Tilgung"].map(lambda v: _de(v)),
                    "Sondertilgung (€)": _df["Sondertilgung"].map(lambda v: _de(v)),
                    "Jahresausgabe (€)": _df["Jahresausgabe"].map(lambda v: _de(v)),
                    "Restschuld Ende (€)": _df["Restschuld_Ende"].map(lambda v: _de(v)),
                })
                st.dataframe(_df_fmt.set_index("Jahr"), use_container_width=True)

        st.divider()

        # ── Sondertilgungen ────────────────────────────────────────────────────
        st.subheader("Einmalrückzahlungen erfassen")
        sondertilgungen = list(d.get("sondertilgungen", []))

        for i, s in enumerate(sondertilgungen):
            sc1, sc2, sc3 = st.columns([2, 3, 1])
            with sc1:
                new_jahr = sc1.number_input(
                    "Jahr", AKTUELLES_JAHR - 30, AKTUELLES_JAHR + 50,
                    value=int(s["jahr"]), step=1,
                    key=f"rc{_rc}_hyp_st_j_{i}",
                )
            with sc2:
                new_betrag = sc2.number_input(
                    "Betrag (€)", 0.0, 10_000_000.0,
                    value=float(s["betrag"]), step=1_000.0,
                    key=f"rc{_rc}_hyp_st_b_{i}",
                )
            with sc3:
                sc3.write("")
                sc3.write("")
                if sc3.button("🗑", key=f"rc{_rc}_hyp_st_del_{i}",
                              help="Sondertilgung entfernen"):
                    sondertilgungen.pop(i)
                    st.session_state["hyp_daten"]["sondertilgungen"] = sondertilgungen
                    st.rerun()
            sondertilgungen[i] = {"jahr": int(new_jahr), "betrag": float(new_betrag)}

        if st.button("➕ Sondertilgung hinzufügen", key=f"rc{_rc}_hyp_st_add"):
            sondertilgungen.append({"jahr": AKTUELLES_JAHR, "betrag": 10_000.0})
            st.session_state["hyp_daten"]["sondertilgungen"] = sondertilgungen
            st.rerun()

        if sondertilgungen != d.get("sondertilgungen", []):
            st.session_state["hyp_daten"]["sondertilgungen"] = sondertilgungen

        st.divider()

        # ── Restschuld-Behandlung (nur wenn Restschuld > 0) ───────────────────
        if restschuld_end > 0.0:
            _restschuld_vergleich_ui(restschuld_end, endjahr, d, _rc)
            st.divider()

        # ── Parameter bearbeiten ───────────────────────────────────────────────
        with st.expander("⚙️ Hypothekdaten bearbeiten"):
            with st.form(f"rc{_rc}_hyp_edit_form"):
                ea, eb = st.columns(2)
                with ea:
                    e_startjahr = st.number_input(
                        "Startjahr", AKTUELLES_JAHR - 30, AKTUELLES_JAHR + 30,
                        value=int(d.get("startjahr", AKTUELLES_JAHR)), step=1,
                        key=f"rc{_rc}_hyp_e_startjahr",
                    )
                    e_betrag = st.number_input(
                        "Darlehensbetrag (€)", 0.0, 10_000_000.0,
                        value=float(d.get("betrag", 300_000.0)),
                        step=5_000.0, key=f"rc{_rc}_hyp_e_betrag",
                    )
                    e_zins = st.number_input(
                        "Nominalzins p.a. (%)", 0.0, 20.0,
                        value=float(d.get("zins_pa", 0.035)) * 100,
                        step=0.05, format="%.2f", key=f"rc{_rc}_hyp_e_zins",
                    )
                with eb:
                    e_endjahr = st.number_input(
                        "Endjahr", AKTUELLES_JAHR, AKTUELLES_JAHR + 50,
                        value=int(d.get("endjahr", AKTUELLES_JAHR + 20)), step=1,
                        key=f"rc{_rc}_hyp_e_endjahr",
                    )
                    e_rate = st.number_input(
                        "Jährl. Annuitätsrate (€/Jahr)", 0.0, 1_000_000.0,
                        value=float(d.get("jaehrl_rate", 15_000.0)),
                        step=500.0, key=f"rc{_rc}_hyp_e_rate",
                    )
                e_raten_in_sim = st.checkbox(
                    "Laufende Raten in Entnahme-Simulation berücksichtigen",
                    value=bool(d.get("raten_in_simulation", False)),
                    key=f"rc{_rc}_hyp_e_raten_in_sim",
                    help="Wenn aktiviert, werden die jährlichen Hypothekraten als Ausgaben "
                         "in der Entnahme-Optimierung abgezogen.",
                )
                e_submitted = st.form_submit_button("💾 Änderungen speichern",
                                                    use_container_width=True)
                if e_submitted:
                    _errs = _validate_hyp(int(e_startjahr), int(e_endjahr),
                                          float(e_betrag), float(e_rate))
                    if _errs:
                        for _e in _errs:
                            st.error(_e)
                    else:
                        st.session_state["hyp_daten"].update({
                            "startjahr": int(e_startjahr),
                            "endjahr": int(e_endjahr),
                            "betrag": float(e_betrag),
                            "jaehrl_rate": float(e_rate),
                            "zins_pa": float(e_zins) / 100.0,
                            "raten_in_simulation": bool(e_raten_in_sim),
                        })
                        st.rerun()

        if st.button("🗑 Hypothek löschen", key=f"rc{_rc}_hyp_del",
                     type="secondary"):
            st.session_state["hyp_daten"] = _default_hyp_daten()
            st.rerun()
