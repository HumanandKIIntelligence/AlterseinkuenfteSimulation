"""Tests für Hilfsmodule: session_io.py und reine Helferfunktionen in tabs/."""

import sys
import os
import tempfile
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import session_io
from session_io import save_session, load_session, list_saves, _load_profil, _PROFIL_LADE_DEFAULTS
from engine import Profil, AKTUELLES_JAHR
from tabs.entnahme_opt import _kv_label_und_wert, _steuer_steckbrief, _de, _analyse_schenkungspotenzial


# ─────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────────────────────

def _profil(**kw) -> Profil:
    defaults = dict(
        geburtsjahr=1965, renteneintritt_alter=67,
        aktuelle_punkte=30.0, punkte_pro_jahr=1.0,
        zusatz_monatlich=0.0, sparkapital=0.0, sparrate=0.0,
        rendite_pa=0.0, rentenanpassung_pa=0.0,
        krankenversicherung="GKV", pkv_beitrag=0.0,
        gkv_zusatzbeitrag=0.017, kinder=True,
    )
    defaults.update(kw)
    return Profil(**defaults)


def _prod_dict(typ: str = "bAV", person: str = "Person 1", vbeg: int = 2010) -> dict:
    return {
        "name": f"Test {typ}",
        "typ": typ,
        "typ_label": typ,
        "person": person,
        "vertragsbeginn": vbeg,
        "teilfreistellung": 0.30,
    }


# ─────────────────────────────────────────────────────────────────────────────
# session_io – Speichern, Laden, Rückwärtskompatibilität
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionIO:
    def test_roundtrip_einzelprofil(self):
        """save_session + load_session ergibt identisches Profil."""
        p1 = _profil(geburtsjahr=1970, aktuelle_punkte=28.5)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(session_io, "DATA_DIR", tmp):
                path = save_session("roundtrip", p1, None, "Getrennt", [], 500.0, 0.02)
                loaded = load_session(path)
        assert loaded["profil1"].geburtsjahr == p1.geburtsjahr
        assert loaded["profil1"].aktuelle_punkte == p1.aktuelle_punkte
        assert loaded["mieteinnahmen"] == pytest.approx(500.0)
        assert loaded["mietsteigerung"] == pytest.approx(0.02)
        assert loaded["profil2"] is None

    def test_roundtrip_mit_partner(self):
        """Partner-Profil übersteht den Speicherrundgang vollständig."""
        p1 = _profil(geburtsjahr=1968)
        p2 = _profil(geburtsjahr=1972, krankenversicherung="PKV", pkv_beitrag=650.0)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(session_io, "DATA_DIR", tmp):
                path = save_session("paar", p1, p2, "Zusammen", [], 0.0, 0.0)
                loaded = load_session(path)
        assert loaded["profil2"].geburtsjahr == 1972
        assert loaded["profil2"].krankenversicherung == "PKV"
        assert loaded["profil2"].pkv_beitrag == pytest.approx(650.0)
        assert loaded["veranlagung"] == "Zusammen"

    def test_backward_compat_fehlende_felder_ergaenzt(self):
        """_load_profil ergänzt Felder die in alten Speicherständen fehlen."""
        altes_json = {
            "geburtsjahr": 1960, "renteneintritt_alter": 67,
            "aktuelle_punkte": 30.0, "punkte_pro_jahr": 1.0,
            "zusatz_monatlich": 0.0, "sparkapital": 0.0, "sparrate": 0.0,
            "rendite_pa": 0.0, "rentenanpassung_pa": 0.0,
            "krankenversicherung": "GKV", "pkv_beitrag": 0.0,
            "gkv_zusatzbeitrag": 0.017, "kinder": True,
            # kvdr_pflicht, kirchensteuer etc. fehlen absichtlich
        }
        p = _load_profil(altes_json)
        assert p.kvdr_pflicht  == _PROFIL_LADE_DEFAULTS["kvdr_pflicht"]
        assert p.kirchensteuer == _PROFIL_LADE_DEFAULTS["kirchensteuer"]
        assert p.ist_pensionaer == _PROFIL_LADE_DEFAULTS["ist_pensionaer"]
        assert p.bereits_rentner == _PROFIL_LADE_DEFAULTS["bereits_rentner"]

    def test_list_saves_leer_wenn_kein_verzeichnis(self):
        with tempfile.TemporaryDirectory() as tmp:
            nicht_existierend = os.path.join(tmp, "nirgendwo")
            with patch.object(session_io, "DATA_DIR", nicht_existierend):
                assert list_saves() == []

    def test_list_saves_findet_gespeicherte_profile(self):
        p1 = _profil()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(session_io, "DATA_DIR", tmp):
                save_session("alpha", p1, None, "Getrennt", [], 0.0, 0.0)
                save_session("beta",  p1, None, "Getrennt", [], 0.0, 0.0)
                saves = list_saves()
        namen = [name for name, _ in saves]
        assert "alpha" in namen
        assert "beta" in namen

    def test_safe_name_filtert_sonderzeichen(self):
        """Sonderzeichen im Profil-Namen werden beim Dateinamen entfernt."""
        p1 = _profil()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(session_io, "DATA_DIR", tmp):
                path = save_session("Müller & Co. 2024!", p1, None, "Getrennt", [], 0.0, 0.0)
        dateiname = os.path.basename(path)
        assert "&" not in dateiname
        assert " " not in dateiname
        assert "!" not in dateiname


