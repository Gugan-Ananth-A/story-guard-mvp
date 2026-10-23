import SwiftUI

struct GenerateView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        VStack(alignment: .leading, spacing: 16) {
            Picker(selection: $model.mode) {
                ForEach(GenerateMode.allCases) { mode in
                    Text(mode.rawValue).tag(mode)
                }
            } label: {
                EmptyView()
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .accessibilityIdentifier("generate.mode")
            .fullWidthLine()

            if model.mode == .sprint, let sprintLoadError = model.sprintLoadError {
                Text(sprintLoadError)
                    .foregroundStyle(.red)
                    .fullWidthLine()
            }

            HStack(alignment: .center, spacing: 12) {
                input(model)
                Button(model.isGenerating ? "Generating…" : "Generate") {
                    model.startGenerate()
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(!model.canGenerate)
                .accessibilityIdentifier("generate.button")
                if model.isGenerating {
                    Button("Cancel") {
                        model.cancelGenerate()
                    }
                    .keyboardShortcut(.cancelAction)
                    .accessibilityIdentifier("generate.cancel")
                }
            }
            .fullWidthLine()

            if let hint = model.inputHint {
                Text(hint)
                    .font(.callout)
                    .foregroundStyle(AppTheme.ink.opacity(0.72))
                    .fullWidthLine()
                    .accessibilityIdentifier("generate.hint")
            }
            if let projectURL = model.projectURL {
                Text(projectURL)
                    .font(.caption)
                    .foregroundStyle(AppTheme.ink.opacity(0.62))
                    .textSelection(.enabled)
                    .fullWidthLine()
            }
            if model.isGenerating || model.run.finished || !model.run.log.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        Text("\(model.run.percent)%")
                            .font(.title3.monospacedDigit().weight(.semibold))
                            .foregroundStyle(AppTheme.ink)
                            .accessibilityIdentifier("generate.percent")
                        Text(coverageLabel)
                            .foregroundStyle(AppTheme.ink.opacity(0.75))
                            .fullWidthLine()
                        if model.run.storyCount > 1, model.run.storyIndex > 0 {
                            Text("Story \(model.run.storyIndex) of \(model.run.storyCount)")
                                .foregroundStyle(AppTheme.ink.opacity(0.75))
                        }
                    }
                    ProgressView(value: Double(model.run.percent), total: 100)
                        .tint(AppTheme.accent)
                        .accessibilityIdentifier("generate.progress")
                    Text(model.run.message.isEmpty ? "Waiting" : model.run.message)
                        .font(.callout)
                        .foregroundStyle(AppTheme.ink)
                        .fullWidthLine()
                        .accessibilityIdentifier("generate.step")
                    DisclosureGroup("Steps") {
                        ScrollView {
                            Text(model.run.log.joined(separator: "\n"))
                                .font(.system(.caption, design: .monospaced))
                                .fullWidthLine()
                                .textSelection(.enabled)
                        }
                        .frame(maxHeight: 160)
                    }
                }
                .themeCard()
            }
            if !model.run.errors.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(model.run.errors) { failure in
                        Text(failure.storyID.isEmpty ? failure.message : "Story \(failure.storyID): \(failure.message)")
                            .font(.callout)
                            .foregroundStyle(.red)
                            .textSelection(.enabled)
                            .fullWidthLine()
                    }
                }
                .accessibilityIdentifier("generate.errors")
            }
            HSplitView {
                reportList(selection: $model.selectedReportID)
                    .frame(minWidth: 200, idealWidth: 240, maxWidth: 320, maxHeight: .infinity)
                ReportView(report: selectedReport, failure: selectedFailure)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .task {
            await model.loadSprints()
            model.refreshSavedReports()
        }
    }

    private var coverageLabel: String {
        if model.run.acTotal > 0 {
            return "\(model.run.acCompleted) of \(model.run.acTotal) acceptance criteria reviewed"
        }
        return "Acceptance-criteria coverage"
    }

    private var rows: [ReportRow] {
        var map: [String: ReportRow] = [:]
        for report in model.savedReports {
            map[report.id] = ReportRow(id: report.id, report: report, error: nil)
        }
        for report in model.run.reports {
            map[report.id] = ReportRow(id: report.id, report: report, error: map[report.id]?.error)
        }
        for failure in model.run.errors where !failure.storyID.isEmpty {
            var row = map[failure.storyID] ?? ReportRow(id: failure.storyID, report: nil, error: nil)
            row.error = failure.message
            map[failure.storyID] = row
        }
        return map.values.sorted { $0.id < $1.id }
    }

    private var selectedReport: StoryReport? {
        guard let id = model.selectedReportID else { return nil }
        return rows.first { $0.id == id }?.report
    }

    private var selectedFailure: String? {
        guard let id = model.selectedReportID else { return nil }
        return rows.first { $0.id == id }?.error
    }

    private func reportList(selection: Binding<String?>) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if rows.isEmpty {
                VStack(spacing: 8) {
                    Text("Reports")
                        .font(.headline)
                        .foregroundStyle(AppTheme.ink)
                    Text("No reports yet")
                        .foregroundStyle(AppTheme.ink.opacity(0.72))
                }
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
                .accessibilityIdentifier("generate.empty")
            } else {
                Text("Reports")
                    .font(.headline)
                    .foregroundStyle(AppTheme.ink)
                    .fullWidthLine()
                List(rows, selection: selection) { row in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(row.id)
                            .fullWidthLine()
                        if row.report == nil, let error = row.error {
                            Text(error)
                                .font(.caption)
                                .foregroundStyle(.red)
                                .lineLimit(2)
                                .fullWidthLine()
                        }
                    }
                    .tag(row.id)
                }
                .scrollContentBackground(.hidden)
                .accessibilityIdentifier("generate.reports")
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(AppTheme.card, in: RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(AppTheme.accent.opacity(0.22))
        )
    }

    @ViewBuilder
    private func input(_ model: AppModel) -> some View {
        @Bindable var model = model
        switch model.mode {
        case .one:
            TextField("User story ID", text: $model.oneStoryText)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: .infinity)
                .accessibilityIdentifier("generate.story")
        case .several:
            TextField("Story IDs, separated by commas", text: $model.severalText)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: .infinity)
                .accessibilityIdentifier("generate.stories")
        case .sprint:
            sprintFields(model)
        }
    }

    private func sprintFields(_ model: AppModel) -> some View {
        @Bindable var model = model
        return HStack(spacing: 12) {
            Picker(selection: $model.sprintPath) {
                Text("Choose a sprint").tag("")
                ForEach(model.sprintChoices, id: \.self) { path in
                    Text(path).tag(path)
                }
                if !model.sprintPath.isEmpty && !model.sprintChoices.contains(model.sprintPath) {
                    Text(model.sprintPath).tag(model.sprintPath)
                }
            } label: {
                EmptyView()
            }
            .labelsHidden()
            .frame(maxWidth: 280)
            .accessibilityIdentifier("generate.sprintPicker")
            TextField("Iteration path", text: $model.sprintPath)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: .infinity)
                .accessibilityIdentifier("generate.sprint")
        }
    }
}

private struct ReportRow: Identifiable, Hashable {
    var id: String
    var report: StoryReport?
    var error: String?
}
