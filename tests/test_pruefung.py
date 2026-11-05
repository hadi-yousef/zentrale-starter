"""Tests zu den Befunden der Code-Prüfung (S-01 bis R-01). Nur Python, keine Pakete, alles in Testordnern.

  python3 -I -m unittest discover -s tests -v        (Windows: py -I -m unittest discover -s tests -v)

Jeder Test baut den Fehlerfall nach und prüft, dass er nicht mehr auftritt. Dazu gibt es Gegenfälle: Was erlaubt ist,
muss weiter gehen. Nichts außerhalb der Testordner wird angefasst; die Zentrale wird nicht gestartet.
"""
import contextlib
import importlib
import importlib.util
import io
import ipaddress
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HIER = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="zs-test-")).resolve()
os.environ["ZENTRALE_DATEN"] = str(TMP / "daten")
os.environ["ZENTRALE_NOTIZEN"] = str(TMP / "daten" / "notizen")
os.environ["ZENTRALE_SCHLUESSEL_ORDNER"] = str(TMP / "keys")
os.environ["AUFRAEUMEN_PROTOKOLL"] = str(TMP / "protokoll.jsonl")
os.environ["FINANZ_DIR"] = str(TMP / "daten" / "finanzen")
for _p in (HIER / "zentrale", HIER / "aufraeumen", HIER):
    sys.path.insert(0, str(_p))

WIN = os.name == "nt"
ALT = time.time() - 30 * 86400


def alt_machen(p):
    """Datei oder ganzen Baum auf „vor 30 Tagen“ setzen."""
    p = Path(p)
    for d, dirs, files in os.walk(p):
        for x in files + dirs:
            if not os.path.islink(os.path.join(d, x)):
                os.utime(os.path.join(d, x), (ALT, ALT))
    os.utime(p, (ALT, ALT))


def link(ziel, name):
    try:
        os.symlink(ziel, name, target_is_directory=Path(ziel).is_dir())
    except (OSError, NotImplementedError) as e:
        raise unittest.SkipTest(f"Verknüpfung nicht möglich: {e}")


