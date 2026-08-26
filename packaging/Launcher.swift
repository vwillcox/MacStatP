// Entry point for MacStatP.app.
//
// This exists only to be a Mach-O binary. It was a /bin/sh stub, which
// works fine but cannot be notarised: Apple's notary service requires a
// bundle's main executable to be a real binary, so a script-based app is
// rejected however it is signed.
//
// All it does is hand over to the Python agent in Resources, exporting
// its own path first so the settings page can write a launch agent that
// points back at this bundle.

import Foundation

let exePath = CommandLine.arguments[0]
let exeURL = URL(fileURLWithPath: exePath).resolvingSymlinksInPath()
let resources = exeURL
    .deletingLastPathComponent()      // MacOS/
    .deletingLastPathComponent()      // Contents/
    .appendingPathComponent("Resources")

setenv("MACSTATP_EXE", exeURL.path, 1)

let script = resources.appendingPathComponent("launch.py").path
guard FileManager.default.fileExists(atPath: script) else {
    FileHandle.standardError.write(
        "MacStatP: launch.py missing from the bundle\n".data(using: .utf8)!)
    exit(1)
}

// execv replaces this process, so there is no extra one hanging about and
// launchd keeps watching the thing that actually does the work.
var args: [String] = ["/usr/bin/python3", script]
args.append(contentsOf: CommandLine.arguments.dropFirst())

var cArgs: [UnsafeMutablePointer<CChar>?] = args.map { strdup($0) }
cArgs.append(nil)
execv("/usr/bin/python3", &cArgs)

FileHandle.standardError.write(
    "MacStatP: could not start python3\n".data(using: .utf8)!)
exit(1)
