package com.creationagentstudio.mobile

import android.app.DownloadManager
import android.content.Context
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.NativeModule
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.uimanager.ViewManager
import java.util.concurrent.Executors

/** Queries only this app's system-managed downloads, including tasks from previous launches. */
class DownloadStatusModule(context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  private val executor = Executors.newSingleThreadExecutor()

  override fun getName() = "DownloadStatus"

  @ReactMethod
  fun listDownloads(promise: Promise) {
    executor.execute {
      try {
        val manager = reactApplicationContext.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        val result = Arguments.createArray()
        manager.query(DownloadManager.Query())?.use { cursor ->
          val idColumn = cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_ID)
          val titleColumn = cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_TITLE)
          val bytesColumn = cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR)
          val totalColumn = cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES)
          val statusColumn = cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS)
          val reasonColumn = cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON)
          val modifiedColumn = cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_LAST_MODIFIED_TIMESTAMP)
          while (cursor.moveToNext()) {
            val item = Arguments.createMap()
            item.putString("id", cursor.getLong(idColumn).toString())
            item.putString("filename", cursor.getString(titleColumn) ?: "未命名文件")
            item.putDouble("downloadedBytes", cursor.getLong(bytesColumn).coerceAtLeast(0).toDouble())
            item.putDouble("totalBytes", cursor.getLong(totalColumn).toDouble())
            item.putDouble("updatedAt", cursor.getLong(modifiedColumn).toDouble())
            item.putInt("reason", cursor.getInt(reasonColumn))
            item.putString("status", when (cursor.getInt(statusColumn)) {
              DownloadManager.STATUS_PENDING -> "pending"
              DownloadManager.STATUS_RUNNING -> "running"
              DownloadManager.STATUS_PAUSED -> "paused"
              DownloadManager.STATUS_SUCCESSFUL -> "completed"
              else -> "failed"
            })
            result.pushMap(item)
          }
        }
        promise.resolve(result)
      } catch (error: Exception) {
        promise.reject("DOWNLOAD_STATUS_FAILED", "无法读取下载进度，请重试。", error)
      }
    }
  }

  override fun invalidate() {
    executor.shutdown()
    super.invalidate()
  }
}

class DownloadStatusPackage : ReactPackage {
  override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(DownloadStatusModule(context))
  override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}