def skript(name, *args, env=None):
    # ohne -I: die Skripte laden ihre Nachbarn (protokoll.py) aus ihrem eigenen Ordner; gestartet wird im Testordner
    e = {k: v for k, v in {**os.environ, **(env or {})}.items() if k != "PYTHONPATH"}
    return subprocess.run([sys.executable, "-B", str(HIER / "aufraeumen" / name), *map(str, args)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=e, cwd=str(TMP))


def neuer_ordner(name):
    d = TMP / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


# ---------- S-01: Titel im Blatt ----------

class S01_TitelAlsText(unittest.TestCase):
    def test_renderSheet_maskiert_titel_und_untertitel(self):
        h = (HIER / "zentrale" / "index.src.html").read_text(encoding="utf-8")
        self.assertIn("<h2>${esc(s.title)}</h2>", h)
        self.assertIn("<p>${esc(s.sub)}</p>", h)
        # keine doppelte Maskierung mehr in Titeln (sonst stünde „&amp;“ im Titel)
        self.assertNotIn("title: esc(", h)
        self.assertNotIn("sub: esc(", h)

    def test_gebaute_seite_ist_aktuell(self):
        src = (HIER / "zentrale" / "index.src.html").read_text(encoding="utf-8")
        fertig = (HIER / "zentrale" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<h2>${esc(s.title)}</h2>", fertig, "index.html neu bauen: python3 zentrale/bauen.py")
        self.assertEqual(src.count("title: pv("), fertig.count("title: pv("))


# ---------- S-04: Notizen über Verknüpfungen ----------

class S04_NotizGrenze(unittest.TestCase):
    def setUp(self):
        import notizen
        self.N = notizen
        self.wurzel = neuer_ordner("notizen-s04")
        self.aussen = neuer_ordner("aussen-s04")
        notizen.WURZEL = self.wurzel
        notizen.PAPIERKORB = self.wurzel / ".papierkorb"
        notizen._kopf.clear()

    def test_neu_schreibt_nicht_durch_ordner_verknuepfung(self):
        link(self.aussen, self.wurzel / "Geteilt")
        with self.assertRaises(ValueError):
            self.N.neu("Geteilt", "Test", "Inhalt")
        self.assertEqual(list(self.aussen.iterdir()), [], "es wurde außerhalb geschrieben")

    def test_neu_legt_keinen_ordner_draussen_an(self):
        link(self.aussen, self.wurzel / "Geteilt")
        with self.assertRaises(ValueError):
            self.N.neu("Geteilt/Neu/Tiefer", "Test", "Inhalt")
        self.assertFalse((self.aussen / "Neu").exists())

    def test_neu_schreibt_nicht_durch_kaputte_datei_verknuepfung(self):
        link(self.aussen / "gibtsnicht.md", self.wurzel / "Test.md")
        r = self.N.neu("", "Test", "Inhalt")
        self.assertEqual(r["pfad"], "Test 2.md")
        self.assertFalse((self.aussen / "gibtsnicht.md").exists())

    def test_liste_und_suche_zeigen_keine_datei_von_aussen(self):
        (self.aussen / "geheim.md").write_text("# Geheim\n\nwort-von-aussen\n", encoding="utf-8")
        link(self.aussen / "geheim.md", self.wurzel / "Verweis.md")
        self.N.neu("", "Eigene", "wort-von-innen")
        pfade = [n["pfad"] for n in self.N.liste()["notizen"]]
        self.assertNotIn("Verweis.md", pfade)
        self.assertEqual(self.N.suche("wort-von-aussen"), [])
        self.assertEqual(len(self.N.suche("wort-von-innen")), 1)

    def test_gegenfall_normale_ordner_gehen(self):
        r = self.N.neu("Projekte/Haus", "Plan", "Text")
        self.assertEqual(r["pfad"], "Projekte/Haus/Plan.md")
        self.assertEqual(self.N.lesen("Projekte/Haus/Plan.md")["titel"], "Plan")


# ---------- D-01 bis D-03: Sicherung ----------

class D01_D03_Sicherung(unittest.TestCase):
    def test_d01_gleichnamige_quellen_brechen_vor_dem_kopieren_ab(self):
        t = neuer_ordner("d01")
        for x, inhalt in (("A", "erste"), ("B", "zweite")):
            (t / x / "Documents").mkdir(parents=True)
            (t / x / "Documents" / "bericht.txt").write_text(inhalt, encoding="utf-8")
        r = skript("sichern.py", t / "A" / "Documents", t / "B" / "Documents", "--ziel", t / "ziel")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Kopiert wurde nichts", r.stdout + r.stderr)
        self.assertFalse((t / "ziel").exists() and any((t / "ziel").rglob("*")), "vor dem Abbruch wurde kopiert")

    def test_d01_gegenfall_verschiedene_namen_beide_vollstaendig(self):
        t = neuer_ordner("d01b")
        for x, inhalt in (("Documents", "erste"), ("Pictures", "zweite")):
            (t / x).mkdir()
            (t / x / "a.txt").write_text(inhalt, encoding="utf-8")
        r = skript("sichern.py", t / "Documents", t / "Pictures", "--ziel", t / "ziel")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((t / "ziel" / "Documents" / "a.txt").read_text(encoding="utf-8"), "erste")
        self.assertEqual((t / "ziel" / "Pictures" / "a.txt").read_text(encoding="utf-8"), "zweite")
        v = json.loads((t / "ziel" / "_sicherung.json").read_text(encoding="utf-8"))
        self.assertTrue(v["vollstaendig"])
        self.assertEqual(sorted(d["pfad"] for d in v["dateien"]), ["Documents/a.txt", "Pictures/a.txt"])

    def test_d02_eigene_ordner_mit_mehrdeutigem_namen_werden_gesichert(self):
        t = neuer_ordner("d02")
        q = t / "Documents"
        for n in ("bin", "build", "dist", "out", "target"):
            (q / n).mkdir(parents=True)
            (q / n / "eigen.txt").write_text(n, encoding="utf-8")
        (q / "app").mkdir()
        (q / "app" / "package.json").write_text("{}", encoding="utf-8")
        (q / "app" / "dist").mkdir()
        (q / "app" / "dist" / "bundle.js").write_text("x", encoding="utf-8")
        (q / "app" / "node_modules").mkdir()
        r = skript("sichern.py", q, "--ziel", t / "ziel")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for n in ("bin", "build", "dist", "out", "target"):
            self.assertTrue((t / "ziel" / "Documents" / n / "eigen.txt").is_file(), f"{n} fehlt in der Sicherung")
        self.assertFalse((t / "ziel" / "Documents" / "app" / "dist").exists(), "Bau-Rest im Projekt sollte fehlen")
        v = json.loads((t / "ziel" / "_sicherung.json").read_text(encoding="utf-8"))
        gruende = {Path(x["pfad"]).name: x["grund"] for x in v["ausgelassen"]}
        self.assertIn("dist", gruende)
        self.assertIn("node_modules", gruende)
        self.assertIn("Ausgelassen", r.stdout)

    @unittest.skipIf(WIN or (hasattr(os, "geteuid") and os.geteuid() == 0), "Leserechte lassen sich hier nicht entziehen")
    def test_d03_nicht_lesbarer_ordner_ist_ein_fehler(self):
        t = neuer_ordner("d03")
        q = t / "Documents"
        (q / "zu").mkdir(parents=True)
        (q / "zu" / "x.txt").write_text("x", encoding="utf-8")
        (q / "offen.txt").write_text("y", encoding="utf-8")
        os.chmod(q / "zu", 0)
        try:
            r = skript("sichern.py", q, "--ziel", t / "ziel")
            p = skript("sichern.py", q, "--ziel", t / "ziel2", "--probe")
        finally:
            os.chmod(q / "zu", 0o755)
        self.assertNotEqual(r.returncode, 0, "unvollständige Sicherung meldet Erfolg")
        self.assertIn("UNVOLLSTÄNDIG", r.stdout + r.stderr)
        self.assertNotEqual(p.returncode, 0, "auch die Probe muss den Lesefehler melden")
        v = json.loads((t / "ziel" / "_sicherung.json").read_text(encoding="utf-8"))
        self.assertFalse(v["vollstaendig"])


# ---------- D-04, D-05: Putzrunde ----------

class D04_D05_Putzen(unittest.TestCase):
    def setUp(self):
        self.P = importlib.import_module("putzen")

    def projekt(self, ort):
        (ort / "app" / ".venv").mkdir(parents=True)
        (ort / "app" / ".venv" / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
        (ort / "app" / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        alt_machen(ort / "app")

    def test_d04_verknuepfte_wurzel_wird_nicht_durchsucht(self):
        heim, aussen = neuer_ordner("d04-heim"), neuer_ordner("d04-aussen")
        self.projekt(aussen)
        link(aussen, heim / "Projects")
        F = self.P.suchen(self.P.Orte(heim), 7, [])
        self.assertEqual([f for f in F if str(aussen) in str(Path(f["pfad"]).resolve())], [])

    def test_d04_gegenfall_echter_ordner_wird_gefunden(self):
        heim = neuer_ordner("d04b-heim")
        (heim / "Projects").mkdir()
        self.projekt(heim / "Projects")
        F = self.P.suchen(self.P.Orte(heim), 7, [])
        self.assertEqual([f["pfad"].name for f in F], [".venv"])
        self.assertTrue(self.P.in_grenze(F[0]["pfad"], F[0]["wurzel"]))

    def test_d04_grenze_vor_dem_entfernen(self):
        heim, aussen = neuer_ordner("d04c-heim"), neuer_ordner("d04c-aussen")
        (heim / "Projects").mkdir()
        (aussen / "x").mkdir()
        link(aussen, heim / "Projects" / "verweis")
        self.assertFalse(self.P.in_grenze(heim / "Projects" / "verweis" / "x", heim / "Projects"))
        self.assertFalse(self.P.in_grenze(aussen / "x", heim / "Projects"))

    def test_d05_frische_datei_tief_im_temp_ordner_haelt_ihn(self):
        heim = neuer_ordner("d05-heim")
        temp = heim / "AppData" / "Local" / "Temp"
        (temp / "arbeit" / "unter").mkdir(parents=True)
        (temp / "arbeit" / "unter" / "neu.txt").write_text("frisch", encoding="utf-8")
        (temp / "fertig" / "unter").mkdir(parents=True)
        (temp / "fertig" / "unter" / "alt.txt").write_text("alt", encoding="utf-8")
        alt_machen(temp / "fertig")
        os.utime(temp / "arbeit" / "unter", (ALT, ALT))
        os.utime(temp / "arbeit", (ALT, ALT))   # Ordnerzeiten alt, die Datei darin frisch
        namen = [f["pfad"].name for f in self.P.temp_alt(self.P.Orte(heim), 7)]
        self.assertNotIn("arbeit", namen)
        self.assertIn("fertig", namen)

    def test_d05_putzrunde_entfernt_nur_altes(self):
        heim = neuer_ordner("d05b-heim")
        temp = heim / "AppData" / "Local" / "Temp"
        (temp / "arbeit" / "unter").mkdir(parents=True)
        (temp / "arbeit" / "unter" / "neu.txt").write_text("frisch", encoding="utf-8")
        (temp / "fertig").mkdir()
        (temp / "fertig" / "alt.txt").write_text("alt", encoding="utf-8")
        alt_machen(temp / "fertig")
        os.utime(temp / "arbeit" / "unter", (ALT, ALT))
        os.utime(temp / "arbeit", (ALT, ALT))
        r = skript("putzen.py", "--wurzel", heim, "--los")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((temp / "arbeit" / "unter" / "neu.txt").is_file())
        self.assertFalse((temp / "fertig").exists())


# ---------- D-06: Protokoll vor dem Verschieben prüfen ----------

class D06_Protokoll(unittest.TestCase):
    def test_kaputtes_protokoll_verschiebt_nichts(self):
        t = neuer_ordner("d06")
        prot = t / "protokoll.jsonl"
        prot.write_text('{"nr": 1, "art": "verschieben", "von": "a", "nach": "b"}\n{"nr": 2, "art": "verschie', encoding="utf-8")
        (t / "datei.txt").write_text("x", encoding="utf-8")
        r = skript("verschieben.py", t / "datei.txt", t / "neu.txt", env={"AUFRAEUMEN_PROTOKOLL": str(prot)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("kaputt", r.stdout + r.stderr)
        self.assertTrue((t / "datei.txt").is_file(), "die Datei wurde trotz kaputtem Protokoll verschoben")
        self.assertFalse((t / "neu.txt").exists())

    def test_gegenfall_heiles_protokoll_verschiebt_und_traegt_ein(self):
        t = neuer_ordner("d06b")
        prot = t / "protokoll.jsonl"
        (t / "datei.txt").write_text("x", encoding="utf-8")
        r = skript("verschieben.py", t / "datei.txt", t / "neu.txt", env={"AUFRAEUMEN_PROTOKOLL": str(prot)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        e = [json.loads(z) for z in prot.read_text(encoding="utf-8").splitlines()]
        self.assertEqual((e[-1]["nr"], e[-1]["art"]), (1, "verschieben"))
        r = skript("rueckgaengig.py", "1", env={"AUFRAEUMEN_PROTOKOLL": str(prot)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((t / "datei.txt").is_file())


# ---------- D-07: Update sichert nachweislich ----------

class D07_Update(unittest.TestCase):
    def git(self, *a, cwd=None):
        return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, *a], cwd=cwd, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_vorhandener_zweigname_wird_nicht_wiederverwendet(self):
        if not shutil.which("git"):
            self.skipTest("git fehlt")
        t = neuer_ordner("d07")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
                        GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@localhost",
                        GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@localhost")
        oben, klon = t / "oben", t / "klon"
        self.git("init", "-q", str(oben))
        self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=oben)
        (oben / "zentrale").mkdir()
        (oben / "zentrale" / "hub.py").write_text('FASSUNG = "test"\n', encoding="utf-8")
        (oben / "arbeit.txt").write_text("OBEN\n", encoding="utf-8")
        self.git("add", ".", cwd=oben)
        self.git("commit", "-qm", "start", cwd=oben)
        self.git("clone", "-q", str(oben), str(klon))
        self.git("branch", "sicherung-vor-update-20261031-120000", cwd=klon)   # gibt es schon, zeigt auf den alten Stand
        (klon / "arbeit.txt").write_text("EIGENE AENDERUNG\n", encoding="utf-8")
        (klon / "neu.txt").write_text("NEUE DATEI\n", encoding="utf-8")

        spec = importlib.util.spec_from_file_location("einrichten_test", HIER / "einrichten.py")
        m = importlib.util.module_from_spec(spec)
        echt_run, echt_zeit = subprocess.run, time.strftime

        def run(args, **kw):
            if args[:2] == [m.sys.executable, str(klon / "regeln_verteilen.py")]:
                return subprocess.CompletedProcess(args, 0, "", "")
            assert args[:3] == ["git", "-C", str(klon)], args
            kw["env"] = {**kw.get("env", self.env), **{k: v for k, v in self.env.items() if k.startswith("GIT_C")}}
            return echt_run(args, **kw)

        with mock.patch.dict(os.environ, self.env, clear=True):
            spec.loader.exec_module(m)
            m.HIER = klon
            aus = io.StringIO()
            # Benutzerordner leer: Auf einem Rechner mit eingerichtetem Hook würde update() sonst dessen Einrichter aufrufen
            with mock.patch.object(m.subprocess, "run", side_effect=run), mock.patch.object(m, "autostart", return_value=[]), \
                    mock.patch.object(m.Path, "home", return_value=t / "leer"), \
                    mock.patch.object(m, "holen", side_effect=AssertionError("kein Netz")), \
                    mock.patch.object(time, "strftime", side_effect=lambda f, *a: "20261031-120000" if f == "%Y%m%d-%H%M%S" else echt_zeit(f, *a)), \
                    contextlib.redirect_stdout(aus):
                m.update()
        zweige = self.git("branch", "--format=%(refname:short)", cwd=klon).split()
        self.assertIn("sicherung-vor-update-20261031-120000-2", zweige, aus.getvalue())
        self.assertEqual(self.git("show", "sicherung-vor-update-20261031-120000-2:arbeit.txt", cwd=klon), "EIGENE AENDERUNG")
        self.assertEqual(self.git("show", "sicherung-vor-update-20261031-120000-2:neu.txt", cwd=klon), "NEUE DATEI")
        self.assertEqual(self.git("show", "sicherung-vor-update-20261031-120000:arbeit.txt", cwd=klon), "OBEN", "alter Zweig verändert")


# ---------- S-03: Wer Aufgaben abhaken darf ----------

class S03_Abhaken(unittest.TestCase):
    def setUp(self):
        import hub, pos
        self.B, self.pos = hub.BESITZER, pos

    def offen(self, aid):
        return not next(a for a in self.pos._lesen()["aufgaben"] if a["id"] == aid)["erledigt"]

    def test_agent_hakt_aufgabe_des_besitzers_nicht_ab(self):
        a = self.pos.aufgabe_neu(self.B, {"titel": "Sache des Besitzers", "fuer": self.B})
        with self.assertRaises(PermissionError):
            self.pos.aufgabe_aendern("codex", a["id"], {"erledigt": True})
        self.assertTrue(self.offen(a["id"]), "die Änderung wurde trotz Fehler gespeichert")
        self.assertTrue(self.pos.aufgabe_aendern(self.B, a["id"], {"erledigt": True})["erledigt"])

    def test_fremder_agent_hakt_nicht_ab_anleger_und_zustaendiger_schon(self):
        a = self.pos.aufgabe_neu("codex", {"titel": "Besitzer: A oder B wählen", "fuer": self.B})
        with self.assertRaises(PermissionError):
            self.pos.aufgabe_aendern("claude", a["id"], {"erledigt": True})
        self.assertTrue(self.pos.aufgabe_aendern("codex", a["id"], {"erledigt": True})["erledigt"])   # im Chat erledigt
        b = self.pos.aufgabe_neu("claude", {"titel": "für codex", "fuer": "codex"})
        self.assertTrue(self.pos.aufgabe_aendern("codex", b["id"], {"erledigt": True})["erledigt"])
        c = self.pos.aufgabe_neu("codex", {"titel": "eigene"})
        self.assertTrue(self.pos.aufgabe_aendern("codex", c["id"], {"erledigt": True})["erledigt"])


# ---------- R-01: Kennungen ohne Doppel ----------

class R01_Kennungen(unittest.TestCase):
    def test_neue_id_nimmt_nie_eine_belegte(self):
        import hub
        L = [{"id": format(i, "06x")} for i in range(100000)]
        folge = iter(["000001", "000abc", "0186a0"])   # zwei belegte, dann eine freie
        with mock.patch.object(hub.secrets, "token_hex", side_effect=lambda n: next(folge)):
            self.assertEqual(hub.neue_id(L), "0186a0")

    def test_erzwungene_doppelte_kennung_trifft_nicht_den_falschen_eintrag(self):
        import hub, pos
        folge = iter(["aaaaaa", "aaaaaa", "bbbbbb"])
        with mock.patch.object(hub.secrets, "token_hex", side_effect=lambda n: next(folge)):
            a = pos.aufgabe_neu("codex", {"titel": "erste"})
            b = pos.aufgabe_neu("codex", {"titel": "zweite"})
        self.assertNotEqual(a["id"], b["id"])
        pos.aufgabe_aendern("codex", b["id"], {"titel": "zweite geändert"})
        A = {x["id"]: x["titel"] for x in pos._lesen()["aufgaben"]}
        self.assertEqual((A[a["id"]], A[b["id"]]), ("erste", "zweite geändert"))


# ---------- F-01 bis F-04, S-05: Finanzen ----------

class F_Finanzen(unittest.TestCase):
    def setUp(self):
        import hub, finanzen
        self.B, self.F = hub.BESITZER, finanzen
        p = Path(os.environ["ZENTRALE_DATEN"]) / "finanzen.json"
        if p.exists():
            p.unlink()

    def test_f01_gleicher_betrag_ist_nicht_gleicher_einkauf(self):
        F = self.F
        F.buchung_neu(self.B, {"betrag": "-20", "text": "Essen", "gegenpartei": "Café Beispiel", "datum": "2026-10-20", "konto": "Bargeld"})
        erg = F._einfuegen(F._lesen(), self.B, [{"datum": "2026-10-21", "betrag_cent": -2000, "text": "Tankstelle Beispiel", "gegenpartei": "Tankstelle"}],
                           "csv", "privat", "Girokonto")
        self.assertEqual((erg["neu"], erg["zusammengefuehrt"]), (1, 0))
        self.assertIn("Vielleicht dieselbe", erg["buchungen"][0]["notiz"])

    def test_f01_gegenfall_echte_doppelte_wird_zusammengefuehrt(self):
        F = self.F
        F.buchung_neu(self.B, {"betrag": "-35", "text": "Tanken", "datum": "2026-10-25"})
        erg = F._einfuegen(F._lesen(), self.B, [{"datum": "2026-10-26", "betrag_cent": -3500, "text": "Tankstelle Beispiel", "gegenpartei": "Tankstelle"}],
                           "csv", "privat", "Girokonto")
        self.assertEqual(erg["zusammengefuehrt"], 1)

    def test_f02_gleiche_nummer_anderer_aussteller_ist_eine_neue_rechnung(self):
        F = self.F
        a = F.rechnung_neu(self.B, {"name": "Lieferant A", "betrag": "50", "rechnungsnr": "2026-001", "bereich": "privat", "bezahlt": True})
        b = F.rechnung_neu(self.B, {"name": "Lieferant B", "betrag": "80", "rechnungsnr": "2026-001", "bereich": "firma"})
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(b["status"], "offen")
        c = F.rechnung_neu(self.B, {"name": "Lieferant B", "betrag": "80", "rechnungsnr": "2026-001", "bereich": "firma", "notiz": "ergänzt"})
        self.assertEqual(c["id"], b["id"], "gleiche Nummer, Aussteller und Bereich ist dieselbe Rechnung")

    def test_f03_privatbuchung_bezahlt_keine_firmenrechnung(self):
        F = self.F
        r = F.rechnung_neu(self.B, {"name": "Laden", "betrag": "20", "bereich": "firma"})
        d = F._lesen()
        x = {"betrag_cent": -2000, "bereich": "privat", "gegenpartei": "Laden", "text": "Laden Einkauf", "datum": F.heute().isoformat(),
             "nr": 99, "kategorie": "lebensmittel"}
        F._nach_buchungen(d, [x])
        self.assertEqual(next(y for y in d["rechnungen"] if y["id"] == r["id"])["status"], "offen")
        x["bereich"] = "firma"
        F._nach_buchungen(d, [x])
        self.assertEqual(next(y for y in d["rechnungen"] if y["id"] == r["id"])["status"], "bezahlt")

    def test_f04_fremdwaehrung_nicht_als_euro(self):
        F = self.F
        d = F._lesen()
        erg = F._einfuegen(d, self.B, [{"datum": "2026-10-22", "betrag_cent": -10000, "text": "Hotel", "gegenpartei": "Hotel", "waehrung": "USD"}],
                           "csv", "privat", "Karte")
        self.assertEqual(erg["neu"], 0)
        self.assertTrue(any("USD" in f for f in erg["fehler"]))
        erg = F._einfuegen(d, self.B, [{"datum": "2026-10-22", "betrag_cent": -1000, "text": "Bäcker", "gegenpartei": "Bäcker", "waehrung": "EUR"}],
                           "csv", "privat", "Karte")
        self.assertEqual(erg["neu"], 1)

    def test_s05_csv_ohne_formeln(self):
        F = self.F
        for t in ("=1+1", "+1", "-1+2", "@SUMME(A1)", " =1+1", "\t=1", "\r=1"):
            self.assertTrue(F._zelle(t).startswith("'"), repr(t))
        self.assertEqual(F._zelle("Laden"), "Laden")
        F.buchung_neu(self.B, {"betrag": "-5", "text": "=1+1", "gegenpartei": "@x", "notiz": "+2", "datum": "2026-10-20"})
        F._exportieren()
        csv = (Path(os.environ["FINANZ_DIR"]) / "Privat" / "Haushaltsbuch.csv").read_text(encoding="utf-8-sig")
        zeile = [z for z in csv.splitlines() if "1+1" in z][0]
        self.assertIn("'=1+1", zeile)
        self.assertIn("'@x", zeile)
        self.assertIn("'+2", zeile)
        self.assertIn("-5,00", zeile, "Beträge bleiben Zahlen")


# ---------- S-02: Andere Geräte nur verschlüsselt ----------

def adr(netz, n=1):
    """Eine Beispiel-Adresse aus einem Netz (so steht keine echte Adresse in den Tests)."""
    return str(ipaddress.ip_network(netz)[n])


TS4, TS6 = adr("100.64.0.0/10"), adr("fd7a:115c:a1e0::/48")
LAN = adr("192.168.0.0/16", 20)


class S02_NurTailscale(unittest.TestCase):
    def setUp(self):
        import app, hub
        self.app, self.hub = app, hub
        self.alt = (hub.HEIMNETZ, hub.LAN_OFFEN)
        hub.HEIMNETZ, hub.LAN_OFFEN = True, False
        hub.ABGEWIESEN.clear()

    def tearDown(self):
        self.hub.HEIMNETZ, self.hub.LAN_OFFEN = self.alt
        self.hub.ABGEWIESEN.clear()

    def test_heimnetz_nimmt_nur_diesen_rechner_und_tailscale(self):
        ok = self.app.absender_ok
        for ip in ("127.0.0.1", "::1", TS4, adr("100.64.0.0/10", -2), TS6, "::ffff:" + TS4):
            self.assertTrue(ok(ip), ip)
        for ip in (LAN, adr("10.0.0.0/8", 5), adr("172.16.0.0/12", 7), adr("169.254.0.0/16", 9), "8.8.8.8",
                   adr("100.128.0.0/16"), "fe80::1", "unsinn"):
            self.assertFalse(ok(ip), ip)
        self.assertIn(LAN, self.hub.ABGEWIESEN, "die Seite soll zeigen, wer abgewiesen wurde")
        self.assertNotIn("8.8.8.8", self.hub.ABGEWIESEN)

    def test_schalter_oeffnet_nur_das_heimnetz(self):
        self.hub.LAN_OFFEN = True
        ok = self.app.absender_ok
        self.assertTrue(ok(LAN))
        self.assertTrue(ok(TS4))
        self.assertFalse(ok("8.8.8.8"), "das Internet bleibt draußen")

    def test_ohne_heimnetz_lauscht_sie_ohnehin_nur_lokal(self):
        self.hub.HEIMNETZ = False
        self.assertTrue(self.app.absender_ok("127.0.0.1"))

    def test_anleitung_holt_den_melder_nicht_ueber_http(self):
        texte = [(HIER / n).read_text(encoding="utf-8") for n in ("docs/HOMELAB.md", "start.py", "melder/melder.py")]
        for x in texte:
            self.assertNotIn("/melder.py', 'melder.py'", x.replace("main/melder/melder.py', 'melder.py'", ""))
            self.assertNotRegex(x, r"(curl[^\n]*|von der Zentrale holen[^\n]*)http://")
        self.assertIn("https://raw.githubusercontent.com/", texte[0])

    def test_adressen_ohne_heimnetz_adresse(self):
        import geraete
        with mock.patch.object(geraete, "tailscale_ip", return_value=TS4), \
                mock.patch.object(geraete, "_eigene_ip", return_value=LAN), mock.patch.dict(os.environ, {"ZENTRALE_ADRESSEN": ""}):
            self.assertEqual(geraete.adressen(), [f"http://{TS4}:{self.hub.PORT}"])
            self.hub.LAN_OFFEN = True
            self.assertEqual(len(geraete.adressen()), 2)

    def test_tailscale_adresse_vom_befehl(self):
        import geraete
        for ausgabe, soll in ((TS4 + "\n", TS4), (LAN + "\n", ""), ("", "")):
            geraete._ts["zeit"] = 0
            with mock.patch.object(geraete.shutil, "which", return_value="tailscale"), \
                    mock.patch.object(geraete.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, ausgabe, "")):
                self.assertEqual(geraete.tailscale_ip(), soll)
        geraete._ts["zeit"] = 0


# ---------- Rückmeldungen aus dem Betrieb: Update, Regeln, Client ----------
def _git_umgebung():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
               GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@localhost",
               GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@localhost")
    return env


def _git(env, *a, cwd=None):
    return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, *a], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


VORLAGE = "# Regeln\n\n## Sprache\n- Deutsch.\n\n## Löschen\n- Nie löschen.\n"


class EigeneRegeln(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git fehlt")
        self.t = Path(tempfile.mkdtemp(prefix="regeln-", dir=TMP)).resolve()   # eigener Ordner: Windows räumt Git-Dateien nicht einfach weg
        self.env = _git_umgebung()
        self.heim = self.t / "heim"
        self.heim.mkdir()
        self.env.update(HOME=str(self.heim), USERPROFILE=str(self.heim))
        self.env.pop("CODEX_HOME", None)
        self.env.pop("CLAUDE_CONFIG_DIR", None)
        self.o = self.t / "zentrale"
        _git(self.env, "init", "-q", str(self.o))
        _git(self.env, "symbolic-ref", "HEAD", "refs/heads/main", cwd=self.o)
        shutil.copy(HIER / "regeln_verteilen.py", self.o / "regeln_verteilen.py")
        (self.o / ".gitignore").write_text("REGELN.lokal.md\nREGELN.ziele.txt\n", encoding="utf-8")
        (self.o / "REGELN.md").write_text(VORLAGE, encoding="utf-8")
        _git(self.env, "add", ".", cwd=self.o)
        _git(self.env, "commit", "-qm", "start", cwd=self.o)
        self.anfang = _git(self.env, "rev-parse", "HEAD", cwd=self.o)

    def verteilen(self, *args, env=None):
        return subprocess.run([sys.executable, "-B", str(self.o / "regeln_verteilen.py"), *args], env=env or self.env,
                              capture_output=True, text=True, encoding="utf-8")

    def update_nachstellen(self, eigener_text):
        """Wie update(): Eigenes liegt im Sicherungszweig, REGELN.md ist wieder die neue Vorlage."""
        _git(self.env, "checkout", "-qb", "sicherung-vor-update-20261101-120000", cwd=self.o)
        (self.o / "REGELN.md").write_text(eigener_text, encoding="utf-8")
        _git(self.env, "commit", "-qam", "eigene Regeln", "--allow-empty", cwd=self.o)
        _git(self.env, "checkout", "-q", "main", cwd=self.o)
        (self.o / "REGELN.md").write_text(VORLAGE + "\n## Neu\n- Neue Regel der Vorlage.\n", encoding="utf-8")
        _git(self.env, "commit", "-qam", "neue Vorlage", cwd=self.o)

    def test_eigene_regel_kommt_aus_der_sicherung_und_bleibt(self):
        self.update_nachstellen(VORLAGE.replace("- Deutsch.\n", "- Deutsch.\n- Immer mit Beispiel.\n"))
        r = self.verteilen()
        self.assertEqual(r.returncode, 0, r.stderr)
        lokal = (self.o / "REGELN.lokal.md").read_text(encoding="utf-8")
        self.assertIn("- Immer mit Beispiel.", lokal)
        self.assertIn("## Sprache", lokal, "die Zeile soll ihren Abschnitt behalten")
        self.assertNotIn("Nie löschen", lokal, "Zeilen der Vorlage gehören nicht hinein")
        anleitung = (self.heim / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("- Immer mit Beispiel.", anleitung)
        self.assertIn("Neue Regel der Vorlage", anleitung)
        self.assertLess(anleitung.index("Neue Regel der Vorlage"), anleitung.index("Immer mit Beispiel"))
        self.assertEqual(_git(self.env, "status", "--porcelain", cwd=self.o), "", "die eigene Datei darf Git nicht stören")
        self.verteilen()
        self.assertEqual((self.o / "REGELN.lokal.md").read_text(encoding="utf-8"), lokal, "zweimal aufrufen doppelt nichts")

    def test_entfernte_datei_kommt_nicht_wieder(self):
        self.update_nachstellen(VORLAGE + "- Eigene Zeile.\n")
        self.verteilen()
        (self.o / "REGELN.lokal.md").unlink()
        self.verteilen()
        self.assertFalse((self.o / "REGELN.lokal.md").exists())

    def test_vorhandene_eigene_regeln_bleiben_erhalten(self):
        (self.o / "REGELN.lokal.md").write_text("- Schon da.\n", encoding="utf-8")
        self.update_nachstellen(VORLAGE + "- Schon da.\n- Noch neu.\n")
        self.verteilen()
        lokal = (self.o / "REGELN.lokal.md").read_text(encoding="utf-8")
        self.assertEqual(lokal.count("- Schon da."), 1, lokal)
        self.assertIn("- Noch neu.", lokal)

    def test_gegenfall_unveraenderte_vorlage_legt_nichts_an(self):
        self.update_nachstellen(VORLAGE)
        self.verteilen()
        self.assertFalse((self.o / "REGELN.lokal.md").exists())

    def test_gegenfall_ohne_git_geht_es_auch(self):
        shutil.rmtree(self.o / ".git", onerror=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
        r = self.verteilen()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Nie löschen", (self.heim / ".claude" / "CLAUDE.md").read_text(encoding="utf-8"))

    def test_weitere_ordner_aus_der_umgebung(self):
        env = dict(self.env, CLAUDE_CONFIG_DIR=str(self.t / "claude2"), CODEX_HOME=str(self.t / "codex2"))
        self.assertEqual(self.verteilen(env=env).returncode, 0)
        for p in (self.t / "claude2" / "CLAUDE.md", self.t / "codex2" / "AGENTS.md", self.heim / ".claude" / "CLAUDE.md",
                  self.heim / ".codex" / "AGENTS.md"):
            self.assertIn("Nie löschen", p.read_text(encoding="utf-8"), str(p))

    def test_ziel_wird_gemerkt(self):
        ziel = self.t / "t3" / "AGENTS.md"
        self.assertEqual(self.verteilen("--ziel", str(ziel)).returncode, 0)
        self.assertIn("Nie löschen", ziel.read_text(encoding="utf-8"))
        (self.o / "REGELN.md").write_text(VORLAGE + "- Später.\n", encoding="utf-8")
        self.verteilen()
        self.assertIn("- Später.", ziel.read_text(encoding="utf-8"), "ohne Schalter muss es auch dort ankommen")
        self.verteilen("--ziel", str(ziel))
        self.assertEqual((self.o / "REGELN.ziele.txt").read_text(encoding="utf-8").count("AGENTS.md"), 1)

    def test_ziel_muss_eine_datei_sein(self):
        r = self.verteilen("--ziel", str(self.t))
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.o / "REGELN.ziele.txt").exists())


class UpdateQuelle(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("einrichten_quelle", HIER / "einrichten.py")
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def finde(self, **remotes):
        def git(*a):
            aus = " ".join(remotes) if a == ("remote",) else remotes.get(a[-1], "")
            return subprocess.CompletedProcess(a, 0, aus + "\n", "")
        return self.m.quelle_finden(git)

    def test_offizielle_adresse_geht_vor(self):
        self.assertEqual(self.finde(origin="https://github.com/jemand/eigene-kopie.git",
                                    oben="ssh://github.com/hadi-yousef/zentrale-starter.git"), "oben")

    def test_anderer_name_mit_offizieller_adresse(self):
        self.assertEqual(self.finde(meine="https://github.com/hadi-yousef/zentrale-starter"), "meine")

    def test_sonst_origin_oder_die_einzige(self):
        self.assertEqual(self.finde(origin="https://example.invalid/a.git", b="https://example.invalid/b.git"), "origin")
        self.assertEqual(self.finde(b="https://example.invalid/b.git"), "b")

    def test_aehnlicher_name_zaehlt_nicht_als_offiziell(self):
        self.assertEqual(self.finde(origin="https://example.invalid/a.git",
                                    b="https://github.com/hadi-yousef/zentrale-starter-kopie.git"), "origin")

    def test_mehrdeutig_bleibt_leer(self):
        self.assertEqual(self.finde(a="https://example.invalid/a.git", b="https://example.invalid/b.git"), "")
        self.assertEqual(self.finde(), "")

    def test_update_mit_anderem_quellnamen_holt_die_neue_fassung(self):
        if not shutil.which("git"):
            self.skipTest("git fehlt")
        t, env = neuer_ordner("quelle"), _git_umgebung()
        oben, klon = t / "oben", t / "klon"
        _git(env, "init", "-q", str(oben))
        _git(env, "symbolic-ref", "HEAD", "refs/heads/main", cwd=oben)
        (oben / "zentrale").mkdir()
        (oben / "zentrale" / "hub.py").write_text('FASSUNG = "alt"\n', encoding="utf-8")
        _git(env, "add", ".", cwd=oben)
        _git(env, "commit", "-qm", "alt", cwd=oben)
        _git(env, "clone", "-q", "-o", "meine-quelle", str(oben), str(klon))
        (oben / "zentrale" / "hub.py").write_text('FASSUNG = "neu"\n', encoding="utf-8")
        _git(env, "commit", "-qam", "neu", cwd=oben)
        echt = subprocess.run

        def run(args, **kw):
            if args[0] != "git":
                return subprocess.CompletedProcess(args, 0, "", "")
            kw["env"] = env
            return echt(args, **kw)
        self.m.HIER = klon
        with mock.patch.object(self.m.subprocess, "run", side_effect=run), mock.patch.object(self.m, "autostart", return_value=[]), \
                mock.patch.object(self.m, "daten_zaehlen", return_value=(t, {})), contextlib.redirect_stdout(io.StringIO()):
            self.m.update()
        self.assertIn('"neu"', (klon / "zentrale" / "hub.py").read_text(encoding="utf-8"))


class ProjektnameInDerAdresse(unittest.TestCase):
    def test_name_mit_leerzeichen_und_umlaut(self):
        import app
        import pos
        import urllib.parse
        name = "Büro Umbau Test"
        pos.projekt_neu("claude", {"name": name})
        kodiert = urllib.parse.quote(name)
        r = app.Handler._post(None, "claude", f"/api/pos/projekte/{kodiert}", ["projekte", kodiert], {"naechster_schritt": "Weiter"})
        self.assertEqual((r["name"], r["naechster_schritt"]), (name, "Weiter"))

    def test_gegenfall_unbekannter_name_bleibt_ein_fehler(self):
        import app
        with self.assertRaises(Exception):
            app.Handler._post(None, "claude", "/api/pos/projekte/Gibt%20es%20nicht", ["projekte", "Gibt%20es%20nicht"], {"naechster_schritt": "x"})


class ClientTexte(unittest.TestCase):
    def setUp(self):
        import zentrale_client
        self.c = zentrale_client
        self.z = mock.Mock()
        self.z.post.return_value = {"nr": 3}

    def befehl(self, **kw):
        import argparse
        with contextlib.redirect_stdout(io.StringIO()) as aus:
            self.c.ausfuehren(self.z, argparse.Namespace(**kw))
        return aus.getvalue()

    def test_bericht_zeigt_den_ganzen_text(self):
        self.z.get.return_value = {"nr": 5, "titel": "T", "von": "claude", "zeit": 0, "kurz": "Kurz", "text": "| Ort | Neu |\n|---|---|", "fragen": [], "verlauf": [], "projekt": "", "wunsch": ""}
        self.assertIn("| Ort | Neu |", self.befehl(befehl="bericht", nr="5", abgeholt=False))

    def test_liegengebliebene_fragen(self):
        alt, neu = time.time() - 30 * 3600, time.time() - 3600
        self.z.get.return_value = {"berichte": [
            {"nr": 1, "titel": "Alt", "von": "claude", "zeit": alt, "fragen": [{"text": "Ja?", "antwort": None}]},
            {"nr": 2, "titel": "Neu", "von": "claude", "zeit": neu, "fragen": [{"text": "Ja?", "antwort": None}]},
            {"nr": 3, "titel": "Fertig", "von": "claude", "zeit": alt, "fragen": [{"text": "Ja?", "antwort": {"text": "Ja"}}]},
            {"nr": 4, "titel": "Nachgefragt", "von": "codex", "zeit": alt, "fragen": [{"text": "A?", "antwort": {"text": "zeig"}}, {"text": "B?", "antwort": None, "zeit": neu}]}]}
        aus = self.befehl(befehl="berichte", offen=24, anzahl=20)
        self.assertIn("Bericht Nr. 1", aus)
        self.assertNotIn("Bericht Nr. 2", aus)
        self.assertNotIn("Bericht Nr. 3", aus)
        self.assertNotIn("Bericht Nr. 4", aus, "die angehängte Frage ist neu")
        self.assertIn("Bericht Nr. 2", self.befehl(befehl="berichte", offen=0.5, anzahl=20))

    def test_text_aus_datei_kommt_unversehrt_an(self):
        d = neuer_ordner("text") / "t.md"
        d.write_text("Text mit `backticks` und $(befehl)\n", encoding="utf-8")
        self.befehl(befehl="wunsch-notiz", nr="3", text=None, text_datei=str(d))
        self.assertEqual(self.z.post.call_args[0], ("/api/wuensche/3/notizen", {"text": "Text mit `backticks` und $(befehl)"}))
        self.befehl(befehl="bericht-antwort", nr="3", text=None, text_datei=str(d))
        self.assertEqual(self.z.post.call_args[0], ("/api/berichte/3/nachricht", {"text": "Text mit `backticks` und $(befehl)"}))

    def test_gegenfall_text_direkt_geht_weiter(self):
        self.befehl(befehl="wunsch-notiz", nr="3", text="Kurz", text_datei=None)
        self.assertEqual(self.z.post.call_args[0][1], {"text": "Kurz"})

    def test_ohne_text_kein_leerer_eintrag(self):
        with self.assertRaises(self.c.Fehler):
            self.befehl(befehl="wunsch-notiz", nr="3", text=None, text_datei=None)
        self.z.post.assert_not_called()

    def test_inventar_merkmale_als_name_wert(self):
        self.z.get.return_value = {"teile": [], "standorte": [], "vorlagen": {}}
        self.z.post.return_value = {"id": "a1b2c3", "name": "HK", "menge": 0, "einheit": "Stück", "kategorie": "Heizkörper", "ort": "x"}
        leer = dict.fromkeys(("beschreibung", "kategorie", "ort", "einheit", "min", "zaehlung", "link", "notiz", "projekte"))
        self.befehl(befehl="inventar-neu", name="HK", artnr="HK-1", merkmal=["Typ=22", "Gewicht=ca. 30 kg"], vergleich=["Zählung 19.10.=79"], **leer)
        self.assertEqual(self.z.post.call_args[0], ("/api/inventar/teile", {"artnr": "HK-1", "werte": {"Typ": "22", "Gewicht": "ca. 30 kg"},
                                                                          "vergleich": {"Zählung 19.10.": "79"}, "name": "HK"}))
        with self.assertRaises(self.c.Fehler):
            self.befehl(befehl="inventar-neu", name="HK", artnr=None, merkmal=["Typ"], vergleich=None, **leer)

    def test_inventar_import_laesst_die_zentrale_alles_pruefen(self):
        L = [{"name": "HK 1", "artnr": "HK-1", "werte": {"Typ": "22"}}, {"name": "HK 2"}]
        self.z.post.return_value = {"teile": [{"id": "a1b2c3", "name": "HK 1", "artnr": "HK-1", "werte": {"Typ": "22"}}, {"id": "b2c3d4", "name": "HK 2"}]}
        d = neuer_ordner("import") / "teile.json"
        d.write_text(json.dumps(L), encoding="utf-8")
        self.assertIn("Probe, nichts angelegt", self.befehl(befehl="inventar-import", datei=str(d), los=False))
        self.assertEqual(self.z.post.call_args[0], ("/api/inventar/import", {"teile": L, "probe": True}))
        self.assertIn("2 Teile angelegt", self.befehl(befehl="inventar-import", datei=str(d), los=True))
        self.assertEqual(self.z.post.call_args[0][1]["probe"], False)
        self.z.post.reset_mock()
        d.write_text(json.dumps({"name": "keine Liste"}), encoding="utf-8")
        with self.assertRaises(self.c.Fehler):
            self.befehl(befehl="inventar-import", datei=str(d), los=True)
        self.z.post.assert_not_called()

    def test_inventar_zaehlen_ohne_standort_in_der_antwort(self):
        self.z.post.return_value = {"teil": {"name": "A", "menge": 5, "einheit": "Stück"}, "buchung": {"delta": 5, "vorher": 0, "nachher": 5}}
        aus = self.befehl(befehl="inventar-zaehlen", teil="A", ort="Lager", menge="5", text=None)
        self.assertIn("Gebucht +5", aus)

    def test_schalter_steht_in_der_hilfe(self):
        for b in ("wunsch-notiz", "bericht-antwort"):
            r = subprocess.run([sys.executable, "-B", str(HIER / "zentrale_client.py"), b, "--help"], capture_output=True,
                               text=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            self.assertIn("--text-datei", r.stdout, b)

    def test_bericht_zeigt_projekt_und_wunsch(self):
        self.z.get.return_value = {"nr": 3, "titel": "T", "von": "claude", "zeit": 0, "kurz": "", "fragen": [], "verlauf": [],
                                   "projekt": "Website", "wunsch": 7}
        aus = self.befehl(befehl="bericht", nr="3", abgeholt=False)
        self.assertIn("Projekt: Website", aus)
        self.assertIn("Wunsch Nr. 7", aus)

    def test_laeufe_zeigen_die_kennung(self):
        l = {"agent": "claude", "lauf": "chat-abc", "titel": "Titel", "start": 0, "ende": 0, "status": "fertig"}
        self.z.get.return_value = {"aktiv": [l], "fertig": [l]}
        self.assertEqual(self.befehl(befehl="laeufe", anzahl=5).count("[Lauf chat-abc]"), 2)


class HookWunsch(unittest.TestCase):
    def test_zitierte_nummer_verschiebt_den_lauf_nicht(self):
        import laeufe
        laeufe.melden("claude", {"aktion": "start", "lauf": "chat-a", "titel": "Erste", "wunsch": "5", "quelle": "hook"})
        x = laeufe.melden("claude", {"aktion": "start", "lauf": "chat-a", "titel": "Zweite", "wunsch": "9", "quelle": "hook"})
        self.assertEqual(x["wunsch"], 5)

    def test_gesetzte_nummer_bleibt_gegen_den_hook(self):
        import laeufe
        laeufe.melden("claude", {"aktion": "start", "lauf": "chat-b", "titel": "Erste", "quelle": "hook"})
        laeufe.melden("claude", {"aktion": "stand", "lauf": "chat-b", "wunsch": "6"})
        x = laeufe.melden("claude", {"aktion": "start", "lauf": "chat-b", "titel": "Zweite", "wunsch": "9", "quelle": "hook"})
        self.assertEqual(x["wunsch"], 6)

    def test_gegenfall_erste_nummer_gilt_und_agent_darf_wechseln(self):
        import laeufe
        laeufe.melden("claude", {"aktion": "start", "lauf": "chat-c", "titel": "Ohne", "quelle": "hook"})
        x = laeufe.melden("claude", {"aktion": "start", "lauf": "chat-c", "titel": "Mit", "wunsch": "4", "quelle": "hook"})
        self.assertEqual(x["wunsch"], 4)
        x = laeufe.melden("claude", {"aktion": "stand", "lauf": "chat-c", "wunsch": "8"})
        self.assertEqual(x["wunsch"], 8)


# ---------- Kalender, E-Mail, Inventar ----------

ADR = "name" + chr(64) + "example.org"
AT = bytes([64])
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


class Inventar(unittest.TestCase):
    def setUp(self):
        import inventar
        self.I = inventar
        t = Path(tempfile.mkdtemp(prefix="inv-", dir=TMP))
        self.datei = t / "inventar.json"
        for ziel, wert in ((inventar, {"DATEI": self.datei, "FOTOS": t / "fotos", "_export_spaeter": lambda: None}),):
            for k, v in wert.items():
                p = mock.patch.object(ziel, k, v)
                p.start()
                self.addCleanup(p.stop)

    def test_buchung_mit_vorher_und_nachher(self):
        t = self.I.teil_neu("besitzer", {"name": "Schrauben M4", "min": 5})
        r = self.I.buchen("besitzer", {"teil": t["id"], "delta": "25"})["buchung"]
        self.assertEqual((r["vorher"], r["nachher"]), (0, 25))
        r = self.I.buchen("claude", {"teil": t["id"], "delta": -3})["buchung"]
        self.assertEqual((r["vorher"], r["nachher"], r["von"]), (25, 22, "claude"))

    def test_nicht_mehr_entnehmen_als_da_ist(self):
        t = self.I.teil_neu("besitzer", {"name": "Kabel"})
        self.I.buchen("besitzer", {"teil": t["id"], "delta": 2})
        with self.assertRaises(ValueError):
            self.I.buchen("besitzer", {"teil": t["id"], "delta": -3})
        self.assertEqual(self.I.stand()["teile"][0]["menge"], 2)

    def test_gleicher_name_nur_einmal(self):
        self.I.teil_neu("besitzer", {"name": "Karton"})
        with self.assertRaises(ValueError):
            self.I.teil_neu("besitzer", {"name": "karton"})

    def test_saetze_ergeben_nur_einen_vorschlag(self):
        t = self.I.teil_neu("besitzer", {"name": "Schrauben M4"})
        v = self.I.verstehen("25x Schrauben M4 dazu")
        self.assertEqual((v["art"], v["menge"], v["richtung"], v["treffer"][0]["id"]), ("buchung", 25, 1, t["id"]))
        v = self.I.verstehen("3 Stück Schrauben M4 entnommen")
        self.assertEqual((v["menge"], v["richtung"]), (3, -1))
        v = self.I.verstehen("2,5 m Kabel rot verbraucht")
        self.assertEqual((v["menge"], v["einheit"], v["name"], v["neu"]), (2.5, "m", "Kabel rot", True))
        self.assertEqual(self.I.verstehen("3 Kartons Papier dazu")["einheit"], "Karton")
        v = self.I.verstehen("Wie viele Schrauben M4 habe ich?")
        self.assertEqual((v["art"], v["treffer"][0]["id"]), ("frage", t["id"]))
        self.assertEqual(self.I.stand()["buchungen"], [], "ein Satz allein bucht nichts")
        with self.assertRaises(ValueError):
            self.I.verstehen("irgendwas ohne Zahl")

    def test_unlesbare_datei_wird_nicht_ueberschrieben(self):
        self.datei.write_text("kaputt", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.I.teil_neu("besitzer", {"name": "X"})
        self.assertEqual(self.datei.read_text(encoding="utf-8"), "kaputt")

    def test_umlaute_und_einkaufsliste_in_der_notiz(self):
        t = self.I.teil_neu("besitzer", {"name": "Dübel", "min": 10, "kategorie": "Kleinteile"})
        self.I.buchen("besitzer", {"teil": t["id"], "delta": 3})
        l = self.I.text_liste()
        self.assertIn("Dübel", l)
        self.assertIn("## Einkaufsliste", l)
        json.loads(self.datei.read_bytes().decode("utf-8"))

    def test_fotos_nur_bilder_und_nur_vom_eigenen_teil(self):
        import base64
        a, b = self.I.teil_neu("besitzer", {"name": "A"}), self.I.teil_neu("besitzer", {"name": "B"})
        with self.assertRaises(ValueError):
            self.I.foto_neu("besitzer", a["id"], {"bild": base64.b64encode(b"<html>").decode()})
        d = self.I.foto_neu("besitzer", a["id"], {"bild": base64.b64encode(PNG).decode()})["fotos"][0]["datei"]
        self.assertTrue(self.I.foto_pfad(a["id"], d).is_file())
        for teil, datei in ((b["id"], d), (a["id"], "../inventar.json")):
            with self.assertRaises(ValueError):
                self.I.foto_pfad(teil, datei)

    # ---------- Standorte, Zählen, Artikelnummer, Vorlagen (z. B. Laden, Lager, Beschädigt) ----------

    def orte(self):
        self.I.standort("besitzer", {"name": "Laden", "adresse": "Straße 1"})
        self.I.standort("besitzer", {"name": "Lager"})
        self.I.standort("besitzer", {"name": "Beschädigt", "verkaufbar": False})

    def test_mengen_je_ort_summe_ohne_beschaedigt(self):
        self.orte()
        t = self.I.teil_neu("besitzer", {"name": "Heizkörper A"})
        for ort, n in (("Laden", 3), ("lager", 5), ("Beschädigt", 2)):
            self.I.buchen("besitzer", {"teil": t["id"], "delta": n, "standort": ort})
        t = self.I.stand()["teile"][0]
        self.assertEqual(t["mengen"], {"Laden": 3, "Lager": 5, "Beschädigt": 2})
        self.assertEqual(t["menge"], 8, "Beschädigt zählt nicht zum Bestand")
        b = next(b for b in self.I.stand()["buchungen"] if b["standort"] == "Beschädigt")   # alle in derselben Sekunde
        self.assertEqual((b["vorher"], b["nachher"], b["delta"]), (0, 2, 2))

    def test_nicht_mehr_entnehmen_als_am_ort(self):
        self.orte()
        t = self.I.teil_neu("besitzer", {"name": "Heizkörper A"})
        self.I.buchen("besitzer", {"teil": t["id"], "delta": 2, "standort": "Lager"})
        self.I.buchen("besitzer", {"teil": t["id"], "delta": 10, "standort": "Laden"})
        with self.assertRaises(ValueError):
            self.I.buchen("besitzer", {"teil": t["id"], "delta": -3, "standort": "Lager"})
        s = self.I.stand()
        self.assertEqual((s["teile"][0]["mengen"], s["teile"][0]["menge"], len(s["buchungen"])), ({"Lager": 2, "Laden": 10}, 12, 2))

    def test_zaehlen_bucht_den_unterschied(self):
        self.orte()
        t = self.I.teil_neu("besitzer", {"name": "Heizkörper A", "artnr": "HK-60-100-22"})
        r = self.I.zaehlen("besitzer", {"teil": "hk-60-100-22", "standort": "Lager", "menge": 47})
        self.assertEqual((r["buchung"]["delta"], r["buchung"]["quelle"], r["teil"]["menge"]), (47, "zaehlung", 47))
        r = self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Lager", "menge": "45"})
        self.assertEqual((r["buchung"]["delta"], r["buchung"]["vorher"], r["buchung"]["nachher"]), (-2, 47, 45))
        r = self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Lager", "menge": 45})
        self.assertIsNone(r["buchung"], "gleiche Zahl: keine Buchung")
        self.assertIn("Lager", r["teil"]["gezaehlt"])
        self.assertEqual(len(self.I.stand()["buchungen"]), 2)
        with self.assertRaises(ValueError):
            self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Lager", "menge": -1})

    def test_ungezaehlt_ist_nicht_null(self):
        self.orte()
        t = self.I.teil_neu("besitzer", {"name": "Heizkörper A"})
        S = self.I.stand()["standorte"]
        self.assertEqual((t["mengen"], t["gezaehlt"]), ({}, {}))
        self.assertEqual(self.I.orte_text(S, t), "Laden – · Lager – · Beschädigt –")
        t = self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Lager", "menge": 0})["teil"]
        self.assertEqual(self.I.orte_text(S, t), "Laden – · Lager 0 · Beschädigt –")

    def test_alter_artikel_ohne_mengen_erst_zaehlen(self):
        t = self.I.teil_neu("besitzer", {"name": "Dübel", "ort": "Regal 2"})
        self.I.buchen("besitzer", {"teil": t["id"], "delta": 10})
        self.orte()
        self.assertNotIn("mengen", self.I.stand()["teile"][0], "Teil mit Bestand bleibt, wie es ist")
        self.I.buchen("besitzer", {"teil": t["id"], "delta": 1})   # ohne Standort geht wie vorher
        with self.assertRaises(ValueError):
            self.I.buchen("besitzer", {"teil": t["id"], "delta": 1, "standort": "Lager"})
        with self.assertRaises(ValueError):
            self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Beschädigt", "menge": 1})
        r = self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Lager", "menge": 7})
        self.assertEqual((r["buchung"]["vorher"], r["buchung"]["nachher"], r["buchung"]["delta"]), (11, 7, -4))
        t = self.I.buchen("besitzer", {"teil": t["id"], "delta": 1, "standort": "Laden"})["teil"]
        self.assertEqual((t["mengen"], t["menge"], t["ort"]), ({"Lager": 7, "Laden": 1}, 8, "Regal 2"))

    def test_erste_zaehlung_bringt_nichts_faelschlich_auf_die_einkaufsliste(self):
        t = self.I.teil_neu("besitzer", {"name": "Schrauben", "min": 5})
        self.I.buchen("besitzer", {"teil": t["id"], "delta": 11})
        self.orte()
        t = self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Laden", "menge": 3})["teil"]
        self.assertEqual((t["menge"], t.get("zaehlung_offen")), (3, True))
        self.assertFalse(self.I.wenig(t), "das Lager ist noch nicht gezählt")
        t = self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Lager", "menge": 1})["teil"]
        self.assertNotIn("zaehlung_offen", t)
        self.assertTrue(self.I.wenig(t), "jetzt ist überall gezählt: 4 unter 5")

    def test_artikelnummer_nur_aus_punkten_geht_nicht(self):
        for falsch in ("..", "."):
            with self.assertRaises(ValueError):
                self.I.teil_neu("besitzer", {"name": "X" + falsch, "artnr": falsch})

    def test_unbekannter_oder_fehlender_standort(self):
        self.orte()
        t = self.I.teil_neu("besitzer", {"name": "Heizkörper A"})
        for b in ({"teil": t["id"], "delta": 1, "standort": "Keller"}, {"teil": t["id"], "delta": 1}):
            with self.assertRaises(ValueError):
                self.I.buchen("besitzer", b)
        with self.assertRaises(ValueError):
            self.I.zaehlen("besitzer", {"teil": t["id"], "menge": 3})
        self.assertEqual(self.I.stand()["buchungen"], [])

    def test_standort_aendern_nur_wenn_leer(self):
        self.orte()
        t = self.I.teil_neu("besitzer", {"name": "Heizkörper A"})
        self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Beschädigt", "menge": 2})
        for b in ({"name": "beschädigt", "verkaufbar": True}, {"name": "Beschädigt", "entfernen": True}):
            with self.assertRaises(ValueError):
                self.I.standort("besitzer", b)
        self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Beschädigt", "menge": 0})
        S = self.I.standort("besitzer", {"name": "Beschädigt", "entfernen": True})["standorte"]
        self.assertEqual([s["name"] for s in S], ["Laden", "Lager"])
        self.assertEqual(self.I.standort("besitzer", {"name": "LADEN", "adresse": "Straße 2"})["standorte"][0], {"name": "Laden", "adresse": "Straße 2", "verkaufbar": True})

    def test_artnr_eindeutig_und_nicht_wie_eine_kennung(self):
        a = self.I.teil_neu("besitzer", {"name": "A", "artnr": "HK-60-100-22"})
        for b in ({"name": "B", "artnr": "hk-60-100-22"}, {"name": "C", "artnr": "a1b2c3"}, {"name": "D", "artnr": "mit leer"}):
            with self.assertRaises(ValueError):
                self.I.teil_neu("besitzer", b)
        b = self.I.teil_neu("besitzer", {"name": "B", "artnr": "HK-60-60-22"})
        with self.assertRaises(ValueError):
            self.I.teil_aendern("besitzer", b["id"], {"artnr": "HK-60-100-22", "beschreibung": "x"})
        self.assertEqual(self.I.stand()["teile"][1]["beschreibung"], "", "ein Fehler ändert nichts")
        self.assertEqual(self.I.teil_aendern("besitzer", "HK-60-100-22", {"name": "A", "ort": "Regal 1"})["id"], a["id"], "gleicher Name bei sich selbst geht")

    def test_vorlage_standardwerte_und_merkmal_entfernen(self):
        self.I.vorlage("besitzer", {"kategorie": "Heizkörper", "merkmale": ["Typ", "Hersteller=Muster", {"name": "Farbe", "standard": "Weiß"}]})
        t = self.I.teil_neu("besitzer", {"name": "A", "kategorie": "heizkörper", "werte": {"Typ": "22", "Farbe": "Grau"}})
        self.assertEqual(t["werte"], {"Typ": "22", "Farbe": "Grau", "Hersteller": "Muster"})
        with self.assertRaises(ValueError):   # Typ hat bei A einen Wert
            self.I.vorlage("besitzer", {"kategorie": "Heizkörper", "merkmale": ["Hersteller", "Farbe"]})
        V = self.I.vorlage("besitzer", {"kategorie": "Heizkörper", "merkmale": ["Typ", "Hersteller=Muster", "Farbe", "Prüfdruck"]})["vorlagen"]
        self.assertEqual([m["name"] for m in V["Heizkörper"]], ["Typ", "Hersteller", "Farbe", "Prüfdruck"])
        with self.assertRaises(ValueError):
            self.I.vorlage("besitzer", {"kategorie": "Heizkörper", "merkmale": ["Typ", "typ"]})

    def test_merkmale_bis_60(self):
        t = self.I.teil_neu("besitzer", {"name": "A", "werte": {f"M{i}": str(i) for i in range(30)}})
        self.assertEqual(len(t["werte"]), 30)
        self.assertEqual(len(self.I.teil_aendern("besitzer", t["id"], {"werte": {f"N{i}": "x" for i in range(30)}})["werte"]), 60)
        with self.assertRaises(ValueError):
            self.I.teil_aendern("besitzer", t["id"], {"werte": {"noch eins": "x"}})

    def test_vergleich_nie_in_menge(self):
        self.orte()
        t = self.I.teil_neu("besitzer", {"name": "A", "vergleich": {"Zählung 19.10.": "79", "Shop 04.11.": "76"}})
        t = self.I.teil_aendern("besitzer", t["id"], {"vergleich": {"Shop 04.11.": ""}})
        self.assertEqual((t["vergleich"], t["menge"]), ({"Zählung 19.10.": "79"}, 0))

    def test_satz_mit_standort_und_artnr(self):
        self.orte()
        t = self.I.teil_neu("besitzer", {"name": "Heizkörper Typ 22 · 60 × 100 cm", "artnr": "HK-60-100-22"})
        self.I.teil_neu("besitzer", {"name": "Lager-Regal"})
        v = self.I.verstehen("3 HK-60-100-22 Laden entnommen")
        self.assertEqual((v["standort"], v["richtung"], v["menge"], [x["id"] for x in v["treffer"]]), ("Laden", -1, 3, [t["id"]]))
        v = self.I.verstehen("Wie viele HK-60-100-22 im Lager?")
        self.assertEqual((v["art"], v["standort"], v["treffer"][0]["id"]), ("frage", "Lager", t["id"]))
        v = self.I.verstehen("2 Lager-Regal dazu")
        self.assertEqual((v["standort"], v["treffer"][0]["name"]), ("", "Lager-Regal"), "Standort nur als ganzes Wort")

    def test_standorte_weg_und_wieder_ohne_verlust(self):
        """Kalte Durchsicht 05.11.2026, Befund 1: Bestand darf sich nie ohne Buchung ändern."""
        self.I.standort("besitzer", {"name": "Lager"})
        t = self.I.teil_neu("besitzer", {"name": "A"})
        self.I.standort("besitzer", {"name": "Lager", "entfernen": True})
        self.assertNotIn("mengen", self.I.stand()["teile"][0], "ohne Standorte: eine Menge je Teil")
        self.I.buchen("besitzer", {"teil": t["id"], "delta": 10})
        self.I.standort("besitzer", {"name": "Lager"})
        with self.assertRaises(ValueError):   # erst zählen
            self.I.buchen("besitzer", {"teil": t["id"], "delta": 1, "standort": "Lager"})
        self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Lager", "menge": 10})
        t = self.I.buchen("besitzer", {"teil": t["id"], "delta": 1, "standort": "Lager"})["teil"]
        s = self.I.stand()
        self.assertEqual((t["menge"], sum(b["delta"] for b in s["buchungen"])), (11, 11), "Bestand = Summe der Buchungen")

    def test_standort_entfernen_vergisst_seine_zahlen(self):
        self.orte()
        t = self.I.teil_neu("besitzer", {"name": "A"})
        self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Laden", "menge": 0})
        self.I.standort("besitzer", {"name": "Laden", "entfernen": True})
        self.I.standort("besitzer", {"name": "Laden"})
        S = self.I.stand()["standorte"]
        self.assertEqual(self.I.orte_text(S, self.I.stand()["teile"][0]), "Lager – · Beschädigt – · Laden –")

    def test_merkmal_gross_klein_ist_derselbe_eintrag(self):
        t = self.I.teil_neu("besitzer", {"name": "A", "werte": {"typ": "22"}})
        self.assertEqual(self.I.teil_aendern("besitzer", t["id"], {"werte": {"Typ": "33"}})["werte"], {"typ": "33"})
        self.assertEqual(self.I.teil_aendern("besitzer", t["id"], {"werte": {"TYP": ""}})["werte"], {})

    def test_vergleich_alle_zeilen_ersetzen(self):
        alt = {f"Alt {i}": str(i) for i in range(20)}
        t = self.I.teil_neu("besitzer", {"name": "A", "vergleich": alt})
        neu = {**{k: "" for k in list(alt)[10:]}, **{f"Neu {i}": "x" for i in range(10)}}   # 10 behalten, 10 ersetzen
        self.assertEqual(len(self.I.teil_aendern("besitzer", t["id"], {"vergleich": neu})["vergleich"]), 20)

    def test_import_ganz_oder_gar_nicht(self):
        self.I.teil_neu("besitzer", {"name": "Alt", "artnr": "HK-9"})
        for falsch in ([{"name": "HK 1"}, {"name": "HK 2", "artnr": "HK 2"}], [{"name": "Neu", "artnr": "hk-9"}], [{"name": "A"}, {"name": "a"}],
                       [{"name": "A", "menge": 5}], [{"name": "A", "werte": ["x"]}], ["kein Teil"]):
            with self.assertRaises(ValueError):
                self.I.teile_import("besitzer", {"teile": falsch})
        self.assertEqual([t["name"] for t in self.I.stand()["teile"]], ["Alt"], "nach einem Fehler ist nichts angelegt")
        r = self.I.teile_import("besitzer", {"teile": [{"name": "HK 1", "artnr": "HK-1"}, {"name": "HK 2"}], "probe": True})
        self.assertEqual((len(r["teile"]), len(self.I.stand()["teile"])), (2, 1), "Probe legt nichts an")
        self.I.teile_import("besitzer", {"teile": [{"name": "HK 1", "artnr": "HK-1"}, {"name": "HK 2"}]})
        self.assertEqual(sorted(t["name"] for t in self.I.stand()["teile"]), ["Alt", "HK 1", "HK 2"])

    def test_zaehlen_mit_standort_ohne_standorte_abgelehnt(self):
        t = self.I.teil_neu("besitzer", {"name": "A"})
        with self.assertRaises(ValueError):
            self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Lager", "menge": 5})
        self.assertEqual((self.I.stand()["teile"][0]["menge"], self.I.stand()["buchungen"]), (0, []))

    def test_zaehlen_am_standort_heisst_gezaehlt(self):
        self.orte()
        t = self.I.teil_neu("besitzer", {"name": "A", "zaehlung": "offen"})
        t = self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Lager", "menge": 47})["teil"]
        self.assertEqual((t["zaehlung"], self.I.menge_text(t)), ("", "47 Stk."))

    def test_lange_saetze_bleiben_schnell(self):
        self.orte()
        start = time.time()
        with self.assertRaises(ValueError):
            self.I.verstehen("im " * 8000 + "x")
        self.assertLess(time.time() - start, 1)
        self.assertEqual(self.I.verstehen("2 Dübel aus dem Lager entnommen")["standort"], "Lager")

    def test_artnr_kennungsform_sagt_warum(self):
        with self.assertRaises(ValueError) as e:
            self.I.teil_neu("besitzer", {"name": "A", "artnr": "123456"})
        self.assertIn("wie eine Kennung", str(e.exception))

    def test_export_zeigt_orte_und_artnr(self):
        self.orte()
        t = self.I.teil_neu("besitzer", {"name": "Heizkörper A", "artnr": "HK-1"})
        self.I.zaehlen("besitzer", {"teil": t["id"], "standort": "Lager", "menge": 47})
        l = self.I.text_liste()
        self.assertIn("Heizkörper A (HK-1)", l)
        self.assertIn("47 Stk. (Laden – · Lager 47 · Beschädigt –)", l)
        self.assertIn("Beschädigt, zählt nicht zum Bestand", l)


class KalenderLokal(unittest.TestCase):
    def setUp(self):
        import kalender
        self.K = kalender
        t = Path(tempfile.mkdtemp(prefix="kal-", dir=TMP))
        for k, v in (("DATEI", t / "kalender.json"), ("TERMINE", t / "termine.json")):
            p = mock.patch.object(kalender, k, v)
            p.start()
            self.addCleanup(p.stop)

    def test_geht_ohne_konto(self):
        from datetime import datetime, timedelta
        m = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        self.K.termin_neu("besitzer", {"titel": "Zahnärztin", "start": m + " 14:00", "dauer": 30, "ort": "Praxis"})
        self.K.termin_neu("claude", {"titel": "Urlaub", "start": m, "ganztag": True})
        d = self.K.termine(tage=3)
        self.assertEqual(sorted(t["titel"] for t in d["termine"]), ["Urlaub", "Zahnärztin"])
        z = next(t for t in d["termine"] if t["titel"] == "Zahnärztin")
        self.assertEqual((z["start"], z["ende"]), (m + "T14:00:00", m + "T14:30:00"))
        self.assertEqual(d["fehler"], [])

    def test_ausserhalb_des_zeitraums_nicht_dabei(self):
        self.K.termin_neu("besitzer", {"titel": "Fern", "start": "2099-01-01 10:00"})
        self.K.termin_neu("besitzer", {"titel": "Alt", "start": "2001-01-01 10:00"})
        self.assertEqual(self.K.termine(tage=7)["termine"], [])

    def test_unsinn_wird_abgewiesen(self):
        for b in ({"titel": "", "start": "2030-01-01 10:00"}, {"titel": "X", "start": "morgen"},
                  {"titel": "X", "start": "2030-01-01 10:00", "ende": "2030-01-01 09:00"}, {"titel": "X", "start": "2030-01-01", "kalender": "Gibtsnicht"}):
            with self.assertRaises(ValueError):
                self.K.termin_neu("besitzer", b)

    def test_entfernen_nur_markiert_und_nur_eigene(self):
        t = self.K.termin_neu("besitzer", {"titel": "Weg", "start": "2030-01-01 10:00"})
        self.K.termin_weg(t["id"])
        self.assertIn("entfernt", json.loads(self.K.TERMINE.read_text(encoding="utf-8"))["termine"][0])
        with self.assertRaises(ValueError):
            self.K.termin_weg(t["id"])

    def ics(self, *z):
        return "\r\n".join(("BEGIN:VCALENDAR", "BEGIN:VEVENT", *z, "END:VEVENT", "END:VCALENDAR"))

    def test_ics_erinnerung_ueberschreibt_den_titel_nicht(self):
        e = self.K._ereignisse(self.ics("SUMMARY:Termin", "DTSTART:20300101T100000Z", "BEGIN:VALARM", "SUMMARY:Alarm", "END:VALARM"), "K")
        self.assertEqual(e[0]["titel"], "Termin")

    def test_ics_abgesagt_und_zeichen(self):
        self.assertEqual(self.K._ereignisse(self.ics("SUMMARY:Weg", "DTSTART:20300101T100000Z", "STATUS:CANCELLED"), "K"), [])
        b = chr(92)
        e = self.K._ereignisse(self.ics(f"SUMMARY:A{b}, B{b}; C{b}nD", "DTSTART;VALUE=DATE:20300101"), "K")
        self.assertEqual((e[0]["titel"], e[0]["ganztag"], e[0]["start"]), ("A, B; C\nD", True, "2030-01-01"))

    def test_ohne_zeitzonen_datenbank_gilt_die_ortszeit(self):
        with mock.patch.object(self.K, "_zone", return_value=None):   # so ist es unter Windows ohne tzdata
            e = self.K._ereignisse(self.ics("DTSTART;TZID=Europe/Vienna:20300101T100000"), "K")
        self.assertEqual(e[0]["start"], "2030-01-01T10:00:00")


class KalenderVerbunden(unittest.TestCase):
    """Gegen einen kleinen CalDAV-Dienst auf diesem Rechner."""
    def setUp(self):
        import http.server
        import threading
        import kalender
        self.K = kalender
        t = Path(tempfile.mkdtemp(prefix="kalv-", dir=TMP))
        for k, v in (("DATEI", t / "kalender.json"), ("TERMINE", t / "termine.json")):
            p = mock.patch.object(kalender, k, v)
            p.start()
            self.addCleanup(p.stop)
        self.puts = []
        test = self

        class Dienst(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def antwort(self, code, text="", **kopf):
                self.send_response(code)
                for k, v in kopf.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(text.encode())))
                self.end_headers()
                self.wfile.write(text.encode())

            def do_PROPFIND(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.path == "/umleitung/":
                    return self.antwort(302, Location="http://localhost:1/geheim/")
                k = '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:a="http://apple.com/ns/ical/"><d:response><d:href>/x/</d:href><d:propstat><d:prop>%s</d:prop></d:propstat></d:response>%s</d:multistatus>'
                if self.path == "/kein-xml/":
                    return self.antwort(207, "das ist kein xml")
                if self.path == "/":
                    return self.antwort(207, k % ("<d:current-user-principal><d:href>/p/</d:href></d:current-user-principal>", ""))
                if self.path == "/p/":
                    return self.antwort(207, k % ("<c:calendar-home-set><d:href>/h/</d:href></c:calendar-home-set>", ""))
                return self.antwort(207, '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:a="http://apple.com/ns/ical/"><d:response><d:href>/h/arbeit/</d:href><d:propstat><d:prop><d:displayname>Arbeit</d:displayname><d:resourcetype><d:collection/><c:calendar/></d:resourcetype></d:prop></d:propstat></d:response></d:multistatus>')

            def do_REPORT(self):
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                ics = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:Besprechung\r\nDTSTART:20300101T100000Z\r\nEND:VEVENT\r\nEND:VCALENDAR"
                self.antwort(207, f'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response><d:href>/h/arbeit/1.ics</d:href><d:propstat><d:prop><c:calendar-data>{ics}</c:calendar-data></d:prop></d:propstat></d:response></d:multistatus>')

            def do_PUT(self):
                test.puts.append((self.path, self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()))
                self.antwort(201)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Dienst)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.url = f"http://127.0.0.1:{self.srv.server_port}"

    def test_verbinden_lesen_eintragen_und_kein_passwort_nach_aussen(self):
        d = self.K.einrichten("andere", ADR, "geheim-1234", self.url + "/")
        self.assertEqual([c["name"] for c in d["kalender"]], ["Arbeit"])
        self.assertEqual(d["ziel_name"], "Arbeit")
        agent = json.dumps(self.K.stand())
        for x in ("geheim-1234", ADR, "/h/arbeit"):
            self.assertNotIn(x, agent)
        self.assertNotIn("geheim-1234", json.dumps(self.K.stand_besitzer()))
        from datetime import datetime
        t = self.K.termine(von=datetime(2030, 1, 1), tage=2)
        self.assertEqual(([x["titel"] for x in t["termine"]], t["fehler"]), (["Besprechung"], []))
        r = self.K.termin_neu("claude", {"titel": "Neu, mit Komma", "start": "2030-02-01 10:00"})
        self.assertFalse(r["lokal"])
        self.assertTrue(self.puts[0][0].startswith("/h/arbeit/zentrale-"))
        self.assertIn("SUMMARY:Neu" + chr(92) + ", mit Komma", self.puts[0][1])
        # zurück auf eigene Termine: nichts geht mehr an den Kalender
        self.K.waehlen("lokal")
        self.assertTrue(self.K.termin_neu("claude", {"titel": "Lokal", "start": "2030-02-02 10:00"})["lokal"])
        self.assertEqual(len(self.puts), 1)

    def test_umleitung_zu_fremden_bekommt_das_passwort_nicht(self):
        with self.assertRaisesRegex(ValueError, "fremde Adresse"):
            self.K.einrichten("andere", ADR, "geheim-1234", self.url + "/umleitung/")

    def test_passwort_nur_ueber_https(self):
        with self.assertRaisesRegex(ValueError, "https"):
            self.K.einrichten("andere", ADR, "geheim-1234", "http://cloud.example.org/dav/")

    def test_kaputte_antwort_ist_ein_klarer_fehler(self):
        with self.assertRaisesRegex(ValueError, "keine lesbare Antwort"):
            self.K.einrichten("andere", ADR, "geheim-1234", self.url + "/kein-xml/")

    def test_nicht_erreichbarer_kalender_steht_in_fehler(self):
        self.K.einrichten("andere", ADR, "geheim-1234", self.url + "/")
        self.K.termin_neu("claude", {"titel": "Lokal", "start": "2030-01-01 10:00", "kalender": "lokal"})
        self.srv.shutdown()
        self.srv.server_close()
        from datetime import datetime
        d = self.K.termine(von=datetime(2030, 1, 1), tage=2)
        self.assertEqual([x["titel"] for x in d["termine"]], ["Lokal"], "die eigenen Termine bleiben sichtbar")
        self.assertEqual(len(d["fehler"]), 1)


class Pinwand(unittest.TestCase):
    def setUp(self):
        import hub, pinwand, pos
        self.pw, self.pos, self.B = pinwand, pos, hub.BESITZER
        t = Path(tempfile.mkdtemp(prefix="pin-", dir=TMP))
        for mod, d in ((pinwand, "pw.json"), (pos, "p.json")):
            p = mock.patch.object(mod, "DATEI", t / d)
            p.start()
            self.addCleanup(p.stop)
        self.pid = pos.projekt_neu(self.B, {"name": "Gartenhaus"})["id"]

    def test_erste_karte_markiert_das_projekt_und_findet_platz(self):
        a = self.pw.neu("claude", self.pid, {"titel": "Holz", "gruppe": "Material"})
        b = self.pw.neu("claude", self.pid, {"titel": "Schrauben", "gruppe": "Material"})
        self.assertTrue(next(p for p in self.pos.stand()["projekte"] if p["id"] == self.pid).get("pinwand"))
        self.assertNotEqual((a["x"], a["y"]), (b["x"], b["y"]), "zwei Karten liegen nicht aufeinander")
        self.assertEqual(json.loads(self.pw.DATEI.read_bytes().decode("utf-8"))["pins"][0]["titel"], "Holz", "immer UTF-8, auch unter Windows")

    def test_sammelanlage_ist_wiederholbar_und_alles_oder_nichts(self):
        L = [{"titel": "A", "gruppe": "G"}, {"titel": "B", "gruppe": "G"}]
        self.pw.neu("claude", self.pid, {"pins": L})
        self.pw.neu("claude", self.pid, {"pins": L})
        self.assertEqual(len(self.pw.pins(self.pid)["pins"]), 2)
        with self.assertRaises(ValueError):
            self.pw.neu("claude", self.pid, {"pins": [{"titel": "C"}, {"titel": ""}]})
        self.assertEqual(len(self.pw.pins(self.pid)["pins"]), 2, "nichts Halbes")

    def test_entfernen_markiert_nur_und_laesst_sich_zurueckholen(self):
        k = self.pw.neu("claude", self.pid, {"titel": "Weg damit"})
        self.pw.aendern(self.B, self.pid, k["id"], {"entfernen": True})
        r = self.pw.pins(self.pid, entfernte=True)
        self.assertEqual((r["pins"], [x["id"] for x in r["entfernte"]]), ([], [k["id"]]))
        self.assertEqual(len(json.loads(self.pw.DATEI.read_text(encoding="utf-8"))["pins"]), 1, "bleibt in den Daten")
        self.pw.zurueckholen("claude", self.pid, k["id"])
        self.assertEqual([x["id"] for x in self.pw.pins(self.pid)["pins"]], [k["id"]])

    def test_verschieben_alles_oder_nichts(self):
        a = self.pw.neu("claude", self.pid, {"titel": "A", "x": 10, "y": 10})
        with self.assertRaises(ValueError):
            self.pw.verschieben("claude", self.pid, {"pins": [{"id": a["id"], "x": 300, "y": 300}, {"id": "ffffff", "x": 1, "y": 1}]})
        self.assertEqual((self.pw.pins(self.pid)["pins"][0]["x"]), 10)
        self.pw.verschieben("claude", self.pid, {"pins": [{"id": a["id"], "x": 300, "y": 300}]})
        self.assertEqual((self.pw.pins(self.pid)["pins"][0]["x"]), 300)

    def test_eingaben_werden_geprueft(self):
        k = self.pw.neu("claude", self.pid, {"titel": "K"})
        for falsch in ({"x": 99999, "y": 1}, {"x": 1}, {"farbe": "pink"}, {"groesse": "XL"}, {"titel": ""}, {"titel": ["Liste"]}, {"b": True}):
            with self.assertRaises(ValueError, msg=falsch):
                self.pw.aendern("claude", self.pid, k["id"], falsch)
        for falsch in ("ffffff", "../x", ""):
            with self.assertRaises(ValueError):
                self.pw.pins(falsch)
        self.pw.aendern("claude", self.pid, k["id"], {"farbe": "gelb", "groesse": "L", "symbol": "🔧"})
        self.pw.aendern("claude", self.pid, k["id"], {"farbe": ""})
        x = self.pw.pins(self.pid)["pins"][0]
        self.assertEqual((x.get("farbe"), x["groesse"], x["symbol"]), (None, "L", "🔧"))


class BerichtProjekt(unittest.TestCase):
    def setUp(self):
        import berichte, hub, pos
        self.b, self.pos, self.B = berichte, pos, hub.BESITZER
        t = Path(tempfile.mkdtemp(prefix="ber-", dir=TMP))
        for mod, name in ((berichte, "DATEI"), (pos, "DATEI")):
            p = mock.patch.object(mod, name, t / (name + mod.__name__))
            p.start()
            self.addCleanup(p.stop)
        self.pos.projekt_neu(self.B, {"name": "Website"})

    def test_name_wird_zum_richtigen_name(self):
        self.assertEqual(self.b.neu("claude", {"titel": "T", "projekt": "website"})["projekt"], "Website")
        self.assertEqual(self.b.neu("claude", {"titel": "T", "projekt": "aufräumen"})["projekt"], "Aufräumen")
        self.assertEqual(self.b.neu("claude", {"titel": "T"})["projekt"], "")

    def test_unbekannt_wird_abgewiesen_und_nennt_die_liste(self):
        with self.assertRaises(ValueError) as e:
            self.b.neu("claude", {"titel": "T", "projekt": "Umzug"})
        self.assertIn("Website", str(e.exception))
        self.assertIn("Aufräumen", str(e.exception))
        self.assertEqual(self.b.liste()["berichte"], [])

    def test_projekt_aendern_nur_besitzer_und_eigener_agent(self):
        x = self.b.neu("claude", {"titel": "T"})
        with self.assertRaises(PermissionError):
            self.b.projekt_aendern("codex", x["id"], {"projekt": "Zentrale"})
        self.assertEqual(self.b.projekt_aendern("claude", x["id"], {"projekt": "zentrale"})["projekt"], "Zentrale")
        self.assertEqual(self.b.projekt_aendern(self.B, x["id"], {"projekt": ""})["projekt"], "")
        with self.assertRaises(ValueError):
            self.b.projekt_aendern("claude", x["id"], {"projekt": "Gibtsnicht"})

    def test_erledigt_merkt_wer_es_war(self):
        x = self.b.neu("claude", {"titel": "T", "fragen": [{"text": "Ja?"}]})
        y = self.b.erledigt("claude", x["id"], {"antworten": ["Ja"]})
        self.assertEqual((y["erledigt_von"], y["fragen"][0]["antwort"]["von"]), ("claude", "claude"))

    def test_lesen_nimmt_anderen_chats_die_antwort_nicht_weg(self):
        x = self.b.neu("claude", {"titel": "T"})
        self.b.nachricht(self.B, x["id"], {"text": "Antwort"})
        self.b.lesen("claude", x["id"])
        self.assertEqual(len(self.b._offen_fuer(self.b._lesen(), "claude", "")), 1, "nur gelesen: bleibt neu")
        self.b.nachricht("claude", x["id"], {"text": "Danke, mache ich"})
        self.assertEqual(self.b._offen_fuer(self.b._lesen(), "claude", ""), [], "beantwortet: abgeholt")
        self.b.nachricht(self.B, x["id"], {"text": "Noch was"})
        self.b.lesen("claude", x["id"], abholen=True)
        self.assertEqual(self.b._offen_fuer(self.b._lesen(), "claude", ""), [], "ausdrücklich abgeholt")
        self.b.nachricht(self.B, x["id"], {"text": "Und das"})
        self.b.erledigt("claude", x["id"], {})
        self.assertEqual(self.b._offen_fuer(self.b._lesen(), "claude", ""), [], "geschlossen: abgeholt")


class HookEinrichten(unittest.TestCase):
    """Rückmeldung eines Kollegen (5.11.2026): Das Update schrieb settings.json jedes Mal neu, mit neuer Reihenfolge und neuer Kopie."""
    def setUp(self):
        t = Path(tempfile.mkdtemp(prefix="hke-", dir=TMP))
        spec = importlib.util.spec_from_file_location("hooks_einrichten", HIER / "hooks" / "einrichten.py")
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        self.m.DATEI = t / "settings.json"
        self.t = t

    def lauf(self, *args):
        with mock.patch.object(sys, "argv", ["x", *args]), contextlib.redirect_stdout(io.StringIO()):
            self.m.main()
        return json.loads(self.m.DATEI.read_text(encoding="utf-8"))

    def kopien(self):
        return sorted(p.name for p in self.t.glob("settings.json.vor-zentrale-*"))

    def test_zweiter_lauf_aendert_nichts_und_legt_keine_kopie(self):
        fremd = {"type": "command", "command": "eigener-melder"}
        self.m.DATEI.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [fremd]}]}}), encoding="utf-8")
        d1 = self.lauf()
        self.assertEqual(d1["hooks"]["Stop"][0]["hooks"][0], fremd, "fremder Hook bleibt vorn")
        self.assertEqual(sorted(d1["hooks"]), ["Stop", "StopFailure", "UserPromptSubmit"])
        roh, k = self.m.DATEI.read_bytes(), self.kopien()
        self.lauf()
        self.assertEqual((self.m.DATEI.read_bytes(), self.kopien()), (roh, k), "nichts geschrieben, keine neue Kopie")

    def test_anderer_python_pfad_bleibt_stehen_kaputter_wird_ersetzt(self):
        gut = {"type": "command", "command": f'"/anderes/python3" "{self.m.HOOK.as_posix()}"', "timeout": 5}
        kaputt = {"type": "command", "command": '"py" "/gibt/es/nicht/claude_lauf.py"'}
        self.m.DATEI.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [gut]}], "UserPromptSubmit": [{"hooks": [kaputt]}]}}), encoding="utf-8")
        d = self.lauf()
        self.assertEqual(d["hooks"]["Stop"][0]["hooks"], [gut])
        self.assertNotIn("/gibt/es/nicht", json.dumps(d))
        self.assertIn("StopFailure", d["hooks"])

    def test_weg_traegt_aus(self):
        self.lauf()
        self.assertNotIn("hooks", self.lauf("--weg"))

    def test_abbruch_wird_als_fehler_gemeldet(self):
        self.assertIn('"quelle": "hook", "fehler": True', (HIER / "hooks" / "claude_lauf.py").read_text(encoding="utf-8"))


