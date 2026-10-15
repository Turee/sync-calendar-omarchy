import QtQuick
import QtQuick.Controls
import Quickshell.Io
import qs.Ui

// The kit's TextField, with paste moved out of the shell process. Qt reads
// pasted clipboard data with no total size or time limit, so paste runs
// wl-paste in a child process with a 2 s deadline and a 64 KiB cap. The
// middle-click and right-click paste paths read natively, so they are off.
TextField {
  id: field

  ContextMenu.menu: null

  Keys.onPressed: function(event) {
    if (!event.matches(StandardKey.Paste)) return
    event.accepted = true
    if (!field.readOnly) pasteProc.running = true
  }

  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.MiddleButton
  }

  Process {
    id: pasteProc
    command: ["sh", "-c", "timeout 2 wl-paste --no-newline --type text 2>/dev/null | head -c 65536"]
    stdout: StdioCollector {
      id: pasted
      onStreamFinished: {
        if (!pasted.text || field.readOnly) return
        if (field.selectedText) field.remove(field.selectionStart, field.selectionEnd)
        field.insert(field.cursorPosition, pasted.text.replace(/[\r\n]+/g, " "))
      }
    }
  }
}
