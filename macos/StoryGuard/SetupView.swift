import SwiftUI

struct SetupView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let installer = model.installer
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Prepare this Mac")
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(AppTheme.ink)
                    .fullWidthLine()
                Text("Story Guard installs a private Python, its libraries, and the local Qwen model. Anything already on this Mac is left in place.")
                    .foregroundStyle(AppTheme.ink.opacity(0.75))
                    .fullWidthLine()
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text("\(installer.percent)%")
                        .font(.system(size: 40, weight: .semibold, design: .rounded))
                        .monospacedDigit()
                        .accessibilityIdentifier("setup.percent")
                    Text(installer.isComplete ? "Ready" : (installer.isRunning ? "Working" : "Stopped"))
                        .foregroundStyle(.secondary)
                    Spacer()
                }
                ProgressView(value: Double(installer.percent), total: 100)
                    .tint(AppTheme.accent)
                    .accessibilityIdentifier("setup.progress")
                VStack(spacing: 0) {
                    ForEach(installer.steps) { step in
                        SetupStepRow(step: step)
                        if step.id != installer.steps.last?.id {
                            Divider().padding(.leading, 36)
                        }
                    }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 4)
                .themeCard()
                if let error = installer.error {
                    Text(error)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                        .fullWidthLine()
                        .accessibilityIdentifier("setup.error")
                    Button("Retry") {
                        model.retrySetup()
                    }
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("setup.retry")
                    .disabled(installer.isRunning)
                }
                if !installer.log.isEmpty {
                    DisclosureGroup("Setup log") {
                        Text(installer.log.joined(separator: "\n"))
                            .font(.system(.caption, design: .monospaced))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                    }
                }
            }
            .padding(28)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

private struct SetupStepRow: View {
    var step: SetupStep

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            stepSymbol
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(step.title)
                Text(step.detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(.vertical, 10)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("setup.step.\(step.id)")
    }

    @ViewBuilder
    private var stepSymbol: some View {
        switch step.state {
        case .waiting:
            Image(systemName: "circle")
                .foregroundStyle(.secondary)
        case .working:
            ProgressView()
                .controlSize(.small)
        case .ready:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(AppTheme.accent)
        case .failed:
            Image(systemName: "xmark.circle.fill")
                .foregroundStyle(.red)
        }
    }
}