# ─────────────────────────────────────────────────────────────────────────────
# _kv_label_und_wert – KV-Spalte im Steuerbrief
# ─────────────────────────────────────────────────────────────────────────────

class TestKvLabelUndWert:
    def _profil_kvdr(self) -> Profil:
        return _profil(krankenversicherung="GKV", kvdr_pflicht=True)

    def _profil_freiwillig(self) -> Profil:
        return _profil(krankenversicherung="GKV", kvdr_pflicht=False)

    def _profil_pkv(self) -> Profil:
        return _profil(krankenversicherung="PKV", pkv_beitrag=650.0)

    def test_pkv_spalte_kv_wert_strich(self):
        col, val = _kv_label_und_wert("bAV", 2010, 0.30, self._profil_pkv())
        assert col == "KV"
        assert val == "–"

    def test_kvdr_bav_ja_mit_freibetrag(self):
        col, val = _kv_label_und_wert("bAV", 2010, 0.30, self._profil_kvdr())
        assert col == "KVdR-pflichtig"
        assert "187" in val          # Freibetrag-Betrag

    def test_kvdr_riester_nein(self):
        col, val = _kv_label_und_wert("Riester", 2010, 0.30, self._profil_kvdr())
        assert col == "KVdR-pflichtig"
        assert val == "Nein"

    def test_freiwillig_bav_ohne_freibetrag(self):
        col, val = _kv_label_und_wert("bAV", 2010, 0.30, self._profil_freiwillig())
        assert col == "KV-pflichtig (§240)"
        assert "240" in val          # freiwillig §240-Hinweis, kein Freibetrag

    def test_freiwillig_privatrente_pflichtig(self):
        col, val = _kv_label_und_wert("PrivateRente", 2010, 0.30, self._profil_freiwillig())
        assert col == "KV-pflichtig (§240)"
        assert val != "Nein"

    def test_kvdr_privatrente_nicht_pflichtig(self):
        col, val = _kv_label_und_wert("PrivateRente", 2010, 0.30, self._profil_kvdr())
        assert col == "KVdR-pflichtig"
        assert val == "Nein"


# ─────────────────────────────────────────────────────────────────────────────
# _steuer_steckbrief – DataFrame-Aufbau, KV-Spaltenlogik
# ─────────────────────────────────────────────────────────────────────────────

