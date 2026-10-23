import Foundation
import Observation

enum SupportPaths {
    static let modelName = "qwen3.5:4b"

    static var root: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Story Guard", isDirectory: true)
    }

    static var python: URL { root.appendingPathComponent("python", isDirectory: true) }
    static var pythonBin: URL { python.appendingPathComponent("bin/python3") }
    static var venv: URL { root.appendingPathComponent("venv", isDirectory: true) }
    static var venvPython: URL { venv.appendingPathComponent("bin/python") }
    static var engine: URL { root.appendingPathComponent("engine", isDirectory: true) }
    static var ollamaDir: URL { root.appendingPathComponent("ollama", isDirectory: true) }
    static var artifacts: URL { root.appendingPathComponent("artifacts", isDirectory: true) }
    static var logs: URL { root.appendingPathComponent("logs", isDirectory: true) }
    static var installerLog: URL { logs.appendingPathComponent("installer.log") }
    static var generateLog: URL { logs.appendingPathComponent("generate.log") }

    static var driverScript: URL? {
        Bundle.main.url(forResource: "driver", withExtension: "py")
    }

    static var bundledEngine: URL? {
        Bundle.main.resourceURL?.appendingPathComponent("engine", isDirectory: true)
    }

    static var bundledOllamaCLI: URL {
        ollamaDir
            .appendingPathComponent("Ollama.app/Contents/Resources/ollama")
    }

    static func prepare() throws {
        for url in [root, logs, artifacts, ollamaDir] {
            try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        }
    }

    static func storyReports() -> [StoryReport] {
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: artifacts,
            includingPropertiesForKeys: nil
        ) else {
            return []
        }
        return files.compactMap { url in
            guard url.pathExtension == "pdf" else { return nil }
            let id = url.deletingPathExtension().lastPathComponent
            guard StoryInput.isStoryID(id) else { return nil }
            let markdown = url.deletingPathExtension().appendingPathExtension("md")
            return StoryReport(id: id, pdfPath: url.path, markdownPath: markdown.path)
        }
        .sorted { $0.id < $1.id }
    }
}

enum SetupStepState: Equatable {
    case waiting
    case working
    case ready
    case failed
}

struct SetupStep: Identifiable, Equatable {
    var id: String
    var title: String
    var detail: String
    var state: SetupStepState

    static func initial() -> [SetupStep] {
        [
            SetupStep(id: "python", title: "Python 3.13", detail: "Waiting", state: .waiting),
            SetupStep(id: "libraries", title: "Libraries", detail: "Waiting", state: .waiting),
            SetupStep(id: "ollama", title: "Ollama", detail: "Waiting", state: .waiting),
            SetupStep(id: "qwen", title: "Qwen 3.5 4B", detail: "Waiting", state: .waiting),
        ]
    }
}

struct InstallerError: LocalizedError {
    var message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

@MainActor
@Observable
final class Installer {
    var steps = SetupStep.initial()
    var percent = 0
    var log: [String] = []
    var error: String?
    var isRunning = false
    var isComplete = false

    // CPython 3.13.16 from python-build-standalone release 20261013.
    // install_only aarch64-apple-darwin tarball. It extracts to python/bin/python3.
    private static let pythonTarball = URL(string: "https://github.com/astral-sh/python-build-standalone/releases/download/20261013/cpython-3.13.16%2B20261013-aarch64-apple-darwin-install_only.tar.gz")!

    // Ollama 0.40.5 macOS zip. Used only when this Mac has no Ollama binary and nothing is listening on port 11434.
    private static let ollamaZip = URL(string: "https://github.com/ollama/ollama/releases/download/v0.40.5/Ollama-darwin.zip")!

    func install() async {
        if isRunning { return }
        isRunning = true
        defer { isRunning = false }
        error = nil
        percent = 0
        log = []
        steps = SetupStep.initial()
        isComplete = false
        do {
            try SupportPaths.prepare()
            resetLog()
        } catch {
            self.error = error.localizedDescription
            return
        }
        note("Checking this Mac")
        do {
            try await installPython()
            try await installLibraries()
            try await installOllama()
            try await installQwen()
        } catch {
            self.error = error.localizedDescription
            note(error.localizedDescription)
            return
        }
        percent = 100
        isComplete = steps.allSatisfy { $0.state == .ready }
        if isComplete {
            note("Setup complete")
        }
    }

