import SwiftUI

enum AppTheme {
    static let green = Color(red: 0.78, green: 0.93, blue: 0.82)
    static let mist = Color(red: 0.93, green: 0.98, blue: 0.95)
    static let accent = Color(red: 0.15, green: 0.50, blue: 0.32)
    static let ink = Color(red: 0.10, green: 0.22, blue: 0.16)
    static let card = Color.white.opacity(0.94)

    static var background: LinearGradient {
        LinearGradient(
            colors: [green, mist, .white],
            startPoint: .top,
            endPoint: .bottom
        )
    }
}

struct FullWidthLine: ViewModifier {
    func body(content: Content) -> some View {
        content
            .frame(maxWidth: .infinity, alignment: .leading)
            .multilineTextAlignment(.leading)
    }
}

extension View {
    func fullWidthLine() -> some View {
        modifier(FullWidthLine())
    }

    func themeCard() -> some View {
        self
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(AppTheme.card, in: RoundedRectangle(cornerRadius: 14))
            .overlay(
                RoundedRectangle(cornerRadius: 14)
                    .stroke(AppTheme.accent.opacity(0.22))
            )
    }
}