class TestSteuerSteckbrief:
    def test_leere_liste_leeres_dataframe(self):
        p = _profil()
        df = _steuer_steckbrief([], p)
        assert df.empty

    def test_alle_kvdr_eine_spalte(self):
        """Alle Produkte auf KVdR-Person → eine KV-Spalte 'KVdR-pflichtig'."""
        p = _profil(krankenversicherung="GKV", kvdr_pflicht=True)
        prods = [_prod_dict("bAV"), _prod_dict("Riester")]
        df = _steuer_steckbrief(prods, p)
        assert "KVdR-pflichtig" in df.columns
        assert "KV-Status" not in df.columns

    def test_alle_pkv_kv_spalte(self):
        """Alle Produkte auf PKV-Person → eine KV-Spalte 'KV'."""
        p = _profil(krankenversicherung="PKV", pkv_beitrag=650.0)
        prods = [_prod_dict("bAV"), _prod_dict("ETF")]
        df = _steuer_steckbrief(prods, p)
        assert "KV" in df.columns

    def test_gemischt_p1_kvdr_p2_pkv_kv_status_spalte(self):
        """P1 KVdR + P2 PKV → gemischte KV-Spalte 'KV-Status'."""
        p1 = _profil(krankenversicherung="GKV", kvdr_pflicht=True)
        p2 = _profil(krankenversicherung="PKV", pkv_beitrag=650.0)
        prods = [
            _prod_dict("bAV", person="Person 1"),
            _prod_dict("bAV", person="Person 2"),
        ]
        df = _steuer_steckbrief(prods, p1, profil2=p2)
        assert "KV-Status" in df.columns
        assert "KVdR-pflichtig" not in df.columns

    def test_spalten_vorhanden(self):
        p = _profil()
        df = _steuer_steckbrief([_prod_dict("bAV")], p)
        for col in ("Produkt", "Typ", "Person", "Einmalauszahlung", "Monatsrente"):
            assert col in df.columns


# ─────────────────────────────────────────────────────────────────────────────
# _de – Deutsche Zahlenformatierung (Punkt als Tausender, Komma als Dezimal)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# _analyse_schenkungspotenzial – Schenkungsanalyse GKV ↔ PKV
# ─────────────────────────────────────────────────────────────────────────────

