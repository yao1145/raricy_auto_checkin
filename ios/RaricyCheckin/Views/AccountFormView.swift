import SwiftUI

/// 添加 / 编辑账号表单。`account == nil` 表示新增。
struct AccountFormView: View {
    let viewModel: CheckinViewModel
    let account: Account?

    @Environment(\.dismiss) private var dismiss
    @State private var username = ""
    @State private var password = ""
    @State private var enabled = true

    private var isEditing: Bool { account != nil }

    var body: some View {
        NavigationStack {
            Form {
                Section("账号") {
                    TextField("用户名", text: $username)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .disabled(isEditing)   // 用户名不可修改

                    SecureField(account == nil ? "密码" : "密码（留空则不修改）", text: $password)
                }

                Section {
                    Toggle("启用", isOn: $enabled)
                }
            }
            .navigationTitle(isEditing ? "编辑账号" : "添加账号")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") { save() }
                        .disabled(!canSave)
                }
            }
            .onAppear {
                if let account {
                    username = account.username
                    enabled = account.enabled
                }
            }
        }
    }

    private var trimmedUsername: String {
        username.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// 用户名为空不可保存；新增时密码亦不可为空。
    private var canSave: Bool {
        !trimmedUsername.isEmpty && (isEditing || !password.isEmpty)
    }

    private func save() {
        if let account {
            viewModel.updateAccount(
                username: account.username,
                password: password.isEmpty ? nil : password,
                enabled: enabled
            )
        } else {
            viewModel.addAccount(
                username: trimmedUsername,
                password: password,
                enabled: enabled
            )
        }
        dismiss()
    }
}
