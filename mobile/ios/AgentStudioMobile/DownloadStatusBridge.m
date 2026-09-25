#import <React/RCTBridgeModule.h>

@interface RCT_EXTERN_MODULE(DownloadStatus, NSObject)
RCT_EXTERN_METHOD(listDownloads:(RCTPromiseResolveBlock)resolve
                  rejecter:(RCTPromiseRejectBlock)reject)
@end