class BerichtFrage(unittest.TestCase):
    """Neue Frage an einen bestehenden Bericht (Vorschlag eines Kollegen): Die Antwort des Besitzers war eine Bitte
    („zeig mir welche“), danach hatte der Bericht keine offene Frage mehr. Mit der angehängten Frage ist er wieder offen."""
    def setUp(self):
        import berichte, hub
        self.b, self.B = berichte, hub.BESITZER
        t = Path(tempfile.mkdtemp(prefix="bfr-", dir=TMP))
        p = mock.patch.object(berichte, "DATEI", t / "b.json")
        p.start()
        self.addCleanup(p.stop)
        x = berichte.neu("claude", {"titel": "Aufräumen", "fragen": [{"text": "Welche Ordner?", "vorschlaege": ["Alle", "Keine"]}]})
        self.id = x["id"]
        berichte.nachricht(self.B, self.id, {"text": "zeig mir welche", "frage": x["fragen"][0]["id"]})

    def test_angehaengte_frage_macht_den_bericht_wieder_offen(self):
        self.b.erledigt("claude", self.id, {})
        x = self.b.frage_dazu("claude", self.id, {"fragen": [{"text": "Diese drei in den Papierkorb?", "vorschlaege": ["Ja", "Nein"]}]})
        f = x["fragen"][-1]
        self.assertEqual((len(x["fragen"]), f["vorschlaege"], f["antwort"]), (2, ["Ja", "Nein"], None))
        self.assertNotEqual(f["id"], x["fragen"][0]["id"])
        self.assertTrue(f.get("zeit"))
        x = self.b.lesen("claude", self.id)
        self.assertEqual(self.b.offene_fragen(x), 1)
        self.assertNotIn("erledigt", x)
        self.assertFalse(x["gelesen"])
        self.assertEqual(self.b._offen_fuer(self.b._lesen(), "claude", ""), [], "wer nachfragt, hat die Antwort davor gelesen")

    def test_antwort_auf_die_neue_frage_kommt_beim_agenten_an(self):
        f = self.b.frage_dazu("claude", self.id, {"fragen": [{"text": "Alle drei?", "vorschlaege": ["Ja", "Nein"]}]})["fragen"][-1]
        self.b.nachricht(self.B, self.id, {"text": "Ja", "frage": f["id"]})
        neu = [m for m in self.b.warten("claude", sekunden=1)["neu"] if m["text"] == "Ja"]
        self.assertEqual([m["offen"] for m in neu], [0])

    def test_nur_besitzer_und_anleger_und_grenzen(self):
        with self.assertRaises(PermissionError):
            self.b.frage_dazu("codex", self.id, {"fragen": [{"text": "Fremd?"}]})
        for b in ({}, {"fragen": []}, {"fragen": [{"text": "  "}]}, {"fragen": [{"text": f"F{i}?"} for i in range(80)]}):
            with self.assertRaises(ValueError):
                self.b.frage_dazu("claude", self.id, b)
        self.assertEqual(len(self.b.lesen("claude", self.id)["fragen"]), 1, "nichts gespeichert")
        self.assertEqual(len(self.b.frage_dazu(self.B, self.id, {"fragen": [{"text": "Selbst?"}]})["fragen"]), 2)

    def test_seite_zeigt_die_frage_nach_der_nachricht_davor(self):
        for datei in ("index.src.html", "index.html"):
            self.assertIn("E.push([Math.max(seit, f.zeit || 0), f.zeit ? 1e6 + k : 2 * k + 1,", (HIER / "zentrale" / datei).read_text(encoding="utf-8"), datei)