class TestSchenkungsanalyse:
    def _prod(self, typ: str, person: str = "Person 1",
              mono: float = 0.0, einmal: float = 0.0, lfd: float = 0.0) -> dict:
        return {
            "name": f"Test {typ}", "typ": typ, "typ_label": typ,
            "person": person, "vertragsbeginn": 2010, "teilfreistellung": 0.30,
            "max_monatsrente": mono, "max_einmalzahlung": einmal,
            "laufende_kapitalertraege_mono": lfd,
        }

    def _p_freiwillig(self) -> Profil:
        return _profil(krankenversicherung="GKV", kvdr_pflicht=False,
                       gkv_zusatzbeitrag=0.017, kinder=True)

    def _p_kvdr(self) -> Profil:
        return _profil(krankenversicherung="GKV", kvdr_pflicht=True,
                       gkv_zusatzbeitrag=0.017, kinder=True)

    def _p_pkv(self) -> Profil:
        return _profil(krankenversicherung="PKV", pkv_beitrag=600.0)

    def test_beide_gkv_gibt_none(self):
        """Beide GKV → keine gemischte Konstellation → None."""
        assert _analyse_schenkungspotenzial([], self._p_freiwillig(), self._p_kvdr()) is None

    def test_beide_pkv_gibt_none(self):
        """Beide PKV → None."""
        assert _analyse_schenkungspotenzial([], self._p_pkv(), self._p_pkv()) is None

    def test_kein_partner_gibt_none(self):
        """Kein Partner → None."""
        assert _analyse_schenkungspotenzial([], self._p_freiwillig(), None) is None

    def test_bav_nicht_verschiebbar(self):
        """bAV geht in nicht_verschiebbar (§ 1 BetrAVG)."""
        prod = self._prod("bAV", mono=500.0)
        result = _analyse_schenkungspotenzial([prod], self._p_freiwillig(), self._p_pkv())
        assert result is not None
        assert any(r["Vertrag"] == "Test bAV" for r in result["nicht_verschiebbar"])
        assert all(r["Vertrag"] != "Test bAV" for r in result["zu_verschieben"])

    def test_ruerup_nicht_verschiebbar(self):
        """Rürup geht in nicht_verschiebbar (§ 97 EStG)."""
        prod = self._prod("Rürup", mono=300.0)
        result = _analyse_schenkungspotenzial([prod], self._p_freiwillig(), self._p_pkv())
        assert any(r["Vertrag"] == "Test Rürup" for r in result["nicht_verschiebbar"])
        assert all(r["Vertrag"] != "Test Rürup" for r in result["zu_verschieben"])

    def test_privaterente_freiwillig_korrekte_ersparnis(self):
        """PrivateRente unter §240: KV-Ersparnis = mono × 12 × (0,146 + zusatz + pv_voll)."""
        prod = self._prod("PrivateRente", mono=500.0)
        result = _analyse_schenkungspotenzial([prod], self._p_freiwillig(), self._p_pkv())
        assert result["hat_empfehlung"]
        expected = 500 * 12 * (0.146 + 0.017 + 0.034)
        assert result["gesamt_ersparnis_pa"] == pytest.approx(expected, rel=1e-6)

    def test_privaterente_kvdr_keine_ersparnis(self):
        """PrivateRente unter KVdR: nicht KV-pflichtig → gesamt_ersparnis_pa == 0."""
        prod = self._prod("PrivateRente", mono=500.0)
        result = _analyse_schenkungspotenzial([prod], self._p_kvdr(), self._p_pkv())
        assert not result["hat_empfehlung"]
        assert result["gesamt_ersparnis_pa"] == pytest.approx(0.0)

    def test_p2_ist_gkv_korrekte_zuweisung(self):
        """Wenn P2 GKV hat, werden P2-Produkte analysiert und P2 als gkv_label gesetzt."""
        prod = self._prod("PrivateRente", person="Person 2", mono=400.0)
        result = _analyse_schenkungspotenzial([prod], self._p_pkv(), self._p_freiwillig())
        assert result["gkv_label"] == "Person 2"
        assert result["pkv_label"] == "Person 1"
        assert result["gesamt_ersparnis_pa"] > 0

    def test_etf_lfd_ertraege_kv_pflichtig_freiwillig(self):
        """ETF-laufende Erträge sind unter §240 KV-pflichtig."""
        prod = self._prod("ETF", lfd=200.0)
        result = _analyse_schenkungspotenzial([prod], self._p_freiwillig(), self._p_pkv())
        expected = 200 * 12 * (0.146 + 0.017 + 0.034)
        assert result["gesamt_ersparnis_pa"] == pytest.approx(expected, rel=1e-6)

    def test_riester_mit_altzertg_hinweis(self):
        """Riester ist übertragbar, aber mit §6-AltZertG-Einschränkung im Hinweis."""
        prod = self._prod("Riester", mono=300.0)
        result = _analyse_schenkungspotenzial([prod], self._p_freiwillig(), self._p_pkv())
        riester_row = next(r for r in result["zu_verschieben"] if r["Vertrag"] == "Test Riester")
        assert "AltZertG" in riester_row["Hinweis"]

    def test_pkv_person_produkte_werden_ignoriert(self):
        """Produkte der PKV-Person werden nicht in die Analyse einbezogen."""
        prod_pkv = self._prod("PrivateRente", person="Person 1", mono=500.0)
        result = _analyse_schenkungspotenzial([prod_pkv], self._p_pkv(), self._p_freiwillig())
        assert result["gesamt_ersparnis_pa"] == pytest.approx(0.0)
        assert result["zu_verschieben"] == []

    def test_kvdr_verbleibender_freibetrag_korrekt(self):
        """KVdR: verbleibender bAV-Freibetrag wird korrekt berechnet."""
        from engine import BAV_FREIBETRAG_MONATLICH
        prod = self._prod("bAV", mono=100.0)
        result = _analyse_schenkungspotenzial([prod], self._p_kvdr(), self._p_pkv())
        assert result["verbleibender_freibetrag_bav_mono"] == pytest.approx(
            BAV_FREIBETRAG_MONATLICH - 100.0
        )


class TestDeFormatierung:
    def test_tausendertrennzeichen_punkt(self):
        assert _de(1_234_567.0) == "1.234.567"

    def test_komma_als_dezimaltrennzeichen(self):
        assert _de(1_234.5, dec=1) == "1.234,5"

    def test_ohne_dezimalstellen(self):
        assert _de(999.9) == "1.000"   # gerundet

    def test_null(self):
        assert _de(0.0) == "0"

    def test_negative_zahl(self):
        result = _de(-1_500.0)
        assert "1.500" in result
