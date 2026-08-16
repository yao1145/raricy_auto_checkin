import SwiftUI

/// 今日运势卡片 —— 橙色强调，展示运势结果与抽取到的卡位。
struct FortuneView: View {
    let fortune: FortuneResult

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("今日运势")
                .font(.caption)
                .foregroundStyle(.orange)

            Text(fortune.resultValue ?? fortune.resultText)
                .font(.title2.bold())
                .foregroundStyle(.orange)

            if fortune.totalCards > 0 {
                Text("第 \(fortune.cardSelected + 1) / \(fortune.totalCards) 张")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}
