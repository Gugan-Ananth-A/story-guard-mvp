import Foundation

struct CommandOutput: Sendable {
    var status: Int32
    var text: String
    var timedOut: Bool
}

enum Command {
    static func run(
        executable: URL,
        arguments: [String],
        environment: [String: String]? = nil,
        directory: URL? = nil,
        timeout: TimeInterval? = nil,
        onLine: (@Sendable (String) -> Void)? = nil
    ) async -> CommandOutput {
        await withCheckedContinuation { continuation in
            let process = Process()
            process.executableURL = executable
            process.arguments = arguments
            if let environment {
                process.environment = environment
            }
            if let directory {
                process.currentDirectoryURL = directory
            }
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe
            let box = ResumeBox(continuation)
            let timedOut = TimedOut()
            do {
                try process.run()
            } catch {
                box.resume(CommandOutput(status: 1, text: error.localizedDescription, timedOut: false))
                return
            }
            if let timeout {
                DispatchQueue.global().asyncAfter(deadline: .now() + timeout) {
                    guard process.isRunning else { return }
                    timedOut.mark()
                    process.terminate()
                    DispatchQueue.global().asyncAfter(deadline: .now() + 2) {
                        if process.isRunning {
                            kill(process.processIdentifier, SIGKILL)
                        }
                    }
                }
            }
            DispatchQueue.global().async {
                let text = readLines(from: pipe.fileHandleForReading, onLine: onLine)
                if process.isRunning {
                    process.waitUntilExit()
                }
                box.resume(CommandOutput(status: process.terminationStatus, text: text, timedOut: timedOut.value))
            }
        }
    }

    private static func readLines(from handle: FileHandle, onLine: (@Sendable (String) -> Void)?) -> String {
        var pending = Data()
        var all = Data()
        while true {
            let chunk = handle.availableData
            if chunk.isEmpty {
                break
            }
            all.append(chunk)
            pending.append(chunk)
            while let newline = pending.firstIndex(of: 10) {
                let lineData = pending.prefix(upTo: newline)
                pending.removeSubrange(...newline)
                let line = String(data: lineData, encoding: .utf8)?
                    .trimmingCharacters(in: CharacterSet(charactersIn: "\r")) ?? ""
                onLine?(line)
            }
        }
        if !pending.isEmpty {
            let line = String(data: pending, encoding: .utf8) ?? ""
            if !line.isEmpty {
                onLine?(line)
            }
        }
        return String(data: all, encoding: .utf8) ?? ""
    }
}

private final class ResumeBox: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<CommandOutput, Never>?

    init(_ continuation: CheckedContinuation<CommandOutput, Never>) {
        self.continuation = continuation
    }

    func resume(_ output: CommandOutput) {
        lock.lock()
        let continuation = self.continuation
        self.continuation = nil
        lock.unlock()
        continuation?.resume(returning: output)
    }
}

private final class TimedOut: @unchecked Sendable {
    private let lock = NSLock()
    private var flagged = false

    func mark() {
        lock.lock()
        flagged = true
        lock.unlock()
    }

    var value: Bool {
        lock.lock()
        defer { lock.unlock() }
        return flagged
    }
}

enum GenerateRequest {
    case stories([String])
    case sprint(String)
}

struct RunnerMessage: Error {
    var message: String
}

@MainActor
@Observable
final class Runner {
    private(set) var wasCancelled = false
    private var process: Process?
    private var processGroup: pid_t = 0

    func listSprints(projectURL: String, token: String) async -> Result<[String], RunnerMessage> {
        guard let driver = SupportPaths.driverScript else {
            return .failure(RunnerMessage(message: "The app is missing driver.py. Rebuild Story Guard."))
        }
        guard FileManager.default.isExecutableFile(atPath: SupportPaths.venvPython.path) else {
            return .failure(RunnerMessage(message: "Story Guard's Python environment is not ready. Quit the app and open it again."))
        }
        let output = await run(
            executable: SupportPaths.venvPython,
            arguments: [driver.path, "sprints"],
            environment: environment(projectURL: projectURL, token: token)
        )
        if output.status != 0 {
            let message = output.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
            return .failure(RunnerMessage(message: message.isEmpty ? "Could not read sprints." : message))
        }
        let text = output.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let data = text.data(using: .utf8),
              let paths = try? JSONDecoder().decode([String].self, from: data)
        else {
            return .failure(RunnerMessage(message: "Sprint list was not JSON."))
        }
        return .success(paths)
    }

