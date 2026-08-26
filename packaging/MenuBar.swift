// MacStatP Control — a menu bar item for the background agent.
//
// The agent itself has no interface: it runs from launchd and talks to the
// board over USB. This puts it somewhere you can reach — the menu bar by
// default, or the Dock as well if you prefer, which is what "Show in Dock"
// switches. Both are the same process; only the activation policy changes.
//
// Compiled rather than scripted because a menu bar item needs a real
// NSStatusItem, and this way there is nothing to install alongside it.

import AppKit
import Foundation

let label = "local.statusdisplay.agent"
let showInDockKey = "ShowInDock"
let openAtLoginKey = "OpenAtLogin"

func home(_ path: String) -> String {
    return NSHomeDirectory() + "/" + path
}

let plistPath = home("Library/LaunchAgents/\(label).plist")
let controlLabel = "local.statusdisplay.control"
let controlPlist = home("Library/LaunchAgents/\(controlLabel).plist")
let logPath = home("Library/Logs/StatusDisplay/agent.log")
let configPath = home("Library/Application Support/MacStatP/config.json")

@discardableResult
func run(_ tool: String, _ args: [String]) -> (Int32, String) {
    let p = Process()
    p.executableURL = URL(fileURLWithPath: tool)
    p.arguments = args
    let pipe = Pipe()
    p.standardOutput = pipe
    p.standardError = Pipe()
    do { try p.run() } catch { return (-1, "") }
    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    p.waitUntilExit()
    return (p.terminationStatus, String(data: data, encoding: .utf8) ?? "")
}

func target() -> String { "gui/\(getuid())/\(label)" }

/// Which port the settings page is on, from the agent's own config.
func webPort() -> Int {
    guard let data = FileManager.default.contents(atPath: configPath),
          let obj = try? JSONSerialization.jsonObject(with: data),
          let dict = obj as? [String: Any],
          let port = dict["web_port"] as? Int
    else { return 8765 }
    return port
}

struct AgentState {
    var loaded = false
    var running = false
    var connected: Bool? = nil
    var boardPort = ""
    var frames = 0
}

func agentState() -> AgentState {
    var s = AgentState()
    let (code, out) = run("/bin/launchctl", ["print", target()])
    s.loaded = code == 0
    s.running = code == 0 && out.contains("state = running")
    guard s.running else { return s }

    // Ask the agent's own settings page what it can see. Short timeout:
    // this runs while the menu is opening.
    let url = URL(string: "http://127.0.0.1:\(webPort())/api/state")!
    var req = URLRequest(url: url)
    req.timeoutInterval = 1.0
    let sem = DispatchSemaphore(value: 0)
    URLSession.shared.dataTask(with: req) { data, _, _ in
        defer { sem.signal() }
        guard let data = data,
              let obj = try? JSONSerialization.jsonObject(with: data),
              let dict = obj as? [String: Any],
              let status = dict["status"] as? [String: Any] else { return }
        s.connected = status["connected"] as? Bool ?? false
        s.boardPort = status["port"] as? String ?? ""
        s.frames = status["frames"] as? Int ?? 0
    }.resume()
    _ = sem.wait(timeout: .now() + 1.5)
    return s
}

func summary(_ s: AgentState) -> String {
    if !s.loaded { return "Not set to run at login" }
    if !s.running { return "Agent stopped" }
    guard let connected = s.connected else { return "Agent running" }
    if !connected { return "Waiting for the Presto" }
    return "Connected · \(s.frames) frames"
}

func notify(_ text: String) {
    let script = "display notification \(text.debugDescription) "
               + "with title \"MacStatP\""
    run("/usr/bin/osascript", ["-e", script])
}

final class Controller: NSObject, NSMenuDelegate {
    let item = NSStatusItem.self
    var statusItem: NSStatusItem!
    let menu = NSMenu()

    func start() {
        statusItem = NSStatusBar.system.statusItem(
            withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.image = NSImage(systemSymbolName: "gauge.medium",
                                   accessibilityDescription: "MacStatP")
                ?? NSImage(systemSymbolName: "speedometer",
                           accessibilityDescription: "MacStatP")
            button.image?.isTemplate = true
            if button.image == nil { button.title = "MSP" }
        }
        menu.delegate = self
        statusItem.menu = menu
        applyDockPreference()
    }