    private func installPython() async throws {
        mark("python", state: .working, detail: "Checking Python 3.13")
        if await pythonReady() {
            mark("python", state: .ready, detail: "Already installed")
            setProgress(step: 0, fraction: 1)
            note("Python 3.13 is already installed")
            return
        }
        #if !arch(arm64)
        mark("python", state: .failed, detail: "Needs an Apple silicon Mac")
        throw InstallerError("The bundled Python build is for Apple silicon.")
        #endif
        note("Downloading Python 3.13.16")
        mark("python", state: .working, detail: "Downloading Python 3.13.16")
        remove(SupportPaths.python)
        let archive = SupportPaths.logs.appendingPathComponent("cpython.tar.gz")
        remove(archive)
        do {
            try await download(Self.pythonTarball, to: archive, step: 0)
            mark("python", state: .working, detail: "Extracting Python")
            let extracted = await Command.run(
                executable: URL(fileURLWithPath: "/usr/bin/tar"),
                arguments: ["-xzf", archive.path, "-C", SupportPaths.root.path],
                timeout: 180
            )
            remove(archive)
            if extracted.status != 0 {
                remove(SupportPaths.python)
                throw InstallerError(tail(extracted.text, fallback: "Python extract failed."))
            }
            await clearQuarantine(SupportPaths.python)
        } catch {
            remove(archive)
            remove(SupportPaths.python)
            mark("python", state: .failed, detail: "Download failed")
            throw error
        }
        guard await pythonReady() else {
            remove(SupportPaths.python)
            mark("python", state: .failed, detail: "Python 3.13 did not start")
            throw InstallerError("The Python install did not report version 3.13.")
        }
        mark("python", state: .ready, detail: "Installed")
        setProgress(step: 0, fraction: 1)
        note("Installed Python 3.13")
    }

    private func installLibraries() async throws {
        mark("libraries", state: .working, detail: "Checking libraries")
        let venvOK = await venvImports()
        let engineOK = venvOK ? await engineImports() : false
        if venvOK && engineOK && stampsMatch() {
            mark("libraries", state: .ready, detail: "Already installed")
            setProgress(step: 1, fraction: 1)
            note("Libraries are already installed")
            return
        }
        if !venvOK {
            note("Creating the Python environment")
            mark("libraries", state: .working, detail: "Creating the environment")
            setProgress(step: 1, fraction: 0.1)
            remove(SupportPaths.venv)
            let created = await Command.run(
                executable: SupportPaths.pythonBin,
                arguments: ["-m", "venv", SupportPaths.venv.path],
                timeout: 180
            )
            if created.status != 0 {
                mark("libraries", state: .failed, detail: "Could not create the environment")
                throw InstallerError(tail(created.text, fallback: "Could not create the Python environment."))
            }
            mark("libraries", state: .working, detail: "Installing reportlab and langgraph")
            setProgress(step: 1, fraction: 0.35)
            note("Installing reportlab and langgraph")
            var env = ProcessInfo.processInfo.environment
            env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
            let installed = await Command.run(
                executable: SupportPaths.venvPython,
                arguments: ["-m", "pip", "install", "reportlab>=4.2,<5", "langgraph>=0.2"],
                environment: env,
                timeout: 900
            )
            appendFile(installed.text)
            if installed.status != 0 || installed.timedOut {
                mark("libraries", state: .failed, detail: "Install failed")
                throw InstallerError(tail(installed.text, fallback: "Could not install reportlab and langgraph."))
            }
        }
        mark("libraries", state: .working, detail: "Copying Story Guard")
        setProgress(step: 1, fraction: 0.85)
        do {
            try syncEngine()
        } catch {
            mark("libraries", state: .failed, detail: "Could not copy Story Guard")
            throw error
        }
        guard await venvImports(), await engineImports() else {
            mark("libraries", state: .failed, detail: "Libraries did not import")
            throw InstallerError("The environment could not import reportlab, langgraph, and story_guard.")
        }
        mark("libraries", state: .ready, detail: "Installed")
        setProgress(step: 1, fraction: 1)
        note("Installed reportlab, langgraph, and Story Guard")
    }

