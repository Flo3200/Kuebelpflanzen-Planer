// Picture of a plant: a real photo, or an AI image (marked "KI") when there is no photo.
import { t } from "../i18n";

export type PlantImg = { url: string; generated: boolean };

export function Thumb({ img, size = 44 }: { img: PlantImg | null | undefined; size?: number }) {
  if (!img) return <span className="thumb empty" style={{ width: size, height: size }} aria-hidden="true" />;
  return (
    <span className="thumb" style={{ width: size, height: size }} title={img.generated ? t("tables.generated") : undefined}>
      <img src={img.url} alt="" loading="lazy" />
      {img.generated && <span className="thumb-ai">KI</span>}
    </span>
  );
}
