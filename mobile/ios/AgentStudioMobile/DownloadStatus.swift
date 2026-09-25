import Foundation
import React

@objc(DownloadStatus)
final class DownloadStatus: NSObject {
  @objc static func requiresMainQueueSetup() -> Bool { true }

  @objc(listDownloads:rejecter:)
  func listDownloads(_ resolve: @escaping RCTPromiseResolveBlock, rejecter reject: @escaping RCTPromiseRejectBlock) {
    DispatchQueue.main.async {
      do { resolve(try WebDownloadManager.shared.listDownloads()) }
      catch { reject("DOWNLOAD_STATUS_FAILED", "无法读取下载进度，请重试。", error) }
    }
  }
}
