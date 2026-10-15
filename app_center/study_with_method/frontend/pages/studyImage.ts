export const MAX_STUDY_IMAGE_EDGE = 2048;

export interface StudyImageOutput {
  width: number;
  height: number;
  scale: number;
  radians: number;
}

export function calculateStudyImageOutput(
  sourceWidth: number,
  sourceHeight: number,
  rotation: number,
  cropPercent: number,
): StudyImageOutput {
  if (sourceWidth <= 0 || sourceHeight <= 0) {
    throw new Error('图片尺寸无效');
  }

  const normalizedRotation = ((rotation % 360) + 360) % 360;
  const swapped = normalizedRotation === 90 || normalizedRotation === 270;
  const rotatedWidth = swapped ? sourceHeight : sourceWidth;
  const rotatedHeight = swapped ? sourceWidth : sourceHeight;
  const cropRatio = Math.min(100, Math.max(1, cropPercent)) / 100;
  const croppedWidth = rotatedWidth * cropRatio;
  const croppedHeight = rotatedHeight * cropRatio;
  const scale = Math.min(
    1,
    MAX_STUDY_IMAGE_EDGE / croppedWidth,
    MAX_STUDY_IMAGE_EDGE / croppedHeight,
  );

  return {
    width: Math.max(1, Math.round(croppedWidth * scale)),
    height: Math.max(1, Math.round(croppedHeight * scale)),
    scale,
    radians: normalizedRotation * Math.PI / 180,
  };
}
