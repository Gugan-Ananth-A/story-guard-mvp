import Foundation

@main
struct LogicTests {
    static func main() {
        var failures: [String] = []
        func expect(_ condition: Bool, _ message: String) {
            if !condition {
                failures.append(message)
            }
        }
        run(expect)
        if !failures.isEmpty {
            for failure in failures {
                fputs("FAIL \(failure)\n", stderr)
            }
            exit(1)
        }
        print("logic tests passed")
    }
}

private func run(_ expect: (Bool, String) -> Void) {

expect(StoryInput.one("121213") == "121213", "one story id")
expect(StoryInput.one("  123086  ") == "123086", "trimmed story id")
expect(StoryInput.one("") == nil, "blank story id")
expect(StoryInput.one("   ") == nil, "whitespace story id")
expect(StoryInput.one("abc") == nil, "non-numeric story id")
expect(StoryInput.one("0") == nil, "zero story id")
expect(StoryInput.one("012") == nil, "leading zero")
expect(StoryInput.one("121213,123086") == nil, "one field rejects a list")

expect(StoryInput.several("121213, 123086\n121213") == ["121213", "123086"], "several ids drop duplicates and keep order")
expect(StoryInput.several("121213 123086") == ["121213", "123086"], "several ids accept spaces")
expect(StoryInput.several("") == nil, "blank several")
expect(StoryInput.several("121213, abc") == nil, "several rejects a bad token")
expect(StoryInput.several("0") == nil, "several rejects zero")

expect(StoryInput.sprint("  Ecom MVP\\Sprint  ") == "Ecom MVP\\Sprint", "sprint trim")
expect(StoryInput.sprint("   ") == nil, "blank sprint")

expect(
    ConnectionURL.make(org: "rootquotient", project: "Ecom MVP") == "https://dev.azure.com/rootquotient/Ecom%20MVP",
    "project space is percent-encoded"
)
expect(ConnectionURL.make(org: "", project: "Ecom MVP") == nil, "blank org")
expect(ConnectionURL.make(org: "rootquotient", project: "Ecom/MVP") == nil, "project slash")
expect(ConnectionURL.make(org: "rootquotient", project: "Ecom?MVP") == nil, "project query")
expect(ConnectionURL.make(org: "bad org", project: "Ecom") == nil, "org space")
expect(
    ConnectionURL.tokenPage(org: "rootquotient")?.absoluteString == "https://dev.azure.com/rootquotient/_usersSettings/tokens",
    "token page"
)

expect(ProgressMath.storyPercent(completed: 3, total: 12) == 25, "three of twelve acceptance criteria")
expect(ProgressMath.storyPercent(completed: 2, total: 8) == 25, "two of eight acceptance criteria")
expect(ProgressMath.storyPercent(completed: 0, total: 12) == 0, "no criteria reviewed yet")
expect(ProgressMath.storyPercent(completed: 12, total: 12) == 100, "all criteria reviewed")
expect(ProgressMath.overall(storyIndex: 1, storyCount: 2, storyPercent: 0) == 0, "before review")
expect(ProgressMath.overall(storyIndex: 1, storyCount: 2, storyPercent: 25) == 12, "mid review overall")
expect(ProgressMath.overall(storyIndex: 1, storyCount: 2, storyPercent: 100) == 50, "one story finished")
expect(ProgressMath.overall(storyIndex: 2, storyCount: 2, storyPercent: 100) == 100, "batch end")

let progress = """
{"event":"progress","story_index":1,"story_count":2,"message":"completed AC-03: 2 predicted test links","percent":12,"ac_completed":3,"ac_total":12}
"""
let decoded = DriverEvent.decodeLine(progress)
expect(decoded?.event == "progress", "decode event")
expect(decoded?.percent == 12, "decode percent")
expect(decoded?.storyIndex == 1, "decode index")
expect(decoded?.acCompleted == 3, "decode ac completed")
expect(decoded?.acTotal == 12, "decode ac total")

var snapshot = RunSnapshot()
snapshot = ProgressMath.reduce(snapshot, decoded!)
expect(snapshot.percent == 12, "reduce percent")
expect(snapshot.acCompleted == 3, "reduce ac completed")
expect(snapshot.acTotal == 12, "reduce ac total")
expect(snapshot.message.contains("completed AC-03"), "reduce message")
snapshot = ProgressMath.reduce(
    snapshot,
    DriverEvent(event: "report", storyIndex: nil, storyCount: nil, message: nil, percent: nil, storyID: "121213", pdf: "/tmp/121213.pdf", markdown: "/tmp/121213.md", written: nil, failed: nil)
)
expect(snapshot.reports.map(\.id) == ["121213"], "reduce report")
snapshot = ProgressMath.reduce(
    snapshot,
    DriverEvent(event: "error", storyIndex: nil, storyCount: nil, message: "story 123086: failed", percent: nil, storyID: "123086", pdf: nil, markdown: nil, written: nil, failed: nil)
)
snapshot = ProgressMath.reduce(
    snapshot,
    DriverEvent(event: "done", storyIndex: nil, storyCount: nil, message: nil, percent: nil, storyID: nil, pdf: nil, markdown: nil, written: ["121213"], failed: ["123086"])
)
expect(snapshot.finished, "reduce done")
expect(snapshot.failed == ["123086"], "reduce failed")
expect(snapshot.reports.count == 1, "a failure keeps the finished report")
}