    func generate(
        request: GenerateRequest,
        projectURL: String,
        token: String,
        onEvent: @escaping @MainActor (DriverEvent) -> Void
    ) async {
        wasCancelled = false
        guard let driver = SupportPaths.driverScript else {
            onEvent(DriverEvent(event: "error", storyIndex: nil, storyCount: nil, message: "The app is missing driver.py. Rebuild Story Guard.", percent: nil, storyID: nil, pdf: nil, markdown: nil, written: nil, failed: nil))
            onEvent(DriverEvent(event: "done", storyIndex: nil, storyCount: nil, message: nil, percent: nil, storyID: nil, pdf: nil, markdown: nil, written: [], failed: []))
            return
        }
        guard FileManager.default.isExecutableFile(atPath: SupportPaths.venvPython.path) else {
            onEvent(DriverEvent(event: "error", storyIndex: nil, storyCount: nil, message: "Story Guard's Python environment is not ready. Quit the app and open it again.", percent: nil, storyID: nil, pdf: nil, markdown: nil, written: nil, failed: nil))
            onEvent(DriverEvent(event: "done", storyIndex: nil, storyCount: nil, message: nil, percent: nil, storyID: nil, pdf: nil, markdown: nil, written: [], failed: []))
            return
        }
        var arguments = [driver.path, "generate"]
        switch request {
        case .stories(let ids):
            for id in ids {
                arguments.append("--story-id")
                arguments.append(id)
            }
        case .sprint(let path):
            arguments.append("--sprint")
            arguments.append(path)
        }
        let (stream, continuation) = AsyncStream.makeStream(of: String.self)
        let pump = Task { @MainActor in
            for await line in stream {
                if let event = DriverEvent.decodeLine(line) {
                    onEvent(event)
                }
            }
        }
        let output = await run(
            executable: SupportPaths.venvPython,
            arguments: arguments,
            environment: environment(projectURL: projectURL, token: token),
            onStdoutLine: { continuation.yield($0) }
        )
        continuation.finish()
        await pump.value
        if output.status != 0, !output.stdout.contains("\"event\":\"done\"") {
            let message = output.stderr.trimmingCharacters(in: .whitespacesAndNewlines)
            if !message.isEmpty {
                onEvent(DriverEvent(event: "error", storyIndex: nil, storyCount: nil, message: message, percent: nil, storyID: nil, pdf: nil, markdown: nil, written: nil, failed: nil))
            }
        }
    }

    func cancel() {
        wasCancelled = true
        guard let process, process.isRunning else { return }
        let pid = processGroup == 0 ? process.processIdentifier : processGroup
        _ = Darwin.kill(-pid, SIGTERM)
        process.terminate()
    }