    private func installOllama() async throws {
        mark("ollama", state: .working, detail: "Checking Ollama")
        let serverUp = await ollamaServerUp()
        var binary = findOllama()
        if serverUp || binary != nil {
            mark("ollama", state: .ready, detail: serverUp ? "Already running" : "Already installed")
            setProgress(step: 2, fraction: 1)
            note(serverUp ? "Ollama is already running" : "Ollama is already installed")
        } else {
            note("Downloading Ollama 0.40.5")
            mark("ollama", state: .working, detail: "Downloading Ollama")
            let archive = SupportPaths.logs.appendingPathComponent("Ollama-darwin.zip")
            remove(archive)
            let app = SupportPaths.ollamaDir.appendingPathComponent("Ollama.app")
            remove(app)
            do {
                try await download(Self.ollamaZip, to: archive, step: 2)
                let extracted = await Command.run(
                    executable: URL(fileURLWithPath: "/usr/bin/ditto"),
                    arguments: ["-x", "-k", archive.path, SupportPaths.ollamaDir.path],
                    timeout: 180
                )
                remove(archive)
                if extracted.status != 0 {
                    throw InstallerError(tail(extracted.text, fallback: "Ollama extract failed."))
                }
                await clearQuarantine(app)
            } catch {
                remove(archive)
                mark("ollama", state: .failed, detail: "Download failed")
                throw error
            }
            binary = findOllama()
            guard binary != nil else {
                mark("ollama", state: .failed, detail: "Ollama binary was not found")
                throw InstallerError("Ollama downloaded, but the ollama binary was not inside the app.")
            }
            mark("ollama", state: .ready, detail: "Installed")
            setProgress(step: 2, fraction: 1)
            note("Installed Ollama")
        }
        if await ollamaServerUp() {
            return
        }
        guard let binary else {
            mark("ollama", state: .failed, detail: "Ollama binary was not found")
            throw InstallerError("Ollama is not installed and nothing is listening on port 11434.")
        }
        mark("ollama", state: .working, detail: "Starting Ollama")
        note("Starting Ollama")
        try startOllama(binary)
        let started = await waitForOllama()
        guard started else {
            mark("ollama", state: .failed, detail: "Ollama did not start")
            throw InstallerError("Ollama did not answer on port 11434.")
        }
        mark("ollama", state: .ready, detail: "Running")
        setProgress(step: 2, fraction: 1)
    }

    private func installQwen() async throws {
        mark("qwen", state: .working, detail: "Checking \(SupportPaths.modelName)")
        guard let binary = findOllama() else {
            mark("qwen", state: .failed, detail: "Ollama binary was not found")
            throw InstallerError("Ollama is required before the model can be checked.")
        }
        if await modelReady(binary) {
            mark("qwen", state: .ready, detail: "Already installed")
            setProgress(step: 3, fraction: 1)
            note("\(SupportPaths.modelName) is already installed")
            return
        }
        note("Pulling \(SupportPaths.modelName)")
        mark("qwen", state: .working, detail: "Pulling \(SupportPaths.modelName)")
        let layers = PullLayers()
        let (stream, continuation) = AsyncStream.makeStream(of: String.self)
        let updates = Task { @MainActor in
            for await line in stream {
                guard let fraction = layers.absorb(line) else { continue }
                self.setProgress(step: 3, fraction: fraction)
                let shown = Int((fraction * 100).rounded(.down))
                self.mark("qwen", state: .working, detail: "Pulling \(SupportPaths.modelName) (\(shown)%)")
            }
        }
        let pulled = await Command.run(
            executable: binary,
            arguments: ["pull", SupportPaths.modelName],
            timeout: 1800,
            onLine: { continuation.yield($0) }
        )
        continuation.finish()
        _ = await updates.value
        appendFile(pulled.text)
        let modelOK = await modelReady(binary)
        if pulled.timedOut || pulled.status != 0 || !modelOK {
            mark("qwen", state: .failed, detail: "Pull failed")
            throw InstallerError(tail(pulled.text, fallback: "Could not pull \(SupportPaths.modelName)."))
        }
        mark("qwen", state: .ready, detail: "Installed")
        setProgress(step: 3, fraction: 1)
        note("Installed \(SupportPaths.modelName)")
    }

