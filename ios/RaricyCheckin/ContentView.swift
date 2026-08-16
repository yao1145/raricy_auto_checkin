import SwiftUI

struct ContentView: View {
    @State private var viewModel = CheckinViewModel()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    AccountListView(viewModel: viewModel)
                    CheckinView(viewModel: viewModel)
                }
                .padding()
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("raricy 打卡")
        }
    }
}
