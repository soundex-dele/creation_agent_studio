export function saveResearchBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url;
  link.download = filename.replace(/[<>:"/\\|?*]/g, '_'); link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
