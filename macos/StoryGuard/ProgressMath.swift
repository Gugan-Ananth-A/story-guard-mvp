import Foundation

struct StoryReport: Identifiable, Equatable, Hashable {
    var id: String
    var pdfPath: String
    var markdownPath: String
}

struct StoryFailure: Identifiable, Equatable {
    var id: Int
    var storyID: String
    var message: String
}

struct RunSnapshot: Equatable {
    var percent: Int = 0
    var message: String = ""
    var log: [String] = []
    var reports: [StoryReport] = []
    var errors: [StoryFailure] = []
    var written: [String] = []
    var failed: [String] = []
    var finished: Bool = false
    var storyIndex: Int = 0
    var storyCount: Int = 0
    var acCompleted: Int = 0
    var acTotal: Int = 0
    var nextFailureID: Int = 1
}

struct DriverEvent: Equatable {
    var event: String
    var storyIndex: Int?
    var storyCount: Int?
    var message: String?
    var percent: Int?
    var storyID: String?
    var pdf: String?
    var markdown: String?
    var written: [String]?
    var failed: [String]?
    var acCompleted: Int?
    var acTotal: Int?

    init(
        event: String,
        storyIndex: Int? = nil,
        storyCount: Int? = nil,
        message: String? = nil,
        percent: Int? = nil,
        storyID: String? = nil,
        pdf: String? = nil,
        markdown: String? = nil,
        written: [String]? = nil,
        failed: [String]? = nil,
        acCompleted: Int? = nil,
        acTotal: Int? = nil
    ) {
        self.event = event
        self.storyIndex = storyIndex
        self.storyCount = storyCount
        self.message = message
        self.percent = percent
        self.storyID = storyID
        self.pdf = pdf
        self.markdown = markdown
        self.written = written
        self.failed = failed
        self.acCompleted = acCompleted
        self.acTotal = acTotal
    }

    static func decodeLine(_ line: String) -> DriverEvent? {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("{"), let data = trimmed.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(DriverEvent.self, from: data)
    }
}

extension DriverEvent: Decodable {
    enum CodingKeys: String, CodingKey {
        case event
        case storyIndex = "story_index"
        case storyCount = "story_count"
        case message
        case percent
        case storyID = "story_id"
        case pdf
        case markdown
        case written
        case failed
        case acCompleted = "ac_completed"
        case acTotal = "ac_total"
    }
}

/// Turns driver JSON events into the percent, step, and report list shown while generating.
enum ProgressMath {
    /// Whole-number share of acceptance criteria that have been reviewed.
    static func storyPercent(completed: Int, total: Int) -> Int {
        guard total > 0, completed > 0 else { return 0 }
        if completed >= total { return 100 }
        return (completed * 100) / total
    }

    /// `((storyIndex - 1) * 100 + storyPercent) / storyCount`. Index is 1-based.
    static func overall(storyIndex: Int, storyCount: Int, storyPercent: Int) -> Int {
        guard storyIndex > 0, storyCount > 0 else { return 0 }
        return ((storyIndex - 1) * 100 + storyPercent) / storyCount
    }

    static func reduce(_ snapshot: RunSnapshot, _ event: DriverEvent) -> RunSnapshot {
        var next = snapshot
        switch event.event {
        case "progress":
            if let percent = event.percent {
                next.percent = min(100, max(0, percent))
            }
            if let message = event.message, !message.isEmpty {
                next.message = message
                next.log.append(message)
            }
            if let storyIndex = event.storyIndex {
                next.storyIndex = storyIndex
            }
            if let storyCount = event.storyCount {
                next.storyCount = storyCount
            }
            if let acCompleted = event.acCompleted {
                next.acCompleted = acCompleted
            }
            if let acTotal = event.acTotal {
                next.acTotal = acTotal
            }
        case "report":
            guard let id = event.storyID, let pdf = event.pdf, !id.isEmpty, !pdf.isEmpty else {
                break
            }
            let report = StoryReport(id: id, pdfPath: pdf, markdownPath: event.markdown ?? "")
            if let index = next.reports.firstIndex(where: { $0.id == id }) {
                next.reports[index] = report
            } else {
                next.reports.append(report)
            }
        case "error":
            let message = event.message ?? "The story failed."
            next.errors.append(StoryFailure(id: next.nextFailureID, storyID: event.storyID ?? "", message: message))
            next.nextFailureID += 1
            if !message.isEmpty {
                next.log.append(message)
            }
        case "done":
            next.written = event.written ?? []
            next.failed = event.failed ?? []
            next.finished = true
        default:
            break
        }
        return next
    }
}
