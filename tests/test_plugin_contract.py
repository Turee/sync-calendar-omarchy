import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]

# plugins.omarchy.org clips the card description to one 21px line with a fade
# (`white-space: nowrap`), and Omarchy's own widget picker elides it the same
# way. Roughly 50 characters survive, so the lead clause has to stand alone.
LISTING_LINE_BUDGET = 50

SHIPPED_SUFFIXES = {".qml", ".js", ".py", ".json", ".md"}
CONFLICT_MARKER = re.compile(r"^(<{7}|={7}|>{7})(?: |$)", re.MULTILINE)


class PluginManifestContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

    def test_bar_widget_entry_point_exists(self):
        self.assertEqual(self.manifest["schemaVersion"], 1)
        self.assertIn("bar-widget", self.manifest["kinds"])
        entry_point = self.manifest["entryPoints"]["barWidget"]
        self.assertTrue((ROOT / entry_point).is_file())

    def test_declares_exclusive_clock_provider_contract(self):
        metadata = self.manifest["barWidget"]
        self.assertFalse(metadata["allowMultiple"])
        self.assertEqual(metadata["defaultSection"], "center")
        self.assertIn("clock", metadata["semanticCapabilities"])

    def test_descriptions_land_their_point_on_the_visible_line(self):
        for field, text in (
            ("description", self.manifest["description"]),
            ("barWidget.description", self.manifest["barWidget"]["description"]),
        ):
            head = text[:LISTING_LINE_BUDGET]
            self.assertTrue(
                len(text) <= LISTING_LINE_BUDGET or any(mark in head for mark in ":;,"),
                f"{field} has no clause break in its first {LISTING_LINE_BUDGET} "
                f"characters, so the card shows a fragment: {head!r}",
            )


class ShippedSourceContractTests(unittest.TestCase):
    def test_no_leftover_merge_conflict_markers(self):
        # One stray marker in Panel.qml shipped in v1.4.1 and v1.4.2: QML refused
        # the whole file, so the popup never opened while the bar still looked fine.
        for path in sorted(ROOT.rglob("*")):
            if path.suffix not in SHIPPED_SUFFIXES or ".git" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            match = CONFLICT_MARKER.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                self.fail(f"{path.relative_to(ROOT)}:{line} has a merge conflict marker")

    def test_text_fields_exist_only_while_their_form_is_open(self):
        # A text field follows every clipboard change while it exists, and the
        # panel lives as long as the shell. Each one must sit in a Loader's
        # sourceComponent, so it is created when its form opens, and must be a
        # BoundedTextField: a plain-text TextEdit whose paste does not read the
        # clipboard natively.
        for path in sorted(ROOT.glob("*.qml")):
            if path.name == "BoundedTextField.qml":
                continue  # the definition: it exists only where a form creates it
            open_blocks = []  # brace depth at which each sourceComponent opened
            depth = 0
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = re.sub(r"(^|\s)//.*", "", line)  # a comment, not the // of a URL
                if "sourceComponent:" in code and "{" in code:
                    open_blocks.append(depth)
                if re.search(r"\b(TextField|TextInput|TextEdit|TextArea)\s*\{", code):
                    self.fail(f"{path.name}:{number} creates a text input that pastes natively")
                if re.search(r"\bBoundedTextField\s*\{", code) and not open_blocks:
                    self.fail(f"{path.name}:{number} creates a text input outside a Loader")
                depth += code.count("{") - code.count("}")
                while open_blocks and depth <= open_blocks[-1]:
                    open_blocks.pop()

    def test_the_agenda_draws_a_bounded_number_of_rows(self):
        # One delegate per event, and a feed decides how many a day holds.
        qml = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        self.assertNotIn("model: root.displayedEvents\n", qml)
        self.assertIn("model: root.displayedEvents.slice(0, root.maxAgendaRows)", qml)

    def test_paste_stops_at_its_byte_cap_and_deadline(self):
        # Run the field's own paste command against a fake wl-paste: one that
        # streams forever, and one that never answers.
        qml = (ROOT / "BoundedTextField.qml").read_text(encoding="utf-8")
        code = "\n".join(re.sub(r"(^|\s)//.*", "", line) for line in qml.splitlines())
        self.assertIn("textFormat: TextEdit.PlainText", code)
        self.assertIsNone(re.search(r"\b(TextField|TextInput|TextArea)\s*\{", code))
        self.assertIn("event.matches(StandardKey.Paste)", code)
        self.assertIn("acceptedButtons: Qt.MiddleButton", code)
        # Qt copies any selection to the primary selection: the token field cannot select.
        self.assertIn("selectByMouse: !field.password", code)
        self.assertIn("selectByKeyboard: !field.password", code)
        self.assertIn("field.password && !field.typesOrDeletes(event)", code)
        script = json.loads(re.search(r'command: \["sh", "-c", ("[^"]+")\]', qml).group(1))
        for name, body in (("streams", "exec yes"), ("stalls", "exec sleep 30")):
            with self.subTest(name), tempfile.TemporaryDirectory() as bin_dir:
                fake = Path(bin_dir) / "wl-paste"
                fake.write_text(f"#!/bin/sh\n{body}\n")
                fake.chmod(0o755)
                env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
                started = time.monotonic()
                out = subprocess.run(["sh", "-c", script], env=env, capture_output=True, timeout=10).stdout
                self.assertLess(time.monotonic() - started, 5)
                self.assertLessEqual(len(out), 65536)


if __name__ == "__main__":
    unittest.main()
