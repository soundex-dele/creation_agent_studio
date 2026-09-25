import Foundation

@main
enum DownloadHistoryTests {
  static func main() throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let url = directory.appendingPathComponent("history.json")
    let history = try DownloadHistory(url: url)
    var running = DownloadRecord(id: "active", filename: "报告.pdf")
    running.status = "running"
    running.downloadedBytes = 123
    try history.update(running)
    var completed = DownloadRecord(id: "done", filename: "report.pdf")
    completed.status = "completed"
    completed.totalBytes = 456
    completed.downloadedBytes = 456
    try history.update(completed)

    let restored = try DownloadHistory(url: url)
    precondition(restored.records["active"]?.status == "failed")
    precondition(restored.records["active"]?.reason == 1008)
    precondition(restored.records["active"]?.downloadedBytes == 123)
    precondition(restored.records["done"]?.status == "completed")
    precondition(restored.records["done"]?.dictionary["totalBytes"] as? Int64 == 456)
    let restoredAgain = try DownloadHistory(url: url)
    precondition(restoredAgain.records["active"]?.status == "failed")

    for input in ["../report.pdf", "a/b/report.pdf", "a\\b\\report.pdf", "\nreport.pdf\r"] {
      precondition(DownloadHistory.safeFilename(input) == "report.pdf")
    }
    for input in ["", ".", "..", " \n "] {
      precondition(DownloadHistory.safeFilename(input) == "未命名文件")
    }
    precondition(DownloadHistory.safeFilename("中文 报告.pdf") == "中文 报告.pdf")
    let stored = try String(contentsOf: url, encoding: .utf8)
    precondition(!stored.contains("cookie") && !stored.contains("https://"))
    print("Download history: persistence, interrupted tasks, completed sizes and safe filenames passed.")
  }
}