class LaufZwischennachricht(unittest.TestCase):
    def test_nachricht_mitten_in_der_antwort_bricht_nichts_ab(self):
        import laeufe
        t0 = time.time() - 400   # echte Zeit: lage() legt sonst alte Läufe ohne Lebenszeichen ab
        with mock.patch.object(laeufe.time, "time", return_value=t0):
            laeufe.melden("claude", {"aktion": "start", "lauf": "chat-zw", "titel": "Aufgabe", "quelle": "hook"})
        with mock.patch.object(laeufe.time, "time", return_value=t0 + 300):
            x = laeufe.melden("claude", {"aktion": "start", "lauf": "chat-zw", "titel": "noch was", "quelle": "hook"})
        self.assertEqual((x["start"], x["titel"]), (t0, "Aufgabe"), "derselbe Lauf läuft weiter")
        self.assertFalse([f for f in laeufe.lage()["fertig"] if f["lauf"] == "chat-zw" and f["status"] == "abgebrochen"])
        with mock.patch.object(laeufe.time, "time", return_value=t0 + 390):
            laeufe.melden("claude", {"aktion": "start", "lauf": "chat-zw", "titel": "Neues Thema", "quelle": "hand"})
        self.assertTrue([f for f in laeufe.lage()["fertig"] if f["lauf"] == "chat-zw" and f["status"] == "abgebrochen"], "ein neuer Lauf von Hand legt den alten ab")


