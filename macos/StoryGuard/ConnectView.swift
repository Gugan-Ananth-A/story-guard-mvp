import SwiftUI

struct ConnectView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Personal access token")
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(AppTheme.ink)
                    .fullWidthLine()
                Text("Paste one token for \(model.org), project \(model.project). Verify checks it, then Story Guard opens.")
                    .foregroundStyle(AppTheme.ink.opacity(0.82))
                    .fullWidthLine()

                VStack(alignment: .leading, spacing: 10) {
                    Text("Create a token")
                        .font(.headline)
                        .foregroundStyle(AppTheme.ink)
                        .fullWidthLine()
                    step("1", "Open the token page and choose New Token.")
                    step("2", "Enter a name and an expiration date.")
                    step("3", "Open Scopes and choose Custom defined.")
                    step("4", "Turn on Work Items (Read) and Test Management (Read).")
                    step("5", "Create the token and copy it. Azure DevOps shows the value one time.")
                    step("6", "Paste it below and choose Verify.")
                    if let page = ConnectionURL.tokenPage(org: model.org) {
                        Link("Open the Azure DevOps token page", destination: page)
                            .fullWidthLine()
                            .accessibilityIdentifier("connect.tokenLink")
                    }
                }
                .themeCard()

                VStack(alignment: .leading, spacing: 10) {
                    Text("Mandatory permissions")
                        .font(.headline)
                        .foregroundStyle(AppTheme.ink)
                        .fullWidthLine()
                    permission(
                        "Work Items — Read",
                        "Stories, acceptance criteria, and sprint iterations."
                    )
                    permission(
                        "Test Management — Read",
                        "Test plans, suites, and test cases."
                    )
                }
                .themeCard()

                HStack(alignment: .center, spacing: 12) {
                    SecureField("Personal access token", text: $model.token)
                        .textFieldStyle(.roundedBorder)
                        .accessibilityIdentifier("connect.token")
                    Button(model.isVerifying ? "Verifying…" : "Verify") {
                        model.verifyFromForm()
                    }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .disabled(model.isVerifying)
                    .accessibilityIdentifier("connect.verify")
                    if model.hasToken {
                        Button("Disconnect") {
                            model.disconnect()
                        }
                        .accessibilityIdentifier("connect.disconnect")
                    }
                }
                .fullWidthLine()

                if let verifyError = model.verifyError {
                    Text(verifyError)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                        .fullWidthLine()
                        .accessibilityIdentifier("connect.error")
                }
            }
            .padding(28)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private func step(_ number: String, _ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(number)
                .font(.headline.monospacedDigit())
                .foregroundStyle(AppTheme.accent)
                .frame(width: 22, alignment: .leading)
            Text(text)
                .foregroundStyle(AppTheme.ink)
                .fullWidthLine()
        }
    }

    private func permission(_ title: String, _ detail: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.body.weight(.semibold))
                .foregroundStyle(AppTheme.ink)
                .fullWidthLine()
            Text(detail)
                .foregroundStyle(AppTheme.ink.opacity(0.75))
                .fullWidthLine()
        }
    }
}
