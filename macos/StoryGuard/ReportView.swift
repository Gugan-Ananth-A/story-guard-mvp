import AppKit
import PDFKit
import SwiftUI
import UniformTypeIdentifiers

struct ReportView: View {
    var report: StoryReport?
    var failure: String?
    @State private var actionError: String?

    private var isEmpty: Bool {
        report == nil && failure == nil
    }

    var body: some View {
        VStack(alignment: isEmpty ? .center : .leading, spacing: 8) {
            if let report {
                PDFKitRepresentable(url: URL(fileURLWithPath: report.pdfPath))
                    .accessibilityIdentifier("report.pdf")
                HStack(spacing: 12) {
                    Button("Download") {
                        download(report)
                    }
                    .accessibilityIdentifier("report.download")
                    Button("Show in Finder") {
                        reveal(report)
                    }
                    .accessibilityIdentifier("report.finder")
                    Spacer(minLength: 0)
                    Text("\(report.id).pdf")
                        .font(.caption)
                        .foregroundStyle(AppTheme.ink.opacity(0.7))
                        .lineLimit(1)
                }
            } else if let failure {
                VStack(spacing: 8) {
                    Text("Report failed")
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(AppTheme.ink)
                        .multilineTextAlignment(.center)
                    Text(failure)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity, alignment: .center)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
            } else {
                VStack(spacing: 8) {
                    Text("No report yet")
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(AppTheme.ink)
                        .multilineTextAlignment(.center)
                    Text("Generate a story to open its PDF here.")
                        .foregroundStyle(AppTheme.ink.opacity(0.72))
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity, alignment: .center)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
                .accessibilityIdentifier("report.empty")
            }
            if let actionError {
                Text(actionError)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .fullWidthLine()
                    .accessibilityIdentifier("report.error")
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: isEmpty ? .center : .topLeading)
        .background(AppTheme.card, in: RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(AppTheme.accent.opacity(0.22))
        )
    }

    private func download(_ report: StoryReport) {
        let source = URL(fileURLWithPath: report.pdfPath)
        guard FileManager.default.fileExists(atPath: source.path) else {
            actionError = "The PDF is no longer in Story Guard's folder."
            return
        }
        let panel = NSSavePanel()
        panel.title = "Download report"
        panel.nameFieldStringValue = "\(report.id).pdf"
        panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
        panel.allowedContentTypes = [.pdf]
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        if source.standardizedFileURL == destination.standardizedFileURL {
            actionError = nil
            return
        }
        do {
            if FileManager.default.fileExists(atPath: destination.path) {
                try FileManager.default.removeItem(at: destination)
            }
            try FileManager.default.copyItem(at: source, to: destination)
            actionError = nil
        } catch {
            actionError = error.localizedDescription
        }
    }

    private func reveal(_ report: StoryReport) {
        let source = URL(fileURLWithPath: report.pdfPath)
        guard FileManager.default.fileExists(atPath: source.path) else {
            actionError = "The PDF is no longer in Story Guard's folder."
            return
        }
        NSWorkspace.shared.activateFileViewerSelecting([source])
        actionError = nil
    }
}

private struct PDFKitRepresentable: NSViewRepresentable {
    var url: URL

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.displayMode = .singlePageContinuous
        view.displaysPageBreaks = true
        view.document = PDFDocument(url: url)
        context.coordinator.loadedPath = url.path
        context.coordinator.loadedMTime = modificationDate(of: url)
        return view
    }

    func updateNSView(_ pdfView: PDFView, context: Context) {
        let mtime = modificationDate(of: url)
        if context.coordinator.loadedPath == url.path, context.coordinator.loadedMTime == mtime {
            return
        }
        pdfView.document = PDFDocument(url: url)
        pdfView.autoScales = true
        context.coordinator.loadedPath = url.path
        context.coordinator.loadedMTime = mtime
    }

    private func modificationDate(of url: URL) -> Date? {
        try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate
    }

    final class Coordinator {
        var loadedPath: String?
        var loadedMTime: Date?
    }
}
