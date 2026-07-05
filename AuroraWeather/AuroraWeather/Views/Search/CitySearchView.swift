import SwiftUI

/// 都市検索 + 保存地点の管理シート
struct CitySearchView: View {
    @Bindable var viewModel: WeatherViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var query = ""
    @State private var results: [GeoPlace] = []
    @State private var isSearching = false
    @State private var searchTask: Task<Void, Never>?

    private let geocoding = GeocodingService()

    var body: some View {
        NavigationStack {
            List {
                // 現在地
                Section {
                    Button {
                        dismiss()
                        Task { await viewModel.useCurrentLocation() }
                    } label: {
                        Label("現在地を使う", systemImage: "location.fill")
                            .foregroundStyle(Color.accentColor)
                    }
                }

                // 通知
                Section {
                    Toggle(isOn: Binding(
                        get: { viewModel.rainAlertsEnabled },
                        set: { newValue in Task { await viewModel.setRainAlerts(newValue) } }
                    )) {
                        Label("雨が近づいたら通知", systemImage: "umbrella")
                    }
                } footer: {
                    Text("アプリを開いた時点の予報をもとに、降り出しの約30分前にお知らせします(降水確率50%以上のとき)。")
                }

                // 検索結果
                if !results.isEmpty {
                    Section("検索結果") {
                        ForEach(results) { result in
                            Button {
                                select(result.asSavedPlace)
                            } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(result.name)
                                            .font(.body.weight(.medium))
                                            .foregroundStyle(.primary)
                                        if !result.detailText.isEmpty {
                                            Text(result.detailText)
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    Spacer()
                                    Button {
                                        viewModel.save(place: result.asSavedPlace)
                                        Haptics.success()
                                    } label: {
                                        Image(systemName: isSaved(result) ? "checkmark.circle.fill" : "plus.circle")
                                            .font(.title3)
                                            .foregroundStyle(isSaved(result) ? Color.green : Color.accentColor)
                                    }
                                    .buttonStyle(.borderless)
                                }
                            }
                        }
                    }
                } else if isSearching {
                    Section {
                        HStack {
                            Spacer()
                            ProgressView()
                            Spacer()
                        }
                    }
                }

                // 保存済みの地点
                if !viewModel.savedPlaces.isEmpty {
                    Section("マイシティ") {
                        ForEach(viewModel.savedPlaces) { place in
                            Button {
                                select(place)
                            } label: {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(place.name)
                                        .font(.body.weight(.medium))
                                        .foregroundStyle(.primary)
                                    if !place.detail.isEmpty {
                                        Text(place.detail)
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                            }
                        }
                        .onDelete { offsets in
                            viewModel.removePlaces(at: offsets)
                        }
                    }
                }
            }
            .navigationTitle("地点を選ぶ")
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "都市名で検索(例: 大阪、Paris)")
            .onChange(of: query) { _, newValue in
                scheduleSearch(newValue)
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("閉じる") { dismiss() }
                }
            }
        }
    }

    private func isSaved(_ place: GeoPlace) -> Bool {
        viewModel.savedPlaces.contains(place.asSavedPlace)
    }

    private func select(_ place: SavedPlace) {
        dismiss()
        Task { await viewModel.selectSearched(place) }
    }

    /// 入力から 0.35 秒デバウンスして検索する
    private func scheduleSearch(_ text: String) {
        searchTask?.cancel()
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            results = []
            isSearching = false
            return
        }
        isSearching = true
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 350_000_000)
            guard !Task.isCancelled else { return }
            let found = (try? await geocoding.search(trimmed)) ?? []
            guard !Task.isCancelled else { return }
            await MainActor.run {
                results = found
                isSearching = false
            }
        }
    }
}