class LaufAbo(unittest.TestCase):
    def test_abo_bleibt_beim_chat_und_wird_gemerkt(self):
        import laeufe
        laeufe.melden("claude", {"aktion": "start", "lauf": "chat-abo1", "titel": "T", "quelle": "hook", "abo": "claude-2"})
        x = laeufe.melden("claude", {"aktion": "start", "lauf": "chat-abo1", "titel": "weiter", "quelle": "hook"})
        self.assertEqual(x["abo"], "claude-2")
        self.assertEqual(laeufe.lage()["abos"]["claude-2"]["agent"], "claude")
        y = laeufe.melden("claude", {"aktion": "start", "lauf": "chat-abo2", "titel": "Ohne", "quelle": "hook"})
        self.assertFalse(y.get("abo"), "ohne Abo wie bisher")


class AufgabenUndWunsch(unittest.TestCase):
    def setUp(self):
        import hub, pos, wuensche
        self.pos, self.w, self.B = pos, wuensche, hub.BESITZER
        t = Path(tempfile.mkdtemp(prefix="auf-", dir=TMP))
        for mod, name, d in ((pos, "DATEI", "p.json"), (wuensche, "DATEI", "w.json")):
            p = mock.patch.object(mod, name, t / d)
            p.start()
            self.addCleanup(p.stop)
        self.wid = wuensche.neu("claude", {"titel": "W", "prio": "hoch"})["id"]

    def test_letzte_aufgabe_hakt_den_wunsch_nicht_mehr_ab(self):
        a = self.pos.aufgabe_neu("claude", {"titel": "A", "wunsch": self.wid})
        x = self.pos.aufgabe_aendern("claude", a["id"], {"erledigt": True})
        self.assertTrue(x["alle_schritte_fertig"])
        self.assertEqual(self.w.zeigen(self.wid)["status"], "offen")

    def test_von_alter_fassung_abgehakt_oeffnet_sich_wieder(self):
        self.w.aendern("zentrale", self.wid, {"status": "erledigt", "ergebnis": "Alle Schritte erledigt"})
        self.pos.aufgabe_neu("claude", {"titel": "Neu", "wunsch": self.wid})
        self.assertEqual(self.w.zeigen(self.wid)["status"], "offen")

    def test_verwerfen_ist_nicht_erledigt_und_merkt_den_grund(self):
        a = self.pos.aufgabe_neu("claude", {"titel": "Aus Test"})
        with self.assertRaises(PermissionError):
            self.pos.aufgabe_aendern("codex", a["id"], {"entfernen": True, "grund": "x"})
        x = self.pos.aufgabe_aendern("claude", a["id"], {"entfernen": True, "grund": "aus einem Test"})
        self.assertEqual((x["erledigt"], x["grund"]), (None, "aus einem Test"))
        self.assertTrue(x["entfernt"])

    def test_projekt_einer_aufgabe_aendern(self):
        p = self.pos.projekt_neu(self.B, {"name": "Lager"})
        a = self.pos.aufgabe_neu("claude", {"titel": "A"})
        self.assertEqual(self.pos.aufgabe_aendern("claude", a["id"], {"projekt": "lager"})["projekt"], p["id"])
        self.assertIsNone(self.pos.aufgabe_aendern("claude", a["id"], {"projekt": ""})["projekt"])