    private func pythonReady() async -> Bool {
        guard FileManager.default.isExecutableFile(atPath: SupportPaths.pythonBin.path) else { return false }
        let result = await Command.run(
            executable: SupportPaths.pythonBin,
            arguments: ["-c", "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 13) else 1)"],
            timeout: 30
        )
        return result.status == 0
    }

    private func venvImports() async -> Bool {
        guard FileManager.default.isExecutableFile(atPath: SupportPaths.venvPython.path) else { return false }
        let result = await Command.run(
            executable: SupportPaths.venvPython,
            arguments: ["-c", "import reportlab, langgraph"],
            environment: pythonEnvironment(),
            timeout: 60
        )
        return result.status == 0
    }

    private func engineImports() async -> Bool {
        guard FileManager.default.isExecutableFile(atPath: SupportPaths.venvPython.path) else { return false }
        let result = await Command.run(
            executable: SupportPaths.venvPython,
            arguments: ["-c", "import story_guard"],
            environment: pythonEnvironment(),
            timeout: 60
        )
        return result.status == 0
    }

    private func pythonEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = SupportPaths.engine.appendingPathComponent("src", isDirectory: true).path
        env["PYTHONNOUSERSITE"] = "1"
        return env
    }

    private func stampsMatch() -> Bool {
        guard let bundled = stamp(in: SupportPaths.bundledEngine),
              let installed = stamp(in: SupportPaths.engine)
        else {
            return false
        }
        return bundled == installed
    }

