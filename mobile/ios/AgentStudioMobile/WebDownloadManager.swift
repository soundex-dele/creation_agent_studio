import Foundation
@preconcurrency import WebKit

/// Main-thread owner, independent of individual windows and React Native reloads.
final class WebDownloadManager: NSObject, WKDownloadDelegate {
  static let shared = WebDownloadManager()
  private var history: DownloadHistory?
  private var historyError: Error?
  private var downloads: [String: WKDownload] = [:]
  private var destinations: [String: URL] = [:]

  private override init() {
    super.init()
    do {
      let support = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                               appropriateFor: nil, create: true)
      history = try DownloadHistory(url: support.appendingPathComponent("download-history.json"))
    } catch {
      historyError = error
    }
    NotificationCenter.default.addObserver(self, selector: #selector(didStartDownload(_:)),
      name: NSNotification.Name("AgentStudioDownloadStarted"), object: nil)
  }

  @objc private func didStartDownload(_ notification: Notification) {
    guard let download = notification.object as? WKDownload else { return }
    let id = UUID().uuidString
    downloads[id] = download
    download.delegate = self
    update(DownloadRecord(id: id, filename: "准备下载"))
  }

  private func id(for download: WKDownload) -> String? {
    downloads.first(where: { $0.value === download })?.key
  }

  private func update(_ record: DownloadRecord, persist: Bool = true) {
    do { try history?.update(record, persist: persist) }
    catch { historyError = error }
  }

  func listDownloads() throws -> [[String: Any]] {
    if let error = historyError { throw error }
    for (id, download) in downloads {
      guard var record = history?.records[id], record.status == "running" else { continue }
      let bytes = max(0, download.progress.completedUnitCount)
      if bytes != record.downloadedBytes {
        record.downloadedBytes = bytes
        record.updatedAt = Date().timeIntervalSince1970 * 1000
      }
      if download.progress.totalUnitCount > 0 { record.totalBytes = download.progress.totalUnitCount }
      update(record, persist: false)
    }
    return history?.records.values.map(\.dictionary) ?? []
  }

  func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
    guard let id = id(for: download), var record = history?.records[id], historyError == nil else {
      completionHandler(nil)
      return
    }
    record.filename = DownloadHistory.safeFilename(suggestedFilename)
    if let response = response as? HTTPURLResponse, response.statusCode >= 400 {
      record.status = "failed"
      record.reason = response.statusCode
      update(record)
      completionHandler(nil)
      return
    }
    do {
      let documents = try FileManager.default.url(for: .documentDirectory, in: .userDomainMask,
                                                  appropriateFor: nil, create: true)
      let directory = documents.appendingPathComponent("Downloads", isDirectory: true)
      try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
      var destination = directory.appendingPathComponent(record.filename)
      let original = destination
      var suffix = 1
      while FileManager.default.fileExists(atPath: destination.path) || destinations.values.contains(destination) {
        let ext = original.pathExtension
        let name = original.deletingPathExtension().lastPathComponent + " (\(suffix))"
        destination = directory.appendingPathComponent(ext.isEmpty ? name : name + "." + ext)
        suffix += 1
      }
      destinations[id] = destination
      record.filename = destination.lastPathComponent
      record.totalBytes = response.expectedContentLength
      record.status = "running"
      update(record)
      completionHandler(historyError == nil ? destination : nil)
    } catch {
      record.status = "failed"
      record.reason = (error as NSError).code == NSFileWriteOutOfSpaceError ? 1006 : 1001
      update(record)
      completionHandler(nil)
    }
  }

  func downloadDidFinish(_ download: WKDownload) {
    guard let id = id(for: download), var record = history?.records[id] else { return }
    do {
      guard let destination = destinations[id] else { throw CocoaError(.fileNoSuchFile) }
      let values = try destination.resourceValues(forKeys: [.fileSizeKey])
      record.downloadedBytes = Int64(values.fileSize ?? 0)
      record.totalBytes = record.downloadedBytes
      record.status = "completed"
    } catch {
      record.status = "failed"
      record.reason = 1001
    }
    record.updatedAt = Date().timeIntervalSince1970 * 1000
    update(record)
    downloads.removeValue(forKey: id)
    destinations.removeValue(forKey: id)
  }

  func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
    guard let id = id(for: download) else { return }
    if var record = history?.records[id] {
      // Preserve specific HTTP / file errors assigned before cancellation.
      if record.status != "failed" {
        record.reason = (error as NSError).code == NSURLErrorCannotWriteToFile ? 1001 : 0
        record.status = "failed"
      }
      record.downloadedBytes = max(record.downloadedBytes, download.progress.completedUnitCount)
      record.updatedAt = Date().timeIntervalSince1970 * 1000
      update(record)
    }
    if let destination = destinations.removeValue(forKey: id) { try? FileManager.default.removeItem(at: destination) }
    downloads.removeValue(forKey: id)
  }

  func download(_ download: WKDownload, didReceive challenge: URLAuthenticationChallenge,
                completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
    // Keep normal system TLS validation; never accept arbitrary server certificates.
    completionHandler(.performDefaultHandling, nil)
  }
}
