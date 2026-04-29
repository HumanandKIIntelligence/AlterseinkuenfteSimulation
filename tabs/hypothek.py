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
        # Restschuld-Strategie
        "restschuld_behandlung": "keine",   # "keine", "ratenkredit", "kapitalanlage", "einmalzahlungen"
        "anschluss_zins_pa": 0.04,
        "anschluss_laufzeit": 10,
        "raten_aus_kapital": False,
        "anschluss_einmalzahlungen": [],
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
        elif behandlung == "einmalzahlungen":
            zins = float(d.get("anschluss_zins_pa", 0.04))
            laufzeit = int(d.get("anschluss_laufzeit", 10))
            plan = _ez_ausgaben_plan(
                list(d.get("anschluss_einmalzahlungen", [])),
                get_hyp_schedule(), restschuld, endjahr, zins, laufzeit,
            )

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
        "restschuld_behandlung": d.get("restschuld_behandlung", "keine"),
        "raten_aus_kapital": bool(d.get("raten_aus_kapital", False)),
        "anschluss_einmalzahlungen": list(d.get("anschluss_einmalzahlungen", [])),
    }


def _ez_ausgaben_plan(
    einmalzahlungen: list[dict],
    hyp_schedule: list[dict],
    restschuld_endjahr: float,
    endjahr: int,
    markt_zins_pa: float,
    anschluss_lz: int,
) -> dict[int, float]:
    """Ausgaben-Plan für Einmalzahlungs-Strategie: laufende Raten + EZ + Anschlusskredit auf Rest."""
    def _rate(k: float, z: float, n: int) -> float:
        if n <= 0 or k <= 0:
            return 0.0
        return k / n if z <= 0 else k * z * (1 + z) ** n / ((1 + z) ** n - 1)

    plan: dict[int, float] = {}
    for row in hyp_schedule:
        plan[row["Jahr"]] = plan.get(row["Jahr"], 0.0) + row["Jahresausgabe"]

    sorted_ezl = sorted(einmalzahlungen, key=lambda e: e["jahr"])
    for e in sorted_ezl:
        plan[e["jahr"]] = plan.get(e["jahr"], 0.0) + float(e["betrag"])

    primary_sum = sum(float(e["betrag"]) for e in sorted_ezl if int(e["jahr"]) <= endjahr)
    ak_bal = max(0.0, restschuld_endjahr - primary_sum)
    if ak_bal <= 0.01 or anschluss_lz <= 0:
        return plan

    ak_payments = sorted(
        [(int(e["jahr"]), float(e["betrag"])) for e in sorted_ezl if int(e["jahr"]) > endjahr],
        key=lambda x: x[0],
    )
    ak_start_yr, years_used, pidx = endjahr, 0, 0
    while ak_bal > 0.01 and years_used < anschluss_lz:
        lz_rem = anschluss_lz - years_used
        rate = _rate(ak_bal, markt_zins_pa, lz_rem)
        next_ep_yr = ak_payments[pidx][0] if pidx < len(ak_payments) else endjahr + anschluss_lz + 1
        seg_end = min(next_ep_yr, endjahr + anschluss_lz)
        for yr in range(ak_start_yr + 1, seg_end + 1):
            if ak_bal <= 0.01 or years_used >= anschluss_lz:
                break
            plan[yr] = plan.get(yr, 0.0) + rate
            ak_bal = max(0.0, ak_bal - max(0.0, rate - ak_bal * markt_zins_pa))
            years_used += 1
        if pidx < len(ak_payments) and ak_payments[pidx][0] == seg_end:
            ak_bal = max(0.0, ak_bal - ak_payments[pidx][1])
            ak_start_yr = ak_payments[pidx][0]
            pidx += 1
        else:
            break
    return plan


def get_ausgaben_plan_optimierung(sondertilgung_endjahr: float = 0.0) -> dict[int, float]:
    """Ausgaben-Plan für Entnahme-Optimierung: laufende Raten + konfigurierte Restschuld-Strategie.

    sondertilgung_endjahr: Geplante Einmaltilgung im Endjahr (z.B. aus Kapital-Entnahmen im
    Entnahme-Tab), die die Restschuld für die Anschlussfinanzierung reduziert.
    """
    d = st.session_state.get("hyp_daten", {})
    if not d.get("aktiv", False):
        return {}

    plan: dict[int, float] = {}
    for row in get_hyp_schedule():
        plan[row["Jahr"]] = plan.get(row["Jahr"], 0.0) + row["Jahresausgabe"]

    restschuld = get_restschuld_end()
    if restschuld <= 0.0:
        return plan

    # Effektive Restschuld nach geplanter Sondertilgung im Endjahr
    eff_rs = max(0.0, restschuld - sondertilgung_endjahr)

    behandlung = d.get("restschuld_behandlung", "keine")
    endjahr = int(d.get("endjahr", AKTUELLES_JAHR + 20))
    zins = float(d.get("anschluss_zins_pa", 0.04))
    laufzeit = int(d.get("anschluss_laufzeit", 10))

    if behandlung == "kapitalanlage":
        if eff_rs > 0.0:
            plan[endjahr] = plan.get(endjahr, 0.0) + eff_rs
    elif behandlung == "ratenkredit":
        if eff_rs > 0.0:
            rate = _annuitaet_rate(eff_rs, zins, laufzeit)
            for i in range(laufzeit):
                plan[endjahr + 1 + i] = plan.get(endjahr + 1 + i, 0.0) + rate
    elif behandlung == "einmalzahlungen":
        plan = _ez_ausgaben_plan(
            list(d.get("anschluss_einmalzahlungen", [])),
            get_hyp_schedule(), restschuld, endjahr, zins, laufzeit,
        )
    return plan