    private func stamp(in directory: URL?) -> String? {
        guard let directory else { return nil }
        let url = directory.appendingPathComponent(".bundle-stamp")
        return try? String(contentsOf: url, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func syncEngine() throws {
        guard let bundled = SupportPaths.bundledEngine,
              FileManager.default.fileExists(atPath: bundled.path)
        else {
            throw InstallerError("The app is missing its Story Guard engine. Rebuild Story Guard.")
        }
        remove(SupportPaths.engine)
        try FileManager.default.copyItem(at: bundled, to: SupportPaths.engine)
    }

    private func ollamaServerUp() async -> Bool {
        guard let url = URL(string: "http://127.0.0.1:11434/api/version") else { return false }
        var request = URLRequest(url: url)
        request.timeoutInterval = 2
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    private func waitForOllama() async -> Bool {
        for _ in 0..<30 {
            if await ollamaServerUp() { return true }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        return await ollamaServerUp()
    }

    private func findOllama() -> URL? {
        var candidates: [URL] = []
        if let path = ProcessInfo.processInfo.environment["PATH"] {
            for directory in path.split(separator: ":") {
                candidates.append(URL(fileURLWithPath: String(directory)).appendingPathComponent("ollama"))
            }
        }
        candidates.append(URL(fileURLWithPath: "/usr/local/bin/ollama"))
        candidates.append(URL(fileURLWithPath: "/opt/homebrew/bin/ollama"))
        candidates.append(SupportPaths.bundledOllamaCLI)
        for url in candidates where FileManager.default.isExecutableFile(atPath: url.path) {
            return url
        }
        return nil
    }

    private func startOllama(_ binary: URL) throws {
        let process = Process()
        process.executableURL = binary
        process.arguments = ["serve"]
        var env = ProcessInfo.processInfo.environment
        env["OLLAMA_HOST"] = "http://127.0.0.1:11434"
        process.environment = env
        let logURL = SupportPaths.logs.appendingPathComponent("ollama.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        let handle = try FileHandle(forWritingTo: logURL)
        process.standardOutput = handle
        process.standardError = handle
        try process.run()
    }

    private func modelReady(_ binary: URL) async -> Bool {
        let result = await Command.run(
            executable: binary,
            arguments: ["show", SupportPaths.modelName],
            timeout: 60
        )
        return result.status == 0
    }

    private func download(_ url: URL, to destination: URL, step: Int) async throws {
        let download = FileDownload(destination: destination)
        download.onFraction = { [weak self] fraction in
            Task { @MainActor in
                self?.setProgress(step: step, fraction: fraction)
            }
        }
        do {
            try await download.start(url)
        } catch {
            remove(destination)
            throw error
        }
    }

    private func clearQuarantine(_ url: URL) async {
        _ = await Command.run(
            executable: URL(fileURLWithPath: "/usr/bin/xattr"),
            arguments: ["-dr", "com.apple.quarantine", url.path],
            timeout: 30
        )
    }

    private func setProgress(step: Int, fraction: Double) {
        let clamped = min(max(fraction, 0), 1)
        let value = (Double(step) + clamped) / 4.0 * 100
        percent = min(100, Int(value.rounded(.down)))
    }

    private func mark(_ id: String, state: SetupStepState, detail: String) {
        guard let index = steps.firstIndex(where: { $0.id == id }) else { return }
        var step = steps[index]
        step.state = state
        step.detail = detail
        steps[index] = step
    }

    private func note(_ message: String) {
        log.append(message)
        appendFile(message + "\n")
    }

    private func resetLog() {
        try? Data().write(to: SupportPaths.installerLog)
    }

    private func appendFile(_ text: String) {
        guard let data = text.data(using: .utf8) else { return }
        if !FileManager.default.fileExists(atPath: SupportPaths.installerLog.path) {
            FileManager.default.createFile(atPath: SupportPaths.installerLog.path, contents: data)
            return
        }
        guard let handle = try? FileHandle(forWritingTo: SupportPaths.installerLog) else { return }
        defer { try? handle.close() }
        _ = try? handle.seekToEnd()
        try? handle.write(contentsOf: data)
    }

    private func remove(_ url: URL) {
        if FileManager.default.fileExists(atPath: url.path) {
            try? FileManager.default.removeItem(at: url)
        }
    }

    private func tail(_ text: String, fallback: String) -> String {
        let lines = text.split(separator: "\n").suffix(12).map(String.init)
        let body = lines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        return body.isEmpty ? fallback : body
    }
}

private final class PullLayers: @unchecked Sendable {
    private let lock = NSLock()
    private var layers: [String: Double] = [:]

    func absorb(_ line: String) -> Double? {
        guard let range = line.range(of: #"(\d+(?:\.\d+)?)%"#, options: .regularExpression) else {
            return nil
        }
        let number = Double(line[range].dropLast()) ?? 0
        let key: String
        if let colon = line.firstIndex(of: ":") {
            key = String(line[..<colon])
        } else {
            key = "all"
        }
        lock.lock()
        layers[key] = number / 100
        let fraction = layers.values.reduce(0, +) / Double(layers.count)
        lock.unlock()
        return fraction
    }
}

final class FileDownload: NSObject, URLSessionDownloadDelegate, @unchecked Sendable {
    private let destination: URL
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Void, Error>?
    private var session: URLSession?
    var onFraction: (@Sendable (Double) -> Void)?

    init(destination: URL) {
        self.destination = destination
    }

    func start(_ url: URL) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            lock.lock()
            self.continuation = continuation
            lock.unlock()
            let session = URLSession(configuration: .ephemeral, delegate: self, delegateQueue: nil)
            self.session = session
            var request = URLRequest(url: url)
            request.timeoutInterval = 120
            session.downloadTask(with: request).resume()
        }
    }

    func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didWriteData bytesWritten: Int64,
        totalBytesWritten: Int64,
        totalBytesExpectedToWrite: Int64
    ) {
        guard totalBytesExpectedToWrite > 0 else { return }
        onFraction?(Double(totalBytesWritten) / Double(totalBytesExpectedToWrite))
    }

    func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didFinishDownloadingTo location: URL
    ) {
        do {
            if let http = downloadTask.response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                throw InstallerError("Download failed with HTTP \(http.statusCode).")
            }
            let folder = destination.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            if FileManager.default.fileExists(atPath: destination.path) {
                try FileManager.default.removeItem(at: destination)
            }
            try FileManager.default.moveItem(at: location, to: destination)
            finish(nil)
        } catch {
            finish(error)
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error {
            finish(error)
        } else {
            finish(nil)
        }
        session.finishTasksAndInvalidate()
    }

    private func finish(_ error: Error?) {
        lock.lock()
        let continuation = self.continuation
        self.continuation = nil
        lock.unlock()
        guard let continuation else { return }
        if let error {
            continuation.resume(throwing: error)
        } else {
            continuation.resume()
        }
    }
}
