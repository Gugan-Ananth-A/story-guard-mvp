import Foundation

/// Private file for the Azure DevOps token. Mode 0600. The value is never logged.
enum TokenStore {
    static var url: URL {
        SupportPaths.root.appendingPathComponent("ado-pat", isDirectory: false)
    }

    static func save(_ token: String) throws {
        let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw TokenStoreError(message: "Paste a personal access token.")
        }
        try SupportPaths.prepare()
        try Data(trimmed.utf8).write(to: url, options: [.atomic])
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }

    static func load() -> String? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        let token = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let token, !token.isEmpty else { return nil }
        return token
    }

    static func delete() {
        try? FileManager.default.removeItem(at: url)
    }
}

struct TokenStoreError: LocalizedError {
    var message: String

    var errorDescription: String? { message }
}
