import SwiftUI

struct ContentView: View {
    @State private var viewModel = WeatherViewModel()
    @State private var showSearch = false

    var body: some View {
        ZStack {
            SkyBackground(
                kind: viewModel.currentKind,
                isDay: viewModel.currentIsDay
            )

            TabView(selection: Bindable(viewModel).selectionID) {
                ForEach(viewModel.pages) { place in
                    WeatherPageView(place: place, viewModel: viewModel)
                        .tag(place.id)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: viewModel.pages.count > 1 ? .automatic : .never))
            .indexViewStyle(.page(backgroundDisplayMode: .never))

            topBar
        }
        .sheet(isPresented: $showSearch) {
            CitySearchView(viewModel: viewModel)
                .presentationDetents([.large])
        }
        .task {
            await viewModel.loadInitial()
        }
        .onChange(of: viewModel.selectionID) { _, newID in
            Haptics.selection()
            Task { await viewModel.ensureLoaded(newID) }
        }
    }

    private var topBar: some View {
        VStack {
            HStack {
                Spacer()

                Button {
                    Haptics.selection()
                    showSearch = true
                } label: {
                    Image(systemName: "magnifyingglass")
                        .font(.title3)
                        .foregroundStyle(.white)
                        .frame(width: 40, height: 40)
                        .background(.ultraThinMaterial, in: Circle())
                }
                .accessibilityLabel("都市を検索")
            }
            .padding(.horizontal, 16)
            Spacer()
        }
    }
}

#Preview {
    ContentView()
}