    private func environment(projectURL: String, token: String) -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        for key in [
            "STORY_GUARD_MODEL",
            "DEEPSEEK_MODEL",
            "DEEPSEEK_BASE_URL",
            "DEEPSEEK_API_KEY",
            "OPENAI_MODEL",
            "OPENAI_BASE_URL",
            "OPENAI_API_KEY",
            "XAI_MODEL",
            "XAI_API_KEY",
        ] {
            env.removeValue(forKey: key)
        }
        env["ADO_PROJECT_URL"] = projectURL
        env["ADO_PAT"] = token
        env["STORY_GUARD_LLM"] = "ollama"
        env["OLLAMA_HOST"] = "http://127.0.0.1:11434"
        env["OLLAMA_MODEL"] = "qwen3.5:4b"
        env["STORY_GUARD_ARTIFACTS_DIR"] = SupportPaths.artifacts.path
        env["PYTHONPATH"] = SupportPaths.engine.appendingPathComponent("src", isDirectory: true).path
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["STORY_GUARD_APP"] = "1"
        return env
    }

    private func run(
        executable: URL,
        arguments: [String],
        environment: [String: String],
        onStdoutLine: (@Sendable (String) -> Void)? = nil
    ) async -> SplitOutput {
        let output = await withCheckedContinuation { continuation in
            let process = Process()
            process.executableURL = executable
            process.arguments = arguments
            process.environment = environment
            process.currentDirectoryURL = SupportPaths.root
            let stdout = Pipe()
            let stderr = Pipe()
            process.standardOutput = stdout
            process.standardError = stderr
            self.process = process
            let box = SplitResume(continuation)
            do {
                try process.run()
                self.processGroup = process.processIdentifier
            } catch {
                self.process = nil
                box.resume(SplitOutput(status: 1, stdout: "", stderr: error.localizedDescription))
                return
            }
            let group = DispatchGroup()
            group.enter()
            group.enter()
            // Process is tied to this MainActor once it is stored on Runner. The finisher
            // is Sendable so the global-queue closures stay off the main actor.
            let finisher = ProcessFinisher(process)
            DispatchQueue.global().async {
                let text = Self.readPipe(stdout.fileHandleForReading, onLine: onStdoutLine)
                box.setStdout(text)
                group.leave()
            }
            DispatchQueue.global().async {
                let text = Self.readPipe(stderr.fileHandleForReading, onLine: nil)
                box.setStderr(text)
                group.leave()
            }
            DispatchQueue.global().async {
                group.wait()
                finisher.complete(box)
            }
        }
        process = nil
        processGroup = 0
        return output
    }

    private nonisolated static func readPipe(_ handle: FileHandle, onLine: (@Sendable (String) -> Void)?) -> String {
        var pending = Data()
        var all = Data()
        while true {
            let chunk = handle.availableData
            if chunk.isEmpty {
                break
            }
            all.append(chunk)
            pending.append(chunk)
            while let newline = pending.firstIndex(of: 10) {
                let lineData = pending.prefix(upTo: newline)
                pending.removeSubrange(...newline)
                let line = String(data: lineData, encoding: .utf8)?
                    .trimmingCharacters(in: CharacterSet(charactersIn: "\r")) ?? ""
                onLine?(line)
            }
        }
        if !pending.isEmpty, let line = String(data: pending, encoding: .utf8), !line.isEmpty {
            onLine?(line)
        }
        return String(data: all, encoding: .utf8) ?? ""
    }
}

/// Owns the child process for the background waiter. `@unchecked Sendable` so a
/// global queue can wait on it without inheriting Runner's main-actor isolation.
private final class ProcessFinisher: @unchecked Sendable {
    private let process: Process

    init(_ process: Process) {
        self.process = process
    }

    func complete(_ box: SplitResume) {
        if process.isRunning {
            process.waitUntilExit()
        }
        box.setStatus(process.terminationStatus)
        box.resumeIfReady()
    }
}

private struct SplitOutput: Sendable {
    var status: Int32
    var stdout: String
    var stderr: String
}

private final class SplitResume: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<SplitOutput, Never>?
    private var status: Int32 = 1
    private var stdout = ""
    private var stderr = ""
    private var stdoutReady = false
    private var stderrReady = false
    private var statusReady = false

    init(_ continuation: CheckedContinuation<SplitOutput, Never>) {
        self.continuation = continuation
    }

    func setStdout(_ text: String) {
        lock.lock()
        stdout = text
        stdoutReady = true
        lock.unlock()
    }

    func setStderr(_ text: String) {
        lock.lock()
        stderr = text
        stderrReady = true
        lock.unlock()
    }

    func setStatus(_ status: Int32) {
        lock.lock()
        self.status = status
        statusReady = true
        lock.unlock()
    }

    /// Resume once when the process never started. Later pipe callbacks see a nil continuation.
    func resume(_ output: SplitOutput) {
        lock.lock()
        let continuation = self.continuation
        self.continuation = nil
        lock.unlock()
        continuation?.resume(returning: output)
    }

    func resumeIfReady() {
        lock.lock()
        guard stdoutReady, stderrReady, statusReady, let continuation else {
            lock.unlock()
            return
        }
        self.continuation = nil
        let output = SplitOutput(status: status, stdout: stdout, stderr: stderr)
        lock.unlock()
        continuation.resume(returning: output)
    }
}
