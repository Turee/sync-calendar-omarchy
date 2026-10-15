import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui

// A one-line field drawn like the kit's TextField, but built on a TextEdit in
// PlainText mode instead of a TextInput: on a clipboard change its canPaste
// path only checks the offered formats. Qt reads pasted data with no total
// size or time limit, so Ctrl+V and Shift+Insert run wl-paste in a child
// process with a 2 s deadline and a 64 KiB cap, and middle-click paste is off.
// The input method still works, so dead keys and compose (ê, ç) type as usual.
FocusScope {
  id: field

  property alias text: editor.text
  property alias font: editor.font
  property alias inputMethodHints: editor.inputMethodHints
  property string placeholderText: ""
  property bool password: false
  property color foreground: Color.foreground
  property color accent: Color.accent
  property real horizontalPadding: Style.spacing.controlPaddingX
  property real verticalPadding: Style.spacing.inputPaddingY
  signal editingFinished()

  readonly property var _borderSpec: Border.controlSpec(activeFocus ? "focus" : (hover.hovered ? "hover-cursor" : "normal"), foreground, accent)
  property real _scroll: 0

  activeFocusOnTab: true
  implicitWidth: Math.max(editor.contentWidth, placeholder.implicitWidth) + viewport.anchors.leftMargin + viewport.anchors.rightMargin
  implicitHeight: Math.max(editor.contentHeight, placeholder.implicitHeight) + viewport.anchors.topMargin + viewport.anchors.bottomMargin

  function selectAll() { editor.selectAll() }

  function caretX() {
    return field.password ? metrics.advanceWidth("\u25cf".repeat(editor.cursorPosition)) : editor.cursorRectangle.x
  }

  function keepCaretVisible() {
    var x = caretX()
    if (x < _scroll) _scroll = x
    else if (x + 1 > _scroll + viewport.width) _scroll = x + 1 - viewport.width
    var shown = field.password ? bullets.contentWidth : editor.contentWidth
    _scroll = Math.max(0, Math.min(_scroll, shown + 1 - viewport.width))
  }

  FontMetrics { id: metrics; font: editor.font }
  HoverHandler { id: hover; cursorShape: Qt.IBeamCursor }

  BorderSurface {
    anchors.fill: parent
    color: Style.controlFill(field.activeFocus, hover.hovered, field.foreground, field.accent)
    borderSpec: field._borderSpec
    radius: Style.cornerRadius
  }

  MouseArea {  // a click on the padding focuses the field too
    anchors.fill: parent
    onPressed: editor.forceActiveFocus()
  }

  Item {
    id: viewport
    anchors.fill: parent
    anchors.leftMargin: field.horizontalPadding + Border.left(field._borderSpec)
    anchors.rightMargin: field.horizontalPadding + Border.right(field._borderSpec)
    anchors.topMargin: field.verticalPadding + Border.top(field._borderSpec)
    anchors.bottomMargin: field.verticalPadding + Border.bottom(field._borderSpec)
    clip: true
    onWidthChanged: field.keepCaretVisible()

    Text {
      id: placeholder
      visible: editor.length === 0 && !editor.preeditText
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width
      elide: Text.ElideRight
      textFormat: Text.PlainText
      text: field.placeholderText
      color: Qt.darker(field.foreground, 1.6)
      font: editor.font
    }

    Text {
      id: bullets
      visible: field.password
      x: -field._scroll
      anchors.verticalCenter: parent.verticalCenter
      textFormat: Text.PlainText
      text: "\u25cf".repeat(editor.length)
      color: field.foreground
      font: editor.font
    }

    Rectangle {  // the caret over the bullets; the editor's own one sits at the hidden text
      visible: field.password && editor.activeFocus
      x: bullets.x + field.caretX()
      anchors.verticalCenter: parent.verticalCenter
      width: 1
      height: metrics.height
      color: field.foreground
    }

    TextEdit {
      id: editor
      focus: true
      x: -field._scroll
      width: Math.max(viewport.width, contentWidth + 1)
      height: viewport.height
      textFormat: TextEdit.PlainText
      wrapMode: TextEdit.NoWrap
      verticalAlignment: TextEdit.AlignVCenter
      font.family: Style.font.family
      font.pixelSize: Style.font.body
      color: field.password ? "transparent" : field.foreground
      selectionColor: field.password ? "transparent" : Style.selectionFillFor(field.foreground, field.accent)
      selectedTextColor: field.foreground
      selectByMouse: !field.password  // a mouse selection is copied to the primary selection
      cursorDelegate: field.password ? hiddenCaret : null
      inputMethodHints: field.password ? Qt.ImhHiddenText | Qt.ImhSensitiveData | Qt.ImhNoPredictiveText : Qt.ImhNone

      onCursorRectangleChanged: field.keepCaretVisible()
      onTextChanged: {
        // Text set from outside puts a TextEdit's caret at the start; a TextField's goes to the end.
        if (!activeFocus) cursorPosition = length
        field.keepCaretVisible()
      }
      onEditingFinished: field.editingFinished()

      Keys.forwardTo: [field]  // the caller's Keys handlers see each key first, as on a TextField
      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        if (event.matches(StandardKey.Paste)) {
          event.accepted = true
          if (!editor.readOnly) pasteProc.running = true
        } else if (field.password && (event.matches(StandardKey.Copy) || event.matches(StandardKey.Cut))) {
          event.accepted = true
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
          event.accepted = true
          field.editingFinished()
          if (!editor.canUndo) editor.cursorPosition = editor.length  // the caller rewrote the text
        } else if (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab) {
          event.accepted = true
          var next = field.nextItemInFocusChain(event.key === Qt.Key_Tab && !(event.modifiers & Qt.ShiftModifier))
          if (next) next.forceActiveFocus(Qt.TabFocusReason)
        }
      }
    }

    MouseArea {  // middle-click would paste the primary selection natively
      anchors.fill: parent
      acceptedButtons: Qt.MiddleButton
    }
  }

  Component { id: hiddenCaret; Item {} }

  Process {
    id: pasteProc
    command: ["sh", "-c", "timeout 2 wl-paste --no-newline --type text 2>/dev/null | head -c 65536"]
    stdout: StdioCollector {
      id: pasted
      onStreamFinished: {
        if (!pasted.text || editor.readOnly) return
        if (editor.selectedText) editor.remove(editor.selectionStart, editor.selectionEnd)
        editor.insert(editor.cursorPosition, pasted.text.replace(/[\r\n\t\u2028\u2029]+/g, " "))
      }
    }
  }
}
