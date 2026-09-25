import Foundation

struct DownloadRecord: Codable {
  let id: String
  var filename: String
  var downloadedBytes: Int64 = 0
  var totalBytes: Int64 = -1
  var updatedAt: Double = Date().timeIntervalSince1970 * 1000
  var reason: Int = 0
  var status: String = "pending"

  var dictionary: [String: Any] {
    ["id": id, "filename": filename, "downloadedBytes": downloadedBytes,
     "totalBytes": totalBytes, "updatedAt": updatedAt, "reason": reason, "status": status]
  }
}

/// Stores metadata only; URLs and session cookies never enter download history.
final class DownloadHistory {
  private let url: URL
  private(set) var records: [String: DownloadRecord] = [:]

  init(url: URL) throws {
    self.url = url
    if FileManager.default.fileExists(atPath: url.path) {
      records = try JSONDecoder().decode([String: DownloadRecord].self, from: Data(contentsOf: url))
    }
    // WKDownload cannot survive app termination. Never leave stale tasks spinning forever.
    for (id, var record) in records where ["pending", "running", "paused"].contains(record.status) {
      record.status = "failed"
      record.reason = 1008
      record.updatedAt = Date().timeIntervalSince1970 * 1000
      records[id] = record
    }
    try save()
  }

  func update(_ record: DownloadRecord, persist: Bool = true) throws {
    records[record.id] = record
    if persist { try save() }
  }

  private func save() throws {
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try JSONEncoder().encode(records).write(to: url, options: .atomic)
  }

  static func safeFilename(_ suggested: String) -> String {
    let name = (suggested.replacingOccurrences(of: "\\", with: "/") as NSString).lastPathComponent
      .components(separatedBy: .controlCharacters).joined()
      .trimmingCharacters(in: .whitespacesAndNewlines)
    return name.isEmpty || name == "." || name == ".." ? "未命名文件" : name
  }
}
