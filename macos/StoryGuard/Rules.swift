import Foundation

/// One story, several stories, or a sprint iteration path.
enum GenerateMode: String, CaseIterable, Identifiable {
    case one = "Story"
    case several = "Multiple stories"
    case sprint = "A sprint"

    var id: String { rawValue }
}

enum StoryInput {
    /// A single positive story id, or nil when the field is blank or not numeric.
    static func one(_ text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard isStoryID(trimmed) else { return nil }
        return trimmed
    }

    /// Comma, space, or newline separated ids. Duplicates are dropped and order is kept.
    /// One invalid token rejects the whole field.
    static func several(_ text: String) -> [String]? {
        let parts = text.split { character in
            character == "," || character.isNewline || character.isWhitespace
        }
        var ordered: [String] = []
        var seen = Set<String>()
        for part in parts {
            let token = String(part)
            guard isStoryID(token) else { return nil }
            if seen.insert(token).inserted {
                ordered.append(token)
            }
        }
        return ordered.isEmpty ? nil : ordered
    }

    static func sprint(_ text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    static func isStoryID(_ text: String) -> Bool {
        text.range(of: #"^[1-9][0-9]*$"#, options: .regularExpression) != nil
    }
}

enum ConnectionURL {
    /// `https://dev.azure.com/{org}/{project}` with the project name percent-encoded.
    static func make(org: String, project: String) -> String? {
        let organization = org.trimmingCharacters(in: .whitespacesAndNewlines)
        let projectName = project.trimmingCharacters(in: .whitespacesAndNewlines)
        guard organization.range(of: #"^[A-Za-z0-9][A-Za-z0-9._-]*$"#, options: .regularExpression) != nil else {
            return nil
        }
        guard !projectName.isEmpty,
              !projectName.contains("?"),
              !projectName.contains("#"),
              !projectName.contains("/")
        else {
            return nil
        }
        guard let encoded = projectName.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) else {
            return nil
        }
        let text = "https://dev.azure.com/\(organization)/\(encoded)"
        guard let url = URL(string: text), url.scheme == "https", url.query == nil, url.fragment == nil else {
            return nil
        }
        return text
    }

    static func tokenPage(org: String) -> URL? {
        let organization = org.trimmingCharacters(in: .whitespacesAndNewlines)
        guard organization.range(of: #"^[A-Za-z0-9][A-Za-z0-9._-]*$"#, options: .regularExpression) != nil else {
            return nil
        }
        return URL(string: "https://dev.azure.com/\(organization)/_usersSettings/tokens")
    }
}
