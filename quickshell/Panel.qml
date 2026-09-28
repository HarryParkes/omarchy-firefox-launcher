import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.harryparkes.firefox-sessions"
  ipcTarget: moduleName

  property int configured: 48
  property int runningCount: 0
  property string savedUrl: "about:blank"
  property string savedWorkspaces: "special:firefox-sessions"
  property bool busy: false
  property string progressText: "Ready"
  property string errorText: ""
  property var scheduledActions: []

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  implicitWidth: barButton.implicitWidth
  implicitHeight: barButton.implicitHeight

  function refresh() {
    if (!statusProcess.running) statusProcess.exec(["firefox-sessions", "status", "--json"])
    if (!scheduleListProcess.running) scheduleListProcess.exec(["firefox-sessions", "schedule", "list", "--json"])
  }

  function applyStatus(text) {
    try {
      var value = JSON.parse(text)
      configured = Number(value.configured)
      runningCount = Number(value.running)
      savedUrl = String(value.url)
      savedWorkspaces = value.workspaces.join(", ")
      if (!urlField.activeFocus) urlField.text = savedUrl
      if (!workspaceField.activeFocus) workspaceField.text = savedWorkspaces
      if (!countField.activeFocus) countField.text = String(configured)
    } catch (error) {
      errorText = "Could not read session status"
    }
  }

  function configurationArgs() {
    return [
      "--count", countField.text,
      "--url", urlField.text,
      "--workspaces", workspaceField.text
    ]
  }

  function saveConfiguration() {
    if (configProcess.running || busy) return
    errorText = ""
    configProcess.exec(["firefox-sessions", "configure"].concat(configurationArgs()))
  }

  function runAction(command) {
    if (actionProcess.running) return
    errorText = ""
    busy = true
    progressText = command === "stop" ? "Stopping managed sessions" : "Starting"
    var arguments = ["firefox-sessions", command]
    if (command === "launch" || command === "relaunch")
      arguments = arguments.concat(configurationArgs()).concat(["--json"])
    else if (command === "reset")
      arguments.push("--yes")
    actionProcess.exec(arguments)
  }

  function setPreset(value) {
    countField.text = value
    saveConfiguration()
  }

  function suggestedTime() {
    var value = new Date(Date.now() + 3600000)
    function pad(number) { return String(number).padStart(2, "0") }
    return value.getFullYear() + "-" + pad(value.getMonth() + 1) + "-" + pad(value.getDate())
      + " " + pad(value.getHours()) + ":" + pad(value.getMinutes())
  }

  function addSchedule() {
    if (scheduleProcess.running) return
    errorText = ""
    scheduleProcess.exec([
      "firefox-sessions", "schedule", "add",
      "--at", scheduleField.text,
      "--action", scheduleActionGroup.value,
      "--json"
    ])
  }

  function cancelSchedule(scheduleId) {
    if (!scheduleProcess.running)
      scheduleProcess.exec(["firefox-sessions", "schedule", "cancel", scheduleId])
  }

  onOpenedChanged: if (opened) {
    if (scheduleField.text === "") scheduleField.text = suggestedTime()
    refresh()
  }

  Timer {
    interval: 2000
    repeat: true
    running: root.opened && !root.busy
    onTriggered: root.refresh()
  }

  Process {
    id: statusProcess
    stdout: StdioCollector {
      onStreamFinished: root.applyStatus(text)
    }
  }

  Process {
    id: configProcess
    stderr: StdioCollector {
      onStreamFinished: if (text.trim() !== "") root.errorText = text.trim()
    }
    onExited: function(code) {
      if (code === 0) root.refresh()
    }
  }

  Process {
    id: scheduleListProcess
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          root.scheduledActions = JSON.parse(text)
        } catch (error) {
          root.errorText = "Could not read scheduled actions"
        }
      }
    }
  }

  Process {
    id: scheduleProcess
    stderr: StdioCollector {
      onStreamFinished: if (text.trim() !== "") root.errorText = text.trim()
    }
    onExited: function(code) {
      if (code === 0) {
        scheduleField.text = root.suggestedTime()
        root.refresh()
      }
    }
  }

  Process {
    id: actionProcess
    stdout: SplitParser {
      onRead: function(line) {
        try {
          var value = JSON.parse(line)
          if (value.event === "progress") {
            root.progressText = "Launching " + value.current + " / " + value.total
            root.runningCount = Number(value.running)
          } else if (value.event === "complete") {
            root.progressText = value.launched === 0 ? "All sessions are already running" : "Launch complete"
            root.runningCount = Number(value.running)
          }
        } catch (error) {
          if (line.trim() !== "") root.progressText = line.trim()
        }
      }
    }
    stderr: StdioCollector {
      onStreamFinished: if (text.trim() !== "") root.errorText = text.trim()
    }
    onExited: function() {
      root.busy = false
      root.refresh()
    }
  }

  BarIconButton {
    id: barButton
    bar: root.bar
    text: "󰈹"
    active: root.opened
    tooltipText: "Firefox Sessions · " + root.runningCount + " / " + root.configured
    onPressed: function(button) {
      if (button === Qt.MiddleButton) root.refresh()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: popup
    anchorItem: barButton
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: contentRoot
    contentWidth: popup.fittedContentWidth(Style.space(430))
    contentHeight: popup.fittedContentHeight(contentColumn.implicitHeight, Style.space(660))

    Item {
      id: contentRoot
      anchors.fill: parent
      focus: true
      Keys.onEscapePressed: root.close()

      Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: contentColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: contentColumn
          width: parent.width
          spacing: Style.spacing.lg

          PanelHero {
            width: parent.width
            title: "Firefox Sessions"
            meta: root.runningCount + " running · " + root.configured + " configured"
            foreground: root.foreground
            fontFamily: root.fontFamily
            iconComponent: Component {
              Text {
                text: "󰈹"
                color: root.runningCount > 0 ? root.foreground : root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.display
              }
            }
          }

          PanelSeparator { foreground: root.foreground }

          FormField {
            width: parent.width
            label: "Target URL"
            TextField {
              id: urlField
              width: parent.width
              foreground: root.foreground
              text: root.savedUrl
              placeholderText: "https://example.com"
              onEditingFinished: root.saveConfiguration()
            }
          }

          FormField {
            width: parent.width
            label: "Session count"
            Column {
              width: parent.width
              spacing: Style.spacing.sm

              ButtonGroup {
                value: ["12", "24", "48"].indexOf(countField.text) >= 0 ? countField.text : ""
                options: ["12", "24", "48"]
                foreground: root.foreground
                onChanged: function(value) { root.setPreset(value) }
              }

              TextField {
                id: countField
                width: parent.width
                foreground: root.foreground
                text: String(root.configured)
                placeholderText: "Custom count"
                validator: IntValidator { bottom: 1; top: 999 }
                onEditingFinished: root.saveConfiguration()
              }
            }
          }

          FormField {
            width: parent.width
            label: "Workspaces · assigned round-robin"
            TextField {
              id: workspaceField
              width: parent.width
              foreground: root.foreground
              text: root.savedWorkspaces
              placeholderText: "special:firefox-sessions or 4, 5, 6"
              onEditingFinished: root.saveConfiguration()
            }
          }

          PanelSeparator { foreground: root.foreground }

          FormField {
            width: parent.width
            label: "One-off schedule · local time"
            Column {
              width: parent.width
              spacing: Style.spacing.sm

              TextField {
                id: scheduleField
                width: parent.width
                foreground: root.foreground
                placeholderText: "YYYY-MM-DD HH:MM"
              }

              ButtonGroup {
                id: scheduleActionGroup
                value: "launch"
                options: [
                  { value: "launch", label: "Launch" },
                  { value: "stop", label: "Stop All" },
                  { value: "relaunch", label: "Relaunch" }
                ]
                foreground: root.foreground
                onChanged: function(value) { scheduleActionGroup.value = value }
              }

              Button {
                width: parent.width
                text: "Schedule Once"
                iconText: "󰃰"
                bordered: true
                foreground: root.foreground
                onClicked: root.addSchedule()
              }
            }
          }

          Column {
            visible: root.scheduledActions.length > 0
            width: parent.width
            spacing: Style.spacing.sm

            PanelSectionHeader {
              text: "SCHEDULED"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Repeater {
              model: root.scheduledActions

              Item {
                required property var modelData
                width: contentColumn.width
                implicitHeight: scheduleRow.implicitHeight

                Row {
                  id: scheduleRow
                  width: parent.width
                  spacing: Style.spacing.sm

                  Column {
                    width: parent.width - cancelButton.width - parent.spacing

                    Text {
                      width: parent.width
                      text: modelData.action.charAt(0).toUpperCase() + modelData.action.slice(1)
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                    }

                    Text {
                      width: parent.width
                      text: modelData.at.replace("T", " ")
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.bodySmall
                    }
                  }

                  Button {
                    id: cancelButton
                    text: "Cancel"
                    bordered: true
                    foreground: root.foreground
                    onClicked: root.cancelSchedule(modelData.id)
                  }
                }
              }
            }
          }

          Column {
            width: parent.width
            spacing: Style.spacing.sm

            Text {
              width: parent.width
              text: root.busy ? root.progressText : "Running " + root.runningCount + " / " + root.configured
              textFormat: Text.PlainText
              color: root.errorText !== "" ? Color.urgent : root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }

            Item {
              width: parent.width
              height: Style.space(6)

              Rectangle {
                anchors.fill: parent
                radius: height / 2
                color: Util.alpha(root.foreground, 0.12)
              }

              Rectangle {
                height: parent.height
                width: parent.width * Math.min(1, root.runningCount / Math.max(1, root.configured))
                radius: height / 2
                color: Color.accent
                Behavior on width { NumberAnimation { duration: Style.duration(140) } }
              }
            }

            Text {
              visible: root.errorText !== ""
              width: parent.width
              text: root.errorText
              textFormat: Text.PlainText
              color: Color.urgent
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
            }
          }

          Grid {
            width: parent.width
            columns: 2
            spacing: Style.spacing.sm

            Button {
              width: (contentColumn.width - parent.spacing) / 2
              text: "Launch Sessions"
              iconText: "󰐊"
              bordered: true
              foreground: root.foreground
              active: root.busy
              onClicked: root.runAction("launch")
            }
            Button {
              width: (contentColumn.width - parent.spacing) / 2
              text: "Launch Missing"
              iconText: "󰑐"
              bordered: true
              foreground: root.foreground
              onClicked: root.runAction("launch")
            }
            Button {
              width: (contentColumn.width - parent.spacing) / 2
              text: "Stop All"
              iconText: "󰓛"
              bordered: true
              foreground: root.foreground
              onClicked: root.runAction("stop")
            }
            Button {
              width: (contentColumn.width - parent.spacing) / 2
              text: "Relaunch"
              iconText: "󰜉"
              bordered: true
              foreground: root.foreground
              onClicked: root.runAction("relaunch")
            }
            Button {
              width: (contentColumn.width - parent.spacing) / 2
              text: "Open Workspace"
              iconText: "󰍹"
              bordered: true
              foreground: root.foreground
              onClicked: Quickshell.execDetached(["firefox-sessions", "focus"])
            }
            Button {
              width: (contentColumn.width - parent.spacing) / 2
              text: "Next Session"
              iconText: "󰒭"
              bordered: true
              foreground: root.foreground
              onClicked: Quickshell.execDetached(["firefox-sessions", "next"])
            }
          }

          Button {
            width: parent.width
            text: "Reset Profiles"
            iconText: "󰆴"
            bordered: true
            foreground: Color.urgent
            onClicked: {
              resetDialog.selectedIndex = 0
              resetDialog.opened = true
              Qt.callLater(function() { resetDialog.forceActiveFocus() })
            }
          }
        }
      }

      ConfirmDialog {
        id: resetDialog
        anchors.fill: parent
        message: "Stop all managed sessions and permanently delete every Firefox Sessions profile?"
        confirmText: "Reset"
        onCanceled: opened = false
        onConfirmed: {
          opened = false
          root.runAction("reset")
        }
        Keys.onPressed: function(event) {
          if (handleKey(event)) event.accepted = true
        }
      }
    }
  }

  component FormField: Column {
    property string label: ""
    default property alias content: holder.children
    spacing: Style.spacing.xs

    Text {
      text: parent.label
      visible: text !== ""
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }

    Item {
      id: holder
      width: parent.width
      implicitHeight: childrenRect.height
    }
  }
}
