import authorizedTimingAnchorUrl from "../../../../data/assets/audio/task4-segmentation-alignment.wav?url";

import type { Exercise } from "../../data/contracts";

const AUTHORIZED_TIMING_ANCHOR_REF =
  "ASSET-AUDIO-TASK4-TONE-SILENCE-TONE-001";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const domainFixtureNotice = (dataType: string): string => {
  switch (dataType) {
    case "audio":
      return "结构化练习夹具：本单元只提供结构化听觉证据，未提供或暗示可播放录音。";
    case "image":
      return "结构化练习夹具：本单元只提供结构化图像证据，未提供或暗示图像媒体。";
    case "video":
      return "结构化练习夹具：本单元只提供结构化时间线证据，未提供或暗示视频媒体。";
    default:
      return "自编结构化练习材料：本单元不依赖外部媒体。";
  }
};

interface AudioAssetProps {
  dataType: string;
  exercise: Exercise;
}

export function AudioAsset({ dataType, exercise }: AudioAssetProps) {
  const authorization = isRecord(exercise.asset_authorization)
    ? exercise.asset_authorization
    : null;
  const studentUseAllowed = authorization?.student_use_allowed === true;
  const authorizationType =
    typeof authorization?.type === "string"
      ? authorization.type
      : "未声明";
  const assetRef =
    typeof exercise.asset_ref === "string"
      ? exercise.asset_ref
      : "未声明资产引用";
  const isAuthorizedTimingAnchor =
    dataType === "audio" &&
    assetRef === AUTHORIZED_TIMING_ANCHOR_REF &&
    studentUseAllowed &&
    authorizationType === "self-authored" &&
    exercise.representation === "authorized_audio" &&
    exercise.manifest_resolution === "resolved" &&
    isRecord(exercise.input) &&
    exercise.input.contains_recorded_speech === false;

  return (
    <div className="asset-panel">
      <dl className="asset-panel__facts">
        <div>
          <dt>资产引用</dt>
          <dd>{assetRef}</dd>
        </div>
        <div>
          <dt>授权类型</dt>
          <dd>{authorizationType}</dd>
        </div>
        <div>
          <dt>学生使用</dt>
          <dd>{studentUseAllowed ? "允许学生使用" : "未授权学生使用"}</dd>
        </div>
      </dl>

      {!studentUseAllowed ? (
        <p className="asset-notice asset-notice--restricted">
          此资产未授权学生使用，因此不会载入任何媒体。
        </p>
      ) : isAuthorizedTimingAnchor ? (
        <div className="authorized-audio">
          <p>
            自编非语音计时锚点音频；仅用于练习时间边界，
            <code>contains_recorded_speech: false</code>。
          </p>
          <audio controls preload="metadata" src={authorizedTimingAnchorUrl}>
            当前浏览器不支持音频播放控件。
          </audio>
        </div>
      ) : (
        <p className="asset-notice">{domainFixtureNotice(dataType)}</p>
      )}
    </div>
  );
}