class NotizTitel(unittest.TestCase):
    def setUp(self):
        import notizen
        self.n = notizen
        t = Path(tempfile.mkdtemp(prefix="ntz-", dir=TMP))
        (t / "Geräte").mkdir()
        p = mock.patch.object(notizen, "WURZEL", t)
        p.start()
        self.addCleanup(p.stop)

    def test_ordner_im_titel_und_endung(self):
        self.assertEqual(self.n.neu("", "Geräte/Drucker.md", "x")["pfad"], "Geräte/Drucker.md")
        self.assertEqual(self.n.neu("", "Lose.md", "x")["pfad"], "Lose.md")

    def test_schraegstrich_ohne_vorhandenen_ordner_bleibt_titel(self):
        self.assertEqual(self.n.neu("", "Rechnung 3/2026", "x")["pfad"], "Rechnung 3 2026.md")
        self.assertEqual(self.n.neu("Geräte", "Und/Oder", "x")["pfad"], "Geräte/Und Oder.md")

    def test_kein_ausbruch(self):
        pfad = self.n.neu("", "../../boese", "x")["pfad"]
        self.assertNotIn("/", pfad)
        self.assertTrue((self.n.WURZEL / pfad).is_file())


class ClientSchalter(unittest.TestCase):
    def test_text_ist_keine_kurzform_von_text_datei(self):
        r = subprocess.run([sys.executable, "-I", str(HIER / "zentrale_client.py"), "wunsch-notiz", "1", "--text-dat", "x"], capture_output=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--text-dat", r.stderr)
        import argparse
        import zentrale_client as c
        self.assertEqual(c.text_aus(argparse.Namespace(text=None, text_schalter="Stand: x")), "Stand: x")


class LaufTitel(unittest.TestCase):
    def test_folge_nachricht_ersetzt_den_titel_nicht(self):
        import laeufe
        laeufe.melden("claude", {"aktion": "start", "lauf": "chat-t", "titel": "Rechnungen ordnen", "quelle": "hook"})
        x = laeufe.melden("claude", {"aktion": "start", "lauf": "chat-t", "titel": "ja mach", "quelle": "hook"})
        self.assertEqual(x["titel"], "Rechnungen ordnen")
        x = laeufe.melden("claude", {"aktion": "stand", "lauf": "chat-t", "schritt": "Block 2", "titel": "Rechnungen und Belege"})
        self.assertEqual((x["titel"], x["schritt"]), ("Rechnungen und Belege", "Block 2"))
        x = laeufe.melden("claude", {"aktion": "start", "lauf": "chat-t", "titel": "weiter", "quelle": "hook"})
        self.assertEqual(x["titel"], "Rechnungen und Belege")


class Mails(unittest.TestCase):
    def setUp(self):
        import mails
        self.M = mails
        t = Path(tempfile.mkdtemp(prefix="mail-", dir=TMP))
        for k, v in (("KONF", t / "mail.json"), ("DATEI", t / "mails.json"), ("KALENDER", t / "kalender.json")):
            p = mock.patch.object(mails, k, v)
            p.start()
            self.addCleanup(p.stop)

    def mail(self, von="a" + chr(64) + "example.org", **k):
        return dict({"konto": "x", "uid": 1, "zeit": 100, "von": von, "von_name": "A", "an": "", "betreff": "B", "text": "T", "anhaenge": [], "message_id": str(k.get("uid", 1)),
                     "status": "neu", "wichtig": None, "grund": "", "kurz": "", "gelesen": False, "erledigt": False, "alt": False}, **k)

    def test_zertifikat_wird_geprueft(self):
        import ssl
        with mock.patch.object(self.M.imaplib, "IMAP4_SSL") as i:
            self.M._imap("imap.example.org", ADR, "x")
        kx = i.call_args.kwargs["ssl_context"]
        self.assertEqual((kx.verify_mode, kx.check_hostname), (ssl.CERT_REQUIRED, True))

    def test_postfach_wird_nur_gelesen(self):
        fake = mock.Mock()
        fake.untagged_responses = {"UIDVALIDITY": [b"7"]}
        fake.select.return_value = ("OK", [b"1"])
        fake.status.return_value = ("OK", [b"INBOX (UIDNEXT 3)"])
        roh = b"From: A <a" + AT + b"b.example>\r\nSubject: Hallo\r\nDate: Tue, 1 Jan 2030 10:00:00 +0000\r\n\r\nText"

        def uid(befehl, *a):
            if befehl == "search":
                return "OK", [b"1 2"]
            return ("OK", [b"1 (RFC822.SIZE 10)"]) if "SIZE" in a[1] else ("OK", [(b"x", roh)])
        fake.uid.side_effect = uid
        with mock.patch.object(self.M, "_imap", return_value=fake):
            neu, st, _ = self.M._holen({"host": "h", "adresse": ADR, "passwort": "p"})
        fake.select.assert_called_once_with("INBOX", readonly=True)
        abrufe = [c.args[2] for c in fake.uid.call_args_list if c.args[0] == "fetch"]
        self.assertTrue(all("PEEK" in x or "SIZE" in x for x in abrufe), abrufe)
        for verboten in ("store", "expunge", "append", "delete", "copy", "move"):
            self.assertFalse(getattr(fake, verboten).called, verboten)
        self.assertFalse([c for c in fake.uid.call_args_list if c.args[0].lower() not in ("search", "fetch")])
        self.assertEqual((len(neu), st["INBOX"]["uid"], neu[0]["betreff"]), (2, 2, "Hallo"))

    def test_html_und_kaputte_bytes(self):
        roh = (b'From: =?utf-8?q?M=C3=BCller?= <m' + AT + b'b.example>\r\nSubject: =?bad?q?x?= \xff\r\nContent-Type: text/html; charset=nix\r\n\r\n'
               b"<style>a{}</style><script>boese()</script><p>Gr\xfc\xdfe</p>")
        m = self.M._zerlegen(roh, "x", 1, False)
        self.assertNotIn("boese", m["text"])
        self.assertEqual(m["von_name"], "Müller")
        json.dumps(m, ensure_ascii=False).encode("utf-8")

    def test_anhaenge_nur_als_name(self):
        roh = (b"From: a" + AT + b"b.example\r\nSubject: S\r\nMIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=g\r\n\r\n--g\r\nContent-Type: text/plain\r\n\r\nHallo\r\n"
               b'--g\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename="r.pdf"\r\nContent-Transfer-Encoding: base64\r\n\r\nQUJD\r\n--g--\r\n')
        m = self.M._zerlegen(roh, "x", 1, False)
        self.assertEqual((m["anhaenge"], m["text"]), (["r.pdf"], "Hallo"))

    def test_agenten_lesen_nur_mit_erlaubnis(self):
        self.M.darf("besitzer")
        with self.assertRaises(PermissionError):
            self.M.darf("claude")
        self.M.agenten_erlauben(True)
        self.M.darf("claude")
        self.M.agenten_erlauben(False)
        with self.assertRaises(PermissionError):
            self.M.darf("claude")

    def test_passwort_kommt_nie_heraus(self):
        with mock.patch.object(self.M, "_imap"):
            self.M.verbinden("andere", ADR, "geheim-1234", "imap.example.org")
        self.assertNotIn("geheim-1234", json.dumps(self.M.liste()))
        self.assertIn("geheim-1234", self.M.KONF.read_text(encoding="utf-8"))

    def test_verbinden_prueft_die_eingaben(self):
        with mock.patch.object(self.M, "_imap") as i:
            for b in (("andere", ADR, "p", "kein host"), ("andere", "keine-adresse", "p", "imap.example.org"), ("andere", ADR, "", "imap.example.org"), ("fremd", ADR, "p", "imap.example.org")):
                with self.assertRaises(ValueError):
                    self.M.verbinden(*b)
            self.assertFalse(i.called)

    def test_regel_des_besitzers_gilt_fuer_neue_und_geht_vor(self):
        with self.M._sperre:
            self.M._einsortieren({}, [self.mail(uid=1)])
        self.M.aendern("besitzer", 1, {"wichtig": True})
        with self.M._sperre:
            self.M._einsortieren(self.M._konf(), [self.mail(uid=2, message_id="2")])
        self.assertEqual(self.M.lesen(2)["wichtig"], True)
        self.M.aendern("claude", 2, {"wichtig": False})
        self.assertEqual(self.M._konf()["regeln"]["a" + chr(64) + "example.org"], True, "ein Agent ändert keine Regel")
        with self.M._sperre:
            self.M._einsortieren(self.M._konf(), [self.mail(uid=3, message_id="3", von="c" + chr(64) + "example.org")])
        self.M.aendern("besitzer", 3, {"wichtig": False})
        self.assertFalse(self.M.bewerten("claude", 3, {"wichtig": True})["wichtig"], "die Regel des Besitzers geht vor")

    # ---------- Zeitraum, Ordner, Suche ----------

    def fake_imap(self, uids, roh=None):
        roh = roh or (b"From: A <a" + AT + b"b.example>\r\nSubject: Hallo\r\nDate: Tue, 1 Jan 2030 10:00:00 +0000\r\n\r\nText")
        fake = mock.Mock()
        fake.untagged_responses = {"UIDVALIDITY": [b"7"]}
        fake.select.return_value = ("OK", [b"1"])
        fake.status.return_value = ("OK", [b"X (UIDNEXT %d)" % (max(uids + [0]) + 1)])

        def uid(befehl, *a):
            if befehl == "search":
                if a[1] == "SINCE":
                    return "OK", [" ".join(map(str, uids)).encode()]
                unten = int(a[1].split()[1].split(":")[0])
                return "OK", [" ".join(str(u) for u in uids if u >= unten).encode() or str(max(uids)).encode()]
            return ("OK", [b"1 (FLAGS (\\Seen) RFC822.SIZE 10)"]) if "SIZE" in a[1] else ("OK", [(b"x", roh)])
        fake.uid.side_effect = uid
        return fake

    def test_zeitraum_holt_aelteres_in_kleinen_schritten_ohne_luecke(self):
        fake = self.fake_imap(list(range(1, 751)))
        x = {"host": "h", "adresse": ADR, "passwort": "p", "tage": 90}
        geholt = []
        with mock.patch.object(self.M, "_imap", return_value=fake):
            for _ in range(4):
                neu, x["stand"], f = self.M._holen(x)
                self.assertEqual(f, "")
                self.assertLessEqual(len(neu), self.M.MAX_RUNDE)
                geholt += [m["uid"] for m in neu]
        self.assertEqual(sorted(geholt), list(range(1, 751)))
        self.assertEqual(x["stand"]["INBOX"]["fertig"], 90)
        self.assertFalse(self.M._holt_nach(x))
        self.assertTrue(self.M._holt_nach(dict(x, tage=365)), "größerer Zeitraum holt weiter nach")

    def test_alter_stand_der_fassung_davor_holt_nichts_doppelt(self):
        fake = self.fake_imap([1, 2, 3])
        x = {"host": "h", "adresse": ADR, "passwort": "p", "uid": 2, "uidvalidity": "7"}
        with mock.patch.object(self.M, "_imap", return_value=fake):
            neu, st, _ = self.M._holen(x)
        self.assertEqual([m["uid"] for m in neu], [3])
        self.assertEqual(st["INBOX"]["uid"], 3)

    def test_ordner_der_nicht_geht_haelt_die_anderen_nicht_auf(self):
        fake = self.fake_imap([1])
        fake.select.side_effect = lambda o, readonly=False: ("NO", []) if "Weg" in o else ("OK", [b"1"])
        with mock.patch.object(self.M, "_imap", return_value=fake):
            neu, st, f = self.M._holen({"host": "h", "adresse": ADR, "passwort": "p", "ordner": ["Weg", "INBOX"]})
        self.assertEqual(len(neu), 1)
        self.assertIn("Weg", f)
        self.assertNotIn("Weg", st)
        self.assertTrue(all(c.kwargs.get("readonly") for c in fake.select.call_args_list), "nur lesend")

    def test_ordnernamen_lesen(self):
        self.assertEqual(self.M.ordner_name("Entw&APw-rfe"), "Entwürfe")
        self.assertEqual(self.M.ordner_name("INBOX"), "Posteingang")
        self.assertEqual(self.M.ordner_name("A&-B"), "A&B")
        z = [b'(\\HasNoChildren) "/" "INBOX"', b'(\\Noselect) "/" "Oben"', b'(\\Junk) "." "Spam"', b'() NIL Archiv', (b'() "/" {6}', b'Lang"x')]
        A = self.M._ordner_lesen(z)
        self.assertEqual([o["id"] for o in A], ["INBOX", "Archiv", 'Lang"x', "Spam"])
        self.assertEqual(next(o["art"] for o in A if o["id"] == "Spam"), "Werbung")
        self.assertEqual(self.M._q('Ein "x"'), '"Ein \\"x\\""')

    def test_einstellen_nur_was_das_postfach_nennt(self):
        with mock.patch.object(self.M, "_imap"):
            self.M.verbinden("andere", ADR, "p", "imap.example.org", tage=30)
        kid = ADR.lower()
        self.assertEqual(self.M.stand()["konten"][0]["tage"], 30)
        with mock.patch.object(self.M, "ordner_liste", return_value={"ordner": [{"id": "Shop"}], "gewaehlt": []}):
            self.M.einstellen(kid, {"ordner": ["INBOX", "Shop"], "tage": 90})
            for falsch in ({"ordner": ["Boese\r\nLOGOUT"]}, {"ordner": []}, {"tage": 5}):
                with self.assertRaises(ValueError):
                    self.M.einstellen(kid, falsch)
        s = self.M.stand()["konten"][0]
        self.assertEqual((s["tage"], [o["id"] for o in s["ordner"]]), (90, ["INBOX", "Shop"]))
        with self.assertRaises(ValueError):
            self.M.verbinden("andere", ADR, "p", "imap.example.org", tage=11)

    def test_neues_passwort_behaelt_ordner_und_stand(self):
        with mock.patch.object(self.M, "_imap"):
            self.M.verbinden("andere", ADR, "p", "imap.example.org", tage=30)
            k = self.M._konf()
            k["konten"][ADR.lower()].update(ordner=["INBOX", "Shop"], stand={"INBOX": {"uid": 9, "validity": "7", "bis": None, "fertig": 30}})
            self.M._konf_schreiben(k)
            self.M.verbinden("andere", ADR, "p2", "imap.example.org")
        x = self.M._konf()["konten"][ADR.lower()]
        self.assertEqual((x["passwort"], x["tage"], x["ordner"], x["stand"]["INBOX"]["uid"]), ("p2", 30, ["INBOX", "Shop"], 9))

    def test_suche_findet_text_auch_in_erledigtem(self):
        with self.M._sperre:
            self.M._einsortieren({}, [self.mail(uid=1, message_id="1", betreff="Anfrage Heizkörper"), self.mail(uid=2, message_id="2", text="Bitte Angebot für Tür"), self.mail(uid=3, message_id="3", betreff="Sonstiges")])
        self.M.aendern("besitzer", 2, {"erledigt": True})
        self.assertNotIn("treffer", self.M.liste())
        self.assertEqual([m["nr"] for m in self.M.liste(suche="heizkörper")["treffer"]], [1])
        self.assertEqual([m["nr"] for m in self.M.liste(suche="ANGEBOT tür")["treffer"]], [2])
        self.assertEqual(self.M.liste(suche="angebot heizung")["treffer"], [])
        self.assertEqual([m["nr"] for m in self.M.liste(art="erledigt")["treffer"]], [2])
        self.assertNotIn("text", self.M.liste(suche="tür")["treffer"][0])

    def test_nummer_wird_nicht_wiederverwendet_und_die_aeltesten_fallen_weg(self):
        with mock.patch.object(self.M, "MAX_MAILS", 2), self.M._sperre:
            self.M._einsortieren({}, [self.mail(uid=1, message_id="1", zeit=300), self.mail(uid=2, message_id="2", zeit=200)])
            self.M._einsortieren({}, [self.mail(uid=3, message_id="3", zeit=100)])   # nachgeholt: alt, Nummer neu
            self.M._einsortieren({}, [self.mail(uid=4, message_id="4", zeit=400)])
        M = self.M._mails()["mails"]
        self.assertEqual(sorted(m["uid"] for m in M), [1, 4])
        self.assertEqual(next(m for m in M if m["uid"] == 4)["nr"], 4)

    def test_gleiche_nummer_in_zwei_ordnern_ohne_kennung(self):
        with self.M._sperre:
            self.M._einsortieren({}, [self.mail(uid=1, message_id="", ordner="INBOX"), self.mail(uid=1, message_id="", ordner="Shop")])
        self.assertEqual(self.M.liste()["gesamt"], 2)

    def test_lange_warteschlange_kommt_mit_neuen_zuerst(self):
        with self.M._sperre:
            self.M._einsortieren({}, [self.mail(uid=1, message_id="1", zeit=100, alt=True), self.mail(uid=2, message_id="2", zeit=50, alt=False), self.mail(uid=3, message_id="3", zeit=200, alt=True)])
        self.assertEqual([m["zeit"] for m in self.M.offen()["mails"]], [50, 200, 100])

    # ---------- Warnung vor Betrug ----------

    def warn(self, von, name="Jemand", konto="ich" + chr(64) + "firma.example", auth="", betreff="B", text="T", vertraut=None):
        return self.M.warnung({"von": von, "von_name": name, "konto": konto, "auth": auth, "betreff": betreff, "text": text}, vertraut)

    def test_betrug_wie_er_vorkommt(self):
        at = chr(64)
        for von, name in (("x" + at + "beispiel-mail.c\u014dm".encode("idna").decode(), "Support"),   # Endung nachgebaut, verschlüsselt geschrieben
                          ("x" + at + "be\u03b9spiel.d\u0119", "Support"),                # griechisches i, Endung mit Akzent
                          ("x" + at + "\u0430\u0440\u0440\u04cf\u0435.com", "Support"),    # ganz in fremder Schrift
                          ("x" + at + "paypa1.com", "Support"),                          # 1 statt l
                          ("x" + at + "kleinanzeigen-support.example", "Support"),        # Name in der Adresse
                          ("x" + at + "post.example", "Kleinanzeigen"),                  # Name stimmt nicht zur Adresse
                          ("x" + at + "post.example", "service" + at + "paypal.com")):    # andere Adresse im Namen
            w = self.warn(von, name)
            self.assertEqual((w or {}).get("stufe"), "hoch", von)

    def test_kein_fehlalarm_bei_echten_absendern(self):
        at = chr(64)
        for von, name in (("noreply" + at + "mail.kleinanzeigen.de", "Kleinanzeigen"), ("service" + at + "paypal.de", "PayPal"), ("x" + at + "m\u00fcller-heizung.de", "Müller"),
                          ("x" + at + "xn--mller-kva.de", "Müller"), ("anna" + at + "beispiel.example", "Anna Berger"), ("x" + at + "applebees.example", "Applebees")):
            self.assertIsNone(self.warn(von, name), von)

    def test_echte_mail_der_marke_mit_druckwoertern_bleibt_ruhig(self):
        at = chr(64)
        t = "Ihr Zertifikat läuft ab, Konto bestätigen"
        self.assertIsNone(self.warn("x" + at + "mail.ionos.de", "IONOS", text=t))
        self.assertEqual(self.warn("x" + at + "post.example", text=t)["stufe"], "vorsicht")

    def test_englische_druckwoerter_von_freemail(self):
        at = chr(64)
        w = self.warn("shop.team" + at + "freemail.example", name="Store Support", text="Your store is at risk. Verify your identity within 24 hours.")
        self.assertEqual((w or {}).get("stufe"), "vorsicht")
        self.assertEqual(self.warn("x" + at + "post.example", name="Shopify", text="Your store is at risk")["stufe"], "hoch")

    def test_eigene_adresse_als_absender(self):
        at = chr(64)
        k = "ich" + at + "firma.example"
        self.assertEqual(self.warn("ich" + at + "firma.example", konto=k, auth="mx.x; spf=none; dkim=none")["stufe"], "hoch")
        self.assertEqual(self.warn("ich" + at + "firma.example", konto=k)["stufe"], "vorsicht")
        self.assertIsNone(self.warn("ich" + at + "firma.example", konto=k, auth="mx.x; dmarc=pass"))

    def test_nur_die_oberste_pruefzeile_zaehlt(self):
        roh = (b"Authentication-Results: mx.echt; dmarc=fail\r\nAuthentication-Results: boese; dmarc=pass\r\nFrom: a" + AT + b"b.example\r\nSubject: S\r\n\r\nT")
        m = self.M._zerlegen(roh, "x", 1, False)
        self.assertIn("dmarc=fail", m["auth"])
        self.assertNotIn("dmarc=pass", m["auth"])
        self.assertEqual(self.M.warnung(m)["stufe"], "hoch")

    def test_verdacht_steht_nicht_unter_wichtig_auch_mit_regel(self):
        at = chr(64)
        boese = "x" + at + "paypa1.com"
        with self.M._sperre:
            self.M._einsortieren({"regeln": {boese: True}}, [self.mail(von=boese)])
        d = self.M.liste()
        self.assertEqual(([m["nr"] for m in d["verdacht"]], d["wichtig"], d["rest"]), ([1], [], []))
        self.assertEqual([m["nr"] for m in self.M.liste(art="verdacht")["treffer"]], [1])

    def test_kein_betrug_sagt_nur_der_besitzer_und_gilt_fuer_den_absender(self):
        at = chr(64)
        von = "x" + at + "post.example"
        with self.M._sperre:
            self.M._einsortieren({}, [self.mail(von=von, von_name="Kleinanzeigen", uid=1, message_id="1"), self.mail(von=von, von_name="Kleinanzeigen", uid=2, message_id="2", auth="mx; dmarc=fail")])
        with self.assertRaises(PermissionError):
            self.M.aendern("claude", 1, {"kein_betrug": True})
        self.assertEqual(len(self.M.liste()["verdacht"]), 2)
        self.M.aendern("besitzer", 1, {"kein_betrug": True})
        d = self.M.liste()
        self.assertEqual([m["nr"] for m in d["verdacht"]], [2], "fällt die Prüfung des Anbieters durch, bleibt die Warnung")
        self.assertEqual(self.M.liste(art="verdacht")["treffer_gesamt"], 1)

    def test_keine_doppelten(self):
        with self.M._sperre:
            self.M._einsortieren({}, [self.mail()])
            self.M._einsortieren({}, [self.mail()])
        self.assertEqual(self.M.liste()["gesamt"], 1)


class Schnittstelle(unittest.TestCase):
    """Rechte und Wege über echte Anfragen an die Zentrale (ohne Schlüsseldatei: der Name steht im Kopf)."""
    def setUp(self):
        import threading
        from http.server import ThreadingHTTPServer
        import app, hub
        self.t = Path(tempfile.mkdtemp(prefix="api-", dir=TMP))
        import inventar, kalender, mails
        for z, k, v in ((inventar, "DATEI", self.t / "i.json"), (inventar, "FOTOS", self.t / "f"), (inventar, "_export_spaeter", lambda: None), (kalender, "DATEI", self.t / "k.json"), (kalender, "TERMINE", self.t / "t.json"),
                        (mails, "KONF", self.t / "m.json"), (mails, "DATEI", self.t / "ms.json"), (mails, "KALENDER", self.t / "k.json"), (hub, "who", lambda h: h.split()[-1] if h else None), (hub, "HEIMNETZ", False)):
            p = mock.patch.object(z, k, v)
            p.start()
            self.addCleanup(p.stop)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def frage(self, wer, pfad, daten=None):
        import urllib.error, urllib.request
        r = urllib.request.Request(f"http://127.0.0.1:{self.srv.server_port}{pfad}", data=None if daten is None else json.dumps(daten).encode(), headers={"Authorization": "Bearer " + wer, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=10) as a:
                return a.status, a.read(), a.headers.get("Content-Type")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), ""

    def test_standorte_entfernen_und_umstellen_nur_der_besitzer(self):
        self.assertEqual(self.frage("claude", "/api/inventar/standorte", {"name": "Lager"})[0], 200, "anlegen dürfen Agenten")
        self.assertEqual(self.frage("claude", "/api/inventar/standorte", {"name": "Lager", "verkaufbar": False})[0], 403)
        self.assertEqual(self.frage("claude", "/api/inventar/standorte", {"name": "Lager", "entfernen": True})[0], 403)
        self.assertEqual(self.frage("besitzer", "/api/inventar/standorte", {"name": "Lager", "entfernen": True})[0], 200)

    def test_grosser_import_ueber_der_normalen_grenze(self):
        L = [{"name": f"Teil {i:04d}", "beschreibung": "x" * 120} for i in range(700)]   # deutlich über 64 KB
        c, b, _ = self.frage("claude", "/api/inventar/import", {"teile": L, "probe": True})
        self.assertEqual(c, 200, b[:200])

    def test_verbinden_nur_der_besitzer(self):
        for pfad in ("/api/kalender/einrichten", "/api/kalender/waehlen", "/api/kalender/trennen", "/api/mail/verbinden", "/api/mail/trennen", "/api/mail/agenten"):
            self.assertEqual(self.frage("claude", pfad, {"ja": True})[0], 403, pfad)

    def test_mails_fuer_agenten_erst_nach_erlaubnis(self):
        self.assertEqual(self.frage("claude", "/api/mail")[0], 403)
        self.assertEqual(self.frage("claude", "/api/mail/1", {"gelesen": True})[0], 403)
        self.assertEqual(self.frage("besitzer", "/api/mail")[0], 200)
        self.assertEqual(self.frage("besitzer", "/api/mail/agenten", {"ja": True})[0], 200)
        self.assertEqual(self.frage("claude", "/api/mail")[0], 200)

    def test_geraete_schluessel_duerfen_nichts_davon(self):
        for pfad in ("/api/kalender", "/api/kalender/termine", "/api/inventar", "/api/mail"):
            self.assertEqual(self.frage("geraet-alt", pfad)[0], 403, pfad)

    def test_ohne_schluessel_nichts(self):
        import urllib.error, urllib.request
        for pfad in ("/api/kalender", "/api/inventar", "/api/mail"):
            with self.assertRaises(urllib.error.HTTPError) as c:
                urllib.request.urlopen(f"http://127.0.0.1:{self.srv.server_port}{pfad}", timeout=10)
            self.assertEqual(c.exception.code, 401)

    def test_wege_inventar_mit_foto_und_kalender(self):
        import base64
        c, b, _ = self.frage("claude", "/api/inventar/teile", {"name": "Dübel"})
        self.assertEqual(c, 200)
        tid = json.loads(b)["id"]
        self.assertEqual(self.frage("claude", f"/api/inventar/teile/{tid}", {"ort": "Regal 1"})[0], 200)
        self.assertEqual(self.frage("claude", "/api/inventar/buchen", {"teil": tid, "delta": 3})[0], 200)
        c, b, _ = self.frage("claude", f"/api/inventar/teile/{tid}/foto", {"bild": base64.b64encode(PNG).decode()})
        self.assertEqual(c, 200)
        d = json.loads(b)["fotos"][0]["datei"]
        c, b, typ = self.frage("besitzer", f"/api/inventar/teile/{tid}/foto/{d}")
        self.assertEqual((c, b, typ), (200, PNG, "image/png"))
        self.assertEqual(self.frage("besitzer", f"/api/inventar/teile/{tid}/foto/..%2Fi.json")[0], 400)
        v = json.loads(self.frage("claude", "/api/inventar/verstehen?text=" + "3x%20D%C3%BCbel%20dazu")[1])
        self.assertEqual(v["treffer"][0]["id"], tid)
        c, b, _ = self.frage("claude", "/api/kalender/termine", {"titel": "T", "start": "2030-01-01 10:00"})
        self.assertEqual(c, 200)
        tt = json.loads(b)["id"]
        self.assertEqual(self.frage("claude", f"/api/kalender/termine/{tt}/weg", {})[0], 200)
        self.assertIn(b'"konto"', self.frage("besitzer", "/api/kalender")[1])
        self.assertNotIn(b'"konto"', self.frage("claude", "/api/kalender")[1])
        self.assertEqual(self.frage("besitzer", "/api/kalender/termine?tage=abc")[0], 400)

    def test_wege_inventar_standorte_zaehlen_vorlagen(self):
        self.assertEqual(self.frage("besitzer", "/api/inventar/standorte", {"name": "Lager"})[0], 200)
        self.assertEqual(self.frage("claude", "/api/inventar/standorte", {"name": "Beschädigt", "verkaufbar": False})[0], 200)
        self.assertEqual(self.frage("claude", "/api/inventar/vorlagen", {"kategorie": "Heizkörper", "merkmale": ["Typ", "Hersteller=Muster"]})[0], 200)
        c, b, _ = self.frage("claude", "/api/inventar/teile", {"name": "HK", "kategorie": "Heizkörper", "artnr": "HK-1"})
        self.assertEqual((c, json.loads(b)["werte"]), (200, {"Hersteller": "Muster"}))
        c, b, _ = self.frage("claude", "/api/inventar/zaehlen", {"teil": "HK-1", "standort": "lager", "menge": 5})
        self.assertEqual((c, json.loads(b)["teil"]["menge"]), (200, 5))
        self.assertEqual(self.frage("claude", "/api/inventar/zaehlen", {"teil": "HK-1", "standort": "Keller", "menge": 5})[0], 400)
        self.assertEqual(self.frage("claude", "/api/inventar/buchen", {"teil": "HK-1", "delta": 1})[0], 400, "ohne Standort")
        d = json.loads(self.frage("claude", "/api/inventar")[1])
        self.assertEqual(([s["name"] for s in d["standorte"]], list(d["vorlagen"])), (["Lager", "Beschädigt"], ["Heizkörper"]))
        from urllib.parse import quote
        for nr in ("HK+1", "Größe-1"):   # Kalte Durchsicht 05.11.2026: Artikelnummer im Pfad kommt kodiert an
            self.assertEqual(self.frage("claude", "/api/inventar/teile", {"name": "T " + nr, "artnr": nr})[0], 200)
            c, b, _ = self.frage("claude", f"/api/inventar/teile/{quote(nr)}", {"ort": "Regal 3"})
            self.assertEqual((c, json.loads(b)["ort"]), (200, "Regal 3"), nr)
        c, b, _ = self.frage("claude", "/api/inventar/import", {"teile": [{"name": "I1"}, {"name": "I2", "artnr": "mit leer"}]})
        self.assertEqual(c, 400)
        self.assertNotIn("I1", [t["name"] for t in json.loads(self.frage("claude", "/api/inventar")[1])["teile"]])


# ---------- Fehler aus der Rückmeldung des Kollegen ----------

class Junctions(unittest.TestCase):
    def test_art_entscheidet_nicht_jeder_reparse_punkt(self):
        import inventur
        from types import SimpleNamespace as NS
        with mock.patch.object(inventur.os, "lstat", return_value=NS(st_reparse_tag=0xA0000003)), mock.patch.object(inventur.os.path, "islink", return_value=False):
            self.assertTrue(inventur.verbindung("x"))
        with mock.patch.object(inventur.os, "lstat", return_value=NS(st_reparse_tag=0x9000001A)), mock.patch.object(inventur.os.path, "islink", return_value=False):   # OneDrive
            self.assertFalse(inventur.verbindung("x"))
        with mock.patch.object(inventur.os, "lstat", side_effect=OSError), mock.patch.object(inventur.os.path, "islink", return_value=False):
            self.assertFalse(inventur.verbindung("x"))

    @unittest.skipUnless(WIN, "Junctions gibt es nur unter Windows")
    def test_messen_geht_nicht_durch_junctions(self):
        import inventur
        t = Path(tempfile.mkdtemp(prefix="jn-", dir=TMP)).resolve()
        ziel, ordner = t / "ziel", t / "ordner" / "tief"
        ziel.mkdir()
        ordner.mkdir(parents=True)
        (ziel / "gross.bin").write_bytes(b"0" * 5000)
        (ordner / "klein.bin").write_bytes(b"0" * 10)
        subprocess.run(["cmd", "/c", "mklink", "/J", str(ordner / "link"), str(ziel)], check=True, capture_output=True)
        self.assertTrue(inventur.verbindung(ordner / "link"))
        self.assertFalse(inventur.verbindung(ordner))
        self.assertEqual(inventur.ordnergroesse(t / "ordner"), 10)
        os.rmdir(ordner / "link")


class Kodierung(unittest.TestCase):
    def test_alle_programmaufrufe_mit_fester_kodierung(self):
        import ast
        fehlt = []
        for f in HIER.rglob("*.py"):
            if {"tests", "vendor", ".git"} & set(f.relative_to(HIER).parts):
                continue
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("run", "check_output", "Popen"):
                    k = {x.arg: x.value for x in n.keywords}
                    if "text" in k and "**" not in str(k) and not ("encoding" in k and "errors" in k):
                        fehlt.append(f"{f.name}:{n.lineno}")
        self.assertEqual(fehlt, [], "unter Windows scheitert das Lesen sonst an Umlauten still (stdout ist None)")


class HookAbbruch(unittest.TestCase):
    def lade(self):
        spec = importlib.util.spec_from_file_location("claude_lauf_test", HIER / "hooks" / "claude_lauf.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_abbruch_am_limit_beendet_den_lauf(self):
        m, e = self.lade(), io.TextIOWrapper(io.BytesIO(json.dumps({"hook_event_name": "StopFailure", "session_id": "s1", "error": "rate_limit", "last_assistant_message": "API Error: Rate limit reached"}).encode()), encoding="utf-8")
        import zentrale_client
        with mock.patch.object(zentrale_client, "Zentrale") as Z, mock.patch.object(sys, "stdin", e):
            m.main()
        d = Z.return_value._anfrage.call_args.args[1]
        self.assertEqual((d["aktion"], d["nur_wenn_aktiv"], d["lauf"]), ("fertig", True, "chat-s1"))
        self.assertIn("Rate limit", d["ergebnis"])

    def test_wird_eingetragen(self):
        spec = importlib.util.spec_from_file_location("hook_einrichten_test", HIER / "hooks" / "einrichten.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertIn("StopFailure", m.EREIGNISSE)


class UpdateFolgen(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("einrichten_folgen", HIER / "einrichten.py")
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)
        if not shutil.which("git"):
            self.skipTest("git fehlt")

    def lauf(self, heim, mit_eigenem=False):
        t, env = Path(tempfile.mkdtemp(prefix="upd-", dir=TMP)).resolve(), _git_umgebung()
        oben, klon = t / "oben", t / "klon"
        _git(env, "init", "-q", str(oben))
        _git(env, "symbolic-ref", "HEAD", "refs/heads/main", cwd=oben)
        (oben / "zentrale").mkdir()
        (oben / "zentrale" / "hub.py").write_text('FASSUNG = "alt"\n', encoding="utf-8")
        _git(env, "add", ".", cwd=oben)
        _git(env, "commit", "-qm", "alt", cwd=oben)
        _git(env, "clone", "-q", str(oben), str(klon))
        if mit_eigenem:
            (klon / "eigen.txt").write_text("x", encoding="utf-8")
            _git(env, "add", ".", cwd=klon)
            _git(env, "commit", "-qm", "eigener Commit", cwd=klon)
        (oben / "zentrale" / "hub.py").write_text('FASSUNG = "neu"\n', encoding="utf-8")
        _git(env, "commit", "-qam", "neu", cwd=oben)
        echt, aufrufe = subprocess.run, []

        def run(args, **kw):
            if args[0] != "git":
                aufrufe.append(args)
                return subprocess.CompletedProcess(args, 0, "", "")
            kw["env"] = env
            return echt(args, **kw)
        self.m.HIER = klon
        aus = io.StringIO()
        with mock.patch.object(self.m.subprocess, "run", side_effect=run), mock.patch.object(self.m, "autostart", return_value=[]), mock.patch.object(self.m.Path, "home", return_value=heim), \
                mock.patch.object(self.m, "daten_zaehlen", return_value=(t, {})), contextlib.redirect_stdout(aus):
            self.m.update()
        return aufrufe, aus.getvalue()

    def test_eigene_commits_werden_richtig_benannt(self):
        heim = Path(tempfile.mkdtemp(prefix="heim-", dir=TMP))
        _, aus = self.lauf(heim, mit_eigenem=True)
        self.assertIn("eigene Commits liegen im Sicherungszweig", aus)
        self.assertNotIn("Geschichte wurde neu geschrieben", aus)

    def test_hook_wird_nur_nachgetragen_wenn_er_schon_da_ist(self):
        heim = Path(tempfile.mkdtemp(prefix="heim-", dir=TMP))
        ohne, _ = self.lauf(heim)
        self.assertFalse([a for a in ohne if "einrichten.py" in str(a)], "ohne Hook wird nichts eingerichtet")
        (heim / ".claude").mkdir()
        (heim / ".claude" / "settings.json").write_text('{"hooks": {"Stop": [{"hooks": [{"command": "py claude_lauf.py"}]}]}}', encoding="utf-8")
        mit, _ = self.lauf(heim)
        self.assertTrue([a for a in mit if "einrichten.py" in str(a)], "der vorhandene Hook bekommt das neue Ereignis")


class ZielMerken(unittest.TestCase):
    def test_datei_wird_gemerkt_auch_wenn_sie_ueber_die_umgebung_dabei_ist(self):
        spec = importlib.util.spec_from_file_location("regeln_ziel_test", HIER / "regeln_verteilen.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        t = Path(tempfile.mkdtemp(prefix="ziel-", dir=TMP)).resolve()
        with mock.patch.object(m, "ZIELE_DATEI", t / "REGELN.ziele.txt"), mock.patch.dict(os.environ, {"CODEX_HOME": str(t / "zweiter")}), contextlib.redirect_stdout(io.StringIO()):
            m.ziel_merken(t / "zweiter" / "AGENTS.md")
            m.ziel_merken(t / "zweiter" / "AGENTS.md")   # zweimal: nur einmal gemerkt
        self.assertEqual((t / "REGELN.ziele.txt").read_text(encoding="utf-8").splitlines(), [str(t / "zweiter" / "AGENTS.md")])


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
