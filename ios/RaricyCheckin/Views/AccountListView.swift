import SwiftUI

/// 账号列表 —— 勾选要打卡的账号、切换启用状态、编辑/删除。
struct AccountListView: View {
    let viewModel: CheckinViewModel

    @State private var showingForm = false
    @State private var editingAccount: Account?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header

            if viewModel.accounts.isEmpty {
                Text("还没有账号，点击「添加」")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(viewModel.accounts) { account in
                    AccountRow(viewModel: viewModel, account: account) {
                        editingAccount = account
                        showingForm = true
                    }
                }
            }
        }
        .padding()
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .sheet(isPresented: $showingForm) {
            AccountFormView(viewModel: viewModel, account: editingAccount)
        }
    }

    private var header: some View {
        HStack {
            Text("账号")
                .font(.headline)
            Spacer()
            Button {
                editingAccount = nil
                showingForm = true
            } label: {
                Label("添加", systemImage: "plus")
            }
        }
    }
}

/// 单行账号 —— 勾选参与打卡、启用开关、编辑入口、今日状态。
private struct AccountRow: View {
    let viewModel: CheckinViewModel
    let account: Account
    let onEdit: () -> Void

    private var isSelected: Bool {
        viewModel.selectedUsernames.contains(account.username)
    }

    var body: some View {
        HStack(spacing: 12) {
            Button {
                if isSelected {
                    viewModel.selectedUsernames.remove(account.username)
                } else {
                    viewModel.selectedUsernames.insert(account.username)
                }
            } label: {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(isSelected ? Color.accentColor : Color.secondary)
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: 2) {
                Text(account.username)
                    .font(.body)
                statusCaption
            }

            Spacer()

            Toggle("", isOn: Binding(
                get: { account.enabled },
                set: { viewModel.setEnabled(username: account.username, enabled: $0) }
            ))
            .labelsHidden()

            Button(action: onEdit) {
                Image(systemName: "pencil")
                    .foregroundStyle(Color.accentColor)
            }
            .buttonStyle(.plain)
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder
    private var statusCaption: some View {
        if let record = viewModel.todayStatus(for: account.username) {
            Text(record.fortune.map { "已打卡 · \($0)" } ?? "已打卡")
                .font(.caption)
                .foregroundStyle(.green)
        } else {
            Text("今日未打卡")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}