def _restschuld_vergleich_ui(restschuld: float, endjahr: int, d: dict, _rc: int) -> None:
    """Strategie für die verbleibende Restschuld nach Hypothek-Endjahr."""
    st.subheader("⚖️ Restschuld-Strategie")

    _opts = ["keine", "ratenkredit", "kapitalanlage", "einmalzahlungen"]
    _cur = d.get("restschuld_behandlung", "keine")
    if _cur not in _opts:
        _cur = "keine"
    behandlung = st.radio(
        "Strategie",
        _opts,
        format_func=lambda x: {
            "keine":           "⬜ Keine Planung (Restschuld offen lassen)",
            "ratenkredit":     "🏦 Anschluss-Ratenkredit",
            "kapitalanlage":   "💰 Einmalige Kapital-Tilgung (im Endjahr aus Pool)",
            "einmalzahlungen": "📅 Sondertilgungen (Einmalzahlungen, Rest als Anschlusskredit)",
        }[x],
        index=_opts.index(_cur),
        key=f"rc{_rc}_hyp_behandlung",
    )
    st.session_state["hyp_daten"]["restschuld_behandlung"] = behandlung

    anschluss_zins = float(d.get("anschluss_zins_pa", 0.04))
    anschluss_laufzeit = int(d.get("anschluss_laufzeit", 10))

    if behandlung in ("ratenkredit", "einmalzahlungen"):
        rc1, rc2 = st.columns(2)
        with rc1:
            anschluss_zins_pct = st.number_input(
                "Zinssatz Anschluss (%)", 0.0, 20.0,
                value=anschluss_zins * 100, step=0.05, format="%.2f",
                key=f"rc{_rc}_hyp_anschl_zins",
            )
            anschluss_zins = anschluss_zins_pct / 100.0
            st.session_state["hyp_daten"]["anschluss_zins_pa"] = anschluss_zins
        with rc2:
            anschluss_laufzeit = st.number_input(
                "Laufzeit (Jahre)", 1, 30,
                value=anschluss_laufzeit, step=1,
                key=f"rc{_rc}_hyp_anschl_lz",
            )
            st.session_state["hyp_daten"]["anschluss_laufzeit"] = int(anschluss_laufzeit)

    if behandlung == "ratenkredit":
        rate_j = _annuitaet_rate(restschuld, anschluss_zins, anschluss_laufzeit)
        zinslast = rate_j * anschluss_laufzeit - restschuld
        st.info(
            f"Jahresrate: **{_de(rate_j)} €** ({_de(rate_j / 12, 0)} €/Mon.) · "
            f"Laufzeit: {anschluss_laufzeit} J. ab {endjahr + 1} · "
            f"Gesamtzinslast: {_de(zinslast)} €",
            icon="🏦",
        )
        raten_aus_kapital = st.checkbox(
            "💳 Raten vorrangig aus Kapital decken (wenn ausreichend)",
            value=bool(d.get("raten_aus_kapital", False)),
            key=f"rc{_rc}_hyp_raten_kapital",
            help="Anschluss-Raten werden vorrangig aus dem Sparkapital gedeckt. "
                 "Reicht das Kapital nicht, übernimmt das laufende Einkommen.",
        )
        st.session_state["hyp_daten"]["raten_aus_kapital"] = raten_aus_kapital

    elif behandlung == "kapitalanlage":
        st.info(
            f"Am Endjahr {endjahr} wird die Restschuld **{_de(restschuld)} €** "
            "einmalig aus dem Kapitalanlage-Pool entnommen. "
            "Ein Fehlbetrag (Pool < Restschuld) verringert das verfügbare Netto.",
            icon="💰",
        )

    elif behandlung == "einmalzahlungen":
        ezl: list[dict] = list(d.get("anschluss_einmalzahlungen", []))
        if ezl:
            _total_ez = sum(float(e["betrag"]) for e in ezl)
            _ak_rs = max(0.0, restschuld - sum(
                float(e["betrag"]) for e in ezl if int(e["jahr"]) <= endjahr
            ))
            if _ak_rs < 0.01:
                st.caption(f"✅ Sondertilgungen ({len(ezl)}×) decken Restschuld **{_de(restschuld)} €** vollständig.")
            else:
                st.caption(
                    f"Sondertilgungen: **{_de(_total_ez)} €** · "
                    f"Anschlusskredit auf **{_de(_ak_rs)} €** ab {endjahr + 1} "
                    f"({anschluss_zins * 100:.2f} %, {anschluss_laufzeit} J.)"
                )
        else:
            st.caption("↑ Sondertilgungen im Abschnitt **Sondertilgungen erfassen** oben hinzufügen.")



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
        st.subheader("Sondertilgungen erfassen")
        sondertilgungen = list(d.get("sondertilgungen", []))

        def _st_row(lst: list, idx: int, key_pfx: str, session_key: str,
                    max_j: int = AKTUELLES_JAHR + 50) -> None:
            """Rendert eine editierbare Zeile mit Ändern + 🗑 Button."""
            _r1, _r2, _r3, _r4 = st.columns([2, 3, 1, 1])
            with _r1:
                _nj = _r1.number_input("Jahr", AKTUELLES_JAHR - 30, max_j,
                    value=int(lst[idx]["jahr"]), step=1, key=f"{key_pfx}_j_{idx}")
            with _r2:
                _nb = _r2.number_input("Betrag (€)", 0.0, 10_000_000.0,
                    value=float(lst[idx]["betrag"]), step=1_000.0, key=f"{key_pfx}_b_{idx}")
            with _r3:
                _r3.write(""); _r3.write("")
                if _r3.button("Ändern", key=f"{key_pfx}_chg_{idx}", help="Änderung speichern"):
                    lst[idx] = {"jahr": int(_nj), "betrag": float(_nb)}
                    lst.sort(key=lambda e: e["jahr"])
                    st.session_state["hyp_daten"][session_key] = lst
                    st.rerun()
            with _r4:
                _r4.write(""); _r4.write("")
                if _r4.button("🗑", key=f"{key_pfx}_del_{idx}", help="Entfernen"):
                    lst.pop(idx)
                    st.session_state["hyp_daten"][session_key] = lst
                    st.rerun()

        for i in range(len(sondertilgungen)):
            _st_row(sondertilgungen, i, f"rc{_rc}_hyp_st", "sondertilgungen")

        if st.button("➕ Sondertilgung hinzufügen", key=f"rc{_rc}_hyp_st_add"):
            sondertilgungen.append({"jahr": AKTUELLES_JAHR, "betrag": 10_000.0})
            st.session_state["hyp_daten"]["sondertilgungen"] = sondertilgungen
            st.rerun()

        # Validierung: Jahr innerhalb Laufzeit + Betrag ≤ verfügbare Restschuld
        _st_start = int(d.get("startjahr", AKTUELLES_JAHR))
        _st_end   = int(d.get("endjahr",   AKTUELLES_JAHR + 20))
        _sched_by_jahr = {r["Jahr"]: r for r in schedule}
        for _sv in sondertilgungen:
            _sj = int(_sv["jahr"])
            _sb = float(_sv["betrag"])
            if not (_st_start <= _sj <= _st_end):
                st.warning(
                    f"⚠️ Sondertilgung {_sj}: Jahr liegt außerhalb der Kreditlaufzeit "
                    f"({_st_start}–{_st_end})."
                )
            elif _sj in _sched_by_jahr:
                _rs_anfang = _sched_by_jahr[_sj]["Restschuld_Anfang"]
                if _sb > _rs_anfang:
                    st.warning(
                        f"⚠️ Sondertilgung {_sj}: Betrag **{_de(_sb)} €** übersteigt die "
                        f"verfügbare Restschuld von **{_de(_rs_anfang)} €**."
                    )

        # Anschluss-Einmalzahlungen hier anzeigen wenn Restschuld-Strategie = einmalzahlungen
        if d.get("restschuld_behandlung") == "einmalzahlungen":
            _ezl = list(d.get("anschluss_einmalzahlungen", []))
            _endjahr_st = int(d.get("endjahr", AKTUELLES_JAHR + 20))
            _lz_st = int(d.get("anschluss_laufzeit", 10))
            st.caption("**Sondertilgungen Anschlussfinanzierung** (werden auf die Anschluss-Restschuld angerechnet):")
            for _ei in range(len(_ezl)):
                _st_row(_ezl, _ei, f"rc{_rc}_hyp_ez", "anschluss_einmalzahlungen",
                        max_j=_endjahr_st + _lz_st)
            if st.button("➕ Sondertilgung Anschluss hinzufügen", key=f"rc{_rc}_hyp_ez_add2"):
                _ezl.append({"jahr": _endjahr_st, "betrag": 10_000.0})
                st.session_state["hyp_daten"]["anschluss_einmalzahlungen"] = _ezl
                st.rerun()

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