    func applyDockPreference() {
        let inDock = UserDefaults.standard.bool(forKey: showInDockKey)
        // .regular puts it in the Dock, .accessory keeps it to the menu
        // bar. Same process either way.
        NSApp.setActivationPolicy(inDock ? .regular : .accessory)
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        let s = agentState()

        let head = NSMenuItem(title: summary(s), action: nil, keyEquivalent: "")
        head.isEnabled = false
        menu.addItem(head)
        if s.running, s.connected == true, !s.boardPort.isEmpty {
            let sub = NSMenuItem(title: "  \(s.boardPort)", action: nil,
                                 keyEquivalent: "")
            sub.isEnabled = false
            menu.addItem(sub)
        }
        menu.addItem(.separator())

        if s.running {
            add(menu, "Open Settings…", #selector(openSettings), "s")
            add(menu, "Restart Agent", #selector(restartAgent), "r")
            add(menu, "Stop Agent", #selector(stopAgent), "")
        } else {
            add(menu, "Start Agent", #selector(startAgent), "")
        }
        add(menu, "Show Log", #selector(showLog), "l")
        menu.addItem(.separator())

        let dock = add(menu, "Show in Dock", #selector(toggleDock), "")
        dock.state = UserDefaults.standard.bool(forKey: showInDockKey)
            ? .on : .off
        let login = add(menu, "Open at Login", #selector(toggleLogin), "")
        login.state = FileManager.default.fileExists(atPath: controlPlist)
            ? .on : .off
        menu.addItem(.separator())
        add(menu, "Quit MacStatP Control", #selector(quit), "q")
    }

    @discardableResult
    func add(_ menu: NSMenu, _ title: String, _ action: Selector,
             _ key: String) -> NSMenuItem {
        let mi = NSMenuItem(title: title, action: action, keyEquivalent: key)
        mi.target = self
        menu.addItem(mi)
        return mi
    }

    @objc func openSettings() {
        NSWorkspace.shared.open(
            URL(string: "http://127.0.0.1:\(webPort())/")!)
    }

    @objc func stopAgent() {
        run("/bin/launchctl", ["bootout", target()])
        notify("Agent stopped. The display shows its standby card.")
    }

    @objc func startAgent() {
        guard FileManager.default.fileExists(atPath: plistPath) else {
            notify("No login item — run tools/install_app.sh first.")
            return
        }
        run("/bin/launchctl", ["bootstrap", "gui/\(getuid())", plistPath])
        notify("Agent started.")
    }

    @objc func restartAgent() {
        // kickstart -k restarts a running job in one step; bootout followed
        // by bootstrap races with launchd letting go of the label.
        let (code, _) = run("/bin/launchctl", ["kickstart", "-k", target()])
        if code != 0 {
            run("/bin/launchctl", ["bootout", target()])
            Thread.sleep(forTimeInterval: 1.5)
            run("/bin/launchctl", ["bootstrap", "gui/\(getuid())", plistPath])
        }
        notify("Agent restarted.")
    }

    @objc func showLog() {
        if FileManager.default.fileExists(atPath: logPath) {
            NSWorkspace.shared.open(URL(fileURLWithPath: logPath))
        } else {
            NSWorkspace.shared.open(
                URL(fileURLWithPath: (logPath as NSString)
                    .deletingLastPathComponent))
        }
    }

    @objc func toggleDock() {
        let now = !UserDefaults.standard.bool(forKey: showInDockKey)
        UserDefaults.standard.set(now, forKey: showInDockKey)
        applyDockPreference()
        notify(now ? "Showing in the Dock as well."
                   : "Hidden to the menu bar.")
    }

    @objc func toggleLogin() {
        let fm = FileManager.default
        if fm.fileExists(atPath: controlPlist) {
            run("/bin/launchctl", ["bootout", "gui/\(getuid())/\(controlLabel)"])
            try? fm.removeItem(atPath: controlPlist)
            notify("Will not open at login.")
            return
        }
        let exe = Bundle.main.executablePath ?? ""
        let plist = """
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
        "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0"><dict>
          <key>Label</key><string>\(controlLabel)</string>
          <key>ProgramArguments</key><array><string>\(exe)</string></array>
          <key>RunAtLoad</key><true/>
        </dict></plist>
        """
        try? fm.createDirectory(
            atPath: (controlPlist as NSString).deletingLastPathComponent,
            withIntermediateDirectories: true)
        try? plist.write(toFile: controlPlist, atomically: true,
                         encoding: .utf8)
        run("/bin/launchctl", ["bootstrap", "gui/\(getuid())", controlPlist])
        notify("Will open at login.")
    }

    @objc func quit() { NSApp.terminate(nil) }
}

// One menu bar item is enough.
let me = ProcessInfo.processInfo.processIdentifier
let mine = Bundle.main.bundleIdentifier ?? controlLabel
for app in NSRunningApplication.runningApplications(withBundleIdentifier: mine)
where app.processIdentifier != me {
    exit(0)
}

let app = NSApplication.shared
let controller = Controller()
controller.start()
app.run()
