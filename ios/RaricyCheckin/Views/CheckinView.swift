import SwiftUI

/// 打卡执行区 —— 一键打卡按钮、实时进度步骤、结果卡片与最近记录。
struct CheckinView: View {
    let viewModel: CheckinViewModel

    var body: some View {
        VStack(spacing: 16) {
            checkinButton

            if !viewModel.steps.isEmpty {
                StepsView(steps: viewModel.steps)
            }

            if !viewModel.results.isEmpty {
                ForEach(viewModel.results) { result in
                    ResultCard(result: result)
                }
            }

            if !viewModel.records.isEmpty {
                HistoryView(records: Array(viewModel.records.prefix(10)))
            }
        }
    }

    private var checkinButton: some View {
        Button {
            Task { @MainActor in
                await viewModel.checkin()
            }
        } label: {
            HStack(spacing: 8) {
                if viewModel.isRunning {
                    ProgressView()
                        .tint(.white)
                } else {
                    Image(systemName: "checkmark.seal.fill")
                }
                Text(viewModel.isRunning ? "打卡中…" : "立即打卡")
            }
            .font(.headline)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 4)
        }
        .buttonStyle(.borderedProminent)
        .disabled(viewModel.isRunning || viewModel.accounts.filter(\.enabled).isEmpty)
    }
}

/// 实时进度步骤列表。
private struct StepsView: View {
    let steps: [CheckinStep]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(steps) { step in
                HStack(spacing: 10) {
                    Image(systemName: iconName(for: step.status))
                        .foregroundStyle(iconColor(for: step.status))
                    Text(step.message)
                        .font(.subheadline)
                    Spacer()
                    Text(AppConfig.timeFormatter.string(from: step.time))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private func iconName(for status: StepStatus) -> String {
        switch status {
        case .running:
            return "circle.dotted"
        case .done:
            return "checkmark.circle.fill"
        case .error:
            return "xmark.circle.fill"
        }
    }

    private func iconColor(for status: StepStatus) -> Color {
        switch status {
        case .running:
            return .secondary
        case .done:
            return .green
        case .error:
            return .red
        }
    }
}

/// 单个账号的打卡结果卡片。
private struct ResultCard: View {
    let result: CheckinResult

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(result.account)
                    .font(.headline)
                Spacer()
                Text(result.success ? "成功" : "失败")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(result.success ? Color.green : Color.red)
            }

            Text(result.message)
                .font(.subheadline)
                .foregroundStyle(.secondary)

            if let fortune = result.fortune, fortune.handled {
                FortuneView(fortune: fortune)
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

/// 最近打卡记录列表。
private struct HistoryView: View {
    let records: [CheckinRecord]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("最近记录")
                .font(.headline)

            ForEach(records) { record in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(record.account)
                        .font(.subheadline)
                        .frame(width: 120, alignment: .leading)
                    Text(record.message)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Spacer(minLength: 8)
                    Text(record.time)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
