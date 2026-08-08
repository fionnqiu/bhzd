export interface SpinnerProps {
  /** 直径 px；默认 20 */
  size?: number;
  large?: boolean;
}

/** 加载指示器。块级加载场景请配合 .loading-block 容器使用。 */
export default function Spinner({ size, large = false }: SpinnerProps) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <span
      className={["spinner", large ? "spinner-lg" : ""].filter(Boolean).join(" ")}
      style={style}
      role="status"
      aria-label="加载中"
    />
  );
}
