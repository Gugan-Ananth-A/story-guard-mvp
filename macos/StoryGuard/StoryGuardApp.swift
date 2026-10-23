import Observation
import SwiftUI

@main
struct StoryGuardApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .frame(minWidth: 900, minHeight: 640)
        }
        .defaultSize(width: 1120, height: 780)
        .commands {
            CommandGroup(after: .appSettings) {
                Button("Connection…") { model.openConnection() }
            }
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Group {
            switch model.phase {
            case .setup:
                SetupView()
            case .connect:
                ConnectView()
            case .generate:
                GenerateView()
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AppTheme.background.ignoresSafeArea())
        .preferredColorScheme(.light)
        .tint(AppTheme.accent)
        .navigationTitle("Story Guard")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button("Connection") { model.openConnection() }
                    .accessibilityIdentifier("toolbar.connection")
            }
        }
        .task { await model.launch() }
    }
}

@MainActor
@Observable
final class AppModel {
    var phase: AppPhase = .setup
    var installer = Installer()
    var runner = Runner()

    var org: String
    var project: String
    var token = ""
    var projectURL: String?
    var verifyError: String?
    var isVerifying = false
    var hasToken = false

    var mode: GenerateMode = .one
    var oneStoryText = ""
    var severalText = ""
    var sprintPath = ""
    var sprintChoices: [String] = []
    var sprintLoadError: String?
    var run = RunSnapshot()
    var savedReports: [StoryReport] = []
    var selectedReportID: String?
    var isGenerating = false

    private var didLaunch = false

    init() {
        let defaults = UserDefaults.standard
        org = defaults.string(forKey: "storyguard.org") ?? "rootquotient"
        project = defaults.string(forKey: "storyguard.project") ?? "Ecom MVP"
        projectURL = defaults.string(forKey: "storyguard.url")
    }

    func launch() async {
        guard !didLaunch else { return }
        didLaunch = true
        phase = .setup
        await runSetup(thenAdvance: true)
    }

    func retrySetup() {
        Task { await runSetup(thenAdvance: true) }
    }

    func openConnection() {
        phase = .connect
    }

    func verifyFromForm() {
        Task { await verifyAndMaybeAdvance() }
    }

    func disconnect() {
        TokenStore.delete()
        token = ""
        hasToken = false
        verifyError = nil
        phase = .connect
    }

    func loadSprints() async {
        guard hasToken, let projectURL, let secret = TokenStore.load() else { return }
        let result = await runner.listSprints(projectURL: projectURL, token: secret)
        switch result {
        case .success(let paths):
            sprintChoices = paths
            sprintLoadError = nil
        case .failure(let error):
            sprintLoadError = error.message
        }
    }

    func refreshSavedReports() {
        savedReports = SupportPaths.storyReports()
        if selectedReportID == nil {
            selectedReportID = savedReports.first?.id
        }
    }

    var inputHint: String? {
        switch mode {
        case .one:
            let trimmed = oneStoryText.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty { return "Enter a story id." }
            if StoryInput.one(oneStoryText) == nil { return "Story ids are positive whole numbers." }
        case .several:
            let trimmed = severalText.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty { return "Enter story ids separated by commas." }
            if StoryInput.several(severalText) == nil { return "One of those ids is not a positive whole number." }
        case .sprint:
            if StoryInput.sprint(sprintPath) == nil { return "Choose or paste an iteration path." }
        }
        if !installer.isComplete { return "Setup is still running." }
        if !hasToken || TokenStore.load() == nil {
            return "Connect to Azure DevOps before generating."
        }
        return nil
    }

    var canGenerate: Bool {
        installer.isComplete && hasToken && TokenStore.load() != nil && !isGenerating && inputHint == nil
    }

    func startGenerate() {
        guard let request = currentRequest(), let projectURL, let secret = TokenStore.load() else { return }
        Task { await generate(request: request, projectURL: projectURL, token: secret) }
    }

    func cancelGenerate() {
        runner.cancel()
    }

    private func runSetup(thenAdvance: Bool) async {
        await installer.install()
        guard thenAdvance, installer.isComplete else { return }
        await routeAfterSetup()
    }

    private func routeAfterSetup() async {
        #if DEBUG
        if ProcessInfo.processInfo.environment["STORY_GUARD_SKIP_CONNECT"] == "1" {
            hasToken = TokenStore.load() != nil
            if projectURL == nil {
                projectURL = ConnectionURL.make(org: org, project: project)
            }
            refreshSavedReports()
            phase = .generate
            return
        }
        #endif
        if let saved = TokenStore.load() {
            token = saved
            hasToken = true
            let ok = await verify(saveToken: false)
            if ok {
                refreshSavedReports()
                phase = .generate
                return
            }
        }
        phase = .connect
    }

    private func verifyAndMaybeAdvance() async {
        let ok = await verify(saveToken: true)
        if ok {
            refreshSavedReports()
            phase = .generate
        }
    }

    @discardableResult
    private func verify(saveToken: Bool) async -> Bool {
        guard let url = ConnectionURL.make(org: org, project: project) else {
            verifyError = "The Azure DevOps project address is not valid."
            return false
        }
        let secret = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !secret.isEmpty else {
            verifyError = "Paste a personal access token."
            return false
        }
        isVerifying = true
        defer { isVerifying = false }
        let result = await runner.listSprints(projectURL: url, token: secret)
        switch result {
        case .failure(let error):
            verifyError = error.message
            return false
        case .success(let paths):
            do {
                if saveToken {
                    try TokenStore.save(secret)
                }
            } catch {
                verifyError = "The token worked, but Story Guard could not save it."
                return false
            }
            verifyError = nil
            projectURL = url
            sprintChoices = paths
            sprintLoadError = nil
            hasToken = true
            let defaults = UserDefaults.standard
            defaults.set(org, forKey: "storyguard.org")
            defaults.set(project, forKey: "storyguard.project")
            defaults.set(url, forKey: "storyguard.url")
            return true
        }
    }

    private func currentRequest() -> GenerateRequest? {
        switch mode {
        case .one:
            guard let id = StoryInput.one(oneStoryText) else { return nil }
            return .stories([id])
        case .several:
            guard let ids = StoryInput.several(severalText) else { return nil }
            return .stories(ids)
        case .sprint:
            guard let path = StoryInput.sprint(sprintPath) else { return nil }
            return .sprint(path)
        }
    }

    private func generate(request: GenerateRequest, projectURL: String, token: String) async {
        isGenerating = true
        run = RunSnapshot()
        defer { isGenerating = false }
        await runner.generate(request: request, projectURL: projectURL, token: token) { [weak self] event in
            guard let self else { return }
            self.run = ProgressMath.reduce(self.run, event)
            if self.selectedReportID == nil, let first = self.run.reports.first {
                self.selectedReportID = first.id
            }
        }
        if !run.finished {
            run.finished = true
            if runner.wasCancelled {
                run.message = "Cancelled"
                run.log.append("Cancelled")
            } else if run.message.isEmpty {
                run.message = "The report run stopped."
            }
        }
        refreshSavedReports()
        if selectedReportID == nil {
            selectedReportID = run.reports.first?.id
        }
    }
}

enum AppPhase {
    case setup
    case connect
    case generate
}
